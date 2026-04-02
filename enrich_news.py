# ── enrich_news.py — Batch enrichment with Ollama + ChromaDB ─────
import os
import uuid
import json
from db import get_connection, run_execute, run_cortex, add_to_vector_index

def safe_str(val, default=''):
    """Convert any value to string safely."""
    if val is None:
        return default
    try:
        return str(val).strip()
    except Exception:
        return default

def enrich_article(title, content):
    """
    Use local Ollama via REST to generate summary,
    sentiment and asset class. Always returns a dict.
    """
    title   = safe_str(title)[:500]
    content = safe_str(content)[:400]

    if not title:
        return {
            "summary":    "No title available",
            "sentiment":  "NEUTRAL",
            "asset_class":"GENERAL"
        }

    prompt = (
        "You are a Canadian financial analyst. "
        "Analyze this news and respond in JSON only. "
        "No explanation, no markdown, just raw JSON. "
        "Title: " + title + " "
        "Content: " + content + " "
        "Return exactly this JSON: "
        '{"summary": "2-3 sentence summary", '
        '"sentiment": "POSITIVE or NEGATIVE or NEUTRAL", '
        '"asset_class": "EQUITIES or BONDS or FX or '
        'REAL_ESTATE or GENERAL"}'
    )

    try:
        raw = run_cortex(prompt)
        raw = safe_str(raw)

        if not raw:
            raise Exception("Empty response from Ollama")

        raw   = raw.replace('```json','').replace('```','').strip()
        start = raw.find('{')
        end   = raw.rfind('}') + 1

        if start < 0 or end <= start:
            raise Exception(f"No JSON found in: {raw[:100]}")

        parsed = json.loads(raw[start:end])

        # Validate all fields exist and are strings
        return {
            "summary":    safe_str(parsed.get('summary'),    title[:200]),
            "sentiment":  safe_str(parsed.get('sentiment'),  'NEUTRAL'),
            "asset_class":safe_str(parsed.get('asset_class'),'GENERAL'),
        }

    except Exception as e:
        print(f"      Fallback ({e.__class__.__name__}: {str(e)[:60]})")
        return {
            "summary":    title[:200],
            "sentiment":  "NEUTRAL",
            "asset_class":"GENERAL"
        }

def enrich_all_news():
    """Enrich all unenriched NEWS_RAW articles."""
    print("Starting batch enrichment...")

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.ID, r.TITLE, r.CONTENT, r.SOURCE,
               r.URL, r.PUBLISHED_AT
        FROM NEWS_RAW r
        LEFT JOIN NEWS_ENRICHED e ON r.ID = e.NEWS_RAW_ID
        WHERE e.ID IS NULL
        ORDER BY r.CREATED_AT DESC
    """)
    rows  = cursor.fetchall()
    cursor.close()
    conn.close()

    # Convert sqlite3.Row to plain tuples safely
    articles = []
    for row in rows:
        try:
            articles.append((
                safe_str(row[0]),
                safe_str(row[1]),
                safe_str(row[2]),
                safe_str(row[3]),
                safe_str(row[4]),
                safe_str(row[5]),
            ))
        except Exception as e:
            print(f"   Skipping bad row: {e}")

    total   = len(articles)
    done    = 0
    success = 0

    if total == 0:
        print("   All articles already enriched.")
        return 0

    print(f"   Found {total} articles to enrich...")
    print()

    for news_id, title, content, source, url, pub_at in articles:
        done += 1
        print(f"   [{done}/{total}] {title[:65]}...")

        try:
                    enriched    = enrich_article(title, content)
                    enrich_id   = str(uuid.uuid4())
                    summary     = safe_str(enriched.get('summary'),     title[:200])
                    sentiment   = safe_str(enriched.get('sentiment'),   'NEUTRAL')
                    asset_class = safe_str(enriched.get('asset_class'), 'GENERAL')

                    print(f"      enriched ok: {sentiment}")

                    # Save enrichment
                    try:
                        run_execute("""
                            INSERT OR IGNORE INTO NEWS_ENRICHED
                                (ID, NEWS_RAW_ID, SUMMARY, SENTIMENT,
                                ENTITIES, ASSET_CLASSES, RELEVANCE_SCORE)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            enrich_id,
                            news_id,
                            summary[:2000],
                            sentiment,
                            json.dumps({"source": source}),
                            json.dumps([asset_class]),
                            0.80
                        ))
                        print(f"      db insert ok")
                    except Exception as e:
                        print(f"      DB INSERT FAILED: {e}")
                        raise

                    # Add to ChromaDB
                    try:
                        index_text = (title + " " + summary).strip() or title
                        add_to_vector_index(
                            doc_id   = enrich_id,
                            text     = index_text,
                            metadata = {
                                "title":         title,
                                "summary":       summary,
                                "sentiment":     sentiment,
                                "source":        source,
                                "url":           url,
                                "published_at":  pub_at,
                                "asset_classes": asset_class
                            }
                        )
                        print(f"      chromadb ok")
                    except Exception as e:
                        print(f"      CHROMADB FAILED: {e}")
                        raise

                    success += 1

        except Exception as e:
            print(f"   ERROR [{done}]: {e}")
                    
    print()
    print("=" * 50)
    print(f"✅ Enrichment complete!")
    print(f"   Success: {success}")
    print(f"   Errors:  {done - success}")
    print(f"   Total:   {total}")
    print("=" * 50)
    return success

if __name__ == "__main__":
    enrich_all_news()
