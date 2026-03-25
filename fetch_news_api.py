import requests
import snowflake.connector
from dotenv import load_dotenv
import os
from datetime import datetime
import uuid

load_dotenv()

# ── Canadian finance keywords to search ───────────────────────────
SEARCH_QUERIES = [
    "Canadian bank interest rates",
    "TSX stock market Canada",
    "Bank of Canada monetary policy",
    "Canada inflation economy",
    "RBC TD BMO CIBC Scotiabank",
    "Canadian mortgage rates housing",
    "Canada bond market yields",
    "Canadian dollar CAD currency"
]

NEWS_API_BASE_URL = "https://newsapi.org/v2/everything"

def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE')
    )

def fetch_articles(query):
    """Fetch articles from NewsAPI for a given query"""
    params = {
        'q':        query,
        'language': 'en',
        'sortBy':   'publishedAt',
        'pageSize': 5,
        'apiKey':   os.getenv('NEWS_API_KEY')
    }
    response = requests.get(NEWS_API_BASE_URL, params=params, timeout=10)
    response.raise_for_status()
    return response.json().get('articles', [])

def fetch_and_store_news():
    print("📰 Fetching financial news from NewsAPI...\n")

    conn   = get_snowflake_connection()
    cursor = conn.cursor()

    total_stored  = 0
    total_skipped = 0

    for query in SEARCH_QUERIES:
        try:
            print(f"  🔎 Searching: '{query}'")
            articles = fetch_articles(query)

            for article in articles:
                title   = article.get('title', '')
                content = article.get('content') or article.get('description') or ''
                url     = article.get('url', '')
                source  = article.get('source', {}).get('name', 'NewsAPI')

                # Skip removed articles
                if not title or title == '[Removed]':
                    total_skipped += 1
                    continue

                # Parse published date
                published_str = article.get('publishedAt', '')
                try:
                    published_at = datetime.strptime(published_str, '%Y-%m-%dT%H:%M:%SZ')
                except:
                    published_at = datetime.now()

                news_id = str(uuid.uuid4())

                # ── Check if URL already exists ────────────────────
                cursor.execute("""
                    SELECT COUNT(*) FROM NEWS_RAW WHERE URL = %s
                """, (url,))

                if cursor.fetchone()[0] == 0:
                    cursor.execute("""
                        INSERT INTO NEWS_RAW
                            (ID, SOURCE, TITLE, CONTENT, URL, PUBLISHED_AT)
                        VALUES
                            (%s, %s, %s, %s, %s, %s)
                    """, (
                        news_id,
                        source[:100],
                        title[:1000],
                        content,
                        url[:2000],
                        published_at
                    ))
                    print(f"    ✅ Stored : {title[:70]}...")
                    total_stored += 1
                else:
                    print(f"    ⏭️  Skipped (already exists): {title[:70]}...")
                    total_skipped += 1

        except Exception as e:
            print(f"    ❌ Failed for query '{query}': {str(e)}")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n🎉 Done! {total_stored} stored, {total_skipped} skipped.")

if __name__ == "__main__":
    fetch_and_store_news()