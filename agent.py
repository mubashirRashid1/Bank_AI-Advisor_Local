# ── agent.py — LangGraph Agent with Conversation Memory ──────────
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional
import pandas as pd
import json
import uuid
import os


# ── Agent State ───────────────────────────────────────────────────
class AdvisorState(TypedDict):
    # Inputs
    question:           str
    customer_name:      str
    query_type:         str
    model:              str
    db_conn: any   # shared connection passed through all nodes

    # Conversation memory — full history passed each turn
    conversation_history: List[dict]   # [{"role": "user/assistant", "content": "..."}]
    thread_id:          str            # links all turns in one conversation

    # Data collected this turn
    news_articles:      List[dict]
    holdings:           List[dict]
    rates:              List[dict]
    prices:             List[dict]

    # Agent reasoning
    tools_needed:       List[str]
    search_attempts:    int
    has_enough_data:    bool

    # Live log
    reasoning_log:      List[str]

    # Output
    final_response:     Optional[str]


# ─────────────────────────────────────────────────────────────────
# NODE 1 — ROUTER
# ─────────────────────────────────────────────────────────────────
def router_node(state: AdvisorState) -> AdvisorState:
    question = state['question'].lower()
    history  = state['conversation_history']
    tools    = ['search_news']

    # Check if follow-up refers to previous context
    followup_keywords = [
        'tell me more', 'elaborate', 'explain',
        'what about', 'and the', 'what does',
        'why', 'how about', 'can you', 'what if'
    ]
    is_followup = any(kw in question for kw in followup_keywords)

    if is_followup and len(history) > 0:
        state['reasoning_log'].append(
            "🔄 **Router** — Follow-up question detected. "
            "Reusing previous context + refreshing news."
        )
        # For follow-ups — skip heavy data reload
        # just refresh news and reuse existing holdings/rates/prices
        tools = ['search_news']
    else:
        # Fresh question — decide tools based on content
        if state['query_type'] == 'customer':
            tools.append('get_holdings')

        rate_kw = [
            'rate', 'boc', 'interest', 'bond',
            'fixed income', 'yield', 'mortgage', 'inflation'
        ]
        if any(kw in question for kw in rate_kw):
            tools.append('get_rates')

        market_kw = [
            'market', 'price', 'stock', 'equity',
            'tsx', 'sector', 'movers', 'rally', 'crash'
        ]
        if any(kw in question for kw in market_kw):
            tools.append('get_prices')

        if len(tools) == 1:
            tools = ['search_news', 'get_holdings',
                     'get_rates', 'get_prices']

    state['tools_needed']    = tools
    state['search_attempts'] = 0
    state['reasoning_log'].append(
        f"🧭 **Router** — "
        f"{'Follow-up' if is_followup else 'Fresh question'}. "
        f"Tools: `{'`, `'.join(tools)}`"
    )
    return state

def search_news_node(state: AdvisorState) -> AdvisorState:
    # REMOVE: from db import get_snowflake_connection
    # REMOVE: conn = get_snowflake_connection()
    conn   = state['db_conn']   # ← use shared connection
    cursor = conn.cursor()

    state['reasoning_log'].append(
        "🔍 **Search News** — Semantic search..."
    )
    try:
        query       = state['question'].replace('"', '')
        filter_json = f'{{"query": "{query}", "limit": 8}}'

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
        raw     = raw[0] if raw else None
        results = json.loads(raw) if isinstance(raw, str) else raw
        news    = results if results else []

        state['news_articles']    = news
        state['search_attempts'] += 1
        state['reasoning_log'].append(
            f"   ✅ Found **{len(news)} articles**"
        )
    except Exception as e:
        state['news_articles'] = []
        state['reasoning_log'].append(
            f"   ⚠️ Search failed: `{str(e)[:80]}`"
        )
    return state


def get_holdings_node(state: AdvisorState) -> AdvisorState:
    if state['query_type'] != 'customer':
        state['holdings'] = []
        return state

    conn   = state['db_conn']   # ← shared
    cursor = conn.cursor()

    state['reasoning_log'].append(
        f"💼 **Get Holdings** — Loading {state['customer_name']}..."
    )
    try:
        cursor.execute("""
            SELECT
                h.SECURITY_NAME, h.ASSET_CLASS,
                h.SECTOR,        h.CURRENT_VALUE,
                h.TICKER,        h.UNREALIZED_PNL,
                h.WEIGHT_PCT
            FROM BANK_POC.INTERNAL_DATA.CUSTOMERS c
            JOIN BANK_POC.INTERNAL_DATA.PORTFOLIOS p
                ON c.CUSTOMER_ID = p.CUSTOMER_ID
            JOIN BANK_POC.INTERNAL_DATA.HOLDINGS h
                ON p.PORTFOLIO_ID = h.PORTFOLIO_ID
            WHERE c.CUSTOMER_NAME = %s
            ORDER BY h.CURRENT_VALUE DESC
        """, (state['customer_name'],))

        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        cursor.close()
        holdings = [dict(zip(columns, r)) for r in rows]

        state['holdings'] = holdings
        total = sum(r['CURRENT_VALUE'] for r in holdings)
        state['reasoning_log'].append(
            f"   ✅ **{len(holdings)} positions** — "
            f"${total:,.0f}"
        )
    except Exception as e:
        state['holdings'] = []
        state['reasoning_log'].append(
            f"   ⚠️ Holdings failed: `{str(e)[:80]}`"
        )
    return state


def get_rates_node(state: AdvisorState) -> AdvisorState:
    conn   = state['db_conn']   # ← shared
    cursor = conn.cursor()

    state['reasoning_log'].append(
        "🏦 **Get Rates** — Fetching BoC rates..."
    )
    try:
        cursor.execute("""
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
        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        cursor.close()
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
    return state


def get_prices_node(state: AdvisorState) -> AdvisorState:
    conn   = state['db_conn']   # ← shared
    cursor = conn.cursor()

    state['reasoning_log'].append(
        "📈 **Get Prices** — Fetching market prices..."
    )
    try:
        cursor.execute("""
            SELECT COMPANY_NAME, PRICE, CHANGE_PCT
            FROM BANK_POC.EXTERNAL_DATA.MARKET_PRICES
            WHERE PRICE_DATE = CURRENT_DATE()
            ORDER BY ABS(CHANGE_PCT) DESC
            LIMIT 8
        """)
        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        cursor.close()
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
    return state
#  ------------ ||||||||||||| ANSWER NODE |||||||||||||||||||||||||||| -----------------


def answer_node(state: AdvisorState) -> AdvisorState:
    conn   = state['db_conn']
    cursor = conn.cursor()

    state['reasoning_log'].append(
        f"💡 **Answer** — Calling `{state['model']}`..."
    )

    # ── Build context strings ─────────────────────────────────────
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

    # ── Build conversation history string ─────────────────────────
    history_text = ""
    if state['conversation_history']:
        history_text = "\n\nCONVERSATION HISTORY:\n"
        for turn in state['conversation_history'][-6:]:
            role    = "Advisor" if turn['role'] == 'user' \
                      else "AI"
            content = turn['content'][:300]
            history_text += f"{role}: {content}\n\n"

    # ── Build prompt based on query type ──────────────────────────
 
    # ── Detect if this is a follow-up question ────────────────────────
    followup_keywords = [
        'tell me more', 'elaborate', 'explain', 'what about',
        'and the', 'what does', 'why', 'how about', 'can you',
        'what if', 'more detail', 'expand', 'clarify', 'what do you mean',
        'give me more', 'what would', 'how would', 'which one',
        'what specifically', 'and what', 'so what', 'but what'
    ]

    question_lower  = state['question'].lower()
    has_history     = len(state['conversation_history']) > 0
    is_followup     = has_history and any(
        kw in question_lower for kw in followup_keywords
    )

    # ── Build prompt based on type ────────────────────────────────────
    if is_followup:
        # ── FOLLOW-UP — plain conversational response ─────────────────
        prompt = (
            "You are a senior Canadian wealth management AI advisor "
            "having a conversation with an advisor. "
            "Answer the follow-up question in plain conversational text. "
            "Do NOT use headers, numbered sections, or bullet points. "
            "Write naturally like you are talking to the advisor. "
            "Be specific and reference the previous conversation context. "
            "Keep the response concise — 2 to 4 paragraphs maximum. "
            + history_text +
            "\n\nFOLLOW-UP QUESTION: " + state['question'] +
            "\n\nADDITIONAL CONTEXT IF NEEDED:"
            "\nNEWS:\n" + news_text +
            "\nRATE CONTEXT:\n" + rates_text
        )

    elif state['query_type'] == 'manager':
        # ── MANAGER — structured 6 sections ──────────────────────────
        prompt = (
            "You are a senior Canadian wealth management AI advisor "
            "briefing a portfolio manager. "
            "Answer using ONLY the data provided. "
            "Be specific, cite actual numbers. "
            "Do not reference any individual customer. "
            + history_text +
            "\n\nQUESTION: " + state['question'] +
            "\n\nLATEST NEWS:\n" + news_text +
            "\n\nBANK OF CANADA RATES:\n" + rates_text +
            "\n\nMARKET PRICES:\n" + prices_text +
            "\n\nRespond using EXACTLY this structure:\n"
            "\n## 1. MARKET SITUATION TODAY\n"
            "\n## 2. TOP 3 RISKS FOR WEALTH PORTFOLIOS\n"
            "\n## 3. SECTORS MOST AFFECTED\n"
            "\n## 4. RECOMMENDED ADVISOR ACTIONS\n"
            "\n## 5. CLIENT SEGMENTS TO PRIORITIZE\n"
            "\n## 6. URGENCY SCORE\nScore: X/10\nRationale: ..."
        )

    else:
        # ── CUSTOMER — structured 6 sections ─────────────────────────
        prompt = (
            "You are a senior Canadian wealth management AI advisor. "
            "Analyze using ONLY the data provided. "
            "Be specific, cite actual numbers. "
            + history_text +
            "\n\nQUESTION: " + state['question'] +
            "\n\nCUSTOMER: " + state['customer_name'] +
            "\n\nHOLDINGS:\n" + holdings_text +
            "\n\nLATEST NEWS:\n" + news_text +
            "\n\nBANK OF CANADA RATES:\n" + rates_text +
            "\n\nMARKET PRICES:\n" + prices_text +
            "\n\nRespond using EXACTLY this structure:\n"
            "\n## 1. SITUATION SUMMARY\n"
            "\n## 2. CUSTOMER IMPACT ASSESSMENT\n"
            "\n## 3. REGULATORY & COMPLIANCE FLAGS\n"
            "\n## 4. RECOMMENDED ACTIONS\n"
            "\n## 5. CLIENT TALKING POINTS\n"
            "\n## 6. URGENCY SCORE\nScore: X/10\nRationale: ..."
        )


    # ── Call Cortex ───────────────────────────────────────────────
    try:
        state['reasoning_log'].append(
        f"💡 **Answer** — "
        f"{'💬 Conversational follow-up' if is_followup else '📋 Structured analysis'} "
        f"using `{state['model']}`..."
    )
        cursor.execute("""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)
        """, (state['model'], prompt))
        response = cursor.fetchone()[0]
        cursor.close()
        state['final_response'] = response
        state['reasoning_log'].append("   ✅ **Analysis complete**")
    except Exception as e:
        state['final_response'] = f"Analysis failed: {e}"
        state['reasoning_log'].append(
            f"   ❌ Failed: `{str(e)[:80]}`"
        )

    return state

# ─────────────────────────────────────────────────────────────────
# NODE 2 — SEARCH NEWS
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# NODE 3 — GET HOLDINGS
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# NODE 4 — GET RATES
# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
# NODE 5 — GET PRICES
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# NODE 6 — EVALUATE
# ─────────────────────────────────────────────────────────────────
def evaluate_node(state: AdvisorState) -> AdvisorState:
    MAX_ATTEMPTS = 2
    has_news     = len(state['news_articles']) >= 3
    has_holdings = (
        len(state['holdings']) > 0
        or state['query_type'] == 'manager'
    )

    state['reasoning_log'].append(
        f"🧠 **Evaluate** — "
        f"News: {'✅' if has_news else '❌'} "
        f"({len(state['news_articles'])} articles) | "
        f"Holdings: {'✅' if has_holdings else '❌'} | "
        f"Attempt {state['search_attempts']}/{MAX_ATTEMPTS}"
    )

    if has_news and has_holdings:
        state['has_enough_data'] = True
        state['reasoning_log'].append(
            "   ✅ Sufficient context — generating analysis"
        )
    elif state['search_attempts'] >= MAX_ATTEMPTS:
        state['has_enough_data'] = True
        state['reasoning_log'].append(
            "   ⚠️ Max attempts reached — answering with "
            "available data"
        )
    else:
        state['has_enough_data'] = False
        state['reasoning_log'].append(
            "   🔄 Insufficient — searching again"
        )

    return state


# ─────────────────────────────────────────────────────────────────
# NODE 7 — ANSWER (with conversation memory)
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# CONDITIONAL EDGE
# ─────────────────────────────────────────────────────────────────
def should_continue(state: AdvisorState) -> str:
    return "answer" if state['has_enough_data'] else "search_more"


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

    # Entry
    graph.set_entry_point("router")

    # SEQUENTIAL — one after another, no parallel
    graph.add_edge("router",       "search_news")
    graph.add_edge("search_news",  "get_holdings")
    graph.add_edge("get_holdings", "get_rates")
    graph.add_edge("get_rates",    "get_prices")
    graph.add_edge("get_prices",   "evaluate")

    # Conditional — loop or answer
    graph.add_conditional_edges(
        "evaluate",
        should_continue,
        {
            "search_more": "search_news",
            "answer":      "answer"
        }
    )

    graph.add_edge("answer", END)
    return graph.compile()

# ─────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────

def log_to_snowflake(state, advisor_name, conn):
    cursor = conn.cursor()
    # ... same insert as before ...
    # just use the passed conn, don't open a new one
    try:
        cursor.execute("""
            INSERT INTO BANK_POC.INTERNAL_DATA.AI_AUDIT_LOG (
                AUDIT_ID, ADVISOR_NAME, CUSTOMER_NAME,
                QUERY_TYPE, USER_QUESTION, TOOLS_CALLED,
                SEARCH_ATTEMPTS, NEWS_TITLES,
                HOLDINGS_TICKERS, RATES_USED, PRICES_USED,
                MODEL_USED, AI_RESPONSE, REASONING_LOG,
                NEWS_COUNT, HOLDINGS_COUNT
            )
            SELECT
                %s::VARCHAR, %s::VARCHAR, %s::VARCHAR,
                %s::VARCHAR, %s::VARCHAR, %s::VARCHAR,
                %s::NUMBER,  %s::VARCHAR, %s::VARCHAR,
                %s::VARCHAR, %s::VARCHAR, %s::VARCHAR,
                %s::VARCHAR, %s::VARCHAR, %s::NUMBER,
                %s::NUMBER
        """, (
            str(uuid.uuid4()),
            advisor_name,
            state['customer_name'],
            state['query_type'],
            state['question'],
            json.dumps(state['tools_needed']),
            state['search_attempts'],
            json.dumps([
                r.get('TITLE', r.get('title', ''))[:100]
                for r in state['news_articles']
            ]),
            json.dumps([
                r.get('TICKER', '')
                for r in state['holdings']
            ]),
            json.dumps([
                {r['SERIES_NAME']: str(r['RATE_VALUE'])}
                for r in state['rates']
            ]),
            json.dumps([
                {r['COMPANY_NAME']: str(r['PRICE'])}
                for r in state['prices']
            ]),
            state['model'],
            state['final_response'],
            json.dumps(state['reasoning_log']),
            len(state['news_articles']),
            len(state['holdings'])
        ))
        conn.commit()
    except Exception as e:
        print(f"Audit log failed: {e}")
    finally:
        cursor.close()


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
    from db import get_snowflake_connection

    # ── Open ONE connection for entire agent run ──────────────────
    conn  = get_snowflake_connection()
    agent = build_agent()

    try:
        result = agent.invoke({
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
            'db_conn':              conn,   # ← shared connection
        })

        try:
            log_to_snowflake(result, advisor_name, conn)
        except Exception as e:
            print(f"Audit log error: {e}")

    finally:
        conn.close()   # ← close once at the very end

    return result