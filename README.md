# 🏦 AI Advisory Platform — Platform Independent POC

> A fully local, open-source AI advisory platform powered by **Ollama**, **ChromaDB**, **SQLite** and **LangGraph** — no cloud, no API keys for AI, zero cost to run.

---

## What Is This?

This is a Proof of Concept AI-powered advisory application built for the financial services industry. It demonstrates how modern AI technologies — Retrieval Augmented Generation (RAG), vector embeddings, agentic workflows, and local LLMs — can be combined into a production-ready architecture that runs entirely on a personal Windows laptop with no cloud dependency.

**Originally built for a Global Asset Management Group POC.** The architecture is domain-agnostic and can be adapted to any enterprise use case.

---

## Architecture

```
External Sources → Pipeline → SQLite DB → AI Layer → Dashboard
```

| Layer | Technology | Purpose |
|---|---|---|
| Data Pipeline | Python | Fetch news, rates, prices |
| Storage | SQLite | Single file, zero setup |
| Vector Search | ChromaDB | Semantic search by meaning |
| Embeddings | sentence-transformers | Text → 768-dim vectors |
| AI Inference | Ollama (local LLMs) | No API key, runs offline |
| Agent Framework | LangGraph | Autonomous tool selection |
| Dashboard | Streamlit | 6-tab advisor interface |

---

## Features

- **Tab 1** — Live news feed with AI sentiment analysis
- **Tab 2** — Market prices (TSX equities via Yahoo Finance)
- **Tab 3** — Customer portfolio with Plotly charts and related news
- **Tab 4** — Real-time research via Tavily (whitelisted sources)
- **Tab 5** — AI Chat with Semantic RAG + structured 6-section analysis
- **Tab 6** — Conversational AI Agent with memory, follow-up questions and audit logging

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime |
| Ollama | Latest | Local LLM inference |
| Git | Latest | Version control |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ai-advisory-platform.git
cd ai-advisory-platform
```

### 2. Create virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate      # Mac/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install and start Ollama

Download from [ollama.com](https://ollama.com/download) then pull a model:

```bash
ollama pull llama3.2:1b     # Fast, recommended for most laptops
ollama pull mistral          # Better quality, needs 8GB+ RAM
```

### 5. Configure environment

Create a `.env` file in the root directory:

```
NEWSAPI_KEY=your_newsapi_key
TAVILY_API_KEY=your_tavily_key

OLLAMA_MODEL=llama3.2:1b
OLLAMA_BASE_URL=http://localhost:11434
DB_PATH=bank_poc.db
CHROMA_PATH=chroma_db
```

Get free API keys:
- NewsAPI: [newsapi.org](https://newsapi.org) — free tier available
- Tavily: [tavily.com](https://tavily.com) — free tier available

### 6. Generate mock data

```bash
python generate_mock_data.py
```

### 7. Run the data pipeline

```bash
python master_pipeline.py
```

### 8. Launch the dashboard

```bash
streamlit run dashboard.py
```

Open your browser at `http://localhost:8501`

---

## Project Structure

```
ai-advisory-platform/
├── dashboard.py            # Main Streamlit dashboard (6 tabs)
├── agent.py                # LangGraph conversational agent
├── db.py                   # Shared database layer (SQLite + ChromaDB + Ollama)
├── master_pipeline.py      # Orchestrates all data fetching
├── fetch_news_api.py       # NewsAPI ingestion
├── fetch_tavily_news.py    # Tavily search ingestion
├── fetch_boc_rates.py      # Bank of Canada rates
├── fetch_market_prices.py  # Yahoo Finance prices
├── enrich_news.py          # Batch AI enrichment with Ollama
├── generate_mock_data.py   # Creates 1,000 mock customers
├── requirements.txt        # Python dependencies
├── .env                    # Your credentials (never committed)
├── .gitignore              # Excludes .env and venv
└── README.md               # This file
```

---

## How It Works

### Data Flow

```
1. Pipeline fetches news, rates, prices → SQLite
2. Ollama enriches each article → sentiment, summary
3. sentence-transformers converts text → 768-dim vectors
4. ChromaDB indexes vectors → enables semantic search
5. Advisor asks question → ChromaDB finds relevant articles
6. Holdings + rates + news passed to Ollama as context
7. Ollama generates structured analysis → dashboard displays
8. Every AI decision logged to AI_AUDIT_LOG table
```

### Semantic Search vs Keyword Search

Traditional keyword search finds exact word matches. Semantic search finds articles by **meaning** — so "central bank tightening" matches a query about "interest rate increases" even though no words overlap.

### LangGraph Agent

The Tab 6 agent autonomously decides:
- Which data sources to query (news, holdings, rates, prices)
- Whether the question is within financial scope
- Whether local data is sufficient or whitelisted sources should be searched
- How to respond (structured analysis vs conversational follow-up)

---

## Adapting to Other Domains

This architecture is domain-agnostic. To adapt it:

1. Replace `fetch_news_api.py` with your data source
2. Update the AI prompt in `run_structured_analysis()`
3. Update the whitelist in `WHITELISTED_SOURCES`
4. Update scope keywords in `router_node()`

The vector search, agent framework, and audit logging require zero changes.

---

## Security Notes

- `.env` is excluded from Git via `.gitignore`
- All AI inference runs locally via Ollama — no data sent externally
- Audit log captures every AI interaction for compliance
- Whitelist restricts external searches to approved domains only

---

## Free API Alternatives

| Current | Free Alternative |
|---|---|
| NewsAPI | RSS feeds, GDELT Project |
| Tavily | DuckDuckGo Search API |
| Yahoo Finance | Alpha Vantage (free tier) |
| Bank of Canada | Any central bank public API |

---

## License

MIT License — free to use, modify and distribute.

---

*Built as a Proof of Concept for Global Asset Management Group — March 2026*
