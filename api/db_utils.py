# api/db_utils.py
from django.db import connection
from contextlib import contextmanager

@contextmanager
def get_db_cursor():
    """Context manager for database cursor"""
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()

def execute_query(query, params=None):
    """Execute a query and return results"""
    with get_db_cursor() as cursor:
        cursor.execute(query, params or [])
        columns = [col[0] for col in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

def execute_update(query, params=None):
    """Execute an update/insert/delete query"""
    with get_db_cursor() as cursor:
        cursor.execute(query, params or [])
        return cursor.rowcount

def execute_insert(query, params=None):
    """Execute an insert query and return last inserted id"""
    with get_db_cursor() as cursor:
        cursor.execute(query, params or [])
        return cursor.lastrowid
