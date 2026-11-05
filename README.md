# Newsroom

A real-time fact-checking and news investigation engine powered by autonomous web retrieval and deterministic verification guardrails.

Newsroom cross-examines claims and news stories against live news feeds (NewsAPI, Google News RSS) and authoritative reference encyclopedias (Wikipedia). Rather than relying blindly on an LLM's parametric memory, the system queries primary sources, extracts quoted evidence, and validates all citations through code-level Python checks before rendering a verdict.

---

## Overview

Large language models frequently generate plausible-sounding assertions, cite fabricated URLs, or conflate events across different years. Newsroom addresses this by decoupling **research and reasoning** from **evidence verification**:

1. **Autonomous Research Loop**: An LLM agent formulates search queries, retrieves live articles and reference pages, inspects page content, and synthesizes findings.
2. **Deterministic Code Guardrails**: Python verification logic intercepts the model's draft report to independently validate every cited URL, check quoted excerpts against raw retrieved page text, and confirm temporal relevance.
3. **Evidence-Backed Verdicts**: Claims are classified as **True**, **False**, **Partially True / Misleading**, or **Unverified**, accompanied by exact verified quotes, stance tags, and direct publisher links.

---

## Architecture

```
User Query / News Article Click
               │
               ▼
┌─────────────────────────────────────────┐
│     Context & Follow-up Detection       │
│      (is_anaphoric_follow_up)           │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│           Source Retrieval              │
│  - Breaking News: NewsAPI / Google News │
│  - Reference / History: Wikipedia API   │
│  - Local Knowledge: Document Index      │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│        Agentic Investigation Loop       │
│  - Model evaluates collected evidence   │
│  - Calls tools (search, fetch_page)     │
│  - Streams progress via SSE to UI       │
│  - Submits structured report draft      │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│       Python Verification Layer         │
│  - URL Whitelist validation             │
│  - Fuzzy sequence matching for quotes   │
│  - Temporal & topic relevance check     │
│  - Stance alignment & confidence rating │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│         Interactive Web UI / CLI        │
│  - Verdict stamp (True / False / ...)   │
│  - Factual reality explanation          │
│  - Interactive verified proof cards     │
└─────────────────────────────────────────┘
```

---

## Evidence Verification Pipeline

The verification layer in `agent/verify.py` acts as a code-level auditor between the model's output and the user:

- **Source Registry Whitelist**: Every URL returned by search tools is registered in an in-memory `SourceRegistry`. Any URL cited in the report that does not originate from an actual tool execution is removed.
- **Fuzzy Quote Verification**: Quoted excerpts are matched against the raw text fetched from the source using `difflib.SequenceMatcher`. If an excerpt cannot be substantiated in the text, it is marked unverified and confidence is reduced.
- **Temporal Relevance Guardrails**: If a claim specifies a past year (e.g., `2021`) and an excerpt references a different year (e.g., `2026`) without corroborating the target year, the quote is flagged as a temporal mismatch and rejected as proof.
- **Verdict Integrity**: If a claim is marked as contradicted or supported, but no matching evidence exists in the retrieved text, the system automatically downgrades the verdict to `unverified` and caps confidence at `low`.

---

## Features

- **Multi-Provider Fallback Router**: Seamlessly chains providers (`Gemini` → `Groq` → `Mistral`). If a primary provider hits rate limits (HTTP 429) or server outages (HTTP 500/503), requests fail over automatically without interrupting research.
- **Dual Retrieval Pipeline**: Uses Google News RSS and NewsAPI for breaking news, and Wikipedia REST APIs for historical events, sports records, biographies, and scientific facts.
- **Live Event Streaming**: Streams research activity in real time using Server-Sent Events (SSE).
- **Interactive Web Interface**: Clean, accessible UI with persistent Dark/Light mode, keyboard shortcuts (`/` to focus), one-click quote copying, and tabbed proof drawers.
- **Local Document Search (RAG)**: Automatically indexes PDF, Markdown, and text files placed in `data/docs/` for private document cross-checking.
- **Command-Line Interface**: Run investigations or system diagnostics directly from your terminal.

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- An API key for at least one supported provider:
  - [Google AI Studio](https://aistudio.google.com/) (`GEMINI_API_KEY`)
  - [Groq Console](https://console.groq.com/) (`GROQ_API_KEY`)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/your-username/newsroom.git
cd newsroom

# Create and activate a virtual environment
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Primary LLM provider
GEMINI_API_KEY=your_gemini_api_key_here

# Backup LLM provider
GROQ_API_KEY=your_groq_api_key_here

# Optional: NewsAPI for expanded news search
NEWSAPI_KEY=your_newsapi_key_here
```

### 4. Running the Application

#### Web Interface
Start the local server:
```bash
python webapp.py
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

#### Command-Line Interface
Run an investigation directly in the terminal:
```bash
python main.py "Did Lewis Hamilton win the 2021 F1 World Championship?"
```

Run system health and provider connectivity diagnostics:
```bash
python main.py --doctor
```

---

## Project Structure

```
├── agent/                  # Core research and verification engine
│   ├── diagnostics.py      # Provider health checks and connectivity tests
│   ├── guardrails.py       # SSRF protection and URL normalisation
│   ├── llm.py              # Multi-provider LLM router with automatic failover
│   ├── loop.py             # Autonomous investigation loop and step planning
│   ├── prompts.py          # System prompt and tool instructions
│   ├── reliability.py      # Source classification and trust tiers
│   ├── schemas.py          # Pydantic data models for claims, evidence, and reports
│   ├── sources.py          # In-memory registry of retrieved URLs and raw text
│   └── verify.py           # Code-level evidence and quote verification
├── tools/                  # Search and retrieval tool implementations
│   ├── docs_search.py      # Local document search (PDF/text index)
│   ├── factcheck.py        # Google Fact Check Tools API integration
│   ├── news.py             # NewsAPI and Google News RSS search
│   ├── reference.py        # Wikipedia reference and encyclopedia search
│   ├── registry.py         # ToolBox schema definition and dispatch
│   └── scraper.py          # Webpage reader and content extractor (Trafilatura)
├── utils/                  # Shared utilities
│   ├── cache.py            # Local disk cache for network requests
│   ├── dates.py            # Date parsing and timezone normalization
│   ├── render.py           # Terminal formatting for CLI output
│   └── text.py             # Text cleaning and entity sanitization
├── web/
│   └── index.html          # Web frontend (responsive, dual theme, SSE stream)
├── config.py               # Settings loader and environment configuration
├── main.py                 # CLI entry point
├── webapp.py               # Web server and SSE streaming backend
├── requirements.txt        # Production dependencies
└── .env.example            # Environment variable template
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | `""` | Google Gemini API key. |
| `GROQ_API_KEY` | `""` | Groq Cloud API key (used for fast backup inference). |
| `MISTRAL_API_KEY` | `""` | Mistral AI API key (optional fallback). |
| `NEWSAPI_KEY` | `""` | NewsAPI key. If omitted, Google News RSS is used. |
| `GOOGLE_FACTCHECK_API_KEY` | `""` | Google Fact Check Tools API key. |
| `WEB_HOST` | `127.0.0.1` | Host address for the web server. |
| `WEB_PORT` | `8000` | Port for the web server. |
| `MAX_STEPS` | `4` | Maximum autonomous research steps per query. |
| `MAX_RESEARCH_SECONDS` | `90` | Hard timeout for research tasks. |
| `TIMEZONE` | `Asia/Kolkata` | Timezone used for relative date queries. |
| `CACHE_TTL_SECONDS` | `3600` | Request cache expiration (set to `0` to disable). |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
