# Newsroom — Evidence-Based Fact Checking & News Assistant

A web tool and Python assistant that checks factual claims against live news articles and Wikipedia reference pages.

Instead of trusting an AI model's internal memory (which can hallucinate or mix up dates), this app forces the model to search external sources, quote exact evidence, and run every citation through code-level Python checks before showing you the verdict.

---

## The Truth About AI Hallucinations (No Hype)

No AI model has "zero hallucinations". Models predict text based on probability, so they can invent plausible-sounding facts, quote things that don't exist, or cite broken URLs.

This project does not claim the AI never makes mistakes. Instead, **deterministic Python code acts as an external auditor**:

1. **URL Verification**: The LLM can only cite URLs that were actually returned by search tools during the session. If the model invents a URL, Python strips it out immediately.
2. **Quote Verification**: When the model provides a quote as evidence, Python checks the quote against the raw text scraped from the website. If the words aren't in the article, the quote is marked unverified and the confidence score is lowered.
3. **Temporal Sanity Checks**: If a claim specifies a year (e.g. 2021) and the model quotes an article from 2026, Python flags the mismatch so unrelated modern news isn't used as "proof" for older events.
4. **Verdict Downgrades**: If the model claims something is false or true but fails to provide matching proof from the retrieved text, Python overrides the verdict and sets it to **Unverified**.

In short: **The model can still be wrong or confused, but Python prevents it from showing fake links, fake quotes, or unbacked confidence.**

---

## How It Works

```
1. User enters a claim or question
   │
   ▼
2. Initial Search (Google News RSS / NewsAPI for breaking news, or Wikipedia for past events)
   │
   ▼
3. Autonomous Research Loop
   - Model reviews search results
   - Model decides if it needs more info (search_news, search_reference, fetch_page)
   - Dispatches tools and reads raw web pages
   │
   ▼
4. Python Verification Gate
   - Checks cited URLs against registered tool results
   - Verifies quotes against retrieved page text
   - Filters out off-topic or temporal mismatches
   - Sets confidence: High, Medium, or Low
   │
   ▼
5. Clean Interactive UI
   - Shows Verdict (True / False / Misleading / Unverified)
   - Explains the factual reality
   - Displays exact verified quotes with source links
```

---

## Quickstart

### 1. Requirements
- Python 3.11 or higher
- At least one AI API key:
  - **Gemini**: `GEMINI_API_KEY` (from [Google AI Studio](https://aistudio.google.com/))
  - **Groq** (backup / fast inference): `GROQ_API_KEY` (from [Groq Console](https://console.groq.com/))

*(Optional)*:
- `NEWSAPI_KEY`: for NewsAPI integration (falls back to Google News RSS if omitted).
- `GOOGLE_FACTCHECK_API_KEY`: for Google Fact Check Tools API.

### 2. Setup

```bash
# Clone the repository and navigate into the folder
cd Agent

# Create and activate a virtual environment
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Add your keys to `.env`:
```env
GEMINI_API_KEY=your_gemini_key_here
GROQ_API_KEY=your_groq_key_here
```

### 4. Run the Web App

```bash
python webapp.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## Project Structure & File Guide

Here is an explanation of every file in the project and what role it plays:

### Root Directory
- **`webapp.py`**: The web server. Serves the web interface, manages user research sessions (saved in a local SQLite file), runs research jobs in the background, and streams live progress updates to the browser using Server-Sent Events (SSE).
- **`main.py`**: The command-line interface (CLI). Lets you run investigations directly in your terminal (`python main.py "your claim"`) or run system diagnostics (`python main.py --doctor`).
- **`config.py`**: Loads environment variables from `.env` and sets defaults (timeouts, model names, step limits, directories).
- **`requirements.txt`**: The list of Python libraries needed to run the application (requests, feedparser, openai, pydantic, trafilatura, etc.).
- **`.env.example`**: Example template showing what environment variables can be configured.

---

### `agent/` (The Research & Verification Engine)
- **`loop.py`**: The core research loop. Starts an investigation, passes the claim to the model, handles tool calls (`search_news`, `fetch_page`, etc.), tracks steps, and manages conversation history.
- **`verify.py`**: The code-level auditor. Intercepts whatever report the model submits. It strips unregistered URLs, checks quoted snippets against the raw retrieved text using sequence matching, verifies that the quoted years match the claim, and determines whether the verdict should stand or be downgraded to "unverified".
- **`llm.py`**: The AI router. Handles communication with Gemini and Groq. If one provider is rate-limited or encounters a server error, it automatically switches to the backup provider without crashing.
- **`prompts.py`**: The system instructions given to the LLM. Explains how to act like an objective fact-checker, which tools to use for what kind of question, and how to format verdicts.
- **`schemas.py`**: Defines data structures using Pydantic (e.g. `Verdict`, `Evidence`, `FactCheckReport`). Ensures data exchanged between the model, Python, and the web UI is properly formatted.
- **`sources.py`**: `SourceRegistry`. A memory store of every URL and text snippet returned by tools during a research task. Used by `verify.py` to prevent the model from citing unvisited websites.
- **`reliability.py`**: Classifies websites into trust tiers (e.g. `official` government domains, `fact_checker` sites, and `established` references like Wikipedia or Reuters).
- **`guardrails.py`**: Security checks. Prevents SSRF (Server-Side Request Forgery) attacks by ensuring the agent only requests public HTTPS URLs and never accesses private local network addresses.
- **`diagnostics.py`**: Runs health checks on your configured API keys and models when you run `python main.py --doctor`.

---

### `tools/` (How the Agent Accesses the Web)
- **`news.py`**: Searches for recent news articles using NewsAPI (if a key is provided) or Google News RSS.
- **`reference.py`**: Searches Wikipedia for historical events, sports champions, biographies, and reference knowledge that news aggregators don't index.
- **`scraper.py`**: Web scraper using `trafilatura`. Downloads a webpage's HTML and extracts the main readable text while discarding ads, menus, and sidebars.
- **`factcheck.py`**: Searches Google's Fact Check Tools API for existing published reviews by professional fact-checking organizations.
- **`docs_search.py`**: Local document search. If you place PDF or text files in `data/docs/`, this allows the agent to search your own files.
- **`registry.py`**: `ToolBox`. Registers all available tools, generates their JSON schemas so the LLM knows how to call them, and executes the appropriate tool function when requested.

---

### `utils/` (Helper Functions)
- **`cache.py`**: Saves web requests to disk (`data/cache/`) so repeat searches or page visits during a session don't consume unnecessary bandwidth or API calls.
- **`dates.py`**: Helpers for parsing dates across different timezone formats.
- **`text.py`**: Text sanitization and cleanup helpers (strips HTML tags and normalizes whitespace).
- **`render.py`**: Formats fact-check reports with colored terminal output when using the CLI (`main.py`).

---

### `web/`
- **`index.html`**: The entire frontend user interface. Built with clean, accessible HTML/CSS/JavaScript with responsive layout, Dark/Light mode support, live research progress streaming, interactive tabs for verified receipts, and one-click quote copying.

---

## Limitations to Keep in Mind

- **Paywalled Sites**: If a news outlet blocks scrapers with a hard paywall or cloudflare challenge, `fetch_page` cannot read the full body text and relies on the search snippet instead.
- **Breaking News Lag**: Very recent news (events that happened within the last 15-30 minutes) may not be indexed by search APIs immediately.
- **API Quotas**: Free API tiers for Groq or NewsAPI have rate limits. If a limit is hit, the application pauses or fails over to alternative providers.
