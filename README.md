# 🗞️ Newsroom AI — Autonomous Evidence & Fact-Checking Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Architecture: Autonomous Agentic Loop](https://img.shields.io/badge/Architecture-Autonomous%20Agentic%20Loop-emerald.svg)](file:///C:/Users/Devansh/OneDrive/Desktop/Project/Agent/agent/loop.py)
[![Design: Glassmorphism & Dual Theme](https://img.shields.io/badge/UI-Dark%20%2F%20Light%20Mode-slate.svg)](file:///C:/Users/Devansh/OneDrive/Desktop/Project/Agent/web/index.html)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **"News with receipts."**  
> An autonomous AI research agent and newsroom assistant that fact-checks breaking claims, interrogates live news wires, validates original publisher quotes against ground-truth retrieved text, and generates evidence-backed executive briefings.

---

## 🌟 Key Highlights

- ⚡ **Autonomous Research Agent Loop**: The agent dynamically formulates query ladders, queries live news feeds (NewsAPI & Google News RSS), consults fact-checking registries, inspects web pages, and cross-checks quotes within a bounded, safe execution loop.
- 🛡️ **Zero-Hallucination Guardrails**:
  - **Source Registry Whitelist**: The agent can *only* cite URLs that were genuinely returned by tool executions. Fabricated URLs are automatically pruned at code level.
  - **Fuzzy Excerpt Verification**: Quoted snippets in fact-check verdicts are checked via sequence matching against retrieved text. Unsubstantiated claims are immediately capped to `low` confidence or flagged `unverified`.
  - **Topical Context Isolation**: Intelligent follow-up detection separates genuine elliptical questions (*"Who won it?"*) from standalone stories (*"What is known about this story: ... "*), preventing topic bleed across turns.
- 📰 **Executive News Summaries**: Synthesizes key takeaways directly from primary journalistic sources, with bulleted takeaways and direct publisher receipts.
- 🌗 **Modern Interactive UI (Dark & Light Mode)**:
  - Custom glassmorphic design featuring Plus Jakarta Sans and editorial Newsreader serif typography.
  - One-click segmented **☀️ Light / 🌙 Dark** theme switcher with instant persistence (`localStorage`).
  - Real-time client-side headline filter (`🔍 Filter headlines...`) to search current desk stories instantly.
  - Live investigation activity stream with step spinners, green checkmarks, and collapsible autonomous reasoning logs.
- 🔀 **Multi-Provider AI Resilience**: Built-in provider fallback router (Gemini → Groq → Mistral) with auto-wait rate-limit handling and offline extractive summarization fallbacks.
- 📁 **Local Document Intelligence (RAG)**: Drop local `.pdf`, `.txt`, or `.md` files into `data/docs/` to automatically enable grounded document search alongside live news.

---

## 🏗️ Architecture & Research Loop

```
                     ┌───────────────────────────────┐
                     │    User Query / Story Click   │
                     └───────────────┬───────────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │  is_anaphoric_follow_up()     │
                     │  (Context Isolation Check)    │
                     └───────────────┬───────────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │   Initial Seed News Search    │
                     │ (NewsAPI / Google News RSS)   │
                     └───────────────┬───────────────┘
                                     │
            ┌────────────────────────▼────────────────────────┐
            │            Autonomous Research Loop             │
            │                                                 │
            │  1. Formulate next inquiry                      │
            │  2. Dispatch tool (search_news, fetch_page,     │
            │     search_factchecks, search_docs)             │
            │  3. Stream live progress event to UI (SSE)      │
            │  4. Ingest raw text into SourceRegistry         │
            └────────────────────────┬────────────────────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │     Code-Level Verification   │
                     │   - Strip unregistered URLs   │
                     │   - Verify quote word overlap │
                     │   - Filter topical relevance  │
                     │   - Assign confidence tier    │
                     └───────────────┬───────────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │  Final Research Dossier & UI  │
                     │  - Executive News Summary     │
                     │  - Claim Verdict Cards        │
                     │  - Verified Receipts Gallery  │
                     └───────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Prerequisites & Environment Setup
Requires Python 3.11 or higher.

```bash
# Clone or navigate to the project directory
cd Agent

# Create and activate virtual environment
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and provide your API keys:

```bash
cp .env.example .env
```

Edit `.env`:
```ini
# LLM Providers (Configure at least one; automatic failover is supported)
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
MISTRAL_API_KEY=your_mistral_api_key_here
LLM_PROVIDER_ORDER=gemini,groq,mistral

# News & Fact-Checking Providers (Optional but recommended)
NEWSAPI_KEY=your_newsapi_org_key_here
GOOGLE_FACTCHECK_API_KEY=your_google_factcheck_api_key_here

# General Settings
TIMEZONE=Asia/Kolkata
MAX_STEPS=6
MAX_RESEARCH_SECONDS=90
```

> **Note**: Even without `NEWSAPI_KEY`, the agent automatically uses Google News RSS as an always-available free fallback!

### 3. Run the Web Application
```bash
python webapp.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 💻 CLI & Batch Usage

You can also run one-off investigations directly from your terminal:

```bash
# Check provider connectivity and tool readiness
python main.py --check

# Run an investigation from CLI
python main.py "Did the Union Cabinet approve a semiconductor policy this week?"

# Inspect formatted markdown report saved to disk
# Reports are automatically stored in data/reports/<slug>.md
```

---

## 📂 Project Organization

```
Agent/
├── agent/
│   ├── guardrails.py     # Domain validation, SSRF network checks, URL normalization
│   ├── llm.py            # Multi-provider client (Gemini, Groq, Mistral) & cooldown router
│   ├── loop.py           # Core autonomous think → act → observe research loop
│   ├── prompts.py        # System instructions, evidence formatting guidelines
│   ├── reliability.py    # Source authority tiers and ranking metrics
│   ├── schemas.py        # Pydantic data models for claims, verdicts, and reports
│   ├── sources.py        # URL Registry tracking every tool output to prevent hallucination
│   └── verify.py         # Code-level fact check verification, quote matching & relevance filter
├── config.py             # Settings loader, environment variable management
├── data/
│   ├── docs/             # Drop .pdf, .md, or .txt files here for local RAG
│   ├── reports/          # Markdown investigation reports generated by the agent
│   └── research_sessions.sqlite3 # Lightweight persistent conversation context
├── main.py               # Command-line interface with formatted terminal rendering
├── tools/
│   ├── docs_search.py    # Local BM25/keyword indexing and document passage retrieval
│   ├── factchecks.py     # Google Fact Check Tools API client
│   ├── news.py           # NewsAPI search with Google News RSS feed fallback
│   ├── pages.py          # Secure HTML page reader with SSRF validation and Trafilatura
│   └── registry.py       # JSON-Schema tool dispatch and model interface
├── web/
│   └── index.html        # Modern responsive frontend (Dark/Light mode, live stream, chips)
├── webapp.py             # Python HTTP server, Server-Sent Events (SSE), API routes
└── requirements.txt      # Production dependencies
```

---

## 📡 API Reference

The built-in web server exposes standard, lightweight endpoints:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the web interface with responsive Dark/Light mode |
| `/api/status` | `GET` | Returns active LLM providers, news backends, and system status |
| `/api/news?category=top` | `GET` | Fetches live stories for desks (`top`, `world`, `politics`, `technology`, `business`, `science`, `sports`, `entertainment`) |
| `/api/ask` | `POST` | Dispatches an autonomous research job (`{"question": "...", "session_id": "..."}`) |
| `/api/jobs/:id/events` | `GET` | Server-Sent Events (SSE) real-time stream of research steps |
| `/api/session` | `POST` | Initializes or refreshes persistent multi-turn session context |

---

## 🔒 Security & Anti-Hallucination Principles

1. **Strict Citing Boundary**: The model is mathematically forbidden from inventing links. Every cited URL must originate from a tool call registered in `SourceRegistry`.
2. **Quote Verification**: The agent checks word-by-word sequence matches between claimed quotes and retrieved page text. Any hallucinated quote resets the claim verdict to `unverified`.
3. **SSRF Protection**: Web page fetching restricts requests to HTTPS only and rejects local/private loopback IP addresses (preventing intranet attacks).
4. **Context Isolation**: Independent story investigations completely purge prior session entities so that earlier inquiries (e.g., sports) never bleed into current investigations (e.g., politics).

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
