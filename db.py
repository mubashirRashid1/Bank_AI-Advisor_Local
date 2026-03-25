# ── db.py — Shared database functions ────────────────────────────
import snowflake.connector
from dotenv import load_dotenv
import os
import pandas as pd
import streamlit as st

load_dotenv()

def get_snowflake_connection():
    return snowflake.connector.connect(
        account   = os.getenv('SNOWFLAKE_ACCOUNT'),
        user      = os.getenv('SNOWFLAKE_USER'),
        password  = os.getenv('SNOWFLAKE_PASSWORD'),
        database  = os.getenv('SNOWFLAKE_DATABASE'),
        schema    = os.getenv('SNOWFLAKE_SCHEMA'),
        warehouse = os.getenv('SNOWFLAKE_WAREHOUSE')
    )

# db.py — add cache to run_query

@st.cache_data(ttl=300, show_spinner=False)
def run_query_cached(query, params=None):
    """
    Cached version — only hits Snowflake every 5 minutes.
    Use for sidebar stats and dropdown lists.
    """
    conn   = get_snowflake_connection()
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    rows    = cursor.fetchall()
    cursor.close()
    conn.close()
    return pd.DataFrame(rows, columns=columns)

def run_query(query, params=None):
    """
    Uncached version — use for fresh data queries
    like AI analysis and portfolio views.
    """
    conn   = get_snowflake_connection()
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    rows    = cursor.fetchall()
    cursor.close()
    conn.close()
    return pd.DataFrame(rows, columns=columns)

def run_cortex(prompt, model='mistral-large2'):
    conn   = get_snowflake_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)
    """, (model, prompt))
    result = cursor.fetchone()[0]
    cursor.close()
    return result