# ── fetch_market_prices.py — SQLite version ───────────────────────
import yfinance as yf
import uuid
from datetime import date
from db import get_connection, run_execute

# TSX tickers relevant to Canadian wealth management
TICKERS = [
    ("RY.TO",   "Royal Bank of Canada"),
    ("TD.TO",   "TD Bank"),
    ("BNS.TO",  "Bank of Nova Scotia"),
    ("BMO.TO",  "Bank of Montreal"),
    ("CM.TO",   "CIBC"),
    ("SU.TO",   "Suncor Energy"),
    ("CNQ.TO",  "Canadian Natural Resources"),
    ("ENB.TO",  "Enbridge"),
    ("TRP.TO",  "TC Energy"),
    ("SHOP.TO", "Shopify"),
    ("CP.TO",   "Canadian Pacific Railway"),
    ("CNR.TO",  "Canadian National Railway"),
    ("BAM.TO",  "Brookfield Asset Management"),
    ("MFC.TO",  "Manulife Financial"),
    ("SLF.TO",  "Sun Life Financial"),
    ("BCE.TO",  "BCE Inc"),
    ("T.TO",    "TELUS"),
    ("NTR.TO",  "Nutrien"),
    ("ABX.TO",  "Barrick Gold"),
    ("WPM.TO",  "Wheaton Precious Metals"),
]

def fetch_and_store_prices():
    print("Fetching market prices from Yahoo Finance...")
    today   = date.today().isoformat()
    saved   = 0
    skipped = 0
    errors  = 0

    for ticker, company_name in TICKERS:
        try:
            # Check if already fetched today
            conn   = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM MARKET_PRICES
                WHERE TICKER = ? AND PRICE_DATE = ?
            """, (ticker, today))
            exists = cursor.fetchone()[0]
            cursor.close()
            conn.close()

            if exists:
                skipped += 1
                continue

            # Fetch from Yahoo Finance
            stock = yf.Ticker(ticker)
            hist  = stock.history(period="2d")

            if hist.empty:
                print(f"   No data for {ticker}")
                errors += 1
                continue

            latest     = hist.iloc[-1]
            price      = round(float(latest['Close']), 2)
            volume     = float(latest['Volume'])

            # Calculate change percentage
            if len(hist) >= 2:
                prev_close = float(hist.iloc[-2]['Close'])
                change_pct = round(
                    ((price - prev_close) / prev_close) * 100, 2
                )
            else:
                change_pct = 0.0

            run_execute("""
                INSERT INTO MARKET_PRICES
                    (ID, TICKER, COMPANY_NAME, PRICE,
                     CHANGE_PCT, VOLUME, PRICE_DATE)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                ticker,
                company_name,
                price,
                change_pct,
                volume,
                today
            ))
            saved += 1
            arrow = "▲" if change_pct >= 0 else "▼"
            print(
                f"   {arrow} {company_name[:35]:35s} "
                f"${price:.2f} ({change_pct:+.2f}%)"
            )

        except Exception as e:
            print(f"   Error fetching {ticker}: {e}")
            errors += 1

    print(f"\n   Market prices: {saved} saved, "
          f"{skipped} skipped, {errors} errors")
    return saved

if __name__ == "__main__":
    fetch_and_store_prices()