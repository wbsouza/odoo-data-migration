import os
import psycopg2
from psycopg2 import OperationalError
from typing import Dict, Any
from configparser import ConfigParser


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
