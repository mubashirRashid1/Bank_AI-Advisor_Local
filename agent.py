# ── agent.py — LangGraph Agent with Semantic Scope Detection ─────
from datetime import date, datetime
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional
import json
import uuid
import os
from db import get_connection, run_cortex, semantic_search_chroma

today = date.today().isoformat()

# ── Agent State ───────────────────────────────────────────────────
class AdvisorState(TypedDict):
    question:             str
    customer_name:        str
    query_type:           str
    model:                str
    conversation_history: List[dict]
    thread_id:            str
    news_articles:        List[dict]
    holdings:             List[dict]
    rates:                List[dict]
    prices:               List[dict]
    tools_needed:         List[str]
    search_attempts:      int
    has_enough_data:      bool
    reasoning_log:        List[str]
    final_response:       Optional[str]

# ── Pre-computed Financial Context Embeddings ─────────────────────
_financial_embeddings = None

def get_financial_embeddings():
    """
    Embed representative financial sentences once.
    Cached after first call — never recomputed.
    """
    global _financial_embeddings
    if _financial_embeddings is None:
        from db import generate_embedding
        import numpy as np

        FINANCIAL_SENTENCES = [
            "Canadian wealth management portfolio investment strategy",
            "Bank of Canada interest rates monetary policy inflation",
            "TSX stock market equity sector analysis performance",
            "OSFI CIRO regulatory compliance requirements advisors",
            "client portfolio risk rebalancing holdings asset allocation",
            "financial advisor wealth management investment advice",
            "Canadian banking financial services industry",
            "mortgage bond yield fixed income market",
            "retirement RRSP TFSA pension fund planning",
            "energy oil gold commodity currency trading",
            "dividend earnings revenue profit growth GDP",
            "hedge fund insurance pension endowment derivatives",
        ]

        _financial_embeddings = np.array([
            generate_embedding(s) for s in FINANCIAL_SENTENCES
        ])

    return _financial_embeddings

def is_financial_question(question: str) -> tuple:
    """
    Returns (is_financial: bool, score: float).
    Uses cosine similarity against financial context embeddings.
    Works with typos, casual phrasing, any word order.
    Threshold 0.25 — deliberately low to avoid false negatives.
    Defaults to True (allow) if embedding fails.
    """
    import numpy as np
    from db import generate_embedding

    try:
        q_vec    = np.array(generate_embedding(question))
        fin_vecs = get_financial_embeddings()

        q_norm   = q_vec / (np.linalg.norm(q_vec) + 1e-10)
        fin_norm = fin_vecs / (
            np.linalg.norm(fin_vecs, axis=1, keepdims=True) + 1e-10
        )
        similarities = fin_norm @ q_norm
        score        = float(np.max(similarities))
        return score > 0.25, round(score, 3)

    except Exception:
        # Embedding failed — default to allow
        return True, 0.0

# ─────────────────────────────────────────────────────────────────
# NODE 1 — ROUTER
# ─────────────────────────────────────────────────────────────────
def router_node(state: AdvisorState) -> AdvisorState:
    question = state['question']
    history  = state['conversation_history']

    # ── If conversation history exists — always continue ──────────
    # Any message after a financial conversation is a follow-up.
    # Handles: typos, "is that correct?", vague references,
    # confirmations — no keyword list needed.
    if len(history) > 0:
        state['reasoning_log'].append(
            "🔄 **Router** — Conversation in progress. "
            "Treating as follow-up."
        )
        state['tools_needed']    = ['search_news']
        state['search_attempts'] = 0
        return state

    # ── First question — semantic scope check ─────────────────────
    is_financial, score = is_financial_question(question)

    state['reasoning_log'].append(
        f"🧭 **Router** — Semantic scope score: `{score}` "
        f"({'✅ Financial' if is_financial else '🚫 Out of scope'})"
    )

    if not is_financial:
        state['tools_needed']    = []
        state['search_attempts'] = 0
        state['final_response']  = (
            "I can only assist with questions related to Canadian "
            "wealth management and financial markets.\n\n"
            "Your question appears to be outside this scope. "
            "Please ask about:\n"
            "- Client portfolios and holdings analysis\n"
            "- Canadian market conditions and TSX\n"
            "- Bank of Canada rates and monetary policy\n"
            "- Investment risk and portfolio rebalancing\n"
            "- Regulatory requirements (OSFI, CIRO)\n"
            "- Sector analysis and market intelligence"
        )
        state['has_enough_data'] = True
        return state

    # ── Financial question — select tools ─────────────────────────
    question_lower = question.lower()

    if state['query_type'] == 'manager':
        tools = ['search_news', 'get_rates', 'get_prices']
    else:
        tools = ['search_news', 'get_holdings',
                 'get_rates', 'get_prices']

    state['reasoning_log'].append(
        f"   Tools: `{'`, `'.join(tools)}`"
    )
    state['tools_needed']    = tools
    state['search_attempts'] = 0
    return state

# ─────────────────────────────────────────────────────────────────
# NODE 2 — SEARCH NEWS
# ─────────────────────────────────────────────────────────────────
def search_news_node(state: AdvisorState) -> AdvisorState:
    state['reasoning_log'].append(
        "🔍 **Search News** — Semantic search..."
    )
    try:
        # ── For follow-ups, enrich search with conversation context ──
        search_query = state['question']
        history      = state['conversation_history']

        if len(history) > 0:
            # Find the original user question from history
            original = next(
                (m['content'] for m in history
                 if m['role'] == 'user'),
                None
            )
            if original:
                # Combine original topic + follow-up for better search
                search_query = (
                    original[:200] + " " + state['question']
                ).strip()
                state['reasoning_log'].append(
                    f"   🔗 Enriched query with original context"
                )

        # ── Regulatory keyword check ──────────────────────────────
        REGULATORY_KEYWORDS = [
            'ciro','iiroc','mfda','osfi','regulatory','regulation',
            'compliance','guidance','requirement','rule change',
            'policy change','new rule','updated guidance',
            'securities commission','financial regulator'
        ]
        question_lower  = state['question'].lower()
        original_lower  = (history[0]['content'].lower()
                          if history else '')
        force_whitelist = any(
            kw in question_lower or kw in original_lower
            for kw in REGULATORY_KEYWORDS
        )

        # ── Always check ChromaDB first ───────────────────────────
        articles   = semantic_search_chroma(search_query, limit=8)
        MINIMUM    = 3
        has_enough = len(articles) >= MINIMUM

        if has_enough:
            state['reasoning_log'].append(
                f"   ✅ Found **{len(articles)} articles** "
                f"from local ChromaDB"
            )
        else:
            if force_whitelist:
                state['reasoning_log'].append(
                    "🏛️ **Regulatory Query** — Local insufficient. "
                    "Searching authoritative sources..."
                )
            else:
                state['reasoning_log'].append(
                    f"   ℹ️ ChromaDB returned {len(articles)} "
                    f"(need {MINIMUM}) — trying whitelist..."
                )

        # ── Whitelist if needed ───────────────────────────────────
        if not has_enough:
            tavily_key = os.getenv('TAVILY_API_KEY')
            if tavily_key:
                try:
                    import requests as req
                    WHITELISTED = [
                        "bankofcanada.ca", "osfi-bsif.gc.ca",
                        "bnnbloomberg.ca", "financialpost.com",
                        "theglobeandmail.com", "reuters.com",
                        "pensionsandinvestments.com", "ciro.ca"
                    ]
                    resp = req.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key":         tavily_key,
                            "query":           search_query,
                            "search_depth":    "basic",
                            "max_results":     5,
                            "include_answer":  False,
                            "include_domains": WHITELISTED
                        },
                        timeout=30
                    )
                    resp.raise_for_status()
                    raw_articles = resp.json().get('results', [])

                    if raw_articles:
                        articles = [{
                            'TITLE':          str(a.get('title',  '') or ''),
                            'SUMMARY':        str(a.get('content','') or '')[:300],
                            'SENTIMENT':      'NEUTRAL',
                            'SOURCE':         (
                                a.get('url','').split('/')[2]
                                .replace('www.','')
                                if a.get('url') and '/'
                                in a.get('url','') else 'unknown'
                            ),
                            'URL':            str(a.get('url', '') or ''),
                            'PUBLISHED_AT':   datetime.now().strftime('%Y-%m-%d'),
                            'ASSET_CLASSES':  'GENERAL',
                            'RELEVANCE_SCORE':0.8
                        } for a in raw_articles]

                        state['reasoning_log'].append(
                            f"   ✅ Whitelist found "
                            f"**{len(articles)} articles** with URLs"
                        )

                        # Save to SQLite + ChromaDB
                        saved_sqlite = 0
                        saved_chroma = 0
                        for a in raw_articles:
                            try:
                                title   = str(a.get('title',   '') or '')
                                content = str(a.get('content', '') or '')
                                url     = str(a.get('url',     '') or '')
                                source  = (
                                    url.split('/')[2].replace('www.','')
                                    if url and '/' in url else 'unknown'
                                )
                                if not url:
                                    continue

                                conn   = get_connection()
                                cursor = conn.cursor()
                                cursor.execute(
                                    "SELECT COUNT(*) FROM NEWS_RAW "
                                    "WHERE URL = ?", (url,)
                                )
                                exists = cursor.fetchone()[0]
                                cursor.close()
                                conn.close()

                                if exists:
                                    continue

                                from db import run_execute
                                news_id = str(uuid.uuid4())
                                run_execute("""
                                    INSERT INTO NEWS_RAW
                                        (ID, SOURCE, TITLE, CONTENT,
                                         URL, PUBLISHED_AT)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                """, (
                                    news_id, source[:100],
                                    title[:1000], content,
                                    url[:2000],
                                    datetime.now().strftime(
                                        '%Y-%m-%dT%H:%M:%SZ'
                                    )
                                ))
                                saved_sqlite += 1

                                enrich_id = str(uuid.uuid4())
                                run_execute("""
                                    INSERT INTO NEWS_ENRICHED
                                        (ID, NEWS_RAW_ID, SUMMARY,
                                         SENTIMENT, ENTITIES,
                                         ASSET_CLASSES, RELEVANCE_SCORE)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    enrich_id, news_id,
                                    content[:2000], 'NEUTRAL',
                                    json.dumps({'source': source}),
                                    json.dumps(['GENERAL']), 0.80
                                ))

                                try:
                                    from db import add_to_vector_index
                                    index_text = (
                                        title + " " + content[:300]
                                    ).strip() or title or "no content"
                                    add_to_vector_index(
                                        doc_id   = enrich_id,
                                        text     = index_text,
                                        metadata = {
                                            'title':        title[:200] or '',
                                            'summary':      content[:300] or '',
                                            'sentiment':    'NEUTRAL',
                                            'source':       source or '',
                                            'url':          url or '',
                                            'published_at': datetime.now()
                                                            .strftime('%Y-%m-%d'),
                                            'asset_classes':'GENERAL'
                                        }
                                    )
                                    saved_chroma += 1
                                except Exception:
                                    pass

                            except Exception:
                                pass

                        try:
                            from db import get_chroma_collection
                            total = get_chroma_collection().count()
                        except Exception:
                            total = -1

                        state['reasoning_log'].append(
                            f"   💾 SQLite: {saved_sqlite} | "
                            f"ChromaDB: {saved_chroma} | "
                            f"Total: {total}"
                        )
                    else:
                        state['reasoning_log'].append(
                            "   ⚠️ Whitelist returned no results"
                        )

                except Exception as e:
                    state['reasoning_log'].append(
                        f"   ⚠️ Whitelist failed: {str(e)[:60]}"
                    )
            else:
                state['reasoning_log'].append(
                    "   ⚠️ TAVILY_API_KEY not set"
                )

        state['news_articles']    = articles
        state['search_attempts'] += 1

    except Exception as e:
        state['news_articles'] = []
        state['reasoning_log'].append(
            f"   ⚠️ Search failed: `{str(e)[:80]}`"
        )
    return state

# ─────────────────────────────────────────────────────────────────
# NODE 3 — GET HOLDINGS
# ─────────────────────────────────────────────────────────────────
def get_holdings_node(state: AdvisorState) -> AdvisorState:
    if state['query_type'] != 'customer':
        state['holdings'] = []
        return state

    state['reasoning_log'].append(
        f"💼 **Get Holdings** — {state['customer_name']}..."
    )
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT h.SECURITY_NAME, h.ASSET_CLASS,
                   h.SECTOR,        h.CURRENT_VALUE,
                   h.TICKER,        h.UNREALIZED_PNL,
                   h.WEIGHT_PCT
            FROM CUSTOMERS c
            JOIN PORTFOLIOS p ON c.CUSTOMER_ID  = p.CUSTOMER_ID
            JOIN HOLDINGS   h ON p.PORTFOLIO_ID = h.PORTFOLIO_ID
            WHERE c.CUSTOMER_NAME = ?
            ORDER BY h.CURRENT_VALUE DESC
        """, (state['customer_name'],))
        columns  = [d[0] for d in cursor.description]
        rows     = cursor.fetchall()
        holdings = [dict(zip(columns, r)) for r in rows]
        state['holdings'] = holdings
        total = sum(r['CURRENT_VALUE'] for r in holdings)
        state['reasoning_log'].append(
            f"   ✅ **{len(holdings)} positions** — ${total:,.0f}"
        )
    except Exception as e:
        state['holdings'] = []
        state['reasoning_log'].append(
            f"   ⚠️ Holdings failed: `{str(e)[:80]}`"
        )
    finally:
        cursor.close()
        conn.close()
    return state

# ─────────────────────────────────────────────────────────────────
# NODE 4 — GET RATES
# ─────────────────────────────────────────────────────────────────
def get_rates_node(state: AdvisorState) -> AdvisorState:
    state['reasoning_log'].append("🏦 **Get Rates** — BoC rates...")
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT SERIES_NAME, RATE_VALUE
            FROM BOC_RATES
            ORDER BY RATE_DATE DESC
            LIMIT 5
        """)
        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        rates   = [dict(zip(columns, r)) for r in rows]
        state['rates'] = rates
        state['reasoning_log'].append(
            f"   ✅ **{len(rates)} rate series**"
        )
    except Exception as e:
        state['rates'] = []
        state['reasoning_log'].append(
            f"   ⚠️ Rates failed: `{str(e)[:80]}`"
        )
    finally:
        cursor.close()
        conn.close()
    return state

# ─────────────────────────────────────────────────────────────────
# NODE 5 — GET PRICES
# ─────────────────────────────────────────────────────────────────
def get_prices_node(state: AdvisorState) -> AdvisorState:
    state['reasoning_log'].append(
        "📈 **Get Prices** — Market prices..."
    )
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COMPANY_NAME, PRICE, CHANGE_PCT
            FROM MARKET_PRICES
            WHERE PRICE_DATE = ?
            ORDER BY ABS(CHANGE_PCT) DESC
            LIMIT 8
        """, (today,))
        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        prices  = [dict(zip(columns, r)) for r in rows]
        state['prices'] = prices
        state['reasoning_log'].append(
            f"   ✅ **{len(prices)} tickers**"
        )
    except Exception as e:
        state['prices'] = []
        state['reasoning_log'].append(
            f"   ⚠️ Prices failed: `{str(e)[:80]}`"
        )
    finally:
        cursor.close()
        conn.close()
    return state

# ─────────────────────────────────────────────────────────────────
# NODE 6 — EVALUATE
# ─────────────────────────────────────────────────────────────────
def evaluate_node(state: AdvisorState) -> AdvisorState:
    state['reasoning_log'].append(
        f"🧠 **Evaluate** — "
        f"News: {len(state['news_articles'])} | "
        f"Attempt: {state['search_attempts']}"
    )

    # ── No relevant articles found — honest response ──────────────
    if not state['news_articles']:
        state['has_enough_data'] = True
        state['final_response']  = (
            "I was unable to find specific and reliable information "
            "about this topic in my available data sources "
            "or approved external sources.\n\n"
            "For authoritative information please check directly:\n"
            "- **CIRO**: ciro.ca\n"
            "- **OSFI**: osfi-bsif.gc.ca\n"
            "- **Bank of Canada**: bankofcanada.ca\n\n"
            "You can also try rephrasing your question — I will "
            "search approved sources again."
        )
        state['reasoning_log'].append(
            "⚠️ **Evaluate** — No articles found. "
            "Returning honest no-data response."
        )
        return state

    state['has_enough_data'] = True
    state['reasoning_log'].append("   ✅ Proceeding to answer")
    return state

# ─────────────────────────────────────────────────────────────────
# NODE 7 — ANSWER
# ─────────────────────────────────────────────────────────────────
def answer_node(state: AdvisorState) -> AdvisorState:
    # Skip if response already set
    if state.get('final_response'):
        return state

    # Build context strings
    holdings_text = "\n".join([
        f"- {r['SECURITY_NAME']} ({r['ASSET_CLASS']} | "
        f"{r['SECTOR']}): ${r['CURRENT_VALUE']:,.0f} | "
        f"P&L: ${r['UNREALIZED_PNL']:,.0f} | "
        f"Weight: {r['WEIGHT_PCT']:.1f}%"
        for r in state['holdings']
    ]) if state['holdings'] else "No holdings"

    news_text = "\n".join([
        f"- [{r.get('SENTIMENT', r.get('sentiment', 'N/A'))}] "
        f"{r.get('TITLE', r.get('title', ''))} — "
        f"{str(r.get('SUMMARY', r.get('summary', '')))[:200]}"
        for r in state['news_articles']
    ]) if state['news_articles'] else "No news found"

    rates_text = "\n".join([
        f"- {r['SERIES_NAME']}: {r['RATE_VALUE']}"
        for r in state['rates']
    ]) if state['rates'] else "No rates"

    prices_text = "\n".join([
        f"- {r['COMPANY_NAME']}: ${r['PRICE']:.2f} "
        f"({r['CHANGE_PCT']:+.2f}%)"
        for r in state['prices']
    ]) if state['prices'] else "No prices"

    # Conversation history
    history_text = ""
    if state['conversation_history']:
        history_text = "\n\nCONVERSATION HISTORY:\n"
        for turn in state['conversation_history'][-6:]:
            role    = "Advisor" if turn['role'] == 'user' else "AI"
            content = str(turn.get('content', ''))[:300]
            history_text += f"{role}: {content}\n\n"

    # Follow-up detection — semantic similarity to conversation
    has_history = len(state['conversation_history']) > 0
    is_followup = False

    if has_history:
        # Use embedding similarity to detect follow-up
        # Compare current question to last AI response
        try:
            import numpy as np
            from db import generate_embedding
            last_ai = next(
                (m['content'] for m in reversed(
                    state['conversation_history']
                ) if m['role'] == 'assistant'),
                None
            )
            if last_ai:
                q_vec  = np.array(
                    generate_embedding(state['question'])
                )
                ai_vec = np.array(
                    generate_embedding(last_ai[:500])
                )
                q_norm  = q_vec  / (np.linalg.norm(q_vec)  + 1e-10)
                ai_norm = ai_vec / (np.linalg.norm(ai_vec) + 1e-10)
                sim     = float(np.dot(q_norm, ai_norm))
                # If question is similar to last response → follow-up
                # If very different → new topic
                is_followup = sim > 0.2
        except Exception:
            # Default: if history exists → treat as follow-up
            is_followup = has_history

    # Build prompt
    if is_followup:
        prompt = (
            "You are a senior Canadian wealth management AI advisor. "
            "Answer the follow-up question using ONLY the information "
            "provided below and in the conversation history. "
            "Do NOT use any knowledge from your training. "
            "Do NOT invent facts, dates, rule names, or policy details. "
            "If the specific information requested is not in the "
            "provided context, say clearly: "
            "'I don't have specific data on that in my current sources. "
            "Please run a fresh search or check the regulator directly.' "
            "Write in plain conversational prose only. "
            "No headers, no numbered sections. "
            "Keep to 2-4 paragraphs."
            + history_text +
            "\n\nFOLLOW-UP QUESTION: " + state['question'] +
            "\n\nAVAILABLE NEWS CONTEXT:\n" + news_text +
            "\n\nRATE CONTEXT:\n" + rates_text +
            "\n\nHOLDINGS CONTEXT:\n" + holdings_text +
            "\n\nIMPORTANT: Only use the above data. "
            "If the answer is not in the data above, say so honestly."
        )
    elif state['query_type'] == 'manager':
        prompt = (
            "You are a senior Canadian wealth management AI advisor "
            "briefing a portfolio manager. "
            "Answer using ONLY the data provided. "
            "Be specific and cite actual numbers. "
            "Do not reference any individual customer. "
            "Write in plain paragraphs only. "
            "Do NOT use headers, numbered sections or bullets. "
            "Cover: market situation, key risks, sectors affected, "
            "advisor actions, and urgency. "
            "Keep to 4-6 paragraphs maximum."
            + history_text +
            "\n\nQUESTION: "             + state['question'] +
            "\n\nLATEST NEWS:\n"         + news_text +
            "\n\nBANK OF CANADA RATES:\n"+ rates_text +
            "\n\nMARKET PRICES:\n"       + prices_text
        )
    else:
        prompt = (
            "You are a senior Canadian wealth management AI advisor. "
            "Analyze using ONLY the data provided. "
            "Be specific and cite actual numbers."
            + history_text +
            "\n\nQUESTION: "             + state['question'] +
            "\n\nCUSTOMER: "             + state['customer_name'] +
            "\n\nHOLDINGS:\n"            + holdings_text +
            "\n\nLATEST NEWS:\n"         + news_text +
            "\n\nBANK OF CANADA RATES:\n"+ rates_text +
            "\n\nMARKET PRICES:\n"       + prices_text +
            "\n\nRespond using EXACTLY this structure:\n"
            "## 1. SITUATION SUMMARY\n"
            "## 2. CUSTOMER IMPACT ASSESSMENT\n"
            "## 3. REGULATORY & COMPLIANCE FLAGS\n"
            "## 4. RECOMMENDED ACTIONS\n"
            "## 5. CLIENT TALKING POINTS\n"
            "## 6. URGENCY SCORE\nScore: X/10\nRationale: ..."
        )

    state['reasoning_log'].append(
        f"💡 **Answer** — "
        f"{'💬 Follow-up' if is_followup else '📋 Structured'} "
        f"using `{state['model']}`..."
    )

    try:
        response = run_cortex(prompt, state['model'])
        state['final_response'] = response
        state['reasoning_log'].append("   ✅ **Analysis complete**")
    except Exception as e:
        state['final_response'] = f"Analysis failed: {e}"
        state['reasoning_log'].append(
            f"   ❌ Failed: `{str(e)[:80]}`"
        )

    return state

# ─────────────────────────────────────────────────────────────────
# CONDITIONAL EDGES
# ─────────────────────────────────────────────────────────────────
def should_continue(state: AdvisorState) -> str:
    return "answer" if state['has_enough_data'] else "search_more"

def should_skip_to_answer(state: AdvisorState) -> str:
    if state.get('final_response'):
        return "answer"
    return "search_news"

# ─────────────────────────────────────────────────────────────────
# BUILD GRAPH
# ─────────────────────────────────────────────────────────────────
def build_agent():
    graph = StateGraph(AdvisorState)

    graph.add_node("router",       router_node)
    graph.add_node("search_news",  search_news_node)
    graph.add_node("get_holdings", get_holdings_node)
    graph.add_node("get_rates",    get_rates_node)
    graph.add_node("get_prices",   get_prices_node)
    graph.add_node("evaluate",     evaluate_node)
    graph.add_node("answer",       answer_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        should_skip_to_answer,
        {"answer": "answer", "search_news": "search_news"}
    )

    graph.add_edge("search_news",  "get_holdings")
    graph.add_edge("get_holdings", "get_rates")
    graph.add_edge("get_rates",    "get_prices")
    graph.add_edge("get_prices",   "evaluate")

    graph.add_conditional_edges(
        "evaluate",
        should_continue,
        {"search_more": "search_news", "answer": "answer"}
    )

    graph.add_edge("answer", END)
    return graph.compile()

# ─────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────
def log_to_snowflake(state, advisor_name, conn=None):
    from db import run_execute
    try:
        run_execute("""
            INSERT INTO AI_AUDIT_LOG (
                AUDIT_ID, ADVISOR_NAME, CUSTOMER_NAME,
                QUERY_TYPE, USER_QUESTION, TOOLS_CALLED,
                SEARCH_ATTEMPTS, NEWS_TITLES,
                HOLDINGS_TICKERS, RATES_USED, PRICES_USED,
                MODEL_USED, AI_RESPONSE, REASONING_LOG,
                NEWS_COUNT, HOLDINGS_COUNT
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(uuid.uuid4()),
            str(advisor_name or ''),
            str(state.get('customer_name', '') or ''),
            str(state.get('query_type',    '') or ''),
            str(state.get('question',      '') or ''),
            json.dumps(state.get('tools_needed',  [])),
            int(state.get('search_attempts', 0)),
            json.dumps([
                r.get('TITLE', r.get('title', ''))[:100]
                for r in state.get('news_articles', [])
            ]),
            json.dumps([
                r.get('TICKER', '')
                for r in state.get('holdings', [])
            ]),
            json.dumps([]),
            json.dumps([]),
            str(state.get('model',          '') or ''),
            str(state.get('final_response', '') or ''),
            json.dumps(state.get('reasoning_log', [])),
            len(state.get('news_articles', [])),
            len(state.get('holdings',      []))
        ))
    except Exception as e:
        print(f"Audit log failed: {e}")

# ─────────────────────────────────────────────────────────────────
# PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────────
def run_advisor_agent(
    question,
    customer_name,
    query_type,
    model,
    conversation_history = None,
    thread_id            = None,
    advisor_name         = "Unknown"
):
    agent = build_agent()

    try:
        result = agent.invoke(
            {
                'question':             question,
                'customer_name':        customer_name,
                'query_type':           query_type,
                'model':                model,
                'conversation_history': conversation_history or [],
                'thread_id':            thread_id or str(uuid.uuid4()),
                'news_articles':        [],
                'holdings':             [],
                'rates':                [],
                'prices':               [],
                'tools_needed':         [],
                'search_attempts':      0,
                'has_enough_data':      False,
                'reasoning_log':        [],
                'final_response':       None,
            },
            config={"recursion_limit": 25}
        )

        try:
            log_to_snowflake(result, advisor_name)
        except Exception as e:
            print(f"Audit log error: {e}")

    except Exception as e:
        result = {
            'final_response':  f"Agent error: {e}",
            'reasoning_log':   [f"❌ {e}"],
            'news_articles':   [],
            'holdings':        [],
            'rates':           [],
            'prices':          [],
            'tools_needed':    [],
            'search_attempts': 0,
        }

    return result
