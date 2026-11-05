"""Local web interface for the News Fact-Check Agent (Python standard library only)."""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread, Timer
from urllib.parse import parse_qs, urlparse

from agent.loop import run_agent
from config import load_settings
from tools.news import search_news

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "web" / "index.html"
SESSION_DB = ROOT / "data" / "research_sessions.sqlite3"
settings = load_settings()

_CATEGORIES = {
    "top": "India",
    "world": "world",
    "politics": "India politics",
    "sports": "sports",
    "business": "business",
    "technology": "technology",
    "science": "science",
    "entertainment": "entertainment",
}
_feed_cache: dict[str, tuple[float, list[dict]]] = {}
_feed_lock = Lock()
_FEED_TTL = 600
_state_lock = Lock()
_sessions: dict[str, dict] = {}
_jobs: dict[str, dict] = {}
_MAX_SESSION_TURNS = 5


def _load_saved_turns(session_id: str) -> list[dict] | None:
    try:
        with sqlite3.connect(SESSION_DB, timeout=5) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, turns TEXT NOT NULL, updated_at REAL NOT NULL)")
            row = connection.execute("SELECT turns FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row:
            turns = json.loads(row[0])
            return turns if isinstance(turns, list) else []
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        return None
    return None


def _save_turns(session_id: str, turns: list[dict]) -> None:
    SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SESSION_DB, timeout=5) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, turns TEXT NOT NULL, updated_at REAL NOT NULL)")
        connection.execute(
            "INSERT INTO sessions(id, turns, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET turns=excluded.turns, updated_at=excluded.updated_at",
            (session_id, json.dumps(turns, ensure_ascii=False), time.time()),
        )


def _fetch_feed(category: str) -> list[dict]:
    query = _CATEGORIES.get(category, _CATEGORIES["top"])
    try:
        sort_by = "relevancy" if category == "top" else "newest"
        items = search_news(query, api_key=settings.newsapi_key, timeout=settings.request_timeout,
                            limit=12, sort_by=sort_by)
    except Exception:
        if not settings.newsapi_key:
            raise
        # NewsAPI plan restrictions should not prevent the RSS feed from working.
        items = search_news(query, api_key="", timeout=settings.request_timeout, limit=12, sort_by=sort_by)
    seen: set[str] = set()
    clean: list[dict] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        key = title.casefold()
        if not title or not url or key in seen:
            continue
        seen.add(key)
        clean.append({
            "title": title,
            "url": url,
            "publisher": str(item.get("source") or "News source"),
            "published_at": str(item.get("published_at") or ""),
            "summary": str(item.get("description") or "").strip(),
        })
    return clean


def get_news(category: str = "top", refresh: bool = False) -> dict:
    category = category.lower()
    if category not in _CATEGORIES:
        raise ValueError("Unknown news category")
    now = time.monotonic()
    with _feed_lock:
        entry = _feed_cache.get(category)
        if not refresh and entry and now - entry[0] < _FEED_TTL:
            return {"category": category, "items": entry[1], "cached": True}
    items = _fetch_feed(category)
    with _feed_lock:
        _feed_cache[category] = (time.monotonic(), items)
    return {"category": category, "items": items, "cached": False}


def get_status() -> dict:
    return {
        "app": "ready",
        "providers": [{"name": p.name, "model": p.model} for p in settings.providers],
        "news_source": "NewsAPI + Google News RSS fallback" if settings.newsapi_key else "Google News RSS",
    }


def answer_question(question: str, session_id: str, job: dict) -> dict:
    activity: list[str] = []
    with _state_lock:
        session = _sessions[session_id]
        context = list(session["turns"][-_MAX_SESSION_TURNS:])

    def log(message: str) -> None:
        activity.append(message)
        job["activity"] = activity
        job["events"].put({"event": "progress", "data": {"message": message}})

    report = run_agent(question, settings, log=log, seed_news=True, context=context)
    response = {
        "answer": report.summary,
        "news_summary": report.summary,
        "topic": report.topic,
        "model": report.model,
        "llm_calls": report.llm_calls,
        "verdicts": [verdict.model_dump(mode="json") for verdict in report.verdicts],
        "sources": [source.model_dump(mode="json") for source in report.sources_considered],
        "related_news": [source.model_dump(mode="json") for source in report.sources_considered],
        "warnings": report.warnings,
        "generated_at": report.generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    response["activity"] = activity
    turn = {
        "question": question,
        "answer": report.summary[:1200],
        "verdicts": [{"claim": v.claim[:300], "verdict": v.verdict} for v in report.verdicts[:4]],
        "sources": [{"title": s.title[:200], "url": s.url} for s in report.sources_considered[:5]],
    }
    with _state_lock:
        # A timed-out background worker may finish later; do not overwrite a newer session turn.
        if job.get("status") != "running":
            return response
        session = _sessions[session_id]
        session["turns"].append(turn)
        session["turns"] = session["turns"][-_MAX_SESSION_TURNS:]
        response["turn_count"] = len(session["turns"])
        session["active_job"] = None
        try:
            _save_turns(session_id, session["turns"])
        except (OSError, sqlite3.Error):
            response["warnings"].append("This answer is available, but follow-up memory could not be saved locally.")
    return response


def _start_job(question: str, requested_session_id: str) -> dict:
    with _state_lock:
        session = _sessions.get(requested_session_id)
        if session is None:
            return {"error": "This research session expired. Refresh the page and try again.", "status": 409}
        if session["active_job"]:
            return {"error": "A question is already being researched in this session.", "status": 409}
        job_id = secrets.token_urlsafe(18)
        job = {"id": job_id, "session_id": requested_session_id, "events": queue.Queue(), "status": "running"}
        job["events"].put({"event": "progress", "data": {"message": "Research task queued."}})
        _jobs[job_id] = job
        session["active_job"] = job_id

    def work() -> None:
        try:
            result = answer_question(question, requested_session_id, job)
            with _state_lock:
                if job["status"] == "running":
                    job["status"] = "complete"
                    job["events"].put({"event": "complete", "data": {"result": result}})
        except Exception as exc:
            with _state_lock:
                if job["status"] != "running":
                    return
                if requested_session_id in _sessions:
                    _sessions[requested_session_id]["active_job"] = None
            job["status"] = "complete"
            job["events"].put({"event": "complete", "data": {"error": f"Research could not finish ({type(exc).__name__})."}})

    def timeout_job() -> None:
        with _state_lock:
            if job["status"] != "running":
                return
            job["status"] = "timed_out"
            session = _sessions.get(requested_session_id)
            if session and session.get("active_job") == job_id:
                session["active_job"] = None
            job["events"].put({"event": "complete", "data": {
                "error": f"Research exceeded the {settings.max_research_seconds}-second time limit. The last activity is shown below.",
                "activity": job.get("activity", []),
            }})

    timer = Timer(settings.max_research_seconds + 10, timeout_job)
    timer.daemon = True
    timer.start()
    Thread(target=work, name=f"research-{job_id[:8]}", daemon=True).start()
    return {"job_id": job_id, "session_id": requested_session_id}


def _create_session(requested_id: str = "") -> dict:
    with _state_lock:
        if requested_id and requested_id in _sessions:
            session = _sessions[requested_id]
            return {"session_id": requested_id, "turn_count": len(session["turns"])}
        if requested_id:
            saved_turns = _load_saved_turns(requested_id)
            if saved_turns is not None:
                _sessions[requested_id] = {"turns": saved_turns[-_MAX_SESSION_TURNS:], "active_job": None}
                return {"session_id": requested_id, "turn_count": len(_sessions[requested_id]["turns"])}
        session_id = secrets.token_urlsafe(18)
        _sessions[session_id] = {"turns": [], "active_job": None}
        try:
            _save_turns(session_id, [])
        except (OSError, sqlite3.Error):
            pass
        return {"session_id": session_id, "turn_count": 0}


def _stream_job(handler: BaseHTTPRequestHandler, job_id: str) -> None:
    with _state_lock:
        job = _jobs.get(job_id)
    if job is None:
        handler.send_error(404, "Research job not found")
        return
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    try:
        while True:
            try:
                item = job["events"].get(timeout=15)
            except queue.Empty:
                handler.wfile.write(b": heartbeat\n\n")
                handler.wfile.flush()
                continue
            data = json.dumps(item["data"], ensure_ascii=False)
            block = f"event: {item['event']}\ndata: {data}\n\n".encode("utf-8")
            handler.wfile.write(block)
            handler.wfile.flush()
            if item["event"] == "complete":
                return
    except (BrokenPipeError, ConnectionResetError):
        return


class NewsroomHandler(BaseHTTPRequestHandler):
    server_version = "NewsroomAI/1.0"

    def log_message(self, format: str, *args) -> None:
        # Keep access logs concise; never log request bodies or API credentials.
        print(f"[{self.log_date_time_string()}] {self.command} {urlparse(self.path).path}")

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            try:
                body = INDEX_FILE.read_bytes()
            except OSError:
                self.send_error(500, "Web interface file is missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/status":
            self.send_json(200, get_status())
            return
        job_match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/events", parsed.path)
        if job_match:
            _stream_job(self, job_match.group(1))
            return
        if parsed.path == "/api/news":
            query = parse_qs(parsed.query)
            category = query.get("category", ["top"])[0][:24]
            refresh = query.get("refresh", [""])[0] == "1"
            try:
                self.send_json(200, get_news(category, refresh))
            except ValueError as exc:
                self.send_json(400, {"detail": str(exc)})
            except Exception as exc:
                self.send_json(502, {"detail": f"The news feed is temporarily unavailable ({type(exc).__name__})."})
            return
        self.send_json(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/ask", "/api/session"):
            self.send_json(404, {"detail": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 0 or length > 8192 or (path == "/api/ask" and length == 0):
            self.send_json(413, {"detail": "Request is empty or too large."})
            return
        try:
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"detail": "Request must be valid JSON."})
            return
        if not isinstance(payload, dict):
            self.send_json(400, {"detail": "Request must be a JSON object."})
            return
        if path == "/api/session":
            requested = payload.get("session_id", "")
            self.send_json(200, _create_session(requested if isinstance(requested, str) else ""))
            return
        question = payload.get("question", "")
        if not isinstance(question, str) or not 3 <= len(question.strip()) <= 500:
            self.send_json(422, {"detail": "Write a question between 3 and 500 characters."})
            return
        session_id = payload.get("session_id", "")
        if not isinstance(session_id, str) or not session_id:
            self.send_json(422, {"detail": "Create a research session before asking a question."})
            return
        job = _start_job(question.strip(), session_id)
        if "error" in job:
            self.send_json(job.pop("status"), {"detail": job["error"]})
            return
        self.send_json(202, job)


def main() -> None:
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), NewsroomHandler)
    print(f"Newsroom AI is running at http://{host}:{port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Newsroom AI…", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
