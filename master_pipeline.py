import snowflake.connector
from dotenv import load_dotenv
import os
from datetime import datetime

from fetch_tavily_news      import fetch_and_store_news      as fetch_tavily
from fetch_news_api         import fetch_and_store_news      as fetch_newsapi
from fetch_boc_rates        import fetch_and_store_rates     as fetch_boc
from fetch_market_prices    import fetch_and_store_prices    as fetch_prices

load_dotenv()

# ── Helpers ────────────────────────────────────────────────────────
def print_header():
    print("=" * 60)
    print("   🏦 CANADIAN BANK POC — MASTER DATA PIPELINE")
    print(f"   ⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    print(f"   ⏰ Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

# ── Single shared connection ───────────────────────────────────────
def get_snowflake_connection():
    return snowflake.connector.connect(
        account   = os.getenv('SNOWFLAKE_ACCOUNT'),
        user      = os.getenv('SNOWFLAKE_USER'),
        password  = os.getenv('SNOWFLAKE_PASSWORD'),
        database  = os.getenv('SNOWFLAKE_DATABASE'),
        schema    = os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse = os.getenv('SNOWFLAKE_WAREHOUSE')
    )

# ── Step 5 — Embeddings ────────────────────────────────────────────
# MUST be defined before run_pipeline()
def generate_embeddings(conn):
    print_section("STEP 5 — GENERATING SEMANTIC EMBEDDINGS")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT
                COUNT(*)                    AS TOTAL,
                COUNT(EMBEDDING)            AS WITH_EMBEDDINGS,
                COUNT(*) - COUNT(EMBEDDING) AS MISSING
            FROM BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED
        """)
        row = cursor.fetchone()
        print(f"   Before: {row[2]} articles missing embeddings")

        if row[2] == 0:
            print("   ✅ All articles already have embeddings — skipping")
            return

        cursor.execute("""
            UPDATE BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED e
            SET e.EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768(
                'snowflake-arctic-embed-m',
                COALESCE(r.TITLE, '') || ' ' ||
                COALESCE(e.SUMMARY, '')
            )
            FROM BANK_POC.EXTERNAL_DATA.NEWS_RAW r
            WHERE r.ID        = e.NEWS_RAW_ID
            AND   e.EMBEDDING IS NULL
            AND   e.SUMMARY   IS NOT NULL
        """)
        conn.commit()

        cursor.execute("""
            SELECT
                COUNT(*)                    AS TOTAL,
                COUNT(EMBEDDING)            AS WITH_EMBEDDINGS,
                COUNT(*) - COUNT(EMBEDDING) AS MISSING
            FROM BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED
        """)
        row = cursor.fetchone()
        print(f"   After:  {row[1]} articles now have embeddings")
        print(f"   Still missing: {row[2]} (no summary available)")
        print(f"   ✅ Cortex Search index will refresh within 1 hour")

    except Exception as e:
        print(f"   ❌ Embedding generation failed: {e}")
    finally:
        cursor.close()

# ── Snowflake Summary ──────────────────────────────────────────────
def print_snowflake_summary(conn):
    print_section("📊 SNOWFLAKE TABLE SUMMARY")
    cursor = conn.cursor()

    tables = [
        ('EXTERNAL_DATA', 'NEWS_RAW',      '📰 Total News Articles'),
        ('EXTERNAL_DATA', 'MARKET_PRICES', '📈 Total Market Prices'),
        ('EXTERNAL_DATA', 'BOC_RATES',     '🏦 Total BOC Rates'),
        ('INTERNAL_DATA', 'CUSTOMERS',     '👤 Total Customers'),
        ('INTERNAL_DATA', 'PORTFOLIOS',    '💼 Total Portfolios'),
        ('INTERNAL_DATA', 'HOLDINGS',      '📋 Total Holdings'),
    ]

    for schema, table, label in tables:
        try:
            cursor.execute(
                f"SELECT COUNT(*) FROM BANK_POC.{schema}.{table}"
            )
            count = cursor.fetchone()[0]
            print(f"   {label:35s} {count:>6} rows")
        except Exception as e:
            print(f"   ❌ Could not query {table}: {e}")

    # Latest headline
    try:
        cursor.execute("""
            SELECT TITLE, SOURCE, PUBLISHED_AT
            FROM BANK_POC.EXTERNAL_DATA.NEWS_RAW
            ORDER BY PUBLISHED_AT DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            print()
            print_section("🗞️  LATEST NEWS HEADLINE")
            print(f"   Title  : {row[0][:70]}...")
            print(f"   Source : {row[1]}")
            print(f"   Time   : {row[2]}")
    except Exception as e:
        print(f"   ❌ Could not fetch latest news: {e}")

    # Latest BoC rate
    try:
        cursor.execute("""
            SELECT SERIES_NAME, RATE_VALUE, RATE_DATE
            FROM BANK_POC.EXTERNAL_DATA.BOC_RATES
            WHERE SERIES_CODE = 'V122530'
            ORDER BY RATE_DATE DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            print()
            print_section("🏦  LATEST BANK OF CANADA RATE")
            print(f"   {row[0]:45s} {row[1]:.4f}% ({row[2]})")
    except Exception as e:
        print(f"   ❌ Could not fetch BOC rate: {e}")

    # Top movers
    try:
        cursor.execute("""
            SELECT TICKER, COMPANY_NAME, PRICE, CHANGE_PCT
            FROM BANK_POC.EXTERNAL_DATA.MARKET_PRICES
            WHERE PRICE_DATE = CURRENT_DATE()
            ORDER BY ABS(CHANGE_PCT) DESC
            LIMIT 3
        """)
        rows = cursor.fetchall()
        if rows:
            print()
            print_section("📈  TOP MARKET MOVERS TODAY")
            for row in rows:
                arrow = "🟢" if row[3] >= 0 else "🔴"
                print(
                    f"   {arrow} {row[1]:40s} "
                    f"${row[2]:.2f} ({row[3]:+.2f}%)"
                )
    except Exception as e:
        print(f"   ❌ Could not fetch market movers: {e}")

    cursor.close()

# ── Main Pipeline ──────────────────────────────────────────────────
def run_pipeline():
    start_time = datetime.now()
    print_header()

    # ── 1. Tavily News ─────────────────────────────────────────────
    print_section("STEP 1 — TAVILY NEWS")
    try:
        fetch_tavily()
    except Exception as e:
        print(f"❌ Tavily fetch failed: {e}")

    # ── 2. NewsAPI ─────────────────────────────────────────────────
    print_section("STEP 2 — NEWSAPI NEWS")
    try:
        fetch_newsapi()
    except Exception as e:
        print(f"❌ NewsAPI fetch failed: {e}")

    # ── 3. Bank of Canada Rates ────────────────────────────────────
    print_section("STEP 3 — BANK OF CANADA RATES")
    try:
        fetch_boc()
    except Exception as e:
        print(f"❌ BOC fetch failed: {e}")

    # ── 4. Yahoo Finance Market Prices ─────────────────────────────
    print_section("STEP 4 — YAHOO FINANCE MARKET PRICES")
    try:
        fetch_prices()
    except Exception as e:
        print(f"❌ Yahoo Finance fetch failed: {e}")

    # ── Open ONE shared connection for steps 5 & 6 ────────────────
    conn = get_snowflake_connection()
    try:
        # ── 5. Embeddings ──────────────────────────────────────────
        generate_embeddings(conn)

        # ── 6. Summary ─────────────────────────────────────────────
        print_snowflake_summary(conn)

    finally:
        conn.close()   # always closes even if step 5 or 6 fails

    print_footer(start_time)

if __name__ == "__main__":
    run_pipeline()
