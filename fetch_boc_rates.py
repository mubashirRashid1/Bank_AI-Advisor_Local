# ── fetch_boc_rates.py — SQLite version ──────────────────────────
import requests
import uuid
from datetime import datetime
from db import get_connection, run_execute
BOC_SERIES = {
    "V122530":  "Bank of Canada Overnight Rate",
    "V122514":  "Prime Rate",
    "V39055":   "Canada 3-Month Treasury Bill",
    "V39056":   "Canada 6-Month Treasury Bill",
    "V39057":   "Canada 1-Year Treasury Bill",
    "V39058":   "Canada 2-Year Government Bond",
    "V39062":   "Canada 10-Year Government Bond",
}

def fetch_and_store_rates():
    print("Fetching Bank of Canada rates...")
    saved   = 0
    skipped = 0

    for series_code, series_name in BOC_SERIES.items():
        try:
            url      = (
                f"https://www.bankofcanada.ca/valet/observations"
                f"/{series_code}/json?recent=1"
            )
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data     = response.json()

            observations = data.get('observations', [])
            if not observations:
                print(f"   No data for {series_code}")
                continue

            latest    = observations[-1]
            rate_date = latest.get('d', '')
            rate_val  = latest.get(series_code, {}).get('v')

            if rate_val is None:
                print(f"   No value for {series_code}")
                continue

            rate_value = float(rate_val)

            # Check for duplicate
            conn   = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM BOC_RATES
                WHERE SERIES_CODE = ? AND RATE_DATE = ?
            """, (series_code, rate_date))
            exists = cursor.fetchone()[0]
            cursor.close()
            conn.close()

            if exists:
                skipped += 1
                print(f"   Skipped (exists): {series_name}")
                continue

            run_execute("""
                INSERT INTO BOC_RATES
                    (ID, SERIES_CODE, SERIES_NAME,
                     RATE_VALUE, RATE_DATE)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                series_code,
                series_name,
                rate_value,
                rate_date
            ))
            saved += 1
            print(f"   Saved: {series_name} = {rate_value}% ({rate_date})")

        except Exception as e:
            print(f"   Error fetching {series_code}: {e}")

    print(f"   BoC rates: {saved} saved, {skipped} skipped")
    return saved

if __name__ == "__main__":
    fetch_and_store_rates()