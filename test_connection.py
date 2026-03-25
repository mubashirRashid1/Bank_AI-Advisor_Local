import snowflake.connector
from dotenv import load_dotenv
import os

load_dotenv()

try:
    conn = snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE')
    )

    cursor = conn.cursor()
    cursor.execute("SELECT CURRENT_VERSION()")
    row = cursor.fetchone()
    print(f"✅ Connected to Snowflake! Version: {row[0]}")

    cursor.execute("SELECT CURRENT_WAREHOUSE()")
    row = cursor.fetchone()
    print(f"✅ Warehouse: {row[0]}")

    cursor.execute("SELECT CURRENT_DATABASE()")
    row = cursor.fetchone()
    print(f"✅ Database: {row[0]}")

    cursor.close()
    conn.close()
    print("\n🎉 All good! Ready to build the pipeline.")

except Exception as e:
    print(f"❌ Connection failed: {str(e)}")