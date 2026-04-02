# Setup Guide — Step by Step

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB | 16 GB |
| Storage | 5 GB free | 10 GB free |
| OS | Windows 10 | Windows 11 |
| Python | 3.11 | 3.11+ |

---

## Step 1 — Install Python

Download Python 3.11 from [python.org](https://python.org).

During installation check **"Add Python to PATH"**.

Verify:
```bash
python --version
pip --version
```

---

## Step 2 — Install Ollama

Download from [ollama.com/download](https://ollama.com/download).

After installation pull the recommended model:
```bash
ollama pull llama3.2:1b
```

Verify Ollama is running:
```bash
ollama list
```

If not running, start it:
```bash
ollama serve
```

---

### 3. Create virtual environment and install dependencies
```bash
git clone https://github.com/YOUR_USERNAME/Bank_AI-Advisor_Local.git
cd Bank_AI-Advisor_Local
python -m venv venv
venv\Scripts\activate
```

**Important — install numpy first before everything else:**
```bash
pip install numpy==1.26.4
pip install -r requirements.txt
```

Verify sentence-transformers works before proceeding:
```bash
python -c "from sentence_transformers import SentenceTransformer; print('OK')"
```

**If you see a numpy or importlib error** — the venv has a conflict.
Create a fresh one with a different name:
```bash
deactivate
python -m venv venv2
venv2\Scripts\activate
pip install numpy==1.26.4
pip install -r requirements.txt
python -c "from sentence_transformers import SentenceTransformer; print('OK')"
```

Use `venv2\Scripts\activate` going forward instead of `venv\Scripts\activate`.
```

---

## Also Update `requirements.txt` — Pin numpy at the top
```
# ── INSTALL THIS FIRST before everything else ─────────────────────
# pip install numpy==1.26.4
# pip install -r requirements.txt
numpy==1.26.4

# ── Web framework ──────────────────────────────────────────────────
streamlit

# ── Data ───────────────────────────────────────────────────────────
pandas
plotly
yfinance

# ── AI / ML ────────────────────────────────────────────────────────
sentence-transformers
chromadb
ollama

# ── Agent framework ────────────────────────────────────────────────
langgraph
langchain
langchain-core

# ── Data sources ───────────────────────────────────────────────────
newsapi-python
requests

# ── Utilities ──────────────────────────────────────────────────────
python-dotenv

## Step 4 — Create .env File

Create a file named `.env` in the project root:

```
NEWSAPI_KEY=your_key_here
TAVILY_API_KEY=your_key_here
OLLAMA_MODEL=llama3.2:1b
OLLAMA_BASE_URL=http://localhost:11434
DB_PATH=bank_poc.db
CHROMA_PATH=chroma_db
```

### Get Free API Keys

**NewsAPI** (free tier — 100 requests/day):
1. Go to [newsapi.org](https://newsapi.org)
2. Click Get API Key
3. Copy the key to `.env`

**Tavily** (free tier — 1000 requests/month):
1. Go to [tavily.com](https://tavily.com)
2. Sign up and get API key
3. Copy the key to `.env`

---

## Step 5 — Initialise the Database

```bash
python generate_mock_data.py
```

Expected output:
```
✅ Database initialised: bank_poc.db
✅ Mock data generation complete!
   Customers:  1,000
   Portfolios: ~2,000
   Holdings:   ~10,000
```

---

## Step 6 — Run the Pipeline

```bash
python master_pipeline.py
```

This fetches live news, rates and market prices.
First run takes 5-10 minutes due to Ollama enrichment.

---

## Step 7 — Launch

```bash
streamlit run dashboard.py
```

Open browser at: `http://localhost:8501`

---

## Troubleshooting

| Error | Fix |
|---|---|
| `ollama: command not found` | Restart terminal after installing Ollama |
| `Ollama is not running` | Run `ollama serve` in a separate terminal |
| `No customers found` | Run `python generate_mock_data.py` |
| `No news articles` | Run `python master_pipeline.py` |
| `Module not found` | Run `pip install -r requirements.txt` |
| `NoneType error in ChromaDB` | Run `python enrich_news.py` to rebuild index |
| Error | Fix |
|---|---|
| `NoneType is not subscriptable` in sentence-transformers | Run: `pip uninstall numpy -y` then `pip install numpy==1.26.4` |
| `Unable to compare versions for numpy` | Same as above — numpy version conflict |
| `importlib_metadata` TypeError | Run: `pip uninstall importlib-metadata huggingface-hub transformers sentence-transformers -y` then `pip install numpy==1.26.4 sentence-transformers` |
| venv cannot be deleted on Windows | Create venv2: `python -m venv venv2` and use that instead |

