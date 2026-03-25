import streamlit as st
import snowflake.connector
from dotenv import load_dotenv
import os
import json
import pandas as pd
import uuid
import plotly.express as px
from datetime import datetime
from db import get_snowflake_connection, run_query, run_cortex, run_query_cached

# FIND these function definitions in dashboard.py and DELETE them:
# def get_snowflake_connection(): ...
# def run_query(): ...
# def run_cortex(): ...

# ADD this import at the top instead:
from db import get_snowflake_connection, run_query, run_cortex

load_dotenv()

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
        .ai-response {
            background: white;
            padding: 20px;
            border-radius: 10px;
            border-left: 4px solid #1565c0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            font-size: 15px;
            line-height: 1.7;
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
        .model-badge {
            background: #e3f2fd;
            color: #1565c0;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
    </style>
""", unsafe_allow_html=True)


#----------- WHITELISTED_SOURCES for AI if result is not found from external feed data

WHITELISTED_SOURCES = [
    "bankofcanada.ca",
    "osfi-bsif.gc.ca",
    "bnnbloomberg.ca",
    "financialpost.com",
    "theglobeandmail.com",
    "reuters.com",
    "ft.com",
    "pensionsandinvestments.com", #GAM specific
    "cppinvestments.com", #GAM specific
    "institutional investor.com" #GAM specific
]
# ── Whitelisted Fallback Search ───────────────────────────────────
def search_whitelisted_sources(query, limit=5):
    """
    Searches Tavily restricted to whitelisted domains only.
    Returns (saved_count, found_count, raw_articles)
    """
    try:
        import requests

        response = requests.post(
            "https://api.tavily.com/search",
            headers={"Content-Type": "application/json"},
            json={
                "api_key":         os.getenv('TAVILY_API_KEY'),
                "query":           query,
                "search_depth":    "advanced",
                "max_results":     limit,
                "include_answer":  False,
                "include_domains": WHITELISTED_SOURCES
            },
            timeout=30
        )
        response.raise_for_status()
        articles = response.json().get('results', [])

        # Save to Snowflake for future queries
        saved = 0
        for article in articles:
            try:
                status = save_article_to_snowflake(
                    title   = article.get('title', ''),
                    content = article.get('content', ''),
                    url     = article.get('url', ''),
                    source  = article.get('url', '').split('/')[2]
                                .replace('www.', '')
                )
                if status == "saved":
                    saved += 1
            except:
                pass

        # Return raw articles too — for immediate use
        return saved, len(articles), articles   # ← added articles

    except Exception as e:
        return 0, 0, []   # ← empty list on failure
# ── Semantic Search Function ──────────────────────────────────────
def semantic_search_news(query, limit=8):
    MINIMUM_RESULTS   = 3
    OVERLAP_THRESHOLD = 0.2

    def has_relevant_results(news_df, query):
        if news_df.empty:
            return False

        # Common financial words that appear in ANY article
        # — exclude these from relevance check
        COMMON_WORDS = {
            "canadian", "canada", "market", "fund", "rate",
            "bank", "financial", "portfolio", "investment",
            "stock", "equity", "today", "year", "2026",
            "latest", "news", "will", "with", "this",
            "that", "from", "what", "have", "been",
            "their", "which", "about", "more", "also",
            "data", "percent", "growth", "global"
        }

        # Only check SPECIFIC words — longer than 5 chars
        # and not in common words list
        query_words = set([
            w.lower() for w in query.split()
            if len(w) > 5
            and w.lower() not in COMMON_WORDS
        ])

        # If no specific words found — can't check relevance
        # trigger whitelist to be safe
        if not query_words:
            return False

        news_df.columns = [c.upper() for c in news_df.columns]
        match_count = 0

        for _, row in news_df.iterrows():
            title    = str(row.get('TITLE',   '')).lower()
            summary  = str(row.get('SUMMARY', '')).lower()
            combined = title + " " + summary

            matches = sum(1 for w in query_words if w in combined)
            overlap = matches / len(query_words)

            if overlap >= 0.3:   # 30% of SPECIFIC words must match
                match_count += 1

        # At least 2 articles must contain specific query terms
        return match_count >= 2

    try:
        # ── Step 1 — Snowflake semantic search ────────────────────
        conn   = get_snowflake_connection()
        cursor = conn.cursor()

        filter_json = f'''
            {{
                "query": "{query.replace('"', '')}",
                "limit": {limit}
            }}
        '''
        cursor.execute("""
            SELECT PARSE_JSON(
                SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
                    'BANK_POC.INTERNAL_DATA.NEWS_SEARCH_SERVICE',
                    %s
                )
            )['results'] AS RESULTS
        """, (filter_json,))

        raw     = cursor.fetchone()
        cursor.close()

        # Guard against empty result from Cortex
        raw     = raw[0] if raw else None
        results = json.loads(raw) if isinstance(raw, str) else raw
        news_df = pd.DataFrame(results) if results else pd.DataFrame()

        if not news_df.empty:
            news_df.columns = [c.upper() for c in news_df.columns]

        # ── Step 2 — Check relevance ──────────────────────────────
        sufficient = (
            len(news_df) >= MINIMUM_RESULTS
            and has_relevant_results(news_df, query)
        )

        if sufficient:
            return news_df, "snowflake"

        # ── Step 3 — Whitelist fallback ───────────────────────────
        try:
            saved, found, whitelist_articles = \
                search_whitelisted_sources(query, limit=5)
        except Exception:
            whitelist_articles = []

        if whitelist_articles:
            whitelist_df = pd.DataFrame([{
                'TITLE':        a.get('title', ''),
                'SUMMARY':      a.get('content', '')[:500],
                'SENTIMENT':    'NEUTRAL',
                'SOURCE':       a.get('url', '').split('/')[2]
                                 .replace('www.', ''),
                'URL':          a.get('url', ''),
                'PUBLISHED_AT': datetime.now().strftime('%Y-%m-%d')
            } for a in whitelist_articles])
            return whitelist_df, "whitelisted_fallback"

        # ── Step 4 — Return whatever Snowflake had ────────────────
        return news_df, "snowflake"

    except Exception as e:
        st.warning(f"Semantic search failed, using keyword search: {e}")
        try:
            news_df = run_query("""
                SELECT r.TITLE, e.SENTIMENT, e.SUMMARY,
                       r.SOURCE, r.URL,
                       r.PUBLISHED_AT::VARCHAR     AS PUBLISHED_AT,
                       e.ASSET_CLASSES::VARCHAR    AS ASSET_CLASSES,
                       e.RELEVANCE_SCORE
                FROM BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED e
                JOIN BANK_POC.EXTERNAL_DATA.NEWS_RAW r
                    ON e.NEWS_RAW_ID = r.ID
                ORDER BY e.RELEVANCE_SCORE DESC
                LIMIT 8
            """)
            return news_df, "keyword_fallback"
        except Exception:
            # Absolute last resort — return empty
            return pd.DataFrame(), "keyword_fallback"

# ── Structured Analysis Function ──────────────────────────────────
# ── Structured Analysis Function — UPDATED ────────────────────────
def run_structured_analysis(
    user_query,
    customer_name,
    holdings_text,
    news_text,
    rates_text,
    prices_text,
    model='mistral-large2',
    query_type='customer'   # ← NEW: 'customer' or 'manager'
):
    if query_type == 'manager':
        # ── Manager prompt — NO customer context ─────────────────
        structured_prompt = (
            "You are a senior Canadian wealth management AI advisor "
            "briefing a portfolio manager at a Big 5 Canadian bank. "
            "Answer the question using ONLY the data provided below. "
            "Be specific, cite actual numbers. "
            "Do not reference any individual customer. "

            "\n\nQUERY: " + user_query +

            "\n\nLATEST NEWS (Semantic Match):\n" + news_text +

            "\n\nBANK OF CANADA RATES:\n" + rates_text +

            "\n\nMARKET PRICES (Today):\n" + prices_text +

            "\n\nRespond using EXACTLY this structure:\n"

            "\n## 1. MARKET SITUATION TODAY\n"
            "One paragraph on what is happening in Canadian "
            "markets right now. Cite specific numbers.\n"

            "\n## 2. TOP 3 RISKS FOR WEALTH PORTFOLIOS\n"
            "Risk 1: [specific risk] — Impact: HIGH/MEDIUM/LOW\n"
            "Risk 2: [specific risk] — Impact: HIGH/MEDIUM/LOW\n"
            "Risk 3: [specific risk] — Impact: HIGH/MEDIUM/LOW\n"

            "\n## 3. SECTORS MOST AFFECTED\n"
            "Which sectors in Canadian wealth portfolios are "
            "most impacted and why. Be specific.\n"

            "\n## 4. RECOMMENDED ADVISOR ACTIONS TODAY\n"
            "Action 1: [specific action] — Priority: HIGH/MEDIUM/LOW\n"
            "Action 2: [specific action] — Priority: HIGH/MEDIUM/LOW\n"
            "Action 3: [specific action] — Priority: HIGH/MEDIUM/LOW\n"

            "\n## 5. CLIENT SEGMENTS TO PRIORITIZE\n"
            "Which client segments (CONSERVATIVE, AGGRESSIVE, "
            "PRIVATE_BANKING, WEALTH etc.) need attention today "
            "and why.\n"

            "\n## 6. URGENCY SCORE\n"
            "Score: X/10\n"
            "Rationale: One sentence."
        )
    else:
        # ── Customer prompt — WITH customer context ───────────────
        structured_prompt = (
            "You are a senior Canadian wealth management AI advisor. "
            "Analyze the query using ONLY the data provided below. "
            "Be specific, cite actual numbers from the data. "
            "Do not make up any information not in the data. "

            "\n\nQUERY: " + user_query +
            "\n\nCUSTOMER: " + customer_name +
            "\n\nHOLDINGS:\n" + holdings_text +
            "\n\nLATEST NEWS (Semantic Match):\n" + news_text +
            "\n\nBANK OF CANADA RATES:\n" + rates_text +
            "\n\nMARKET PRICES:\n" + prices_text +

            "\n\nRespond using EXACTLY this structure:\n"

            "\n## 1. SITUATION SUMMARY\n"
            "One paragraph summarizing what is happening in the "
            "market relevant to this customer right now. "
            "Cite specific numbers.\n"

            "\n## 2. CUSTOMER IMPACT ASSESSMENT\n"
            "- Which specific holdings are affected and why\n"
            "- Estimated portfolio impact in dollars and percentage\n"
            "- Risk level: LOW / MEDIUM / HIGH / CRITICAL\n"

            "\n## 3. REGULATORY & COMPLIANCE FLAGS\n"
            "- Any KYC or suitability concerns based on holdings\n"
            "- Any regulatory changes from the news that affect "
            "this customer\n"
            "- If none: state No compliance flags identified\n"

            "\n## 4. RECOMMENDED ACTIONS\n"
            "Action 1: [Specific action] — Priority: HIGH/MEDIUM/LOW\n"
            "Action 2: [Specific action] — Priority: HIGH/MEDIUM/LOW\n"
            "Action 3: [Specific action] — Priority: HIGH/MEDIUM/LOW\n"

            "\n## 5. CLIENT TALKING POINTS\n"
            "3-5 bullet points the advisor can use directly "
            "in a client call. Use plain language, no jargon.\n"

            "\n## 6. URGENCY SCORE\n"
            "Score: X/10\n"
            "Rationale: One sentence explaining the urgency score."
        )

    return run_cortex(structured_prompt, model)


# ── Tavily Search ─────────────────────────────────────────────────
def tavily_search(query, max_results=8):
    try:
        import requests
        response = requests.post(
            "https://api.tavily.com/search",
            headers={"Content-Type": "application/json"},
            json={
                "api_key":        os.getenv('TAVILY_API_KEY'),
                "query":          query,
                "search_depth":   "advanced",
                "max_results":    max_results,
                "include_answer": True
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Tavily search failed: {e}")
        return {}

# ── Save Tavily Article to Snowflake ─────────────────────────────
# REPLACE WITH THIS
def save_article_to_snowflake(title, content, url, source):
    conn   = get_snowflake_connection()
    cursor = conn.cursor()

    try:
        # Check duplicate
        cursor.execute("""
            SELECT COUNT(*) FROM BANK_POC.EXTERNAL_DATA.NEWS_RAW
            WHERE URL = %s
        """, (url,))

        if cursor.fetchone()[0] > 0:
            cursor.close()
            return "skipped"

        # Insert raw article — explicit CAST for all types
        news_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO BANK_POC.EXTERNAL_DATA.NEWS_RAW
                (ID, SOURCE, TITLE, CONTENT, URL, PUBLISHED_AT)
            SELECT
                %s::VARCHAR,
                %s::VARCHAR,
                %s::VARCHAR,
                %s::VARCHAR,
                %s::VARCHAR,
                CURRENT_TIMESTAMP()::TIMESTAMP_NTZ
        """, (
            news_id,
            str(source)[:100],
            str(title)[:1000],
            str(content),
            str(url)[:2000]
        ))
        conn.commit()

        # Enrich with Cortex AI
        enrich_prompt = (
            "You are a Canadian financial analyst. "
            "Analyze this news article and respond in JSON only. "
            "No explanation, no markdown, just raw JSON. "
            "Title: " + str(title) + " "
            "Content: " + str(content)[:500] + " "
            "Return exactly this structure: "
            '{"summary": "2-3 sentence summary", '
            '"sentiment": "POSITIVE or NEGATIVE or NEUTRAL", '
            '"asset_class": "EQUITIES or BONDS or FX or REAL_ESTATE or GENERAL"}'
        )

        cursor.execute("""
            SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', %s)
        """, (enrich_prompt,))

        raw_response = cursor.fetchone()[0]
        raw_response = raw_response.replace(
            '```json', ''
        ).replace('```', '').strip()

        enriched  = json.loads(raw_response)
        enrich_id = str(uuid.uuid4())

        cursor.execute("""
            INSERT INTO BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED
                (ID, NEWS_RAW_ID, SUMMARY, SENTIMENT,
                 ENTITIES, ASSET_CLASSES, RELEVANCE_SCORE, CREATED_AT)
            SELECT
                %s::VARCHAR,
                %s::VARCHAR,
                %s::VARCHAR,
                %s::VARCHAR,
                PARSE_JSON(%s),
                PARSE_JSON(%s),
                %s::FLOAT,
                CURRENT_TIMESTAMP()::TIMESTAMP_NTZ
        """, (
            enrich_id,
            news_id,
            str(enriched.get('summary', ''))[:2000],
            str(enriched.get('sentiment', 'NEUTRAL')),
            json.dumps({'source': 'tavily_search'}),
            json.dumps([enriched.get('asset_class', 'GENERAL')]),
            0.90
        ))
        conn.commit()
                # ADD THIS after the final conn.commit()
        # Auto-generate embedding for newly saved article
        try:
            cursor.execute("""
                UPDATE BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED e
                SET e.EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768(
                    'snowflake-arctic-embed-m',
                    COALESCE(r.TITLE, '') || ' ' || COALESCE(e.SUMMARY, '')
                )
                FROM BANK_POC.EXTERNAL_DATA.NEWS_RAW r
                WHERE r.ID        = e.NEWS_RAW_ID
                AND   e.NEWS_RAW_ID = %s
                AND   e.EMBEDDING IS NULL
            """, (news_id,))
            conn.commit()
        except:
            pass  # embedding failure should not block article save

        cursor.close()
        return "saved"

    except Exception as e:
        cursor.close()
        raise e

# ── Models Available in Snowflake Cortex ─────────────────────────
MODELS = {
    "Claude 3.5 Sonnet (Anthropic) — Best Quality":    "claude-3-5-sonnet",
    "Claude 4 Sonnet (Anthropic) — Latest":            "claude-4-sonnet",
    "Mistral Large 2 — General Purpose":               "mistral-large2",
    "Mixtral 8x7b (Mistral) — Fast & Cost Effective":  "mixtral-8x7b",
    "Llama 3.1 70b (Meta) — Powerful Open Source":     "llama3.1-70b",
    "Llama 3.1 8b (Meta) — Lightweight & Fast":        "llama3.1-8b",
    "DeepSeek R1 — Best for Reasoning":                "deepseek-r1",
    "Snowflake Arctic — Enterprise Optimized":         "snowflake-arctic",
    "Gemma 7b (Google) — Code & Text":                 "gemma-7b",
    "GPT-5 (OpenAI) — Latest & Most Capable":          "openai-gpt-5",
    "GPT-4.1 (OpenAI) — Fast & Reliable":              "openai-gpt-4.1",
    "GPT-5 Mini (OpenAI) — Lightweight":               "openai-gpt-5-mini",

}

# ── Header ────────────────────────────────────────────────────────
col_logo, col_title = st.columns([1, 8])
with col_logo:
    st.markdown("# 🏦")
with col_title:
    st.markdown("# Canadian Bank AI Advisor")
    st.markdown("*Powered by Snowflake Cortex AI + Live Market Data*")

st.divider()

# ── Sidebar ───────────────────────────────────────────────────────
# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")

    # ── ADVISOR LOGIN (Level 1) ───────────────────────────────────
    st.markdown("### 👔 Advisor")

    try:
        advisors_df = run_query_cached("""
            SELECT DISTINCT RELATIONSHIP_MANAGER
            FROM BANK_POC.INTERNAL_DATA.CUSTOMERS
            WHERE RELATIONSHIP_MANAGER IS NOT NULL
            ORDER BY RELATIONSHIP_MANAGER
        """)
        advisor_list = ["ALL CUSTOMERS"] + advisors_df[
            'RELATIONSHIP_MANAGER'
        ].tolist()
    except:
        advisor_list = ["ALL CUSTOMERS"]

    selected_advisor = st.selectbox(
        "You are logged in as",
        advisor_list
    )

    # Show advisor summary
    if selected_advisor != "ALL CUSTOMERS":
        try:
            advisor_stats = run_query_cached(f"""
                SELECT
                    COUNT(*)                    AS TOTAL_CUSTOMERS,
                    SUM(TOTAL_AUM)              AS TOTAL_AUM,
                    COUNT(DISTINCT SEGMENT)     AS SEGMENTS
                FROM BANK_POC.INTERNAL_DATA.CUSTOMERS
                WHERE RELATIONSHIP_MANAGER = '{selected_advisor}'
            """)
            row = advisor_stats.iloc[0]
            st.markdown(f"""
                <div style="background:#1e293b; border-radius:8px;
                            padding:12px; margin-top:8px;
                            border-left:3px solid #22c55e">
                    <div style="font-size:13px; font-weight:700;
                                color:#f8fafc; margin-bottom:6px">
                        👔 {selected_advisor}
                    </div>
                    <div style="font-size:11px; color:#94a3b8;
                                line-height:1.8">
                        👥 {int(row['TOTAL_CUSTOMERS'])} customers<br>
                        💰 ${row['TOTAL_AUM']:,.0f} total AUM<br>
                        📊 {int(row['SEGMENTS'])} segments
                    </div>
                </div>
            """, unsafe_allow_html=True)
        except:
            pass

    # Build advisor WHERE clause
    if selected_advisor == "ALL CUSTOMERS":
        advisor_where = "1=1"
    else:
        advisor_where = f"RELATIONSHIP_MANAGER = '{selected_advisor}'"

    st.markdown("---")

    # ── IMPROVEMENT 7 — Filters ───────────────────────────────────
    st.markdown("### 🎯 Filter Customers")

    selected_segment = st.selectbox(
        "Segment",
        ["ALL", "RETAIL", "WEALTH", "CORPORATE",
         "SMALL_BUSINESS", "PRIVATE_BANKING"]
    )

    selected_risk = st.selectbox(
        "Risk Profile",
        ["ALL", "CONSERVATIVE", "MODERATE", "GROWTH", "AGGRESSIVE"]
    )

    aum_ranges = {
        "ALL":              (0, 999_999_999),
        "Under $100K":      (0, 100_000),
        "$100K – $500K":    (100_000, 500_000),
        "$500K – $2M":      (500_000, 2_000_000),
        "$2M – $10M":       (2_000_000, 10_000_000),
        "Over $10M":        (10_000_000, 999_999_999),
    }
    selected_aum_label = st.selectbox(
        "AUM Range", list(aum_ranges.keys())
    )
    aum_min, aum_max = aum_ranges[selected_aum_label]

    # Build full filter WHERE clause
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

    # ── IMPROVEMENT 1 — Search Bar ────────────────────────────────
    st.markdown("### 🔍 Find Customer")

    search_term = st.text_input(
        "Search by name or email",
        placeholder="e.g. John, ABC Corp, smith..."
    )

    try:
        search_clause = ""
        if search_term and len(search_term) >= 2:
            s = search_term.replace("'", "''")
            search_clause = (
                f"AND (LOWER(CUSTOMER_NAME) LIKE LOWER('%{s}%') "
                f"OR LOWER(EMAIL) LIKE LOWER('%{s}%') "
                f"OR LOWER(CONTACT_NAME) LIKE LOWER('%{s}%'))"
            )

        customers_df = run_query_cached(f"""
            SELECT
                CUSTOMER_ID,
                CUSTOMER_NAME,
                SEGMENT,
                RISK_PROFILE,
                TOTAL_AUM,
                CITY,
                EMAIL,
                CONTACT_NAME,
                RELATIONSHIP_MANAGER
            FROM BANK_POC.INTERNAL_DATA.CUSTOMERS
            WHERE {filter_where}
            {search_clause}
            ORDER BY TOTAL_AUM DESC
            LIMIT 50
        """)

        if customers_df.empty:
            st.warning("No customers match your filters.")
            selected_customer = None
            customer_row      = None
        else:
            if search_term and len(search_term) >= 2:
                st.success(f"🔍 {len(customers_df)} match(es) found")
            else:
                st.caption(
                    f"Showing top {len(customers_df)} by AUM"
                )

            selected_customer = st.selectbox(
                "Select Customer",
                customers_df['CUSTOMER_NAME'].tolist(),
                label_visibility="collapsed"
            )

            customer_row = customers_df[
                customers_df['CUSTOMER_NAME'] == selected_customer
            ].iloc[0]

            # Customer info card
            st.markdown(f"""
                <div style="background:#1e293b; border-radius:8px;
                            padding:12px; margin-top:8px;
                            border-left:3px solid #fbbf24">
                    <div style="font-size:13px; font-weight:700;
                                color:#f8fafc; margin-bottom:6px">
                        {selected_customer}
                    </div>
                    <div style="font-size:11px; color:#94a3b8;
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

    # ── Data Status ───────────────────────────────────────────────
    st.markdown("### 📅 Data Status")
    try:
        news_count = run_query_cached("""
            SELECT COUNT(*) AS CNT
            FROM BANK_POC.EXTERNAL_DATA.NEWS_RAW
        """)
        enriched_count = run_query_cached("""
            SELECT COUNT(*) AS CNT
            FROM BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED
        """)
        price_count = run_query_cached("""
            SELECT COUNT(*) AS CNT
            FROM BANK_POC.EXTERNAL_DATA.MARKET_PRICES
            WHERE PRICE_DATE = CURRENT_DATE()
        """)
        customer_total = run_query_cached("""
            SELECT COUNT(*) AS CNT
            FROM BANK_POC.INTERNAL_DATA.CUSTOMERS
        """)
        st.metric("👥 Total Customers", int(customer_total['CNT'][0]))
        st.metric("📰 News Articles",   int(news_count['CNT'][0]))
        st.metric("🤖 AI Enriched",     int(enriched_count['CNT'][0]))
        st.metric("📈 Prices Today",    int(price_count['CNT'][0]))
    except:
        st.warning("Could not load stats")

    st.markdown("---")
    st.markdown("*Built for Canadian Bank POC*")
    st.markdown("*Data: Yahoo Finance, BoC, NewsAPI, Tavily*")

# ── Main Tabs ─────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📰 News Feed",
    "📈 Market Prices",
    "💼 Customer Portfolio",
    "🔍 Tavily News Search",
    "🤖 AI Chat",
    "🦾 AI Agent"
])

# ─────────────────────────────────────────────────────────────────
# TAB 1 — NEWS FEED
# ─────────────────────────────────────────────────────────────────
with tab1:
    st.markdown("## 📰 Latest Financial News")
    st.markdown("*AI-enriched news from NewsAPI, Tavily & live searches*")

    col_f1, col_f2 = st.columns([2, 6])
    with col_f1:
        sentiment_filter = st.selectbox(
            "Filter by Sentiment",
            ["ALL", "POSITIVE", "NEGATIVE", "NEUTRAL"]
        )

    sentiment_where = ""
    if sentiment_filter != "ALL":
        sentiment_where = f"AND e.SENTIMENT = '{sentiment_filter}'"

    try:
        news_df = run_query(f"""
            SELECT
                r.SOURCE,
                r.TITLE,
                r.URL,
                e.SENTIMENT,
                e.SUMMARY,
                e.ASSET_CLASSES::VARCHAR    AS ASSET_CLASS,
                e.RELEVANCE_SCORE,
                r.PUBLISHED_AT
            FROM BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED e
            JOIN BANK_POC.EXTERNAL_DATA.NEWS_RAW r
                ON e.NEWS_RAW_ID = r.ID
            WHERE 1=1 {sentiment_where}
            ORDER BY e.RELEVANCE_SCORE DESC, r.PUBLISHED_AT DESC
            LIMIT 20
        """)

        if news_df.empty:
            st.warning("No news articles found.")
        else:
            for _, row in news_df.iterrows():
                sentiment = row['SENTIMENT']
                icon  = "🟢" if sentiment == "POSITIVE" else \
                        "🔴" if sentiment == "NEGATIVE" else "🟡"

                st.markdown(f"""
                    <div class="news-card">
                        <div style="display:flex;
                                    justify-content:space-between;
                                    margin-bottom:6px">
                            <span style="font-weight:700;
                                         font-size:15px">
                                {row['TITLE']}
                            </span>
                            <span style="font-size:13px; color:#666">
                                {icon} {sentiment}
                            </span>
                        </div>
                        <div style="color:#444; font-size:14px;
                                    margin-bottom:6px">
                            {row['SUMMARY'] or 'No summary available'}
                        </div>
                        <div style="display:flex; gap:15px;
                                    font-size:12px; color:#888">
                            <span>📌 {row['SOURCE']}</span>
                            <span>🏷️ {row['ASSET_CLASS']}</span>
                            <span>⭐ {round(row['RELEVANCE_SCORE'], 2)}</span>
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
    st.markdown("*Source: Yahoo Finance — updated by pipeline*")

    try:
        prices_df = run_query("""
            SELECT TICKER, COMPANY_NAME, PRICE,
                   CHANGE_PCT, VOLUME, PRICE_DATE
            FROM BANK_POC.EXTERNAL_DATA.MARKET_PRICES
            WHERE PRICE_DATE = CURRENT_DATE()
            ORDER BY ABS(CHANGE_PCT) DESC
        """)

        if prices_df.empty:
            st.warning("No prices for today. Run the pipeline first.")
        else:
            cols = st.columns(4)
            for i, (_, row) in enumerate(prices_df.head(4).iterrows()):
                with cols[i]:
                    st.metric(
                        label=row['COMPANY_NAME'][:25],
                        value=f"${row['PRICE']:.2f}",
                        delta=f"{row['CHANGE_PCT']:+.2f}%"
                    )

            st.markdown("---")

            display_df               = prices_df.copy()
            display_df['DIRECTION']  = display_df['CHANGE_PCT'].apply(
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
                    'TICKER', 'COMPANY_NAME', 'PRICE',
                    'CHANGE_PCT', 'DIRECTION', 'PRICE_DATE'
                ]],
                use_container_width=True,
                hide_index=True
            )

    except Exception as e:
        st.error(f"Could not load prices: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 3 — CUSTOMER PORTFOLIO
# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
# TAB 3 — CUSTOMER PORTFOLIO (IMPROVED)
# ─────────────────────────────────────────────────────────────────
with tab3:
    if not selected_customer:
        st.warning("⚠️ Please search and select a customer from the sidebar.")
    else:
        st.markdown(f"## 💼 Portfolio View — {selected_customer}")

        try:
            portfolio_df = run_query("""
                SELECT
                    p.PORTFOLIO_NAME,
                    h.SECURITY_NAME,
                    h.TICKER,
                    h.ASSET_CLASS,
                    h.SECTOR,
                    h.QUANTITY,
                    h.AVERAGE_COST,
                    h.CURRENT_PRICE,
                    h.CURRENT_VALUE,
                    h.UNREALIZED_PNL,
                    h.WEIGHT_PCT,
                    m.PRICE         AS MARKET_PRICE,
                    m.CHANGE_PCT    AS TODAY_CHANGE
                FROM BANK_POC.INTERNAL_DATA.CUSTOMERS c
                JOIN BANK_POC.INTERNAL_DATA.PORTFOLIOS p
                    ON c.CUSTOMER_ID = p.CUSTOMER_ID
                JOIN BANK_POC.INTERNAL_DATA.HOLDINGS h
                    ON p.PORTFOLIO_ID = h.PORTFOLIO_ID
                LEFT JOIN BANK_POC.EXTERNAL_DATA.MARKET_PRICES m
                    ON h.TICKER = m.TICKER
                    AND m.PRICE_DATE = CURRENT_DATE()
                WHERE c.CUSTOMER_NAME = %s
                ORDER BY p.PORTFOLIO_NAME, h.CURRENT_VALUE DESC
            """, (selected_customer,))

            if portfolio_df.empty:
                st.warning(f"No holdings found for {selected_customer}")
            else:

                # ── Summary Metrics Bar ───────────────────────────
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

                unrealized_color = "#22c55e" if total_unrealized >= 0 else "#ef4444"
                today_color      = "#22c55e" if today_gain >= 0 else "#ef4444"
                unrealized_arrow = "▲" if total_unrealized >= 0 else "▼"
                today_arrow      = "▲" if today_gain >= 0 else "▼"

                st.markdown(f"""
                    <div style="display:grid; grid-template-columns:repeat(5,1fr);
                                gap:12px; margin-bottom:20px">
                        <div style="background:white; border-radius:10px;
                                    padding:16px; border-top:3px solid #1565c0;
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px; color:#888;
                                        letter-spacing:1px">TOTAL AUM</div>
                            <div style="font-size:22px; font-weight:800;
                                        color:#1565c0; margin-top:4px">
                                ${total_value:,.0f}
                            </div>
                            <div style="font-size:11px; color:#888">CAD</div>
                        </div>
                        <div style="background:white; border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid {unrealized_color};
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px; color:#888;
                                        letter-spacing:1px">UNREALIZED P&L</div>
                            <div style="font-size:22px; font-weight:800;
                                        color:{unrealized_color}; margin-top:4px">
                                {unrealized_arrow} ${abs(total_unrealized):,.0f}
                            </div>
                            <div style="font-size:11px; color:#888">all time</div>
                        </div>
                        <div style="background:white; border-radius:10px;
                                    padding:16px;
                                    border-top:3px solid {today_color};
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px; color:#888;
                                        letter-spacing:1px">TODAY'S GAIN/LOSS</div>
                            <div style="font-size:22px; font-weight:800;
                                        color:{today_color}; margin-top:4px">
                                {today_arrow} ${abs(today_gain):,.0f}
                            </div>
                            <div style="font-size:11px; color:#888">today</div>
                        </div>
                        <div style="background:white; border-radius:10px;
                                    padding:16px; border-top:3px solid #f59e0b;
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px; color:#888;
                                        letter-spacing:1px">HOLDINGS</div>
                            <div style="font-size:22px; font-weight:800;
                                        color:#f59e0b; margin-top:4px">
                                {total_holdings}
                            </div>
                            <div style="font-size:11px; color:#888">positions</div>
                        </div>
                        <div style="background:white; border-radius:10px;
                                    padding:16px; border-top:3px solid #8b5cf6;
                                    box-shadow:0 2px 4px rgba(0,0,0,0.05)">
                            <div style="font-size:10px; color:#888;
                                        letter-spacing:1px">PORTFOLIOS</div>
                            <div style="font-size:22px; font-weight:800;
                                        color:#8b5cf6; margin-top:4px">
                                {total_portfolios}
                            </div>
                            <div style="font-size:11px; color:#888">accounts</div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # ── Charts Row ────────────────────────────────────
                import plotly.express as px

                chart_col1, chart_col2 = st.columns(2)

                with chart_col1:
                    st.markdown("#### 🥧 Asset Allocation")
                    try:
                        asset_allocation = (
                            portfolio_df.groupby('ASSET_CLASS')['CURRENT_VALUE']
                            .sum()
                            .reset_index()
                        )
                        asset_allocation.columns = ['Asset Class', 'Value']
                        fig_pie = px.pie(
                            asset_allocation,
                            names='Asset Class',
                            values='Value',
                            color_discrete_sequence=[
                                '#3b82f6','#22c55e','#f59e0b',
                                '#8b5cf6','#ef4444','#06b6d4','#f97316'
                            ],
                            hole=0.4
                        )
                        fig_pie.update_layout(
                            margin=dict(t=0, b=0, l=0, r=0),
                            height=280,
                            showlegend=True,
                            legend=dict(
                                orientation="v",
                                yanchor="middle",
                                y=0.5,
                                font=dict(size=11)
                            ),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )
                        fig_pie.update_traces(
                            textposition='inside',
                            textinfo='percent',
                            textfont_size=11
                        )
                        st.plotly_chart(fig_pie, use_container_width=True)
                    except Exception as e:
                        st.error(f"Chart error: {e}")

                with chart_col2:
                    st.markdown("#### 🏭 Sector Breakdown")
                    try:
                        sector_data = (
                            portfolio_df.groupby('SECTOR')['CURRENT_VALUE']
                            .sum()
                            .reset_index()
                            .sort_values('CURRENT_VALUE', ascending=True)
                        )
                        sector_data.columns = ['Sector', 'Value']
                        sector_data['Pct']  = (
                            sector_data['Value'] /
                            sector_data['Value'].sum() * 100
                        ).round(1)
                        fig_bar = px.bar(
                            sector_data,
                            x='Value',
                            y='Sector',
                            orientation='h',
                            color='Pct',
                            color_continuous_scale=[
                                '#dbeafe','#3b82f6','#1d4ed8'
                            ],
                            text=sector_data['Pct'].apply(
                                lambda x: f"{x:.1f}%"
                            )
                        )
                        fig_bar.update_layout(
                            margin=dict(t=0, b=0, l=0, r=0),
                            height=280,
                            showlegend=False,
                            coloraxis_showscale=False,
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            xaxis=dict(
                                showgrid=True,
                                gridcolor='#f1f5f9',
                                title=''
                            ),
                            yaxis=dict(title='')
                        )
                        fig_bar.update_traces(
                            textposition='outside',
                            textfont_size=10
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)
                    except Exception as e:
                        st.error(f"Sector chart error: {e}")

                st.markdown("---")

                # ── Holdings by Portfolio ─────────────────────────
                st.markdown("#### 📁 Holdings Detail")

                for portfolio in portfolio_df['PORTFOLIO_NAME'].unique():
                    pf_data  = portfolio_df[
                        portfolio_df['PORTFOLIO_NAME'] == portfolio
                    ].copy()
                    pf_total = pf_data['CURRENT_VALUE'].sum()
                    pf_pnl   = pf_data['UNREALIZED_PNL'].sum()

                    with st.expander(
                        f"📁 {portfolio}  —  "
                        f"${pf_total:,.0f}  |  "
                        f"P&L: ${pf_pnl:+,.0f}",
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
                            lambda x: f"+${x:,.0f}" if x >= 0 else f"-${abs(x):,.0f}"
                        )
                        display['AVERAGE_COST'] = display['AVERAGE_COST'].apply(
                            lambda x: f"${x:,.2f}"
                        )
                        display['WEIGHT_PCT'] = display['WEIGHT_PCT'].apply(
                            lambda x: f"{x:.1f}%"
                        )
                        st.dataframe(
                            display[[
                                'SECURITY_NAME', 'TICKER', 'ASSET_CLASS',
                                'SECTOR', 'QUANTITY', 'AVERAGE_COST',
                                'CURRENT_VALUE', 'UNREALIZED_PNL',
                                'TODAY_CHANGE', 'WEIGHT_PCT'
                            ]].rename(columns={
                                'SECURITY_NAME':  'Security',
                                'TICKER':         'Ticker',
                                'ASSET_CLASS':    'Class',
                                'SECTOR':         'Sector',
                                'QUANTITY':       'Qty',
                                'AVERAGE_COST':   'Avg Cost',
                                'CURRENT_VALUE':  'Value',
                                'UNREALIZED_PNL': 'Unreal. P&L',
                                'TODAY_CHANGE':   'Today %',
                                'WEIGHT_PCT':     'Weight'
                            }),
                            use_container_width=True,
                            hide_index=True
                        )

                st.markdown("---")

                # ── Related News Section ──────────────────────────
                st.markdown("#### 📰 News Affecting This Portfolio")

                names    = portfolio_df['SECURITY_NAME'].tolist()
                keywords = []
                for name in names[:8]:
                    word = name.split()[0]
                    if len(word) > 3:
                        keywords.append(word.lower())

                if keywords:
                    keyword_conditions = " OR ".join([
                        f"LOWER(r.TITLE) LIKE '%{kw}%'"
                        for kw in keywords[:6]
                    ])
                    try:
                        related_news = run_query(f"""
                            SELECT
                                r.TITLE,
                                r.SOURCE,
                                r.URL,
                                e.SENTIMENT,
                                e.SUMMARY,
                                r.PUBLISHED_AT
                            FROM BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED e
                            JOIN BANK_POC.EXTERNAL_DATA.NEWS_RAW r
                                ON e.NEWS_RAW_ID = r.ID
                            WHERE ({keyword_conditions})
                            ORDER BY r.PUBLISHED_AT DESC
                            LIMIT 5
                        """)

                        if related_news.empty:
                            st.info(
                                "No related news found for "
                                "this portfolio's holdings."
                            )
                        else:
                            for _, news_row in related_news.iterrows():
                                sentiment  = news_row['SENTIMENT']
                                icon       = "🟢" if sentiment == "POSITIVE" \
                                    else "🔴" if sentiment == "NEGATIVE" \
                                    else "🟡"
                                border_clr = "#22c55e" if sentiment == "POSITIVE" \
                                    else "#ef4444" if sentiment == "NEGATIVE" \
                                    else "#f59e0b"
                                st.markdown(f"""
                                    <div style="background:white;
                                                padding:12px 16px;
                                                border-radius:8px;
                                                margin-bottom:8px;
                                                border-left:4px solid {border_clr};
                                                box-shadow:0 1px 3px rgba(0,0,0,0.05)">
                                        <div style="display:flex;
                                                    justify-content:space-between;
                                                    margin-bottom:4px">
                                            <span style="font-weight:600;
                                                         font-size:13px; color:#111">
                                                {news_row['TITLE']}
                                            </span>
                                            <span style="font-size:12px; color:#666;
                                                         white-space:nowrap;
                                                         margin-left:12px">
                                                {icon} {sentiment}
                                            </span>
                                        </div>
                                        <div style="font-size:12px; color:#555;
                                                    margin-bottom:6px">
                                            {news_row['SUMMARY'] or ''}
                                        </div>
                                        <div style="font-size:11px; color:#888">
                                            📌 {news_row['SOURCE']} &nbsp;|&nbsp;
                                            <a href="{news_row['URL']}"
                                               target="_blank"
                                               style="color:#3b82f6">
                                                Read more →
                                            </a>
                                        </div>
                                    </div>
                                """, unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Could not load related news: {e}")

        except Exception as e:
            st.error(f"Could not load portfolio: {e}")
            
# ─────────────────────────────────────────────────────────────────
# TAB 4 — TAVILY NEWS SEARCH
# ─────────────────────────────────────────────────────────────────
with tab4:
    st.markdown("## 🔍 Search Latest News")
    st.markdown(
        "*Search the live web — results automatically "
        "saved & AI-enriched in Snowflake*"
    )

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.info("🔍 You Search")
    col_b.info("🌍 Tavily Fetches")
    col_c.info("💾 Saved to Snowflake")
    col_d.info("🤖 AI Enriches")

    st.markdown("---")

    search_query = st.text_input(
        "What would you like to search for?",
        placeholder="e.g. Bank of Canada rate decision, "
                    "TSX market today, Canadian housing..."
    )

    if st.button("🔍 Search & Save to Snowflake", type="primary"):
        if not search_query:
            st.warning("Please enter a search query.")
        else:
            with st.spinner(f"Searching '{search_query}'..."):
                results       = tavily_search(search_query)
                answer        = results.get('answer')
                articles      = results.get('results', [])
                saved_count   = 0
                skipped_count = 0

                # REPLACE WITH THIS
                if answer:
                    st.markdown("### 🤖 AI Answer")
                    st.markdown("---")
                    st.markdown(answer)
                    
                    st.markdown("---")

                st.markdown("### 📰 Search Results")

                if not articles:
                    st.warning("No results found.")
                else:
                    for article in articles:
                        title   = article.get('title', '')
                        content = article.get('content', '')
                        url     = article.get('url', '')
                        source  = url.split('/')[2].replace(
                            'www.', ''
                        ) if url else 'Unknown'

                        try:
                            status = save_article_to_snowflake(
                                title, content, url, source
                            )
                            if status == "saved":
                                saved_count  += 1
                                status_badge  = (
                                    '<span class="saved-badge">'
                                    '✅ Saved & AI Enriched</span>'
                                )
                            else:
                                skipped_count += 1
                                status_badge   = (
                                    '<span class="skipped-badge">'
                                    '⏭️ Already in Snowflake</span>'
                                )
                      # REPLACE WITH THIS — shows the actual error
                        except Exception as save_err:
                            status_badge = (
                                f'<span class="skipped-badge">'
                                f'❌ {str(save_err)[:60]}</span>'
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
                                    {status_badge}
                                </div>
                                <div style="color:#444; font-size:14px;
                                            margin-bottom:6px">
                                    {content[:300]}...
                                </div>
                                <div style="font-size:12px; color:#888">
                                    📌 {source} |
                                    <a href="{url}" target="_blank">
                                        Read more →
                                    </a>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)

                    st.markdown("---")
                    s1, s2, s3 = st.columns(3)
                    s1.metric("🔍 Results Found",      len(articles))
                    s2.metric("💾 Saved to Snowflake", saved_count)
                    s3.metric("⏭️ Already Existed",    skipped_count)

                    if saved_count > 0:
                        st.success(
                            f"✅ {saved_count} new articles saved! "
                            f"Check the News Feed tab."
                        )

# ─────────────────────────────────────────────────────────────────
#OLD TAB 5 — AI CHAT WITH MODEL SELECTOR
# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
# NEW TAB 5 — AI CHAT WITH SEMANTIC RAG + STRUCTURED REASONING
# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
# TAB 5 — AI CHAT — REDESIGNED LAYOUT
# ─────────────────────────────────────────────────────────────────
with tab5:
    if not selected_customer:
        st.warning("⚠️ Please search and select a customer from the sidebar.")
    else:

        # ── Top Header Row ────────────────────────────────────────
        st.markdown("## 🤖 AI Advisor")
        st.markdown(
            f"*Semantic RAG + Structured Reasoning — {selected_customer}*"
        )

        # ── How It Works Banner ───────────────────────────────────
        b1, b2, b3, b4 = st.columns(4)
        b1.info("🔍 Semantic Search\nFinds by meaning")
        b2.info("📊 Customer Context\nHoldings + rates")
        b3.info("🧠 Structured Reasoning\n6-section analysis")
        b4.info("✅ Consistent Output\nAlways same format")

        st.markdown("---")

        # ── TWO COLUMN LAYOUT ─────────────────────────────────────
        left_col, right_col = st.columns([2, 3], gap="large")

        # ════════════════════════════════════════════════════════
        # LEFT COLUMN — Controls & Buttons
        # ════════════════════════════════════════════════════════
        with left_col:

            # ── Model Selector ────────────────────────────────
            st.markdown("#### 🧠 AI Model")
            selected_model_label = st.selectbox(
                "Model",
                list(MODELS.keys()),
                label_visibility="collapsed"
            )
            selected_model = MODELS[selected_model_label]

            # Model info badge
            if "GPT" in selected_model_label:
                st.caption("🟢 OpenAI · Inside Snowflake")
            elif "Claude" in selected_model_label:
                st.caption("🟣 Anthropic · Inside Snowflake")
            elif "Mistral Large" in selected_model_label:
                st.caption("🔵 Mistral AI · Inside Snowflake")
            elif "Mixtral" in selected_model_label:
                st.caption("🔵 Mistral AI · Inside Snowflake")
            elif "Llama 3.1 70b" in selected_model_label:
                st.caption("🟠 Meta · Inside Snowflake")
            elif "Llama 3.1 8b" in selected_model_label:
                st.caption("🟠 Meta · Inside Snowflake")
            elif "DeepSeek" in selected_model_label:
                st.caption("⚫ DeepSeek · Inside Snowflake")
            elif "Arctic" in selected_model_label:
                st.caption("🔷 Snowflake · Inside Snowflake")
            elif "Gemma" in selected_model_label:
                st.caption("🔴 Google · Inside Snowflake")

            st.markdown("---")

            # ── News Limit ────────────────────────────────────
            st.markdown("#### 🎯 Articles to Retrieve")
            news_limit = st.slider(
                "Articles",
                min_value=3,
                max_value=15,
                value=8,
                key="ai_news_limit",
                label_visibility="collapsed"
            )
            st.caption(f"{news_limit} articles via semantic search")

            st.markdown("---")

            # ── Advisor Buttons ───────────────────────────────
            st.markdown("#### 💼 Advisor Questions")

            if st.button(
                "📞 Pre-call briefing",
                use_container_width=True,
                key="btn_precall"
            ):
                st.session_state.ai_prompt  = (
                    f"I have a call with {selected_customer} in "
                    f"10 minutes. Summarize their portfolio, "
                    f"any news affecting their holdings today "
                    f"and give me 3 talking points."
                )
                st.session_state.query_type = "customer"

            if st.button(
                "⚠️ Holdings at risk today",
                use_container_width=True,
                key="btn_risk"
            ):
                st.session_state.ai_prompt  = (
                    f"Based on today's market news, which of "
                    f"{selected_customer}'s holdings are most "
                    f"at risk and what should I do?"
                )
                st.session_state.query_type = "customer"

            if st.button(
                "🔄 Rebalancing needed?",
                use_container_width=True,
                key="btn_rebalance"
            ):
                st.session_state.ai_prompt  = (
                    f"Does {selected_customer}'s portfolio need "
                    f"rebalancing? Consider their risk profile, "
                    f"current allocation and market conditions."
                )
                st.session_state.query_type = "customer"

            if st.button(
                "💬 Retention strategy",
                use_container_width=True,
                key="btn_retain"
            ):
                st.session_state.ai_prompt  = (
                    f"What should I do to retain "
                    f"{selected_customer} as a client given "
                    f"their portfolio performance and today's market?"
                )
                st.session_state.query_type = "customer"

            st.markdown("---")

            # ── Manager Buttons ───────────────────────────────
            st.markdown("#### 📋 Manager Questions")

            if st.button(
                "🚨 Who to call today?",
                use_container_width=True,
                key="btn_whocall"
            ):
                st.session_state.ai_prompt  = (
                    "Based on today's market news, which types "
                    "of clients should advisors prioritize calling "
                    "today and why? Consider sector exposure "
                    "and risk profiles."
                )
                st.session_state.query_type = "manager"

            if st.button(
                "📊 Sector exposure risk",
                use_container_width=True,
                key="btn_sector"
            ):
                st.session_state.ai_prompt  = (
                    "Based on today's news, which market sectors "
                    "are under pressure? What is the likely impact "
                    "on a Canadian wealth management book with "
                    "exposure to energy, financials and real estate?"
                )
                st.session_state.query_type = "manager"

            if st.button(
                "🏦 BoC rate impact",
                use_container_width=True,
                key="btn_boc"
            ):
                st.session_state.ai_prompt  = (
                    "The Bank of Canada held rates at 2.25%. "
                    "What is the impact on a Canadian wealth "
                    "management portfolio? Which client segments "
                    "and asset classes are most affected and "
                    "what actions should advisors take?"
                )
                st.session_state.query_type = "manager"

            if st.button(
                "📰 Morning intelligence",
                use_container_width=True,
                key="btn_morning"
            ):
                st.session_state.ai_prompt  = (
                    "Give me a senior manager morning briefing: "
                    "top 3 market risks today, which sectors are "
                    "moving, Bank of Canada rate outlook, and the "
                    "top 3 actions wealth advisors should take today."
                )
                st.session_state.query_type = "manager"

        # ════════════════════════════════════════════════════════
        # RIGHT COLUMN — Chat Interface
        # ════════════════════════════════════════════════════════
        with right_col:

            st.markdown("#### 💬 Ask a Question")

            user_prompt = st.text_area(
                "Question",
                value=st.session_state.get('ai_prompt', ''),
                height=140,
                placeholder=(
                    f"Ask anything about {selected_customer}, "
                    f"market conditions, portfolio risk, "
                    f"rebalancing, client retention...\n\n"
                    f"Or click a quick question on the left →"
                ),
                label_visibility="collapsed"
            )

            # Query type indicator
            query_type = st.session_state.get('query_type', 'customer')
            if query_type == "manager":
                st.caption(
                    "📋 Manager mode — market-wide response, "
                    "no customer context"
                )
            else:
                st.caption(
                    f"💼 Advisor mode — response focused on "
                    f"{selected_customer}"
                )

            if st.button(
                "🤖 Get Structured AI Analysis",
                type="primary",
                use_container_width=True
            ):
                if not user_prompt:
                    st.warning("Please enter a question.")
                else:
                    progress = st.progress(0)
                    status   = st.empty()

                    try:
                        # Step 1 — Semantic search
                        # ── Step 1 — Semantic News Retrieval ─────────────────
                        status.markdown(
                            "🔍 **Step 1/4** — Semantic search "
                            "retrieving relevant news..."
                        )
                        progress.progress(10)

                        news, search_method = semantic_search_news(
                            query=user_prompt,
                            limit=news_limit
                        )

                        # ── Show indicator if whitelist fallback triggered ────
                        if search_method == "whitelisted_fallback":
                            st.info(
                                "🌐 **Live Whitelisted Search Triggered** — "
                                "Snowflake had insufficient data for this query. "
                                "Automatically searched pre-approved sources: "
                                "BNN Bloomberg, Financial Post, Reuters, "
                                "Bank of Canada, OSFI and more. "
                                "Results saved to Snowflake for future queries."
                            )
                        elif search_method == "keyword_fallback":
                            st.warning(
                                "⚠️ **Keyword Fallback** — Semantic search "
                                "unavailable. Using keyword matching instead."
                            )

                        progress.progress(30)

                        # ── Step 2 — Customer Context ─────────────────────────────
                        status.markdown(
                            "📊 **Step 2/4** — Loading market context..."
                        )

                        query_type = st.session_state.get('query_type', 'customer')

                        # Holdings — customer mode only
                        if query_type == "customer":
                            holdings = run_query("""
                                SELECT
                                    h.SECURITY_NAME, h.ASSET_CLASS,
                                    h.SECTOR, h.CURRENT_VALUE,
                                    h.TICKER, h.UNREALIZED_PNL,
                                    h.WEIGHT_PCT, h.QUANTITY
                                FROM BANK_POC.INTERNAL_DATA.CUSTOMERS c
                                JOIN BANK_POC.INTERNAL_DATA.PORTFOLIOS p
                                    ON c.CUSTOMER_ID = p.CUSTOMER_ID
                                JOIN BANK_POC.INTERNAL_DATA.HOLDINGS h
                                    ON p.PORTFOLIO_ID = h.PORTFOLIO_ID
                                WHERE c.CUSTOMER_NAME = %s
                                ORDER BY h.CURRENT_VALUE DESC
                            """, (selected_customer,))
                        else:
                            holdings = pd.DataFrame()

                        # Rates and prices — ALWAYS load for both modes
                        rates = run_query("""
                            SELECT SERIES_NAME, RATE_VALUE
                            FROM (
                                SELECT SERIES_NAME, RATE_VALUE,
                                    ROW_NUMBER() OVER (
                                        PARTITION BY SERIES_CODE
                                        ORDER BY RATE_DATE DESC
                                    ) AS RN
                                FROM BANK_POC.EXTERNAL_DATA.BOC_RATES
                            ) WHERE RN = 1
                        """)

                        prices = run_query("""
                            SELECT COMPANY_NAME, PRICE, CHANGE_PCT
                            FROM BANK_POC.EXTERNAL_DATA.MARKET_PRICES
                            WHERE PRICE_DATE = CURRENT_DATE()
                            ORDER BY ABS(CHANGE_PCT) DESC
                            LIMIT 8
                        """)
                        
                        # Step 3 — Build context
                        status.markdown(
                            "⚙️ **Step 3/4** — Building analysis "
                            "context..."
                        )
                        holdings_text = "\n".join([
                            f"- {r['SECURITY_NAME']} "
                            f"({r['ASSET_CLASS']} | {r['SECTOR']}): "
                            f"${r['CURRENT_VALUE']:,.0f} | "
                            f"P&L: ${r['UNREALIZED_PNL']:,.0f} | "
                            f"Weight: {r['WEIGHT_PCT']:.1f}%"
                            for _, r in holdings.iterrows()
                        ]) if not holdings.empty else "No holdings found"
                        # REPLACE WITH THIS — safe column access with .get()

                        if not news.empty:
                            # Normalise all column names to uppercase
                            news.columns = [c.upper() for c in news.columns]
                            news_text = "\n".join([
                                f"- [{r.get('SENTIMENT', 'N/A')}] "
                                f"{r.get('TITLE', 'No title')} — "
                                f"{str(r.get('SUMMARY', ''))[:200]}"
                                for _, r in news.iterrows()
                            ])
                        else:
                            news_text = "No relevant news found"

                        rates_text = "\n".join([
                            f"- {r['SERIES_NAME']}: {r['RATE_VALUE']}"
                            for _, r in rates.iterrows()
                        ]) if not rates.empty else "No rates available"

                        prices_text = "\n".join([
                            f"- {r['COMPANY_NAME']}: "
                            f"${r['PRICE']:.2f} "
                            f"({r['CHANGE_PCT']:+.2f}%)"
                            for _, r in prices.iterrows()
                        ]) if not prices.empty else "No prices available"

                        progress.progress(70)

                        # Step 4 — AI analysis
                        status.markdown(
                            f"🧠 **Step 4/4** — "
                            f"{selected_model_label.split('—')[0].strip()} "
                            f"generating structured analysis..."
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

                        # ── Response Header ───────────────────────
                        mode_badge = (
                            "📋 Manager · Market-Wide"
                            if query_type == "manager"
                            else f"💼 Advisor · {selected_customer}"
                        )
                        st.markdown(
                            f"### 💡 AI Analysis "
                            f"<span style='font-size:12px;color:#888'>"
                            f"— "
                            f"{selected_model_label.split('(')[0].strip()}"
                            f" · Semantic RAG · {mode_badge}"
                            f"</span>",
                            unsafe_allow_html=True
                        )

                        # ── Retrieval Metrics ─────────────────────
                        rc1, rc2, rc3 = st.columns(3)
                        rc1.metric(
                            "📰 News Retrieved",
                            f"{len(news)} articles"
                        )
                        rc2.metric(
                            "💼 Holdings",
                            f"{len(holdings)} positions"
                        )
                        # Update the metric display
                        method_display = {
                        "snowflake":            "🧠 Semantic RAG",
                        "whitelisted_fallback": "🌐 Live Whitelist",
                        "keyword_fallback":     "⚠️ Keyword Search"
                        }
                        rc3.metric(
                            "🔍 Search Method",
                            method_display.get(search_method, search_method)
                        )
#                        rc3.metric(
#                            "🔍 Method",
#                           "Semantic RAG"
#                      )

                        st.markdown("---")

                        # ── AI Response ───────────────────────────
                        st.markdown(response)

                        # ── Data Sources ──────────────────────────
                        with st.expander(
                            "📊 View Data Sources Used"
                        ):
                            ds1, ds2 = st.columns(2)
                            with ds1:
                                st.markdown(
                                    "**Semantically Retrieved News**"
                                )
                                if not news.empty:
                                    display_news = news.copy()
                                    display_news.columns = [
                                        c.upper()
                                        for c in display_news.columns
                                    ]
                                    show_cols = [
                                        c for c in
                                        ['TITLE','SENTIMENT','SOURCE']
                                        if c in display_news.columns
                                    ]
                                    st.dataframe(
                                        display_news[show_cols],
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                st.markdown("**BoC Rates**")
                                st.dataframe(
                                    rates,
                                    use_container_width=True,
                                    hide_index=True
                                )
                            with ds2:
                              # REPLACE WITH THIS
                                if query_type == "customer" and not holdings.empty:
                                    st.markdown("**Customer Holdings**")
                                    st.dataframe(
                                        holdings[[
                                            'SECURITY_NAME', 'ASSET_CLASS',
                                            'CURRENT_VALUE', 'UNREALIZED_PNL',
                                            'WEIGHT_PCT'
                                        ]],
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                else:
                                    st.markdown("**Customer Holdings**")
                                    st.info("ℹ️ Not loaded — Manager mode uses market-wide context only.")

                                st.markdown("**Market Prices**")
                                st.dataframe(
                                    prices,
                                    use_container_width=True,
                                    hide_index=True
                                )
                    except Exception as e:
                        progress.empty()
                        status.empty()
                        st.error(f"Analysis failed: {e}")

# ─────────────────────────────────────────────────────────────────
# TAB 6 — LANGGRAPH CONVERSATIONAL AGENT
# ─────────────────────────────────────────────────────────────────
with tab6:
    if not selected_customer:
        st.warning(
            "⚠️ Please select a customer from the sidebar."
        )
    else:
        st.markdown("## 🦾 Agentic AI Advisor")
        st.markdown(
            "*LangGraph · Conversational Memory · "
            "Audit Logged · Ask follow-up questions*"
        )

        # ── Banner ────────────────────────────────────────────────
        a1, a2, a3, a4 = st.columns(4)
        a1.info("🧭 Router\nDecides tools")
        a2.info("🔄 Agent Loop\nRetries if thin")
        a3.info("💬 Memory\nFollowup aware")
        a4.info("📋 Audit Log\nEvery decision saved")

        st.markdown("---")

        # ── Session State Init ────────────────────────────────────
        if 'agent_messages'   not in st.session_state:
            st.session_state.agent_messages   = []
        if 'agent_thread_id'  not in st.session_state:
            st.session_state.agent_thread_id  = str(uuid.uuid4())
        if 'agent_query_type' not in st.session_state:
            st.session_state.agent_query_type = 'customer'

        # ── Two Column Layout ─────────────────────────────────────
        left_col, right_col = st.columns([2, 3], gap="large")

        # ════════════════════════════════════════════════════════
        # LEFT — Controls
        # ════════════════════════════════════════════════════════
        with left_col:

            st.markdown("#### 🧠 AI Model")
            agent_model_label = st.selectbox(
                "Model",
                list(MODELS.keys()),
                key="agent_model_select",
                label_visibility="collapsed"
            )
            agent_model = MODELS[agent_model_label]

            if "Claude"  in agent_model_label:
                st.caption("🟣 Anthropic · Inside Snowflake")
            elif "GPT"   in agent_model_label:
                st.caption("🟢 OpenAI · Inside Snowflake")
            elif "Mistral" in agent_model_label:
                st.caption("🔵 Mistral · Inside Snowflake")
            else:
                st.caption("⚙️ Inside Snowflake")

            st.markdown("---")

            # ── Query Mode ────────────────────────────────────────
            st.markdown("#### 🎯 Mode")
            agent_mode = st.radio(
                "Mode",
                ["💼 Advisor", "📋 Manager"],
                key="agent_mode_radio",
                label_visibility="collapsed"
            )
            st.session_state.agent_query_type = (
                "customer" if "Advisor" in agent_mode
                else "manager"
            )
            st.caption(
                f"{'Customer: ' + selected_customer if st.session_state.agent_query_type == 'customer' else 'Market-wide, no customer context'}"
            )

            st.markdown("---")

            # ── Conversation Controls ─────────────────────────────
            st.markdown("#### 💬 Conversation")

            # Show thread info
            msg_count = len([
                m for m in st.session_state.agent_messages
                if m['role'] == 'user'
            ])
            st.caption(
                f"Thread: `{st.session_state.agent_thread_id[:8]}...`\n"
                f"{msg_count} question(s) in this conversation"
            )

            if st.button(
                "🗑️ Clear — Start New Conversation",
                use_container_width=True,
                key="clear_agent_chat"
            ):
                st.session_state.agent_messages  = []
                st.session_state.agent_thread_id = str(uuid.uuid4())
                st.rerun()

            st.markdown("---")

            # ── Quick Questions ───────────────────────────────────
            st.markdown("#### 💼 Advisor Questions")

            advisor_questions = {
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

            for label, (prompt, qtype) in advisor_questions.items():
                if st.button(
                    label,
                    use_container_width = True,
                    key                 = f"agent_q_{label}"
                ):
                    st.session_state.agent_prefill    = prompt
                    st.session_state.agent_query_type = qtype
                    st.session_state.agent_input_text = prompt
                    #st.rerun()

            st.markdown("#### 📋 Manager Questions")

            manager_questions = {
                "🚨 Who to call today?": (
                    "Which client segments should advisors "
                    "prioritize calling today based on "
                    "today's market news and sector movements?",
                    "manager"
                ),
                "🏦 BoC rate impact": (
                    "What is the impact of current Bank of Canada "
                    "rates on Canadian wealth management portfolios? "
                    "Which asset classes and client segments are "
                    "most affected and what should advisors do?",
                    "manager"
                ),
                "📰 Morning briefing": (
                    "Give me a senior manager morning briefing: "
                    "top 3 market risks today, which sectors are "
                    "moving and the top 3 actions advisors "
                    "should take today.",
                    "manager"
                ),
                "📊 Sector exposure risk": (
                    "Which market sectors are under pressure today? "
                    "What is the likely impact on a Canadian wealth "
                    "management book with exposure to energy, "
                    "financials and real estate?",
                    "manager"
                ),
            }

            for label, (prompt, qtype) in manager_questions.items():
                if st.button(
                    label,
                    use_container_width = True,
                    key                 = f"agent_mq_{label}"
                ):
                    st.session_state.agent_prefill    = prompt
                    st.session_state.agent_query_type = qtype
                    st.session_state.agent_input_text = prompt
                   # st.rerun()

        # ════════════════════════════════════════════════════════
        # RIGHT — Chat Interface
        # ════════════════════════════════════════════════════════
        with right_col:

            st.markdown("#### 💬 Conversation")

            # ── Render Chat History ───────────────────────────────────────
            # NO height-constrained container — causes rendering issues
            for msg in st.session_state.agent_messages:
                with st.chat_message(msg['role']):
                    if msg['role'] == 'assistant':

                        # Reasoning log expander
                        if msg.get('reasoning_log'):
                            with st.expander(
                                f"🔍 Agent Reasoning "
                                f"({len(msg['reasoning_log'])} steps)",
                                expanded=False
                            ):
                                for step in msg['reasoning_log']:
                                    st.markdown(step)

                                mc1, mc2, mc3 = st.columns(3)
                                mc1.metric("📰 News",    msg.get('news_count', 0))
                                mc2.metric("🛠️ Tools",   msg.get('tools_count', 0))
                                mc3.metric("🔄 Searches",msg.get('search_attempts', 0))

                        # Response text
                        if msg.get('content'):
                            st.markdown(msg['content'])
                        else:
                            st.warning("No response generated.")
                    else:
                        st.markdown(msg['content'])

            # Empty state
            if not st.session_state.agent_messages:
                st.info(
                    "🦾 Ask the agent anything. "
                    "It remembers your conversation — "
                    "ask follow-up questions naturally."
                )

            st.markdown("---")

            # ── Input Area ────────────────────────────────────────────────
            if 'agent_text_area' not in st.session_state:
                st.session_state.agent_text_area = ""

            # When button sets prefill — write directly to the key
            # (already handled in button click via agent_input_text)
            # Sync prefill into the actual widget key
            if st.session_state.get('agent_input_text', ''):
                st.session_state.agent_text_area  = \
                    st.session_state.agent_input_text
                st.session_state.agent_input_text = ""

            user_input = st.text_area(
                "Your question",
                height           = 100,
                placeholder      = "Ask a question or follow up...",
                key              = "agent_text_area",   # ← value now controlled
                label_visibility = "collapsed"          #    via session state key
            )

            st.caption(
                "📋 Manager mode — market-wide"
                if st.session_state.agent_query_type == "manager"
                else f"💼 Advisor mode — {selected_customer}"
            )

            send_col, clear_col = st.columns([3, 1])

            with send_col:
                send_clicked = st.button(
                    "🦾 Send to Agent",
                    type                = "primary",
                    use_container_width = True,
                    key                 = "send_agent_btn"
                )

            with clear_col:
                if st.button(
                    "🗑️ Clear",
                    use_container_width = True,
                    key                 = "clear_chat_btn"
                ):
                    st.session_state.agent_messages   = []
                    st.session_state.agent_thread_id  = str(uuid.uuid4())
                    st.session_state.agent_input_text = ""
                    st.rerun()

            # ── Process Input ─────────────────────────────────────────────
            if send_clicked and user_input.strip():
                from agent import run_advisor_agent

                question = user_input.strip()

                # Clear input immediately
                st.session_state.agent_input_text = ""

                # Add user message
                st.session_state.agent_messages.append({
                    'role':    'user',
                    'content': question
                })

                # Build conversation history
                conv_history = [
                    {
                        'role':    m['role'],
                        'content': m['content'][:500]
                    }
                    for m in st.session_state.agent_messages[:-1]
                ]

                # Run agent with visible spinner
                with st.spinner("🦾 Agent is reasoning — please wait..."):
                    try:
                        result = run_advisor_agent(
                            question             = question,
                            customer_name        = selected_customer,
                            query_type           = st.session_state.agent_query_type,
                            model                = agent_model,
                            conversation_history = conv_history,
                            thread_id            = st.session_state.agent_thread_id,
                            advisor_name         = selected_advisor
                        )

                        # Add response
                        st.session_state.agent_messages.append({
                            'role':            'assistant',
                            'content':         result.get('final_response')
                                            or "No response generated.",
                            'reasoning_log':   result.get('reasoning_log', []),
                            'news_count':      len(result.get('news_articles', [])),
                            'tools_count':     len(result.get('tools_needed', [])),
                            'search_attempts': result.get('search_attempts', 0)
                        })

                    except Exception as e:
                        # Show error as a message — don't crash
                        st.session_state.agent_messages.append({
                            'role':    'assistant',
                            'content': f"❌ Agent failed: {str(e)}",
                            'reasoning_log': [],
                            'news_count': 0,
                            'tools_count': 0,
                            'search_attempts': 0
                        })

                st.rerun()
                
