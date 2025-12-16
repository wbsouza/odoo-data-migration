from configparser import ConfigParser, NoOptionError, NoSectionError
from typing import List, Dict, Optional, Any

import odoorpc
import logging

_logger = logging.getLogger(__name__)

SOURCE = 'source'
DESTINATION = 'destination'

class OdooConnection:
    
    def __init__(self, params: Dict[str, Any]):
        self.session = None
        self._params = params
        self._connection_type = params['connection_type']
        self._host = params['host']
        self._port = params['port']
        self._db_name = params['db_name'] 
        self._username = params['username']
        self._password = params['password']
        self.closed = True

    def get_company_id(self):
        return self._params['company_id']

    def get_language(self):
        return self._params['language']

    def connect(self):
        """
        Establish a connection to the Odoo instance based on the configuration.
        This method can be called separately after initialization.
        """
        try:
            self.session = odoorpc.ODOO(host=self._host, port=self._port)
            self.session.login(self._db_name, self._username, self._password)
            self.closed = False
            _logger.info(f"Odoo {self._connection_type} at {self._host}:{self._port}, db_name: {self._db_name}")
        except Exception as e:
            _logger.error(f"Failed to connect on Odoo {self._connection_type} at {self._host}:{self._port}: {e}")
            raise e

    def get_model(self, model_name: str) -> odoorpc.models.Model:
        """
        Retrieve the model from the Odoo connection.
        :param model_name: The name of the model to interact with (e.g., 'res.users').
        :return: The model instance.
        """
        if not self.session:
            raise Exception(f"Connection to {self._connection_type} Odoo instance is not established.")
        try:
            # Always include archived/inactive records to avoid missing data during migration.
            # Individual handlers can still override behavior by applying a different context.
            return self.session.env[model_name].with_context(active_test=False)
        except Exception as e:
            _logger.error(f"Failed to retrieve model '{model_name}': {e}")
            raise e

    def search_by_field(self, model_name: str, field_name: str, value, limit: int = 1):
        model = self.get_model(model_name)
        domain = [(field_name, '=', value)]
        return model.search(domain, limit=limit)

    def fetch_ids(self, model_name: str, domain=None, offset: int = 0, order: str = None,
                  limit: int = 100) -> List[Dict]:
        domain = [] if domain is None else domain
        model = self.get_model(model_name)
        ids = model.search(domain, offset=offset, limit=limit, order=order)
        return ids

    def fetch_items(self, model_name: str, domain=None, offset: int = 0,
                    order: str = None,
                    limit: int = 100) -> List[Dict]:
        """
        Retrieve a list of records based on a search domain and convert them to dictionaries.
        :param model_name: The model name (e.g., 'res.partner', 'res.users').
        :param domain: The search domain.
        :param offset: The offset for pagination.
        :param limit: The number of records to retrieve.
        :param order: The order for sorting the results.
        :return: A list of records as dictionaries.
        """
        result = []

        ids = self.fetch_ids(model_name, domain=domain, offset=offset, order=order, limit=limit)
        for item_id in ids:
            model = self.get_model(model_name)
            item = model.browse(item_id)
            result.append(item)
        return result


class OdooConnectionProvider:

    _instance = None # static field (belongs to the class)

    # instance fields
    _config: ConfigParser
    _connection_cache: Dict[str, OdooConnection] = {}

    def __new__(cls, configs: ConfigParser):
        """Ensure only one instance of this class exists (Singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._configs = configs
        return cls._instance

    def get_odoo_configs(self, connection_type: str) -> Dict[str, Any]:
        """Get odoo configurations"""
        odoo_configs: Dict[str, Any] = {
            'connection_type': connection_type,
            'host': self._configs.get(connection_type, 'odoo_host', fallback='localhost'),
            'port':  self._configs.getint(connection_type, 'odoo_port'),
            'db_name': self._configs.get(connection_type, 'db_name'),
            'username': self._configs.get(connection_type, 'odoo_user', fallback='odoo'),
            'password': self._configs.get(connection_type, 'odoo_pass', fallback='odoo'),
            'language': self._configs.get('settings', 'language', fallback='en_US'),
            'company_id': self._configs.getint(connection_type, 'company_id', fallback=1),
        }
        return odoo_configs


    def get_odoo_connection(self, connection_type: str):

        # Reuse cached connection if open
        if connection_type in self._connection_cache:
            odoo_conn = self._connection_cache[connection_type]
            
            if odoo_conn.closed == 0:  # 0 means open
                return odoo_conn
            else:
                # Remove closed connection
                del self._connection_cache[connection_type]

        # Create a new connection
        try:
            conn_params = self.get_odoo_configs(connection_type)
            odoo_conn = OdooConnection(conn_params)
            odoo_conn.connect()
            self._connection_cache[connection_type] = odoo_conn
            return odoo_conn
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Odoo: {e}")
