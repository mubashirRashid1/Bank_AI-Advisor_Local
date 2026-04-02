# ── fetch_tavily_news.py — SQLite version ────────────────────────
import requests
import uuid
import json
from datetime import datetime
from dotenv import load_dotenv
import os
from db import get_connection, run_execute

load_dotenv()

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

QUERIES = [
    "Canadian bank wealth management news today",
    "Bank of Canada monetary policy 2026",
    "TSX stock market Canadian equities today",
    "Canadian real estate investment 2026",
    "OSFI Canadian banking regulation",
]

def fetch_and_store_news():
    print("Fetching news from Tavily...")

    if not TAVILY_API_KEY:
        print("   WARNING: TAVILY_API_KEY not set — skipping")
        return 0

    saved   = 0
    skipped = 0

    for query in QUERIES:
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                headers={"Content-Type": "application/json"},
                json={
                    "api_key":        TAVILY_API_KEY,
                    "query":          query,
                    "search_depth":   "basic",
                    "max_results":    5,
                    "include_answer": False
                },
                timeout=30
            )
            response.raise_for_status()
            articles = response.json().get('results', [])

            for article in articles:
                if not article or not isinstance(article, dict):
                    continue

                title   = str(article.get('title',   '') or '')
                content = str(article.get('content', '') or '')
                url     = str(article.get('url',     '') or '')
                source  = url.split('/')[2].replace('www.','') \
                          if url else 'tavily'

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

                # Save raw article only — enrichment done separately
                run_execute("""
                    INSERT INTO NEWS_RAW
                        (ID, SOURCE, TITLE, CONTENT,
                         URL, PUBLISHED_AT)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    source[:100],
                    title[:1000],
                    content,
                    url[:2000],
                    datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
                ))
                saved += 1
                print(f"   Saved: {title[:70]}...")

        except Exception as e:
            print(f"   Error fetching '{query}': {e}")

    print(f"\n   Tavily: {saved} saved, {skipped} skipped")
    return saved

if __name__ == "__main__":
    fetch_and_store_news()