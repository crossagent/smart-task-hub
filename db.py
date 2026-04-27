import os
import json
import psycopg2
import datetime
from decimal import Decimal
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any
from contextlib import contextmanager

class CustomEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle dates, datetimes, decimals, and bytes properly."""
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return super().default(obj)

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "smart_task_hub"),
        user=os.getenv("DB_USER", "smart_user"),
        password=os.getenv("DB_PASSWORD", "smart_pass")
    )

@contextmanager
def db_transaction():
    """Context manager for atomic database transactions."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def execute_query(query: str, params: tuple = None, connection=None) -> List[Dict[str, Any]]:
    """Execute a read query and return full results as dicts."""
    try:
        if connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params) if params else cursor.execute(query)
                return cursor.fetchall()
        else:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params) if params else cursor.execute(query)
                    return cursor.fetchall()
    except Exception as e:
        raise Exception(f"Query error: {e}")

def execute_mutation(query: str, params: tuple = None, connection=None) -> int:
    """Execute a write query (INSERT/UPDATE/DELETE) and return rowcount."""
    try:
        if connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params) if params else cursor.execute(query)
                return cursor.rowcount
        else:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params) if params else cursor.execute(query)
                    conn.commit()
                    return cursor.rowcount
    except Exception as e:
        raise Exception(f"Mutation error: {e}")
