from configparser import ConfigParser, NoOptionError, NoSectionError
from typing import List, Dict, Optional

import odoorpc
import logging
import os

_logger = logging.getLogger(__name__)


class OdooConnection:
    def __init__(self, configs: ConfigParser, connection_type: str):
        """
        Initialize the Odoo connection and load configuration settings.
        :param configs: The app configuration.
        :param connection_type: Type of connection ('source' or 'destination').
        """
        try:
            self.connection_type = connection_type
            self.host = configs.get(self.connection_type, 'host')
            self.port = configs.getint(self.connection_type, 'port')
            self.db = configs.get(self.connection_type, 'database')
            self.username = configs.get(self.connection_type, 'username')
            self.password = configs.get(self.connection_type, 'password')
            self.host = configs.get(self.connection_type, 'host')

            # Load the preferred language and company_id from the 'settings' section
            self.language = configs.get('settings', 'language', fallback='en_US')
            self.company_id = configs.getint('settings', 'company_id', fallback=1)

        except NoSectionError as e:
            _logger.error(f"Configuration error: section '{self.connection_type}' not found: {e}")
            raise e
        except NoOptionError as e:
            _logger.error(f"Configuration error: missing option in section '{self.connection_type}': {e}")
            raise e

    def connect(self):
        """
        Establish a connection to the Odoo instance based on the configuration.
        This method can be called separately after initialization.
        """
        try:
            self.session = odoorpc.ODOO(host=self.host, port=self.port)
            self.session.login(self.db, self.username, self.password)
            _logger.info(f"Connected to Odoo {self.connection_type} at {self.host}:{self.port}, database: {self.db}")
        except Exception as e:
            _logger.error(f"Failed to connect on Odoo {self.connection_type} at {self.host}:{self.port}: {e}")
            raise e

    def get_model(self, model_name: str) -> odoorpc.models.Model:
        """
        Retrieve the model from the Odoo connection.
        :param model_name: The name of the model to interact with (e.g., 'res.users').
        :return: The model instance.
        """
        if not self.session:
            raise Exception(f"Connection to {self.connection_type} Odoo instance is not established.")
        try:
            return self.session.env[model_name]
        except Exception as e:
            _logger.error(f"Failed to retrieve model '{model_name}': {e}")
            raise e

    def search_by_field(self, model_name: str, field_name: str, value, limit: int = 1):
        model = self.session.env[model_name]
        domain = [(field_name, '=', value)]
        return model.search(domain, limit=limit)

    def fetch_ids(self, model_name: str, domain=None, offset: int = 0, order: str = None,
                  limit: int = 100) -> List[Dict]:
        domain = [] if domain is None else domain
        model = self.session.env[model_name]
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
            model = self.session.env[model_name]
            item = model.browse(item_id)
            result.append(item)
        return result
