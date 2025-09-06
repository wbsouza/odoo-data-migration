import logging

from typing import List, Dict, Any

from ..core.database import DBConnectionProvider
from ..core.odoo_connection import OdooConnection, OdooConnectionProvider

_logger = logging.getLogger(__name__)

SOURCE = 'source'
DESTINATION = 'destination'


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

    def __init__(self, odoo_provider: OdooConnectionProvider, db_provider: DBConnectionProvider, model_name: str):
        self._odoo_provider = odoo_provider
        self._db_provider = db_provider
        self.src_model_name = model_name

    def get_src_model(self, model_name: str = None) -> Any:
        if model_name is None:
            model_name = self.src_model_name
        odoo_conn = self._odoo_provider.get_odoo_connection(SOURCE)
        return odoo_conn.session.env[model_name].with_context(active_test=False)

    def get_dst_model_name(self) -> Any:
        return self.src_model_name

    def get_dst_model(self, model_name: str = None) -> Any:
        if model_name is None:
            model_name = self.get_dst_model_name()
        odoo_conn = self._odoo_provider.get_odoo_connection(DESTINATION)
        return odoo_conn.session.env[model_name].with_context(active_test=False)

    @staticmethod
    def record_exists(odoo: OdooConnection, model_name: str, field: str, value: str) -> bool:
        model = odoo.session.env[model_name]
        domain = [(field, '=', value)]
        return bool(model.search(domain, limit=1))

    @staticmethod
    def get_item(odoo: OdooConnection, model_name: str, _id: int) -> Dict:
        try:
            model = odoo.session.env[model_name]
            resp = model.browse(_id).read()[0]  # Ensure record is read and returned as a dict
            record = dict({key: value for key, value in resp.items() if value is not None})
            return record
        except ValueError as ex:
            _logger.error(str(ex))
            raise ResourceNotFoundException()

    @staticmethod
    def fetch_items(odoo: OdooConnection, model_name: str, domain=None, offset: int = 0, order: str = None,
                    limit: int = 100) -> List[Dict]:
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

    def _update_tracking_id(self, connection_type, model_name, record_id, field_name, field_value):
        try:
            conn = self._db_provider.get_connection(connection_type)
            conn.autocommit = True
            cursor = conn.cursor()
            table_name = model_name.replace('.', '_')
            sql = f'UPDATE {table_name} SET {field_name} = {field_value} WHERE id={record_id}'
            cursor.execute(sql)
            cursor.close()
            return True
        except Exception as ex:
            _logger.error(f"Failed to update tracking id: {ex}")
            return False

    def update_tracking_ids(self, new_id: int, record: Any):
        result = self._update_tracking_id(
            connection_type=SOURCE,
            model_name=self.src_model_name,
            field_name='x_new_id',
            field_value=new_id,
            record_id=record.id
        )
        if result:
            self._update_tracking_id(
                connection_type=DESTINATION,
                model_name=self.get_dst_model_name(),
                field_name='x_old_id',
                field_value=record.id,
                record_id=new_id
            )
        return result
