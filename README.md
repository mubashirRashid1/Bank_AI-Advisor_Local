# 🏦 Canadian Bank AI Advisor — POC

An AI-powered wealth advisory platform built on Snowflake Cortex,
LangGraph and Semantic RAG. Enables advisors and managers to ask
plain-English questions about clients, market conditions and
portfolio risk — with full audit logging for compliance.

---

## Architecture
```
External Sources → Pipeline → Data Store → AI Layer → Dashboard
```

- **Data pipeline** — NewsAPI, Tavily, Yahoo Finance, Bank of Canada
- **AI enrichment** — sentiment, summary, embeddings via Snowflake Cortex
- **Semantic search** — vector similarity via Cortex Search Service
- **Dashboard** — 6-tab Streamlit app (News, Prices, Portfolio, Research, AI Chat, AI Agent)
- **LangGraph Agent** — conversational AI with memory and audit logging
- **Compliance** — every AI decision logged to Snowflake audit table

---

## Setup

### Prerequisites
- Python 3.11+
- Snowflake account
- NewsAPI key
- Tavily API key

### Installation
```bash
git clone https://github.com/YOUR_USERNAME/bank-poc-ai-advisor.git
cd bank-poc-ai-advisor

python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate      # Mac/Linux

pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the root directory:
```
SNOWFLAKE_ACCOUNT=your_account
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_DATABASE=BANK_POC
SNOWFLAKE_SCHEMA=EXTERNAL_DATA
SNOWFLAKE_WAREHOUSE=your_warehouse

NEWSAPI_KEY=your_newsapi_key
TAVILY_API_KEY=your_tavily_key
```

### Snowflake Setup

Run the SQL setup scripts in Snowflake in this order:
1. Create database and schemas
2. Create external tables (NEWS_RAW, NEWS_ENRICHED, MARKET_PRICES, BOC_RATES)
3. Create internal tables (CUSTOMERS, PORTFOLIOS, HOLDINGS)
4. Create audit table (AI_AUDIT_LOG)
5. Generate mock data: `python generate_mock_data.py`
6. Create Cortex Search Service

### Run the Pipeline
```bash
python master_pipeline.py
```

### Launch the Dashboard
```bash
streamlit run dashboard.py
```

Open `http://localhost:8501`

---

## Project Structure
```
bank-poc-ai-advisor/
├── dashboard.py          # Main Streamlit dashboard
├── agent.py              # LangGraph conversational agent
├── db.py                 # Shared database functions
├── master_pipeline.py    # Master data pipeline
├── fetch_news_api.py     # NewsAPI ingestion
├── fetch_tavily_news.py  # Tavily ingestion
├── fetch_boc_rates.py    # Bank of Canada rates
├── fetch_market_prices.py# Yahoo Finance prices
├── generate_mock_data.py # Mock customer data generator
├── requirements.txt      # Python dependencies
├── .gitignore            # Git ignore rules
└── README.md             # This file
```

---

## Features

### Tab 5 — AI Chat
- Semantic RAG with Snowflake Cortex Search
- Automatic whitelisted fallback for thin data
- Structured 6-section analysis
- Customer and manager modes
- Multi-model selector (GPT, Claude, Mistral, Llama)

### Tab 6 — AI Agent
- LangGraph state machine with 7 nodes
- Conversational memory across turns
- Live reasoning log
- Snowflake audit log for compliance
- Follow-up question detection

---

## Security

- All data stays inside Snowflake — no customer data sent externally
- AI inference runs inside Snowflake Cortex
- Every AI decision logged to AI_AUDIT_LOG table
- Whitelisted sources only for external search fallback

---

## Disclaimer

This is a Proof of Concept for demonstration purposes.
Not intended for production use without additional
security hardening, authentication, and compliance review.

---

*Built for Global Asset Management Group — Internal POC*