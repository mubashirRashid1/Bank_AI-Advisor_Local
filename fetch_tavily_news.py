from tavily import TavilyClient
import snowflake.connector
from dotenv import load_dotenv
import os
from datetime import datetime
import uuid

load_dotenv()

# ── Canadian banking & finance search queries ──────────────────────
SEARCH_QUERIES = [
    "Canadian bank interest rates news today",
    "TSX stock market Canada today",
    "Bank of Canada monetary policy news",
    "Canadian portfolio investment news today",
    "Canada inflation economy news today",
    "RBC TD BMO CIBC Scotiabank news today",
    "Canadian bond market news today",
    "Canada housing market mortgage rates news"
]

def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE')
    )

def fetch_and_store_news():
    print("🔍 Fetching financial news from Tavily...\n")

    tavily  = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))
    conn    = get_snowflake_connection()
    cursor  = conn.cursor()

    # ── Make sure these are initialized BEFORE the loop ───────────
    total_stored  = 0
    total_skipped = 0

    for query in SEARCH_QUERIES:
        try:
            print(f"  🔎 Searching: '{query}'")
            response = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=5,
                include_answer=True
            )

            results = response.get('results', [])

            for article in results:
                news_id     = str(uuid.uuid4())
                title       = article.get('title', '')[:1000]
                content     = article.get('content', '')
                url         = article.get('url', '')[:2000]
                published   = article.get('published_date', None)
                source      = extract_source(url)

                published_at = None
                if published:
                    try:
                        published_at = datetime.strptime(published, '%Y-%m-%dT%H:%M:%SZ')
                    except:
                        published_at = datetime.now()
                else:
                    published_at = datetime.now()

                cursor.execute("""
                    SELECT COUNT(*) FROM NEWS_RAW WHERE URL = %s
                """, (url,))

                if cursor.fetchone()[0] == 0:
                    cursor.execute("""
                        INSERT INTO NEWS_RAW
                            (ID, SOURCE, TITLE, CONTENT, URL, PUBLISHED_AT)
                        VALUES
                            (%s, %s, %s, %s, %s, %s)
                    """, (news_id, source, title, content, url, published_at))
                    print(f"    ✅ Stored : {title[:70]}...")
                    total_stored += 1
                else:
                    print(f"    ⏭️  Skipped (already exists): {title[:70]}...")
                    total_skipped += 1

        except Exception as e:
            print(f"    ❌ Failed for query '{query}': {str(e)}")
            continue   # ← add this so loop keeps going after error

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n🎉 Done! {total_stored} stored, {total_skipped} skipped.")
    
def extract_source(url):
    """Extract domain name as source from URL"""
    try:
        domain = url.split('/')[2]
        domain = domain.replace('www.', '')
        return domain[:100]
    except:
        return 'Unknown'

if __name__ == "__main__":
    fetch_and_store_news()