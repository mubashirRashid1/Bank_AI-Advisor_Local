from openai import OpenAI
import snowflake.connector
from dotenv import load_dotenv
import os
import json
import uuid
from datetime import datetime

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE')
    )

def enrich_article(title, content):
    """Send article to OpenAI and get structured enrichment back"""

    prompt = f"""
    You are a Canadian financial analyst AI assistant.
    Analyze the following news article and return a JSON response only.
    No explanation, no markdown, just raw JSON.

    Article Title: {title}
    Article Content: {content[:1000]}

    Return this exact JSON structure:
    {{
        "summary": "2-3 sentence summary of the article",
        "sentiment": "POSITIVE or NEGATIVE or NEUTRAL",
        "sentiment_reason": "one line explanation of sentiment",
        "entities": ["list", "of", "companies", "or", "banks", "mentioned"],
        "tickers": ["list", "of", "stock", "tickers", "if", "mentioned"],
        "asset_classes": ["EQUITIES", "BONDS", "FX", "COMMODITIES", "REAL_ESTATE", "CASH"],
        "topics": ["INTEREST_RATES", "INFLATION", "HOUSING", "BANKING", "ENERGY", "MARKETS"],
        "relevance_score": 0.95,
        "impact_level": "HIGH or MEDIUM or LOW",
        "recommended_action": "one line action an advisor might take based on this news"
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a Canadian financial analyst. Always respond with valid JSON only."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3,
        max_tokens=500
    )

    raw = response.choices[0].message.content.strip()

    # Clean up in case model adds markdown backticks
    raw = raw.replace('```json', '').replace('```', '').strip()

    return json.loads(raw)

def fetch_unenriched_articles(cursor):
    """Get articles from NEWS_RAW that haven't been enriched yet"""
    cursor.execute("""
        SELECT n.ID, n.TITLE, n.CONTENT, n.SOURCE, n.PUBLISHED_AT
        FROM BANK_POC.EXTERNAL_DATA.NEWS_RAW n
        LEFT JOIN BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED e
            ON n.ID = e.NEWS_RAW_ID
        WHERE e.NEWS_RAW_ID IS NULL
        AND n.CONTENT IS NOT NULL
        AND LENGTH(n.CONTENT) > 50
        ORDER BY n.PUBLISHED_AT DESC
    """)
    return cursor.fetchall()

def enrich_and_store():
    print("🤖 Starting AI enrichment of news articles...\n")

    conn   = get_snowflake_connection()
    cursor = conn.cursor()

    articles = fetch_unenriched_articles(cursor)
    total    = len(articles)

    if total == 0:
        print("✅ All articles already enriched! Nothing to do.")
        cursor.close()
        conn.close()
        return

    print(f"📋 Found {total} articles to enrich...\n")

    success_count = 0
    failed_count  = 0

    for i, (news_id, title, content, source, published_at) in enumerate(articles, 1):
        try:
            print(f"  [{i}/{total}] Enriching: {title[:65]}...")

            enriched = enrich_article(title, content)

            enrich_id = str(uuid.uuid4())

            cursor.execute("""
                INSERT INTO BANK_POC.EXTERNAL_DATA.NEWS_ENRICHED
                    (ID, NEWS_RAW_ID, SUMMARY, SENTIMENT, ENTITIES,
                     ASSET_CLASSES, RELEVANCE_SCORE, CREATED_AT)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                enrich_id,
                news_id,
                enriched.get('summary', ''),
                enriched.get('sentiment', 'NEUTRAL'),
                json.dumps({
                    "sentiment_reason":   enriched.get('sentiment_reason', ''),
                    "entities":           enriched.get('entities', []),
                    "tickers":            enriched.get('tickers', []),
                    "topics":             enriched.get('topics', []),
                    "impact_level":       enriched.get('impact_level', 'LOW'),
                    "recommended_action": enriched.get('recommended_action', '')
                }),
                json.dumps(enriched.get('asset_classes', [])),
                enriched.get('relevance_score', 0.0),
                datetime.now()
            ))

            conn.commit()

            # Print enrichment result
            sentiment_icon = "🟢" if enriched.get('sentiment') == 'POSITIVE' else \
                             "🔴" if enriched.get('sentiment') == 'NEGATIVE' else "🟡"

            print(f"         {sentiment_icon} Sentiment : {enriched.get('sentiment')}")
            print(f"         📝 Summary  : {enriched.get('summary', '')[:80]}...")
            print(f"         🏢 Entities : {', '.join(enriched.get('entities', [])[:4])}")
            print(f"         💡 Action   : {enriched.get('recommended_action', '')[:80]}")
            print()

            success_count += 1

        except Exception as e:
            print(f"         ❌ Failed: {str(e)}\n")
            failed_count += 1
            continue

    cursor.close()
    conn.close()

    print("=" * 60)
    print(f"🎉 Enrichment Complete!")
    print(f"   ✅ Successfully enriched : {success_count}")
    print(f"   ❌ Failed                : {failed_count}")
    print(f"   📊 Total processed       : {total}")
    print("=" * 60)

if __name__ == "__main__":
    enrich_and_store()