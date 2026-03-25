import yfinance as yf
import snowflake.connector
from dotenv import load_dotenv
import os
from datetime import date
import uuid

load_dotenv()

# ── Canadian bank & TSX tickers to track ──────────────────────────
TICKERS = {
    'RY.TO':    'Royal Bank of Canada',
    'TD.TO':    'Toronto Dominion Bank',
    'BNS.TO':   'Bank of Nova Scotia',
    'BMO.TO':   'Bank of Montreal',
    'CM.TO':    'CIBC',
    'SU.TO':    'Suncor Energy',
    'SHOP.TO':  'Shopify Inc',
    'CNR.TO':   'Canadian National Railway',
    'ENB.TO':   'Enbridge Inc',
    'BCE.TO':   'BCE Inc',
    '^GSPTSE':  'TSX Composite Index',
    'CAD=X':    'CAD/USD Exchange Rate'
}

def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE')
    )

def fetch_and_store_prices():
    print("📈 Fetching market prices from Yahoo Finance...\n")

    conn   = get_snowflake_connection()
    cursor = conn.cursor()

    success_count = 0

    for ticker, company_name in TICKERS.items():
        try:
            stock = yf.Ticker(ticker)
            info  = stock.info

            price      = info.get('currentPrice') or info.get('regularMarketPrice') or 0
            change_pct = info.get('regularMarketChangePercent') or 0
            volume     = info.get('regularMarketVolume') or 0
            market_cap = info.get('marketCap') or 0
            price_date = date.today()
            price_id   = str(uuid.uuid4())

            # ── Check if ticker + date already exists ──────────────
            cursor.execute("""
                SELECT COUNT(*) FROM MARKET_PRICES
                WHERE TICKER = %s AND PRICE_DATE = %s
            """, (ticker, price_date))

            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO MARKET_PRICES
                        (ID, TICKER, COMPANY_NAME, PRICE, CHANGE_PCT, VOLUME, MARKET_CAP, PRICE_DATE)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (price_id, ticker, company_name, price, change_pct, volume, market_cap, price_date))
                arrow = "🟢" if change_pct >= 0 else "🔴"
                print(f"  {arrow} {company_name:45s} ${price:.2f}  ({change_pct:+.2f}%)")
                success_count += 1
            else:
                print(f"  ⏭️  Skipped (already exists): {company_name}")

        except Exception as e:
            print(f"  ❌ Failed for {ticker}: {str(e)}")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n🎉 Done! {success_count} stored, rest skipped.")

if __name__ == "__main__":
    fetch_and_store_prices()