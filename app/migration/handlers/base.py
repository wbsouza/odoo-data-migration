import logging

from typing import List, Dict, Any
from ..core.odoo import OdooConnection


_logger = logging.getLogger(__name__)


class HandlerNotFoundException(Exception):
    """Exception raised when a resource is not found in Odoo."""
    def __init__(self, message="Handler not found for this model"):
        self.message = message
        super().__init__(self.message)


class ResourceNotFoundException(Exception):
    """Exception raised when a resource is not found in Odoo."""
    def __init__(self, message="The requested resource was not found"):
        self.message = message
        super().__init__(self.message)


class DomainHandler:
    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, model_name: str):
        """
        Initialize the DomainHandler with source and destination Odoo connections and the model name.
        :param src_odoo: OdooConnection instance for the source Odoo instance.
        :param dst_odoo: OdooConnection instance for the destination Odoo instance.
        :param model_name: The model name being handled (e.g., 'res.groups', 'res.users').
        """
        self.src_odoo = src_odoo
        self.dst_odoo = dst_odoo
        self.model_name = model_name

    def get_src_model(self) -> Any:
        """Return the source Odoo model instance."""
        return self.src_odoo.session.env[self.model_name]

    def get_dst_model(self) -> Any:
        """Return the source Odoo model instance."""
        return self.dst_odoo.session.env[self.model_name]

    def record_exists(self, odoo: OdooConnection, model_name: str, field: str, value: str) -> bool:
        """
        Check if a record with the given field-value pair already exists in the destination Odoo system.
        :param odoo: The odoo connection.
        :param model_name: The model name (e.g., 'res.partner', 'res.users').
        :param field: The name of the field (e.g., 'name').
        :param value: The value to search for in the field (e.g., 'John Doe').
        :return: True if the record exists, False otherwise.
        """
        model = odoo.session.env[model_name]
        domain = [(field, '=', value)]
        return bool(model.search(domain, limit=1))

    def get_item(self, odoo: OdooConnection, model_name: str, _id: int) -> Dict:
        """
        Retrieve a specific record by its ID and convert it to a dictionary.
        :param odoo: The odoo connection.
        :param model_name: The model name (e.g., 'res.partner', 'res.users').
        :param _id: The ID of the record.
        :return: The record as a dictionary.
        """
        try:
            model = odoo.session.env[model_name]
            resp = model.browse(_id).read()[0]  # Ensure record is read and returned as a dict
            record = dict({key: value for key, value in resp.items() if value is not None})
            return record
        except ValueError as ex:
            _logger.error(str(ex))
            raise ResourceNotFoundException()

    def fetch_items(self, odoo: OdooConnection, model_name: str, domain=None, offset: int = 0, order: str = None,
                    limit: int = 100) -> List[Dict]:
        """
        Retrieve a list of records based on a search domain and convert them to dictionaries.
        :param odoo: The odoo connection.
        :param model_name: The model name (e.g., 'res.partner', 'res.users').
        :param domain: The search domain.
        :param offset: The offset for pagination.
        :param limit: The number of records to retrieve.
        :param order: The order for sorting the results.
        :return: A list of records as dictionaries.
        """
        result = []
        domain = [] if domain is None else domain
        model = odoo.session.env[model_name]
        ids = model.search(domain, offset=offset, limit=limit, order=order)
        for record in model.browse(ids):
            result.append(record)
        return result

    def apply_transformations(self, record: Dict) -> List[Dict]:
        """
        This method should be overridden by subclasses to apply any necessary transformations
        to the records, such as splitting or merging data.
        :param record: The record from the source Odoo.
        :return: A list of transformed records.
        """
        raise NotImplementedError("Subclasses should implement this method.")

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        This method should be implemented in subclasses, since each use case might require
        writing to different models in the destination system.
        :param transformed_records: A list of transformed records.
        """
        raise NotImplementedError("Subclasses should implement this method.")
