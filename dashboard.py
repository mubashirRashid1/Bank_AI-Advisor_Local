# ── dashboard.py — Local SQLite + ChromaDB + Ollama version ──────
import streamlit as st
import pandas as pd
import uuid
import json
import os
import requests
from datetime import datetime, date
from dotenv import load_dotenv

from db import (
    run_query, run_execute, run_cortex,
    semantic_search_chroma, add_to_vector_index,
    generate_embedding, get_connection
)

load_dotenv()

OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2:1b')

# ── Page Config ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Canadian Bank AI Advisor",
    page_icon="🏦",
    layout="wide"
)

# ── Styling ───────────────────────────────────────────────────────
st.markdown("""
    <style>
        .main { background-color: #f5f7fa; }
        .block-container { padding-top: 1rem; }
        .stTextArea textarea { font-size: 16px; }
        .news-card {
            background: white;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid #d32f2f;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .saved-badge {
            background: #e8f5e9;
            color: #2e7d32;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .skipped-badge {
            background: #fff3e0;
            color: #e65100;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
    </style>
""", unsafe_allow_html=True)

# ── Cached Sidebar Queries ────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def cached_query(query, params=None):
    return run_query(query, params)

# ── Models Available (local Ollama) ───────────────────────────────
# REPLACE WITH THIS
MODELS = {
    "Claude Haiku — Fast & Smart":      "claude-haiku-4-5-20251001",
    "Claude Sonnet — Balanced":         "claude-sonnet-4-6",
    "Llama 3.2 1B — Local Lightweight": "llama3.2:1b",
    "Mistral — Local General Purpose":  "mistral",
    "Llama 3.1 8B — Local Balanced":    "llama3.1:8b",
}

# ── Semantic Search with ChromaDB ────────────────────────────────
WHITELISTED_SOURCES = [
    "bankofcanada.ca",
    "osfi-bsif.gc.ca",
    "bnnbloomberg.ca",
    "financialpost.com",
    "theglobeandmail.com",
    "reuters.com",
    "pensionsandinvestments.com"
]

def has_relevant_results(articles, query):
    if not articles:
        return False
    COMMON_WORDS = {
        "canadian","canada","market","fund","rate","bank",
        "financial","portfolio","investment","stock","equity",
        "today","year","latest","news","will","with","this",
        "that","from","what","have","been","their","which",
        "about","more","also","data","percent","growth","global"
    }
    query_words = set([
        w.lower() for w in query.split()
        if len(w) > 5 and w.lower() not in COMMON_WORDS
    ])
    if not query_words:
        return False

    match_count = 0
    for r in articles:
        combined = (
            str(r.get('TITLE',   '') or '') + " " +
            str(r.get('SUMMARY', '') or '')
        ).lower()
        matches = sum(1 for w in query_words if w in combined)
        if matches / len(query_words) >= 0.3:
            match_count += 1

    return match_count >= 2

def search_whitelisted_sources(query, limit=5):
    tavily_key = os.getenv('TAVILY_API_KEY')
    if not tavily_key:
        return 0, 0, []
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            headers={"Content-Type": "application/json"},
            json={
                "api_key":         tavily_key,
                "query":           query,
                "search_depth":    "basic",
                "max_results":     limit,
                "include_answer":  False,
                "include_domains": WHITELISTED_SOURCES
            },
            timeout=30
        )
        response.raise_for_status()
        articles = response.json().get('results', [])

        saved = 0
        for article in articles:
            try:
                status = save_article_to_db(
                    title   = article.get('title',   ''),
                    content = article.get('content', ''),
                    url     = article.get('url',     ''),
                    source  = article.get('url','').split('/')[2]
                               .replace('www.','') if article.get('url') else ''
                )
                if status == "saved":
                    saved += 1
            except Exception:
                pass

        return saved, len(articles), articles
    except Exception:
        return 0, 0, []

def semantic_search_news(query, limit=8):
    MINIMUM_RESULTS = 3

    try:
        # ChromaDB semantic search
        articles = semantic_search_chroma(query, limit=limit)

        if (len(articles) >= MINIMUM_RESULTS
                and has_relevant_results(articles, query)):
            return pd.DataFrame(articles), "semantic"

        # Whitelist fallback
        saved, found, raw_articles = search_whitelisted_sources(
            query, limit=5
        )

        if raw_articles:
            whitelist_df = pd.DataFrame([{
                'TITLE':          str(a.get('title',   '') or ''),
                'SUMMARY':        str(a.get('content', '') or '')[:300],
                'SENTIMENT':      'NEUTRAL',
                'SOURCE':         str(a.get('url','').split('/')[2]
                                   .replace('www.','')) if a.get('url') else '',
                'URL':            str(a.get('url', '') or ''),
                'PUBLISHED_AT':   datetime.now().strftime('%Y-%m-%d'),
                'ASSET_CLASSES':  'GENERAL',
                'RELEVANCE_SCORE':0.7
            } for a in raw_articles])
            return whitelist_df, "whitelisted_fallback"

        return pd.DataFrame(articles), "semantic"

    except Exception as e:
        st.warning(f"Semantic search failed, using keyword search: {e}")
        try:
            df = run_query("""
                SELECT r.TITLE, e.SENTIMENT, e.SUMMARY,
                       r.SOURCE, r.URL,
                       r.PUBLISHED_AT,
                       e.ASSET_CLASSES,
                       e.RELEVANCE_SCORE
                FROM NEWS_ENRICHED e
                JOIN NEWS_RAW r ON e.NEWS_RAW_ID = r.ID
                ORDER BY e.RELEVANCE_SCORE DESC
                LIMIT ?
            """, (limit,))
            return df, "keyword_fallback"
        except Exception:
            return pd.DataFrame(), "keyword_fallback"

# ── Structured AI Analysis ────────────────────────────────────────
def run_structured_analysis(
    user_query, customer_name, holdings_text,
    news_text, rates_text, prices_text,
    model=None, query_type='customer'
):
    model = model or OLLAMA_MODEL

    followup_keywords = [
    'tell me more','elaborate','explain','what about',
    'why','how about','can you','what if','more detail',
    'expand','clarify','and what','so what','but what',
    'which one','what specifically','how would','what would',
    'give me more','what does','can you explain'
    ]
    is_followup = any(kw in user_query.lower()
                  for kw in followup_keywords)

    if is_followup:
        prompt = (
        "You are a senior Canadian wealth management AI advisor "
        "having a natural conversation. "
        "Answer in plain conversational prose only. "
        "Do NOT use any headers, numbered sections "
        "or bullet points whatsoever. "
        "Write naturally as if speaking directly to the advisor. "
        "Be specific. Keep to 2-4 paragraphs maximum.\n\n"
        "QUESTION: " + user_query + "\n\n"
        "CONTEXT:\n" + news_text + "\n\n"
        "RATES:\n" + rates_text + "\n\n"
        "HOLDINGS:\n" + holdings_text
        )

    elif query_type == 'manager':
        prompt = (
            "You are a senior Canadian wealth management AI advisor "
            "briefing a portfolio manager. "
            "Answer using ONLY the data provided. "
            "Be specific, cite actual numbers. "
            "Do not reference any individual customer.\n\n"
            "QUESTION: " + user_query + "\n\n"
            "LATEST NEWS:\n" + news_text + "\n\n"
            "BANK OF CANADA RATES:\n" + rates_text + "\n\n"
            "MARKET PRICES:\n" + prices_text + "\n\n"
            "Respond using EXACTLY this structure:\n"
            "## 1. MARKET SITUATION TODAY\n"
            "## 2. TOP 3 RISKS FOR WEALTH PORTFOLIOS\n"
            "## 3. SECTORS MOST AFFECTED\n"
            "## 4. RECOMMENDED ADVISOR ACTIONS\n"
            "## 5. CLIENT SEGMENTS TO PRIORITIZE\n"
            "## 6. URGENCY SCORE\nScore: X/10\nRationale: ..."
        )
    else:
        prompt = (
            "You are a senior Canadian wealth management AI advisor. "
            "Analyze using ONLY the data provided. "
            "Be specific, cite actual numbers.\n\n"
            "QUESTION: " + user_query + "\n\n"
            "CUSTOMER: " + customer_name + "\n\n"
            "HOLDINGS:\n" + holdings_text + "\n\n"
            "LATEST NEWS:\n" + news_text + "\n\n"
            "BANK OF CANADA RATES:\n" + rates_text + "\n\n"
            "MARKET PRICES:\n" + prices_text + "\n\n"
            "Respond using EXACTLY this structure:\n"
            "## 1. SITUATION SUMMARY\n"
            "## 2. CUSTOMER IMPACT ASSESSMENT\n"
            "## 3. REGULATORY & COMPLIANCE FLAGS\n"
            "## 4. RECOMMENDED ACTIONS\n"
            "## 5. CLIENT TALKING POINTS\n"
            "## 6. URGENCY SCORE\nScore: X/10\nRationale: ..."
        )

    return run_cortex(prompt, model)

# ── Save Article to SQLite + ChromaDB ────────────────────────────
def save_article_to_db(title, content, url, source):
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM NEWS_RAW WHERE URL = ?", (url,)
        )
        exists = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        if exists:
            return "skipped"

        news_id = str(uuid.uuid4())
        run_execute("""
            INSERT INTO NEWS_RAW
                (ID, SOURCE, TITLE, CONTENT, URL, PUBLISHED_AT)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            news_id,
            str(source or '')[:100],
            str(title  or '')[:1000],
            str(content or ''),
            str(url    or '')[:2000],
            datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        ))

        # Quick enrichment with Ollama
        enrich_prompt = (
            "You are a Canadian financial analyst. "
            "Analyze this news and respond in JSON only. "
            "No explanation, no markdown. "
            "Title: " + str(title)[:200] + " "
            "Content: " + str(content)[:300] + " "
            'Return: {"summary":"2-3 sentences",'
            '"sentiment":"POSITIVE or NEGATIVE or NEUTRAL",'
            '"asset_class":"EQUITIES or BONDS or FX or '
            'REAL_ESTATE or GENERAL"}'
        )

        try:
            raw      = run_cortex(enrich_prompt)
            raw      = raw.replace('```json','').replace('```','').strip()
            start    = raw.find('{')
            end      = raw.rfind('}') + 1
            enriched = json.loads(raw[start:end]) \
                       if start >= 0 and end > start else {}
        except Exception:
            enriched = {}

        summary     = str(enriched.get('summary',    title) or title)[:2000]
        sentiment   = str(enriched.get('sentiment',  'NEUTRAL') or 'NEUTRAL')
        asset_class = str(enriched.get('asset_class','GENERAL') or 'GENERAL')
        enrich_id   = str(uuid.uuid4())

        run_execute("""
            INSERT INTO NEWS_ENRICHED
                (ID, NEWS_RAW_ID, SUMMARY, SENTIMENT,
                 ENTITIES, ASSET_CLASSES, RELEVANCE_SCORE)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            enrich_id, news_id, summary, sentiment,
            json.dumps({'source': source}),
            json.dumps([asset_class]), 0.90
        ))

        # Add to ChromaDB immediately
        add_to_vector_index(
            doc_id   = enrich_id,
            text     = (str(title) + " " + summary).strip(),
            metadata = {
                'title':         str(title   or ''),
                'summary':       summary,
                'sentiment':     sentiment,
                'source':        str(source  or ''),
                'url':           str(url     or ''),
                'published_at':  datetime.now().strftime('%Y-%m-%d'),
                'asset_classes': asset_class
            }
        )
        return "saved"

    except Exception as e:
        raise e

# ── Header ────────────────────────────────────────────────────────
col_logo, col_title = st.columns([1, 8])
with col_logo:
    st.markdown("# 🏦")
with col_title:
    st.markdown("# Canadian Bank AI Advisor")
    st.markdown(
        "*Powered by Local AI (Ollama) + ChromaDB + SQLite*"
    )

st.divider()

# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")

    st.markdown("### 👔 Advisor")
    try:
        advisors_df  = cached_query("""
            SELECT DISTINCT RELATIONSHIP_MANAGER
            FROM CUSTOMERS
            WHERE RELATIONSHIP_MANAGER IS NOT NULL
            ORDER BY RELATIONSHIP_MANAGER
        """)
        advisor_list = ["ALL CUSTOMERS"] + \
                       advisors_df['RELATIONSHIP_MANAGER'].tolist()
    except Exception:
        advisor_list = ["ALL CUSTOMERS"]

    selected_advisor = st.selectbox("You are logged in as", advisor_list)

    if selected_advisor != "ALL CUSTOMERS":
        try:
            advisor_stats = cached_query("""
                SELECT
                    COUNT(*)            AS TOTAL_CUSTOMERS,
                    SUM(TOTAL_AUM)      AS TOTAL_AUM,
                    COUNT(DISTINCT SEGMENT) AS SEGMENTS
                FROM CUSTOMERS
                WHERE RELATIONSHIP_MANAGER = ?
            """, (selected_advisor,))
            row = advisor_stats.iloc[0]
            st.markdown(f"""
                <div style="background:#1e293b;border-radius:8px;
                            padding:12px;margin-top:8px;
                            border-left:3px solid #22c55e">
                    <div style="font-size:13px;font-weight:700;
                                color:#f8fafc;margin-bottom:6px">
                        👔 {selected_advisor}
                    </div>
                    <div style="font-size:11px;color:#94a3b8;
                                line-height:1.8">
                        👥 {int(row['TOTAL_CUSTOMERS'])} customers<br>
                        💰 ${row['TOTAL_AUM']:,.0f} total AUM<br>
                        📊 {int(row['SEGMENTS'])} segments
                    </div>
                </div>
            """, unsafe_allow_html=True)
        except Exception:
            pass

    advisor_where = (
        "1=1" if selected_advisor == "ALL CUSTOMERS"
        else f"RELATIONSHIP_MANAGER = '{selected_advisor}'"
    )

    st.markdown("---")
    st.markdown("### 🎯 Filter Customers")

    selected_segment = st.selectbox(
        "Segment",
        ["ALL","RETAIL","WEALTH","CORPORATE",
         "SMALL_BUSINESS","PRIVATE_BANKING"]
    )
    selected_risk = st.selectbox(
        "Risk Profile",
        ["ALL","CONSERVATIVE","MODERATE","GROWTH","AGGRESSIVE"]
    )

    aum_ranges = {
        "ALL":           (0, 999_999_999),
        "Under $100K":   (0, 100_000),
        "$100K–$500K":   (100_000, 500_000),
        "$500K–$2M":     (500_000, 2_000_000),
        "$2M–$10M":      (2_000_000, 10_000_000),
        "Over $10M":     (10_000_000, 999_999_999),
    }
    selected_aum_label = st.selectbox("AUM Range", list(aum_ranges.keys()))
    aum_min, aum_max   = aum_ranges[selected_aum_label]

    filter_conditions = [advisor_where]
    if selected_segment != "ALL":
        filter_conditions.append(f"SEGMENT = '{selected_segment}'")
    if selected_risk != "ALL":
        filter_conditions.append(f"RISK_PROFILE = '{selected_risk}'")
    filter_conditions.append(
        f"TOTAL_AUM BETWEEN {aum_min} AND {aum_max}"
    )
    filter_where = " AND ".join(filter_conditions)

    st.markdown("---")
    st.markdown("### 🔍 Find Customer")
    search_term = st.text_input(
        "Search by name", placeholder="e.g. John, Smith..."
    )

    try:
        search_clause = ""
        if search_term and len(search_term) >= 2:
            s = search_term.replace("'","''")
            search_clause = (
                f"AND (LOWER(CUSTOMER_NAME) LIKE LOWER('%{s}%') "
                f"OR LOWER(EMAIL) LIKE LOWER('%{s}%'))"
            )

        customers_df = cached_query(f"""
            SELECT CUSTOMER_ID, CUSTOMER_NAME, SEGMENT,
                   RISK_PROFILE, TOTAL_AUM, CITY, EMAIL,
                   CONTACT_NAME, RELATIONSHIP_MANAGER
            FROM CUSTOMERS
            WHERE {filter_where}
            {search_clause}
            ORDER BY TOTAL_AUM DESC
            LIMIT 50
        """)

        if customers_df.empty:
            st.warning("No customers match filters.")
            selected_customer = None
            customer_row      = None
        else:
            if search_term and len(search_term) >= 2:
                st.success(f"🔍 {len(customers_df)} match(es)")
            else:
                st.caption(f"Top {len(customers_df)} by AUM")

            selected_customer = st.selectbox(
                "Select Customer",
                customers_df['CUSTOMER_NAME'].tolist(),
                label_visibility="collapsed"
            )
            customer_row = customers_df[
                customers_df['CUSTOMER_NAME'] == selected_customer
            ].iloc[0]

            st.markdown(f"""
                <div style="background:#1e293b;border-radius:8px;
                            padding:12px;margin-top:8px;
                            border-left:3px solid #fbbf24">
                    <div style="font-size:13px;font-weight:700;
                                color:#f8fafc;margin-bottom:6px">
                        {selected_customer}
                    </div>
                    <div style="font-size:11px;color:#94a3b8;
                                line-height:1.8">
                        📌 {customer_row['SEGMENT']}<br>
                        ⚡ {customer_row['RISK_PROFILE']}<br>
                        💰 ${customer_row['TOTAL_AUM']:,.0f} AUM<br>
                        📍 {customer_row['CITY']}<br>
                        👤 {customer_row['RELATIONSHIP_MANAGER']}
                    </div>
                </div>
            """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Could not load customers: {e}")
        selected_customer = None
        customer_row      = None

    st.markdown("---")
    st.markdown("### 📅 Data Status")
    try:
        today = date.today().isoformat()
        st.metric("👥 Customers",
            int(cached_query("SELECT COUNT(*) AS C FROM CUSTOMERS")['C'][0]))
        st.metric("📰 News Articles",
            int(cached_query("SELECT COUNT(*) AS C FROM NEWS_RAW")['C'][0]))
        st.metric("🤖 AI Enriched",
            int(cached_query("SELECT COUNT(*) AS C FROM NEWS_ENRICHED")['C'][0]))
        st.metric("📈 Prices Today",
            int(cached_query(
                f"SELECT COUNT(*) AS C FROM MARKET_PRICES WHERE PRICE_DATE = '{today}'"
            )['C'][0]))
    except Exception:
        st.warning("Could not load stats")

    st.markdown("---")
    st.markdown("*Built for Canadian Bank POC*")
    st.markdown("*Local: SQLite + ChromaDB + Ollama*")

# ── Tabs ──────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📰 News Feed",
    "📈 Market Prices",
    "💼 Customer Portfolio",
    "🔍 Tavily Research",
    "🤖 AI Chat",
    "🦾 AI Agent"
])

# ─────────────────────────────────────────────────────────────────
# TAB 1 — NEWS FEED
# ─────────────────────────────────────────────────────────────────
with tab1:
    st.markdown("## 📰 Latest Financial News")
    st.markdown("*AI-enriched news — local Ollama enrichment*")

    sentiment_filter = st.selectbox(
        "Filter by Sentiment",
        ["ALL","POSITIVE","NEGATIVE","NEUTRAL"]
    )
    sentiment_where = (
        f"AND e.SENTIMENT = '{sentiment_filter}'"
        if sentiment_filter != "ALL" else ""
    )

    try:
        news_df = run_query(f"""
            SELECT r.SOURCE, r.TITLE, r.URL,
                   e.SENTIMENT, e.SUMMARY,
                   e.ASSET_CLASSES AS ASSET_CLASS,
                   e.RELEVANCE_SCORE, r.PUBLISHED_AT
            FROM NEWS_ENRICHED e
            JOIN NEWS_RAW r ON e.NEWS_RAW_ID = r.ID
            WHERE 1=1 {sentiment_where}
            ORDER BY e.RELEVANCE_SCORE DESC, r.PUBLISHED_AT DESC
            LIMIT 20
        """)

        if news_df.empty:
            st.warning("No news articles found. Run the pipeline first.")
        else:
            for _, row in news_df.iterrows():
                sentiment = str(row['SENTIMENT'] or 'NEUTRAL')
                icon = ("🟢" if sentiment == "POSITIVE"
                        else "🔴" if sentiment == "NEGATIVE" else "🟡")
                st.markdown(f"""
                    <div class="news-card">
                        <div style="display:flex;
                                    justify-content:space-between;
                                    margin-bottom:6px">
                            <span style="font-weight:700;font-size:15px">
                                {row['TITLE']}
                            </span>
                            <span style="font-size:13px;color:#666">
                                {icon} {sentiment}
                            </span>
                        </div>
                        <div style="color:#444;font-size:14px;
                                    margin-bottom:6px">
                            {row['SUMMARY'] or 'No summary available'}
                        </div>
                        <div style="display:flex;gap:15px;
                                    font-size:12px;color:#888">
                            <span>📌 {row['SOURCE']}</span>
                            <span>🏷️ {row['ASSET_CLASS']}</span>
                            <span>⭐ {round(float(row['RELEVANCE_SCORE'] or 0),2)}</span>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Could not load news: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 2 — MARKET PRICES
# ─────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("## 📈 Live Market Prices")
    st.markdown("*Source: Yahoo Finance*")

    try:
        today     = date.today().isoformat()
        prices_df = run_query(f"""
            SELECT TICKER, COMPANY_NAME, PRICE,
                   CHANGE_PCT, VOLUME, PRICE_DATE
            FROM MARKET_PRICES
            WHERE PRICE_DATE = '{today}'
            ORDER BY ABS(CHANGE_PCT) DESC
        """)

        if prices_df.empty:
            st.warning("No prices today. Run: python master_pipeline.py")
        else:
            cols = st.columns(4)
            for i, (_, row) in enumerate(prices_df.head(4).iterrows()):
                with cols[i]:
                    st.metric(
                        label = str(row['COMPANY_NAME'])[:25],
                        value = f"${row['PRICE']:.2f}",
                        delta = f"{row['CHANGE_PCT']:+.2f}%"
                    )
            st.markdown("---")
            display_df = prices_df.copy()
            display_df['DIRECTION'] = display_df['CHANGE_PCT'].apply(
                lambda x: "🟢 Up" if x > 0 else "🔴 Down"
            )
            display_df['CHANGE_PCT'] = display_df['CHANGE_PCT'].apply(
                lambda x: f"{x:+.2f}%"
            )
            display_df['PRICE'] = display_df['PRICE'].apply(
                lambda x: f"${x:.2f}"
            )
            st.dataframe(
                display_df[[
                    'TICKER','COMPANY_NAME','PRICE',
                    'CHANGE_PCT','DIRECTION','PRICE_DATE'
                ]],
                use_container_width=True,
                hide_index=True
            )
    except Exception as e:
        st.error(f"Could not load prices: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 3 — CUSTOMER PORTFOLIO
# ─────────────────────────────────────────────────────────────────
with tab3:
    if not selected_customer:
        st.warning("⚠️ Please select a customer from the sidebar.")
    else:
        st.markdown(f"## 💼 Portfolio — {selected_customer}")
        try:
            portfolio_df = run_query("""
                SELECT
                    p.PORTFOLIO_NAME,
                    h.SECURITY_NAME, h.TICKER,
                    h.ASSET_CLASS,  h.SECTOR,
                    h.QUANTITY,     h.AVERAGE_COST,
                    h.CURRENT_PRICE,h.CURRENT_VALUE,
                    h.UNREALIZED_PNL, h.WEIGHT_PCT,
                    m.PRICE       AS MARKET_PRICE,
                    m.CHANGE_PCT  AS TODAY_CHANGE
                FROM CUSTOMERS c
                JOIN PORTFOLIOS p ON c.CUSTOMER_ID = p.CUSTOMER_ID
                JOIN HOLDINGS h   ON p.PORTFOLIO_ID = h.PORTFOLIO_ID
                LEFT JOIN MARKET_PRICES m
                    ON h.TICKER = m.TICKER
                    AND m.PRICE_DATE = date('now')
                WHERE c.CUSTOMER_NAME = ?
                ORDER BY p.PORTFOLIO_NAME, h.CURRENT_VALUE DESC
            """, (selected_customer,))

            if portfolio_df.empty:
                st.warning(f"No holdings found for {selected_customer}")
            else:
                total_value      = portfolio_df['CURRENT_VALUE'].sum()
                total_unrealized = portfolio_df['UNREALIZED_PNL'].sum()
                total_holdings   = len(portfolio_df)
                total_portfolios = portfolio_df['PORTFOLIO_NAME'].nunique()

                portfolio_df['TODAY_GAIN'] = portfolio_df.apply(
                    lambda r: (
                        (r['TODAY_CHANGE'] / 100) * r['CURRENT_VALUE']
                        if pd.notna(r['TODAY_CHANGE']) else 0
                    ), axis=1
                )
                today_gain = portfolio_df['TODAY_GAIN'].sum()

                unrealized_color = "#22c55e" if total_unrealized >= 0 \
                                   else "#ef4444"
                today_color      = "#22c55e" if today_gain >= 0 \
                                   else "#ef4444"
                unrealized_arrow = "▲" if total_unrealized >= 0 else "▼"
                today_arrow      = "▲" if today_gain >= 0 else "▼"

                st.markdown(f"""
                    <div style="display:grid;
                                grid-template-columns:repeat(5,1fr);
                                gap:12px;margin-bottom:20px">
                        <div style="background:white;border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid #1565c0;
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px;color:#888;
                                        letter-spacing:1px">TOTAL AUM</div>
                            <div style="font-size:22px;font-weight:800;
                                        color:#1565c0;margin-top:4px">
                                ${total_value:,.0f}</div>
                            <div style="font-size:11px;color:#888">CAD</div>
                        </div>
                        <div style="background:white;border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid {unrealized_color};
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px;color:#888;
                                        letter-spacing:1px">UNREALIZED P&L</div>
                            <div style="font-size:22px;font-weight:800;
                                        color:{unrealized_color};margin-top:4px">
                                {unrealized_arrow} ${abs(total_unrealized):,.0f}
                            </div>
                            <div style="font-size:11px;color:#888">all time</div>
                        </div>
                        <div style="background:white;border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid {today_color};
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px;color:#888;
                                        letter-spacing:1px">TODAY GAIN/LOSS</div>
                            <div style="font-size:22px;font-weight:800;
                                        color:{today_color};margin-top:4px">
                                {today_arrow} ${abs(today_gain):,.0f}
                            </div>
                            <div style="font-size:11px;color:#888">today</div>
                        </div>
                        <div style="background:white;border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid #f59e0b;
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px;color:#888;
                                        letter-spacing:1px">HOLDINGS</div>
                            <div style="font-size:22px;font-weight:800;
                                        color:#f59e0b;margin-top:4px">
                                {total_holdings}</div>
                            <div style="font-size:11px;color:#888">positions</div>
                        </div>
                        <div style="background:white;border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid #8b5cf6;
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px;color:#888;
                                        letter-spacing:1px">PORTFOLIOS</div>
                            <div style="font-size:22px;font-weight:800;
                                        color:#8b5cf6;margin-top:4px">
                                {total_portfolios}</div>
                            <div style="font-size:11px;color:#888">accounts</div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                st.markdown("---")
                import plotly.express as px

                chart_col1, chart_col2 = st.columns(2)
                with chart_col1:
                    st.markdown("#### 🥧 Asset Allocation")
                    asset_data = (
                        portfolio_df.groupby('ASSET_CLASS')['CURRENT_VALUE']
                        .sum().reset_index()
                    )
                    asset_data.columns = ['Asset Class','Value']
                    fig_pie = px.pie(
                        asset_data, names='Asset Class', values='Value',
                        color_discrete_sequence=[
                            '#3b82f6','#22c55e','#f59e0b',
                            '#8b5cf6','#ef4444','#06b6d4'
                        ], hole=0.4
                    )
                    fig_pie.update_layout(
                        margin=dict(t=0,b=0,l=0,r=0), height=280,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

                with chart_col2:
                    st.markdown("#### 🏭 Sector Breakdown")
                    sector_data = (
                        portfolio_df.groupby('SECTOR')['CURRENT_VALUE']
                        .sum().reset_index()
                        .sort_values('CURRENT_VALUE', ascending=True)
                    )
                    sector_data.columns = ['Sector','Value']
                    sector_data['Pct'] = (
                        sector_data['Value'] /
                        sector_data['Value'].sum() * 100
                    ).round(1)
                    fig_bar = px.bar(
                        sector_data, x='Value', y='Sector',
                        orientation='h',
                        color='Pct',
                        color_continuous_scale=['#dbeafe','#3b82f6','#1d4ed8'],
                        text=sector_data['Pct'].apply(lambda x: f"{x:.1f}%")
                    )
                    fig_bar.update_layout(
                        margin=dict(t=0,b=0,l=0,r=0), height=280,
                        showlegend=False, coloraxis_showscale=False,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)

                st.markdown("---")
                st.markdown("#### 📁 Holdings Detail")

                for portfolio in portfolio_df['PORTFOLIO_NAME'].unique():
                    pf_data  = portfolio_df[
                        portfolio_df['PORTFOLIO_NAME'] == portfolio
                    ].copy()
                    pf_total = pf_data['CURRENT_VALUE'].sum()
                    pf_pnl   = pf_data['UNREALIZED_PNL'].sum()

                    with st.expander(
                        f"📁 {portfolio}  —  "
                        f"${pf_total:,.0f}  |  P&L: ${pf_pnl:+,.0f}",
                        expanded=True
                    ):
                        display = pf_data.copy()
                        display['TODAY_CHANGE'] = display['TODAY_CHANGE'].apply(
                            lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A"
                        )
                        display['CURRENT_VALUE'] = display['CURRENT_VALUE'].apply(
                            lambda x: f"${x:,.0f}"
                        )
                        display['UNREALIZED_PNL'] = display['UNREALIZED_PNL'].apply(
                            lambda x: f"+${x:,.0f}" if x >= 0
                                      else f"-${abs(x):,.0f}"
                        )
                        display['AVERAGE_COST'] = display['AVERAGE_COST'].apply(
                            lambda x: f"${x:,.2f}"
                        )
                        display['WEIGHT_PCT'] = display['WEIGHT_PCT'].apply(
                            lambda x: f"{x:.1f}%"
                        )
                        st.dataframe(
                            display[[
                                'SECURITY_NAME','TICKER','ASSET_CLASS',
                                'SECTOR','QUANTITY','AVERAGE_COST',
                                'CURRENT_VALUE','UNREALIZED_PNL',
                                'TODAY_CHANGE','WEIGHT_PCT'
                            ]].rename(columns={
                                'SECURITY_NAME': 'Security',
                                'TICKER':        'Ticker',
                                'ASSET_CLASS':   'Class',
                                'SECTOR':        'Sector',
                                'QUANTITY':      'Qty',
                                'AVERAGE_COST':  'Avg Cost',
                                'CURRENT_VALUE': 'Value',
                                'UNREALIZED_PNL':'Unreal. P&L',
                                'TODAY_CHANGE':  'Today %',
                                'WEIGHT_PCT':    'Weight'
                            }),
                            use_container_width=True,
                            hide_index=True
                        )

                st.markdown("---")
                st.markdown("#### 📰 News Affecting This Portfolio")
                names    = portfolio_df['SECURITY_NAME'].tolist()
                keywords = []
                for name in names[:8]:
                    word = name.split()[0]
                    if len(word) > 3:
                        keywords.append(word.lower())

                if keywords:
                    kw_conditions = " OR ".join([
                        f"LOWER(r.TITLE) LIKE '%{kw}%'"
                        for kw in keywords[:6]
                    ])
                    try:
                        related_news = run_query(f"""
                            SELECT r.TITLE, r.SOURCE, r.URL,
                                   e.SENTIMENT, e.SUMMARY,
                                   r.PUBLISHED_AT
                            FROM NEWS_ENRICHED e
                            JOIN NEWS_RAW r ON e.NEWS_RAW_ID = r.ID
                            WHERE ({kw_conditions})
                            ORDER BY r.PUBLISHED_AT DESC
                            LIMIT 5
                        """)
                        if related_news.empty:
                            st.info("No related news found.")
                        else:
                            for _, news_row in related_news.iterrows():
                                sentiment  = str(news_row['SENTIMENT'] or 'NEUTRAL')
                                icon       = ("🟢" if sentiment == "POSITIVE"
                                              else "🔴" if sentiment == "NEGATIVE"
                                              else "🟡")
                                border_clr = ("#22c55e" if sentiment == "POSITIVE"
                                              else "#ef4444" if sentiment == "NEGATIVE"
                                              else "#f59e0b")
                                st.markdown(f"""
                                    <div style="background:white;padding:12px 16px;
                                                border-radius:8px;margin-bottom:8px;
                                                border-left:4px solid {border_clr};
                                                box-shadow:0 1px 3px rgba(0,0,0,0.05)">
                                        <div style="font-weight:600;font-size:13px;
                                                    color:#111;margin-bottom:4px">
                                            {icon} {news_row['TITLE']}
                                        </div>
                                        <div style="font-size:12px;color:#555;
                                                    margin-bottom:6px">
                                            {news_row['SUMMARY'] or ''}
                                        </div>
                                        <div style="font-size:11px;color:#888">
                                            📌 {news_row['SOURCE']}
                                        </div>
                                    </div>
                                """, unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Could not load related news: {e}")

        except Exception as e:
            st.error(f"Could not load portfolio: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 4 — TAVILY RESEARCH
# ─────────────────────────────────────────────────────────────────
with tab4:
    st.markdown("## 🔍 Real-Time Research")
    st.markdown(
        "*Search whitelisted sources — results saved "
        "to SQLite and indexed in ChromaDB*"
    )

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.info("🔍 You Search")
    col_b.info("🌍 Tavily Fetches")
    col_c.info("💾 Saved to SQLite")
    col_d.info("🧠 Ollama Enriches")

    st.markdown("---")

    search_query = st.text_input(
        "What would you like to research?",
        placeholder=(
            "e.g. Bank of Canada rate decision, "
            "TSX market today, Canadian housing..."
        )
    )

    if st.button("🔍 Search & Save", type="primary"):
        if not search_query:
            st.warning("Please enter a search query.")
        else:
            tavily_key = os.getenv('TAVILY_API_KEY')
            if not tavily_key:
                st.error("TAVILY_API_KEY not set in .env")
            else:
                with st.spinner(f"Searching '{search_query}'..."):
                    try:
                        response = requests.post(
                            "https://api.tavily.com/search",
                            headers={"Content-Type":"application/json"},
                            json={
                                "api_key":       tavily_key,
                                "query":         search_query,
                                "search_depth":  "advanced",
                                "max_results":   8,
                                "include_answer":True
                            },
                            timeout=30
                        )
                        response.raise_for_status()
                        data          = response.json()
                        answer        = data.get('answer')
                        articles      = data.get('results', [])
                        saved_count   = 0
                        skipped_count = 0

                        if answer:
                            st.markdown("### 🤖 AI Answer")
                            st.markdown("---")
                            st.markdown(answer)
                            st.markdown("---")

                        st.markdown("### 📰 Search Results")

                        for article in articles:
                            if not article:
                                continue
                            title   = str(article.get('title',   '') or '')
                            content = str(article.get('content', '') or '')
                            url     = str(article.get('url',     '') or '')
                            source  = url.split('/')[2].replace('www.','') \
                                      if url else 'Unknown'
                            try:
                                status = save_article_to_db(
                                    title, content, url, source
                                )
                                if status == "saved":
                                    saved_count += 1
                                    badge = (
                                        '<span class="saved-badge">'
                                        '✅ Saved & Indexed</span>'
                                    )
                                else:
                                    skipped_count += 1
                                    badge = (
                                        '<span class="skipped-badge">'
                                        '⏭️ Already exists</span>'
                                    )
                            except Exception as save_err:
                                badge = (
                                    f'<span class="skipped-badge">'
                                    f'❌ {str(save_err)[:50]}</span>'
                                )

                            st.markdown(f"""
                                <div class="news-card">
                                    <div style="display:flex;
                                                justify-content:space-between;
                                                margin-bottom:6px">
                                        <span style="font-weight:700;
                                                     font-size:15px">
                                            {title}
                                        </span>
                                        {badge}
                                    </div>
                                    <div style="color:#444;font-size:14px;
                                                margin-bottom:6px">
                                        {content[:300]}...
                                    </div>
                                    <div style="font-size:12px;color:#888">
                                        📌 {source}
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)

                        st.markdown("---")
                        s1, s2, s3 = st.columns(3)
                        s1.metric("🔍 Found",   len(articles))
                        s2.metric("💾 Saved",   saved_count)
                        s3.metric("⏭️ Existed", skipped_count)

                        if saved_count > 0:
                            st.success(
                                f"✅ {saved_count} new articles saved "
                                f"and indexed in ChromaDB!"
                            )

                    except Exception as e:
                        st.error(f"Search failed: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 5 — AI CHAT
# ─────────────────────────────────────────────────────────────────
with tab5:
    if not selected_customer:
        st.warning("⚠️ Please select a customer from the sidebar.")
    else:
        st.markdown("## 🤖 AI Advisor")
        st.markdown(
            f"*Semantic RAG + Structured Reasoning "
            f"— {selected_customer}*"
        )

        b1, b2, b3, b4 = st.columns(4)
        b1.info("🔍 Semantic Search\nFinds by meaning")
        b2.info("📊 Customer Context\nHoldings + rates")
        b3.info("🧠 Structured Output\n6-section analysis")
        b4.info("🏠 Local AI\nOllama on device")

        st.markdown("---")

        left_col, right_col = st.columns([2, 3], gap="large")

        with left_col:
            st.markdown("#### 🧠 AI Model")
            selected_model_label = st.selectbox(
                "Model", list(MODELS.keys()),
                key="tab5_model",
                label_visibility="collapsed"
            )
            selected_model = MODELS[selected_model_label]
            st.caption(f"🏠 Running locally via Ollama")

            st.markdown("---")

            st.markdown("#### 🎯 Articles to Retrieve")
            news_limit = st.slider(
                "Articles", 3, 15, 8,
                key="tab5_news_limit",
                label_visibility="collapsed"
            )

            st.markdown("---")

            st.markdown("#### 💼 Advisor Questions")
            advisor_qs = {
                "📞 Pre-call briefing": (
                    f"I have a call with {selected_customer} in "
                    f"10 minutes. Summarize their portfolio, "
                    f"any news affecting their holdings today "
                    f"and give me 3 talking points.",
                    "customer"
                ),
                "⚠️ Holdings at risk": (
                    f"Which of {selected_customer}'s holdings "
                    f"are most at risk based on today's news?",
                    "customer"
                ),
                "🔄 Rebalancing needed?": (
                    f"Does {selected_customer}'s portfolio need "
                    f"rebalancing given their risk profile?",
                    "customer"
                ),
                "💬 Retention strategy": (
                    f"How do I retain {selected_customer} "
                    f"given current market conditions?",
                    "customer"
                ),
            }
            for label, (prompt, qtype) in advisor_qs.items():
                if st.button(
                    label, use_container_width=True,
                    key=f"tab5_adv_{label}"
                ):
                    st.session_state.tab5_input  = prompt
                    st.session_state.tab5_qtype  = qtype

            st.markdown("#### 📋 Manager Questions")
            manager_qs = {
                "🚨 Who to call today?": (
                    "Which client segments should advisors "
                    "prioritize calling today based on "
                    "today's market news?",
                    "manager"
                ),
                "🏦 BoC rate impact": (
                    "What is the impact of current Bank of Canada "
                    "rates on Canadian wealth portfolios?",
                    "manager"
                ),
                "📰 Morning briefing": (
                    "Give me a senior manager morning briefing: "
                    "top 3 market risks today, which sectors are "
                    "moving and the top 3 actions advisors "
                    "should take today.",
                    "manager"
                ),
            }
            for label, (prompt, qtype) in manager_qs.items():
                if st.button(
                    label, use_container_width=True,
                    key=f"tab5_mgr_{label}"
                ):
                    st.session_state.tab5_input = prompt
                    st.session_state.tab5_qtype = qtype

        with right_col:
            st.markdown("#### 💬 Ask a Question")

            if 'tab5_input_text' not in st.session_state:
                st.session_state.tab5_input_text = ""

            if st.session_state.get('tab5_input'):
                st.session_state.tab5_input_text = \
                    st.session_state.tab5_input
                del st.session_state.tab5_input

            user_prompt = st.text_area(
                "Question",
                value            = st.session_state.tab5_input_text,
                height           = 120,
                placeholder      = (
                    f"Ask anything about {selected_customer}, "
                    f"market conditions, portfolio risk..."
                ),
                key              = "tab5_text_area",
                label_visibility = "collapsed"
            )

            query_type = st.session_state.get('tab5_qtype','customer')
            st.caption(
                "📋 Manager mode — market-wide"
                if query_type == "manager"
                else f"💼 Advisor mode — {selected_customer}"
            )

            send_col, clear_col = st.columns([3,1])
            with send_col:
                send = st.button(
                    "🤖 Get Structured AI Analysis",
                    type="primary",
                    use_container_width=True,
                    key="tab5_send"
                )
            with clear_col:
                if st.button(
                    "🗑️ Clear", use_container_width=True,
                    key="tab5_clear"
                ):
                    st.session_state.tab5_input_text = ""
                    st.rerun()

            if send and user_prompt.strip():
                st.session_state.tab5_input_text = ""
                progress = st.progress(0)
                status   = st.empty()

                try:
                    status.markdown(
                        "🔍 **Step 1/4** — Semantic search..."
                    )
                    progress.progress(10)

                    news, search_method = semantic_search_news(
                        user_prompt, limit=news_limit
                    )
                    progress.progress(30)

                    if search_method == "whitelisted_fallback":
                        st.info(
                            "🌐 **Live Whitelisted Search Triggered** — "
                            "Searched pre-approved sources and saved "
                            "results to local database."
                        )
                    elif search_method == "keyword_fallback":
                        st.warning(
                            "⚠️ Semantic search unavailable — "
                            "using keyword fallback."
                        )

                    status.markdown(
                        "📊 **Step 2/4** — Loading customer context..."
                    )

                    if query_type == "customer":
                        holdings = run_query("""
                            SELECT h.SECURITY_NAME, h.ASSET_CLASS,
                                   h.SECTOR, h.CURRENT_VALUE,
                                   h.TICKER, h.UNREALIZED_PNL,
                                   h.WEIGHT_PCT
                            FROM CUSTOMERS c
                            JOIN PORTFOLIOS p
                                ON c.CUSTOMER_ID = p.CUSTOMER_ID
                            JOIN HOLDINGS h
                                ON p.PORTFOLIO_ID = h.PORTFOLIO_ID
                            WHERE c.CUSTOMER_NAME = ?
                            ORDER BY h.CURRENT_VALUE DESC
                        """, (selected_customer,))
                    else:
                        holdings = pd.DataFrame()

                    rates = run_query("""
                        SELECT SERIES_NAME, RATE_VALUE
                        FROM BOC_RATES
                        ORDER BY RATE_DATE DESC
                        LIMIT 5
                    """)

                    today = date.today().isoformat()
                    prices = run_query(f"""
                        SELECT COMPANY_NAME, PRICE, CHANGE_PCT
                        FROM MARKET_PRICES
                        WHERE PRICE_DATE = '{today}'
                        ORDER BY ABS(CHANGE_PCT) DESC
                        LIMIT 8
                    """)
                    progress.progress(55)

                    status.markdown(
                        "⚙️ **Step 3/4** — Building context..."
                    )

                    holdings_text = "\n".join([
                        f"- {r['SECURITY_NAME']} "
                        f"({r['ASSET_CLASS']} | {r['SECTOR']}): "
                        f"${r['CURRENT_VALUE']:,.0f} | "
                        f"P&L: ${r['UNREALIZED_PNL']:,.0f} | "
                        f"Weight: {r['WEIGHT_PCT']:.1f}%"
                        for _, r in holdings.iterrows()
                    ]) if not holdings.empty else "No holdings"

                    news_text = "\n".join([
                        f"- [{r.get('SENTIMENT','N/A')}] "
                        f"{r.get('TITLE','')} — "
                        f"{str(r.get('SUMMARY',''))[:200]}"
                        for _, r in news.iterrows()
                    ]) if not news.empty else "No news found"

                    rates_text = "\n".join([
                        f"- {r['SERIES_NAME']}: {r['RATE_VALUE']}"
                        for _, r in rates.iterrows()
                    ]) if not rates.empty else "No rates"

                    prices_text = "\n".join([
                        f"- {r['COMPANY_NAME']}: "
                        f"${r['PRICE']:.2f} ({r['CHANGE_PCT']:+.2f}%)"
                        for _, r in prices.iterrows()
                    ]) if not prices.empty else "No prices"

                    progress.progress(70)

                    status.markdown(
                        f"🧠 **Step 4/4** — "
                        f"{selected_model_label} generating analysis..."
                    )

                    response = run_structured_analysis(
                        user_query    = user_prompt,
                        customer_name = selected_customer,
                        holdings_text = holdings_text,
                        news_text     = news_text,
                        rates_text    = rates_text,
                        prices_text   = prices_text,
                        model         = selected_model,
                        query_type    = query_type
                    )

                    progress.progress(100)
                    status.empty()
                    progress.empty()

                    mode_badge = (
                        "Manager · Market-Wide"
                        if query_type == "manager"
                        else f"Advisor · {selected_customer}"
                    )
                    st.markdown(
                        f"### 💡 AI Analysis "
                        f"<span style='font-size:12px;color:#888'>"
                        f"— {selected_model_label} · "
                        f"Semantic RAG · {mode_badge}</span>",
                        unsafe_allow_html=True
                    )

                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("📰 News", f"{len(news)} articles")
                    rc2.metric(
                        "💼 Holdings" if query_type=="customer"
                        else "📋 Mode",
                        f"{len(holdings)} positions"
                        if query_type=="customer" else "Market-Wide"
                    )
                    method_labels = {
                        "semantic":            "🧠 Semantic",
                        "whitelisted_fallback": "🌐 Whitelist",
                        "keyword_fallback":    "⚠️ Keyword"
                    }
                    rc3.metric(
                        "🔍 Method",
                        method_labels.get(search_method, search_method)
                    )

                    st.markdown("---")
                    st.markdown(response)

                except Exception as e:
                    progress.empty()
                    status.empty()
                    st.error(f"Analysis failed: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 6 — AI AGENT (Conversational with memory)
# ─────────────────────────────────────────────────────────────────
with tab6:
    if not selected_customer:
        st.warning("⚠️ Please select a customer from the sidebar.")
    else:
        st.markdown("## 🦾 Agentic AI Advisor")
        st.markdown(
            "*Conversational memory · Follow-up questions · "
            "Local Ollama · Audit logged*"
        )

        a1, a2, a3, a4 = st.columns(4)
        a1.info("🧭 Router\nDecides tools")
        a2.info("🔄 Retry Loop\nIf data thin")
        a3.info("💬 Memory\nFollowup aware")
        a4.info("📋 Audit Log\nEvery decision")

        st.markdown("---")

        # ── Session state initialisation ──────────────────────────
        if 'agent_messages'      not in st.session_state:
            st.session_state.agent_messages      = []
        if 'agent_thread_id'     not in st.session_state:
            st.session_state.agent_thread_id     = str(uuid.uuid4())
        if 'agent_query_type'    not in st.session_state:
            st.session_state.agent_query_type    = 'customer'
        if 'agent_input_counter' not in st.session_state:
            st.session_state.agent_input_counter = 0

        left_col, right_col = st.columns([2, 3], gap="large")

        # ════════════════════════════════════════════════════════
        # LEFT — Controls
        # ════════════════════════════════════════════════════════
        with left_col:
            st.markdown("#### 🧠 AI Model")
            agent_model_label = st.selectbox(
                "Agent Model", list(MODELS.keys()),
                key="agent_model_select",
                label_visibility="collapsed"
            )
            agent_model = MODELS[agent_model_label]
#            st.caption("🏠 Running locally via Ollama")
            selected_model_name = list(MODELS.keys())[0]  # just for reference
            current_model = MODELS.get(
                st.session_state.get("tab5_model", ""),
                OLLAMA_MODEL
            )
            if current_model.startswith("claude"):
                st.caption("☁️ Anthropic API — data sent to Anthropic")
            else:
                st.caption("🏠 Running locally via Ollama — zero data transit")            

            st.markdown("---")

            st.markdown("#### 🎯 Mode")
            agent_mode = st.radio(
                "Mode",
                ["💼 Advisor", "📋 Manager"],
                key="agent_mode_radio",
                label_visibility="collapsed"
            )
            st.session_state.agent_query_type = (
                "customer" if "Advisor" in agent_mode else "manager"
            )
            st.caption(
                f"{'Customer: ' + selected_customer if st.session_state.agent_query_type == 'customer' else 'Market-wide, no customer context'}"
            )

            st.markdown("---")

            st.markdown("#### 💬 Conversation")
            msg_count = len([
                m for m in st.session_state.agent_messages
                if m['role'] == 'user'
            ])
            st.caption(
                f"Thread: `{st.session_state.agent_thread_id[:8]}...`\n"
                f"{msg_count} question(s) in this session"
            )
            if st.button(
                "🗑️ Clear — Start New Conversation",
                use_container_width=True,
                key="clear_agent_chat"
            ):
                st.session_state.agent_messages       = []
                st.session_state.agent_thread_id      = str(uuid.uuid4())
                st.session_state.agent_input_counter += 1
                st.session_state.pop('agent_prefill_value', None)
                st.session_state.pop('agent_pending_question', None)
                st.rerun()

            st.markdown("---")

            # ── Advisor buttons ───────────────────────────────────
            st.markdown("#### 💼 Advisor Questions")
            advisor_agent_qs = {
                "📞 Pre-call briefing": (
                    f"I have a call with {selected_customer} in "
                    f"10 minutes. Summarize their portfolio, "
                    f"news affecting their holdings and give me "
                    f"3 talking points.",
                    "customer"
                ),
                "⚠️ Holdings at risk": (
                    f"Which of {selected_customer}'s holdings "
                    f"are most at risk based on today's news?",
                    "customer"
                ),
                "🔄 Rebalancing needed?": (
                    f"Does {selected_customer}'s portfolio need "
                    f"rebalancing given their risk profile?",
                    "customer"
                ),
                "💬 Retention strategy": (
                    f"How do I retain {selected_customer} "
                    f"given current market conditions?",
                    "customer"
                ),
            }
            for label, (prompt, qtype) in advisor_agent_qs.items():
                if st.button(
                    label, use_container_width=True,
                    key=f"agent_q_{label}"
                ):
                    st.session_state.agent_prefill_value = prompt
                    st.session_state.agent_query_type    = qtype
                    st.session_state.agent_input_counter += 1  # ← ADD THIS

            st.markdown("#### 📋 Manager Questions")
            manager_agent_qs = {
                "🚨 Who to call today?": (
                    "Which client segments should advisors "
                    "prioritize calling today based on market news?",
                    "manager"
                ),
                "🏦 BoC rate impact": (
                    "What is the impact of current Bank of Canada "
                    "rates on Canadian wealth portfolios?",
                    "manager"
                ),
                "📰 Morning briefing": (
                    "Give me a senior manager morning briefing: "
                    "top 3 market risks, sector movements and "
                    "top 3 advisor actions for today.",
                    "manager"
                ),
            }
            for label, (prompt, qtype) in manager_agent_qs.items():
                if st.button(
                    label, use_container_width=True,
                    key=f"agent_mq_{label}"
                ):
                    st.session_state.agent_prefill_value = prompt
                    st.session_state.agent_query_type    = qtype
                    st.session_state.agent_input_counter += 1  # ← ADD THIS

        # ════════════════════════════════════════════════════════
        # RIGHT — Chat Interface
        # ════════════════════════════════════════════════════════
        with right_col:
            st.markdown("#### 💬 Conversation")

            # ── Chat history display ──────────────────────────────
            for msg in st.session_state.agent_messages:
                with st.chat_message(msg['role']):
                    if msg['role'] == 'assistant':
                        if msg.get('reasoning_log'):
                            with st.expander(
                                f"🔍 Agent Reasoning "
                                f"({len(msg['reasoning_log'])} steps)",
                                expanded=False
                            ):
                                for step in msg['reasoning_log']:
                                    st.markdown(step)
                                mc1, mc2, mc3 = st.columns(3)
                                mc1.metric("📰 News",
                                    msg.get('news_count', 0))
                                mc2.metric("🛠️ Tools",
                                    msg.get('tools_count', 0))
                                mc3.metric("🔄 Searches",
                                    msg.get('search_attempts', 0))

                        st.markdown(msg['content'])
                        
                        if msg.get('sources'):
                            with st.expander(
                                f"📊 Data Sources Used "
                                f"({len(msg['sources'])} articles)",
                                expanded=False
                            ):
                                for i, src in enumerate(msg['sources'], 1):
                                    # Handle both upper and lowercase keys
                                    title  = str(src.get('TITLE',  src.get('title',  '')) or 'No title')
                                    url    = str(src.get('URL',    src.get('url',    '')) or '')
                                    source = str(src.get('SOURCE', src.get('source', '')) or 'Unknown')
                                    pub_at = str(src.get('PUBLISHED_AT', src.get('published_at', '')) or '')
                                    sent   = str(src.get('SENTIMENT',    src.get('sentiment', 'NEUTRAL')) or 'NEUTRAL')
                                    icon   = (
                                        "🟢" if sent == "POSITIVE"
                                        else "🔴" if sent == "NEGATIVE"
                                        else "🟡"
                                    )
                                    st.markdown(f"**{i}. {icon} {title}**")
                                    st.markdown(f"📌 Source: `{source}`")
                                    if pub_at:
                                        st.markdown(f"📅 Published: `{pub_at}`")
                                    if url and url.startswith('http'):
                                        st.markdown(f"🔗 Full URL:")
                                        st.code(url, language=None)
                                        st.markdown(f"[Read full article →]({url})")
                                    else:
                                        st.markdown("🔗 No URL available")
                                    st.divider()            
                    else:
                        st.markdown(msg['content'])

            if not st.session_state.agent_messages:
                st.info(
                    "🦾 Ask the agent anything. "
                    "It remembers your conversation — "
                    "ask follow-up questions naturally."
                )

            st.markdown("---")

            st.caption(
                "📋 Manager mode — market-wide"
                if st.session_state.agent_query_type == "manager"
                else f"💼 Advisor mode — {selected_customer}"
            )

            # ── Process pending question BEFORE rendering input ───
            # This runs AFTER a send click on previous rerun
            if 'agent_pending_question' in st.session_state:
                pending    = st.session_state.pop(
                    'agent_pending_question'
                )
                question   = pending['question']
                query_type = pending['query_type']

                conv_history = [
                    {
                        'role':    m['role'],
                        'content': m['content'][:500]
                    }
                    for m in st.session_state.agent_messages[:-1]
                ]

                with st.spinner("🦾 Agent is reasoning..."):
                    try:
                        from agent import run_advisor_agent
                        result = run_advisor_agent(
                            question             = question,
                            customer_name        = selected_customer,
                            query_type           = query_type,
                            model                = agent_model,
                            conversation_history = conv_history,
                            thread_id            = st.session_state
                                                   .agent_thread_id,
                            advisor_name         = selected_advisor
                        )
                        st.session_state.agent_messages.append({
                            'role':            'assistant',
                            'content':         result.get(
                                'final_response',
                                'No response generated.'
                            ),
                            'reasoning_log':   result.get(
                                'reasoning_log', []
                            ),
                            'news_count':      len(result.get(
                                'news_articles', []
                            )),
                            'tools_count':     len(result.get(
                                'tools_needed', []
                            )),
                            'search_attempts': result.get(
                                'search_attempts', 0
                            ),
                            'sources':         result.get(
                                'news_articles', []
                            )
                        })
                    except Exception as e:
                        st.session_state.agent_messages.append({
                            'role':            'assistant',
                            'content':         f"❌ Agent error: {e}",
                            'reasoning_log':   [],
                            'news_count':      0,
                            'tools_count':     0,
                            'search_attempts': 0,
                            'sources':         []
                        })
                st.rerun()

            # ── Input box — prefill from buttons ─────────────────
            # Use .get() to safely read — never del manually
            prefill = st.session_state.get('agent_prefill_value', '')

            user_input = st.text_area(
                "Your question",
                value            = prefill,
                height           = 100,
                placeholder      = "Ask a question or follow up...",
                label_visibility = "collapsed",
                key = f"agent_input_{st.session_state.agent_input_counter}"
            )

            fc1, fc2 = st.columns([3, 1])
            with fc1:
                send_clicked = st.button(
                    "🦾 Send to Agent",
                    type                = "primary",
                    use_container_width = True,
                    key                 = "send_agent_btn"
                )
            with fc2:
                if st.button(
                    "🗑️ Clear",
                    use_container_width = True,
                    key                 = "clear_chat_btn"
                ):
                    st.session_state.agent_messages       = []
                    st.session_state.agent_thread_id      = str(uuid.uuid4())
                    st.session_state.agent_input_counter += 1
                    st.session_state.pop('agent_prefill_value',    None)
                    st.session_state.pop('agent_pending_question', None)
                    st.rerun()

            # ── Handle send click ─────────────────────────────────
            if send_clicked and user_input.strip():
                question   = user_input.strip()
                query_type = st.session_state.agent_query_type

                # Add user message immediately
                st.session_state.agent_messages.append({
                    'role':    'user',
                    'content': question
                })

                # Store for processing on next rerun
                st.session_state.agent_pending_question = {
                    'question':   question,
                    'query_type': query_type
                }

                # Clear prefill and increment counter to empty box
                st.session_state.pop('agent_prefill_value', None)
                st.session_state.agent_input_counter += 1

                st.rerun()
