# ── fetch_news_api.py — SQLite version (fast fetch, no enrichment) 
import requests
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from db import get_connection, run_execute

load_dotenv()

NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')

QUERIES = [
    "Bank of Canada interest rates",
    "Canadian stock market TSX",
    "Canadian real estate housing market",
    "Canadian banks earnings",
    "Canadian oil energy sector",
    "Canadian inflation economy",
    "Canadian wealth management investing",
    "Canadian regulatory OSFI financial",
]

def fetch_and_store_news():
    print("Fetching news from NewsAPI...")

    if not NEWSAPI_KEY:
        print("   ERROR: NEWSAPI_KEY not set in .env")
        return 0

    saved   = 0
    skipped = 0

    for query in QUERIES:
        try:
            from_date = (
                datetime.now() - timedelta(days=7)
            ).strftime('%Y-%m-%d')

            response = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q":        query,
                    "apiKey":   NEWSAPI_KEY,
                    "language": "en",
                    "sortBy":   "publishedAt",
                    "pageSize": 5,
                    "from":     from_date,
                },
                timeout=15
            )
            response.raise_for_status()
            articles = response.json().get('articles', [])

                # ── Fix 1: guard against None articles ───────────
            for article in articles:
    # Guard against None or non-dict articles
                if not article or not isinstance(article, dict):
                    continue

                title   = article.get('title')   or ''
                content = article.get('content') or \
                        article.get('description') or ''
                url     = article.get('url')     or ''
                pub_at  = article.get('publishedAt') or ''

                # Safe source extraction
                source_obj = article.get('source')
                if isinstance(source_obj, dict):
                    source = source_obj.get('name') or ''
                else:
                    source = str(source_obj) if source_obj else ''

                if not title or not url:
                    continue

                # Check duplicate
                conn   = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM NEWS_RAW WHERE URL = ?",
                    (url,)
                )
                exists = cursor.fetchone()[0]
                cursor.close()
                conn.close()

                if exists:
                    skipped += 1
                    continue

                # Save raw article only — no enrichment here
                run_execute("""
                    INSERT INTO NEWS_RAW
                        (ID, SOURCE, TITLE, CONTENT,
                         URL, PUBLISHED_AT)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    str(source)[:100],
                    str(title)[:1000],
                    str(content),
                    str(url)[:2000],
                    str(pub_at)
                ))
                saved += 1
                print(f"   Saved: {title[:70]}...")

        except Exception as e:
            print(f"   Error fetching '{query}': {e}")

    print(f"\n   NewsAPI: {saved} saved, {skipped} skipped")
    return saved

if __name__ == "__main__":
    fetch_and_store_news()