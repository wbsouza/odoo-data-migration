import os
import psycopg2
from psycopg2 import OperationalError
from psycopg2.extensions import connection
import re
from configparser import ConfigParser
from typing import Dict, Tuple, Any

import logging

_logger = logging.getLogger(__name__)

class DBConnectionProvider:

    _instance = None # static field (belongs to the class)

    # instance fields
    _config: ConfigParser
    _connection_cache: Dict[str, psycopg2.extensions.connection] = {}

    def __new__(cls, config: ConfigParser):
        """Ensure only one instance of this class exists (Singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = config
        return cls._instance

    def get_db_configs(self, connection_type: str) -> Dict[str, Any]:
        """Get source database configurations"""
        db_configs: Dict[str, Any] = {
            'host': self._config.get(connection_type, 'db_host', fallback=os.environ.get('DB_HOST', 'localhost')),
            'port': int(self._config.get(connection_type, 'db_port', fallback=os.environ.get('DB_PORT', '5432'))),
            'database': self._config.get(connection_type, 'db_name', fallback=os.environ.get('DB_NAME')),
            'user': self._config.get(connection_type, 'db_user', fallback=os.environ.get('DB_USER', 'odoo')),
            'password': self._config.get(connection_type, 'db_pass', fallback=os.environ.get('DB_PASS', 'odoo'))
        }
        return db_configs

    def get_connection(self, connection_type: str):

        # Reuse cached connection if open
        if connection_type in self._connection_cache:
            conn = self._connection_cache[connection_type]
            if conn.closed == 0:  # 0 means open
                return conn
            else:
                # Remove closed connection
                del self._connection_cache[connection_type]

        # Create a new connection
        try:
            conn_params = self.get_db_configs(connection_type)
            conn = psycopg2.connect(**conn_params)
            self._connection_cache[connection_type] = conn
            return conn
        except OperationalError as e:
            raise RuntimeError(f"Failed to connect to database: {e}")


def execute_sql(conn: psycopg2.extensions.connection, sql: str):
    try:
        with conn.cursor() as cursor:
            rows_affected = cursor.execute(sql)
    except Exception as e:
        raise RuntimeError(f"Failed to execute SQL: {e}")
    return rows_affected


def fetch_sql(conn: connection, sql: str):
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            # Handle queries that don't return rows (e.g. UPDATE without RETURNING)
            if cursor.description is None:
                return []
            col_names = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(col_names, row)) for row in rows]

    except Exception as e:
        raise RuntimeError(f"Failed to fetch SQL: {e}")


def find_record_by_field_name(conn: connection, table_name: str, field_name: str, field_value: Any):
    try:
        if isinstance(field_value, str):
            field_value = f"'{field_value}'"
        sql = f"SELECT * FROM {table_name} WHERE {field_name} = {field_value} LIMIT 1"
        rows = fetch_sql(conn, sql)
        return rows[0] if rows else None
    except Exception as e:
        _logger.warning(f"Error finding record by {field_name} = {field_value} in {table_name}: {e}")
        return None


def find_invoice_id_by_old_id(conn: connection, x_old_id: int):
    """
    Optimized helper: fetch only the id from account_move by x_old_id.
    :return: int id or None
    """
    row = find_invoice_by_field_name(conn, 'x_old_id', x_old_id, ['id'])
    return row['id'] if row else None

def find_id_by_field_name(conn: connection, table_name: str, field_name: str, field_value: Any):
    try:
        if isinstance(field_value, str):
            field_value = f"'{field_value}'"
        sql = f"SELECT id FROM {table_name} WHERE {field_name} = {field_value} LIMIT 1"
        rows = fetch_sql(conn, sql)
        return rows[0]['id'] if rows else None
    except Exception as e:
        _logger.warning(f"Error finding ID by {field_name} = {field_value} in {table_name}: {e}")
        return None


def find_invoice_by_field_name(conn: connection, field_name: str, field_value: Any, fields: list[str]):
    """
    Fetch a single account_move row selecting only the specified columns.

    This is a specialized/optimized version for invoices/moves to avoid SELECT *.

    :param conn: psycopg2 connection
    :param field_name: filter column (e.g., 'x_old_id')
    :param field_value: value to match
    :param fields: list of column names to return (e.g., ['id','name','state'])
    :return: dict with requested columns or None
    """
    try:
        # default to id only if not provided
        if not fields:
            fields = ['id']

        # very simple column sanitization to avoid SQL injection via identifiers
        safe_cols = []
        for col in fields:
            col_str = str(col)
            if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', col_str):
                raise ValueError(f"Unsafe column name: {col_str}")
            safe_cols.append(col_str)

        # sanitize field_name as identifier
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', str(field_name)):
            raise ValueError(f"Unsafe field name: {field_name}")

        # quote strings, keep numerics as-is (align with existing helpers' style)
        value_sql = f"'{field_value}'" if isinstance(field_value, str) else str(field_value)

        cols_sql = ', '.join(safe_cols)
        sql = f"SELECT {cols_sql} FROM account_move WHERE {field_name} = {value_sql} LIMIT 1"
        rows = fetch_sql(conn, sql)
        return rows[0] if rows else None
    except Exception as e:
        _logger.warning(f"Error finding invoice by {field_name} = {field_value}: {e}")
        return None


def find_record_by_old_id(conn: connection, table_name: str, x_old_id: int):
    """
    Find a record in the destination database using x_old_id.
    This is more reliable than name-based lookups which can have duplicates.
    
    :param conn: Database connection to destination
    :param table_name: Table name (e.g., 'product_template')
    :param x_old_id: The source record ID to look for
    :return: Dictionary with record data or None if not found
    """
    return find_record_by_field_name(conn, table_name, 'x_old_id', x_old_id)


def find_id_by_old_id(conn: connection, table_name: str, x_old_id: int):
    """
    Find a record ID in the destination database using x_old_id.
    Returns only the scalar ID value, compatible with OdooRPC operations.
    
    :param conn: Database connection to destination
    :param table_name: Table name (e.g., 'product_template')
    :param x_old_id: The source record ID to look for
    :return: Integer ID or None if not found
    """
    return find_id_by_field_name(conn, table_name, 'x_old_id', x_old_id)


def find_id_by_name(conn: connection, table_name: str, name: str):
    """
    Find a record ID in the destination database using name.
    Returns only the scalar ID value, compatible with OdooRPC operations.

    :param conn: Database connection to destination
    :param table_name: Table name (e.g., 'product_template')
    :param name: The name to look for
    :return: Integer ID or None if not found
    """
    try:
        lower_name = name.strip().lower()
        lower_name = re.sub(r'\(s\)', '', lower_name).strip()
        sql = f"SELECT id FROM {table_name} WHERE LOWER(name->>'en_US') LIKE '{lower_name}%' LIMIT 1"
        rows = fetch_sql(conn, sql)
        return rows[0]['id'] if rows else None
    except Exception as e:
        _logger.warning(f"Error finding ID by name = '{name}' in {table_name}: {e}")
        return None




    return find_id_by_field_name(conn, table_name, 'name', name)

def create_tracking_fields(config: ConfigParser):
    connection_provider = DBConnectionProvider(config)

    # Tables to add fields to
    src_tables = [
        'res_partner',
        'res_users',
        'res_partner',
        'product_category',
        'product_attribute',
        'product_attribute_value',
        'product_attribute_line',
        'product_template',
        'product_product'
    ]

    # Create x_new_id in Odoo 11 (source)
    try:
        conn = connection_provider.get_connection('source')
        conn.autocommit = True
        for table in src_tables:
            try:
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS x_new_id INTEGER"
                execute_sql(conn, sql)
            except Exception as e:
                print(f"  ⚠️ Could not add x_new_id to {table}: {e}")
    except Exception as e:
        print(f"❌ Failed to connect to Odoo 11: {e}")
        return False

    dst_tables = [
        'res_partner',
        'res_users',
        'res_partner',
        'product_category',
        'product_attribute',
        'product_attribute_value',
        'product_template_attribute_line',
        'product_template',
        'product_product',
        'account_move',
        'account_move_line',

    ]

    # Create x_old_id in Odoo 17 (destination)
    try:
        dst_conn = connection_provider.get_connection('destination')
        dst_conn.autocommit = True
        for table in dst_tables:
            try:
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS x_old_id INTEGER"
                execute_sql(dst_conn, sql)
            except Exception as e:
                print(f"  ⚠️ Could not add x_old_id to {table}: {e}")
    except Exception as e:
        print(f"❌ Failed to connect to Odoo 17: {e}")
        return False

    return True