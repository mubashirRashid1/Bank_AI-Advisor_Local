# ── db.py — Local SQLite + ChromaDB + Ollama (no Snowflake) ──────
import sqlite3
import pandas as pd
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH      = os.getenv('DB_PATH',         'bank_poc.db')
CHROMA_PATH  = os.getenv('CHROMA_PATH',     'chroma_db')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL',    'llama3.2:1b')
OLLAMA_URL   = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')

# ── SQLite Connection ─────────────────────────────────────────────
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_query(query, params=None):
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows    = cursor.fetchall()
        return pd.DataFrame(
            [dict(zip(columns, tuple(r))) for r in rows],
            columns=columns
        )
    except Exception as e:
        raise e
    finally:
        cursor.close()
        conn.close()

def run_query_cached(query, params=None):
    return run_query(query, params)

def run_execute(query, params=None):
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

# ── Ollama AI Inference — uses REST API directly ──────────────────
def run_cortex(prompt, model=None):
    """Call local Ollama via HTTP REST."""
    model = model or OLLAMA_MODEL
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":    model,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False
            },
            timeout=300   # ← increase from 120 to 300 seconds
        )
        response.raise_for_status()
        data = response.json()

        message = data.get("message")
        if message is None:
            raise Exception(f"No message in response: {data}")
        content = message.get("content")
        if content is None:
            raise Exception(f"No content in message: {message}")
        return str(content)

    except requests.exceptions.ConnectionError:
        raise Exception(
            "Ollama is not running. Start with: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise Exception(
            "Ollama timed out. The model is taking too long. "
            "Try switching to llama3.2:1b in .env"
        )
    except Exception as e:
        raise Exception(f"Ollama inference failed: {e}")

# ── Embedding Generation ──────────────────────────────────────────
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model

def generate_embedding(text):
    model = get_embedding_model()
    return model.encode(str(text or '')).tolist()

# ── ChromaDB Vector Search ────────────────────────────────────────
_chroma_client     = None
_chroma_collection = None

def get_chroma_collection():
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        import chromadb
        _chroma_client     = chromadb.PersistentClient(path=CHROMA_PATH)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name     = "news_articles",
            metadata = {"hnsw:space": "cosine"}
        )
    return _chroma_collection

def add_to_vector_index(doc_id, text, metadata=None):
    """Add document to ChromaDB — resets cache on failure and retries."""
    global _chroma_client, _chroma_collection

    text = str(text or '').strip() or "empty document"
    embedding = [float(x) for x in generate_embedding(text)]

    safe_meta = {}
    if metadata:
        for k, v in metadata.items():
            k = str(k)
            if v is None:
                safe_meta[k] = ''
            elif isinstance(v, (int, float)):
                safe_meta[k] = v
            else:
                safe_meta[k] = str(v)[:500]

    def do_upsert():
        collection = get_chroma_collection()
        collection.upsert(
            ids        = [str(doc_id)],
            embeddings = [embedding],
            documents  = [text[:1000]],
            metadatas  = [safe_meta]
        )

    try:
        do_upsert()
    except Exception as first_err:
        # Reset cached collection and retry once
        try:
            _chroma_collection = None
            _chroma_client     = None
            do_upsert()
        except Exception as retry_err:
            raise Exception(
                f"ChromaDB upsert failed after retry: {retry_err}"
            )
            
def semantic_search_chroma(query, limit=8):
    """Search ChromaDB by semantic similarity."""
    try:
        collection = get_chroma_collection()

        count = collection.count()
        if count == 0:
            return []

        n = min(limit, count)
        embedding = generate_embedding(query)

        results = collection.query(
            query_embeddings = [embedding],
            n_results        = n,
            include          = ["documents", "metadatas", "distances"]
        )

        if not results:
            return []

        # Safely extract lists — default to empty list if None
        metadatas = results.get('metadatas') or []
        distances = results.get('distances') or []

        # ChromaDB wraps results in outer list — unwrap safely
        meta_list = metadatas[0] if metadatas and len(metadatas) > 0 else []
        dist_list = distances[0] if distances and len(distances) > 0 else []

        if not meta_list:
            return []

        articles = []
        for i in range(len(meta_list)):
            meta = meta_list[i]
            if meta is None:
                meta = {}

            # Safely get distance
            try:
                dist = float(dist_list[i]) if i < len(dist_list) else 0.0
            except (TypeError, IndexError, ValueError):
                dist = 0.0

            articles.append({
                'TITLE':          str(meta.get('title',        '') or ''),
                'SUMMARY':        str(meta.get('summary',      '') or ''),
                'SENTIMENT':      str(meta.get('sentiment',    'NEUTRAL') or 'NEUTRAL'),
                'SOURCE':         str(meta.get('source',       '') or ''),
                'URL':            str(meta.get('url',          '') or ''),
                'PUBLISHED_AT':   str(meta.get('published_at', '') or ''),
                'ASSET_CLASSES':  str(meta.get('asset_classes','') or ''),
                'RELEVANCE_SCORE':round(1 - dist, 3)
            })

        return articles

    except Exception as e:
        print(f"ChromaDB search error: {e}")
        import traceback
        traceback.print_exc()
        return []
        
# ── Database Initialisation ───────────────────────────────────────
def init_database():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS NEWS_RAW (
            ID           TEXT PRIMARY KEY,
            SOURCE       TEXT,
            TITLE        TEXT,
            CONTENT      TEXT,
            URL          TEXT UNIQUE,
            PUBLISHED_AT TEXT,
            CREATED_AT   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS NEWS_ENRICHED (
            ID              TEXT PRIMARY KEY,
            NEWS_RAW_ID     TEXT,
            SUMMARY         TEXT,
            SENTIMENT       TEXT,
            ENTITIES        TEXT,
            ASSET_CLASSES   TEXT,
            RELEVANCE_SCORE REAL DEFAULT 0.8,
            CREATED_AT      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (NEWS_RAW_ID) REFERENCES NEWS_RAW(ID)
        );
        CREATE TABLE IF NOT EXISTS MARKET_PRICES (
            ID           TEXT PRIMARY KEY,
            TICKER       TEXT,
            COMPANY_NAME TEXT,
            PRICE        REAL,
            CHANGE_PCT   REAL,
            VOLUME       REAL,
            PRICE_DATE   TEXT,
            CREATED_AT   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS BOC_RATES (
            ID           TEXT PRIMARY KEY,
            SERIES_CODE  TEXT,
            SERIES_NAME  TEXT,
            RATE_VALUE   REAL,
            RATE_DATE    TEXT,
            CREATED_AT   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS CUSTOMERS (
            CUSTOMER_ID          TEXT PRIMARY KEY,
            CUSTOMER_NAME        TEXT,
            SEGMENT              TEXT,
            RISK_PROFILE         TEXT,
            TOTAL_AUM            REAL,
            CITY                 TEXT,
            EMAIL                TEXT,
            CONTACT_NAME         TEXT,
            RELATIONSHIP_MANAGER TEXT,
            CREATED_AT           TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS PORTFOLIOS (
            PORTFOLIO_ID   TEXT PRIMARY KEY,
            CUSTOMER_ID    TEXT,
            PORTFOLIO_NAME TEXT,
            ACCOUNT_TYPE   TEXT,
            CREATED_AT     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (CUSTOMER_ID) REFERENCES CUSTOMERS(CUSTOMER_ID)
        );
        CREATE TABLE IF NOT EXISTS HOLDINGS (
            HOLDING_ID     TEXT PRIMARY KEY,
            PORTFOLIO_ID   TEXT,
            SECURITY_NAME  TEXT,
            TICKER         TEXT,
            ASSET_CLASS    TEXT,
            SECTOR         TEXT,
            QUANTITY       REAL,
            AVERAGE_COST   REAL,
            CURRENT_PRICE  REAL,
            CURRENT_VALUE  REAL,
            UNREALIZED_PNL REAL,
            WEIGHT_PCT     REAL,
            CREATED_AT     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (PORTFOLIO_ID) REFERENCES PORTFOLIOS(PORTFOLIO_ID)
        );
        CREATE TABLE IF NOT EXISTS AI_AUDIT_LOG (
            AUDIT_ID         TEXT PRIMARY KEY,
            TIMESTAMP        TEXT DEFAULT (datetime('now')),
            ADVISOR_NAME     TEXT,
            CUSTOMER_NAME    TEXT,
            QUERY_TYPE       TEXT,
            USER_QUESTION    TEXT,
            TOOLS_CALLED     TEXT,
            SEARCH_ATTEMPTS  INTEGER,
            NEWS_TITLES      TEXT,
            HOLDINGS_TICKERS TEXT,
            RATES_USED       TEXT,
            PRICES_USED      TEXT,
            MODEL_USED       TEXT,
            AI_RESPONSE      TEXT,
            REASONING_LOG    TEXT,
            NEWS_COUNT       INTEGER,
            HOLDINGS_COUNT   INTEGER
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Database initialised:", DB_PATH)

init_database()