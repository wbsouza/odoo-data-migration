import os
import psycopg2
from psycopg2 import OperationalError
from psycopg2.extensions import connection

from configparser import ConfigParser
from typing import Dict, Tuple, Any


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