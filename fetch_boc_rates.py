import requests
import snowflake.connector
from dotenv import load_dotenv
import os
from datetime import datetime
import uuid

load_dotenv()

# ── Bank of Canada series codes we want ───────────────────────────
BOC_SERIES = {
    'FXCADUSD':  'CAD/USD Exchange Rate',
    'AVG.INTWO': 'Overnight Money Market Rate',
    'V122530':   'Bank of Canada Overnight Rate',
    'V122495':   'Prime Rate',
    'V122508':   '3 Month Treasury Bill Rate',
    'V122518':   '10 Year Government Bond Yield',
}

BOC_BASE_URL = "https://www.bankofcanada.ca/valet"

def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE')
    )

def fetch_series(series_code):
    """Fetch latest value for a single BOC series"""
    url = f"{BOC_BASE_URL}/observations/{series_code}/json?recent=1"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    observations = data.get('observations', [])
    if not observations:
        return None, None

    latest     = observations[-1]
    rate_date  = latest.get('d')
    rate_value = latest.get(series_code, {}).get('v')

    return rate_date, float(rate_value) if rate_value else None

def fetch_and_store_rates():
    print("🏦 Fetching rates from Bank of Canada API...\n")

    conn   = get_snowflake_connection()
    cursor = conn.cursor()

    success_count = 0

    for series_code, series_name in BOC_SERIES.items():
        try:
            rate_date, rate_value = fetch_series(series_code)

            if rate_value is None:
                print(f"  ⚠️  No data for {series_name}")
                continue

            rate_id     = str(uuid.uuid4())
            parsed_date = datetime.strptime(rate_date, '%Y-%m-%d').date()

            # ── Check if rate for this series + date already exists ─
            cursor.execute("""
                SELECT COUNT(*) FROM BOC_RATES
                WHERE SERIES_CODE = %s AND RATE_DATE = %s
            """, (series_code, parsed_date))

            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO BOC_RATES
                        (ID, SERIES_NAME, SERIES_CODE, RATE_VALUE, RATE_DATE)
                    VALUES
                        (%s, %s, %s, %s, %s)
                """, (rate_id, series_name, series_code, rate_value, parsed_date))
                print(f"  ✅ {series_name:45s} {rate_value:.4f}  ({rate_date})")
                success_count += 1
            else:
                print(f"  ⏭️  Skipped (already exists): {series_name}")

        except Exception as e:
            print(f"  ❌ Failed for {series_name}: {str(e)}")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n🎉 Done! {success_count} stored, rest skipped.")

if __name__ == "__main__":
    fetch_and_store_rates()