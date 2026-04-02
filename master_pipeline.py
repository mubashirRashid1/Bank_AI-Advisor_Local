# ── master_pipeline.py — Local SQLite version ─────────────────────
from datetime import datetime
from dotenv import load_dotenv

from fetch_tavily_news   import fetch_and_store_news as fetch_tavily
from fetch_news_api      import fetch_and_store_news as fetch_newsapi
from fetch_boc_rates     import fetch_and_store_rates as fetch_boc
from fetch_market_prices import fetch_and_store_prices as fetch_prices
from enrich_news         import enrich_all_news

load_dotenv()

def print_header():
    print("=" * 60)
    print("   🏦 CANADIAN BANK AI ADVISOR — LOCAL PIPELINE")
    print(f"   ⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

def print_section(title):
    print()
    print(f"─── {title} {'─' * (50 - len(title))}")

def print_footer(start_time):
    duration = (datetime.now() - start_time).seconds
    print()
    print("=" * 60)
    print(f"   ✅ PIPELINE COMPLETE")
    print(f"   ⏱️  Total time: {duration} seconds")
    print(f"   ⏰ Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

def print_summary():
    from db import run_query
    print()
    print_section("📊 DATABASE SUMMARY")

    tables = [
        ("NEWS_RAW",       "📰 Total News Articles"),
        ("NEWS_ENRICHED",  "🤖 AI Enriched"),
        ("MARKET_PRICES",  "📈 Market Prices"),
        ("BOC_RATES",      "🏦 BoC Rates"),
        ("CUSTOMERS",      "👤 Customers"),
        ("PORTFOLIOS",     "💼 Portfolios"),
        ("HOLDINGS",       "📋 Holdings"),
    ]

    for table, label in tables:
        try:
            df    = run_query(f"SELECT COUNT(*) as CNT FROM {table}")
            count = int(df['CNT'].iloc[0])
            print(f"   {label:35s} {count:>6} rows")
        except Exception as e:
            print(f"   ❌ Could not query {table}: {e}")

    # Latest headline
    try:
        df = run_query("""
            SELECT TITLE, SOURCE, PUBLISHED_AT
            FROM NEWS_RAW
            ORDER BY CREATED_AT DESC
            LIMIT 1
        """)
        if not df.empty:
            row = df.iloc[0]
            print()
            print_section("🗞️  LATEST HEADLINE")
            print(f"   Title  : {str(row['TITLE'])[:70]}")
            print(f"   Source : {row['SOURCE']}")
            print(f"   Time   : {row['PUBLISHED_AT']}")
    except Exception as e:
        print(f"   ❌ Could not fetch headline: {e}")

    # Latest BoC rate
    try:
        df = run_query("""
            SELECT SERIES_NAME, RATE_VALUE, RATE_DATE
            FROM BOC_RATES
            WHERE SERIES_CODE = 'V122530'
            ORDER BY RATE_DATE DESC
            LIMIT 1
        """)
        if not df.empty:
            row = df.iloc[0]
            print()
            print_section("🏦  LATEST BOC RATE")
            print(
                f"   {str(row['SERIES_NAME']):45s} "
                f"{row['RATE_VALUE']:.4f}% ({row['RATE_DATE']})"
            )
    except Exception as e:
        print(f"   ❌ Could not fetch BoC rate: {e}")

    # Top market movers
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        df    = run_query(f"""
            SELECT TICKER, COMPANY_NAME, PRICE, CHANGE_PCT
            FROM MARKET_PRICES
            WHERE PRICE_DATE = '{today}'
            ORDER BY ABS(CHANGE_PCT) DESC
            LIMIT 3
        """)
        if not df.empty:
            print()
            print_section("📈  TOP MARKET MOVERS")
            for _, row in df.iterrows():
                arrow = "🟢" if row['CHANGE_PCT'] >= 0 else "🔴"
                print(
                    f"   {arrow} {str(row['COMPANY_NAME']):40s} "
                    f"${row['PRICE']:.2f} ({row['CHANGE_PCT']:+.2f}%)"
                )
    except Exception as e:
        print(f"   ❌ Could not fetch movers: {e}")

def run_pipeline():
    start_time = datetime.now()
    print_header()

    # ── 1. Tavily News ─────────────────────────────────────────────
    print_section("STEP 1 — TAVILY NEWS")
    try:
        fetch_tavily()
    except Exception as e:
        print(f"   ❌ Tavily failed: {e}")

    # ── 2. NewsAPI ─────────────────────────────────────────────────
    print_section("STEP 2 — NEWSAPI")
    try:
        fetch_newsapi()
    except Exception as e:
        print(f"   ❌ NewsAPI failed: {e}")

    # ── 3. Bank of Canada Rates ────────────────────────────────────
    print_section("STEP 3 — BANK OF CANADA RATES")
    try:
        fetch_boc()
    except Exception as e:
        print(f"   ❌ BoC failed: {e}")

    # ── 4. Market Prices ───────────────────────────────────────────
    print_section("STEP 4 — MARKET PRICES")
    try:
        fetch_prices()
    except Exception as e:
        print(f"   ❌ Prices failed: {e}")

    # ── 5. Enrich + Index ──────────────────────────────────────────
    print_section("STEP 5 — ENRICH & INDEX NEW ARTICLES")
    try:
        enrich_all_news()
    except Exception as e:
        print(f"   ❌ Enrichment failed: {e}")

    # ── 6. Summary ─────────────────────────────────────────────────
    print_summary()
    print_footer(start_time)

if __name__ == "__main__":
    run_pipeline()