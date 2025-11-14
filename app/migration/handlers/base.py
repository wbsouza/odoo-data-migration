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

    def fetch_items(self, odoo: OdooConnection, model_name: str, domain=None, offset: int = 0, order: str = None,
                    limit: int = 100) -> List[Dict]:
        result = []
        domain = [] if domain is None else domain
        model = self.get_src_model(model_name)
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

    def save_records(
        self,
        transformed_records: List[Dict],
        default_model_name: str = None,
        entity_label: str = 'record',
        name_field: str = 'name',
    ) -> None:
        """
        Generic create/update + tracking routine to DRY up handler implementations.

        - Uses `model` from each transformed record, falling back to `default_model_name`
          or this handler's destination model name.
        - Logs create/update with a readable label resolved from `name_field` on src_record.
        - Updates tracking ids via `update_tracking_ids` when a record is created/updated.
        - Catches exceptions per-record and continues.
        """
        for tr in transformed_records:
            model_name = tr.get('model', default_model_name or self.get_dst_model_name())
            data = tr['data']
            action = tr['action']
            src_record = tr['src_record']
            dst_record = tr.get('dst_record')
            x_new_id = None

            # Resolve a user-friendly label for logging
            try:
                label = getattr(src_record, name_field, None)
                # Discard callables or empty labels
                if callable(label) or label is None or label == '':
                    label = getattr(src_record, 'id', 'unknown')
            except Exception:
                label = getattr(src_record, 'id', 'unknown')

            try:
                if action == 'create':
                    # Pure JSON-RPC: create returns the new ID (int)
                    dst_model = self.get_dst_model(model_name)
                    logging.info(f"Creating {entity_label} \"{label}\" ...")
                    x_new_id = dst_model.create(data)
                    dst_record['id'] = x_new_id

                elif action == 'update' and dst_record:
                    # Pure JSON-RPC: avoid browse()/recordsets; write by ids only
                    logging.info(f"Updating {entity_label} \"{label}\" ...")
                    dst_model = self.get_dst_model(model_name)
                    try:
                        dst_id = dst_record['id'] if isinstance(dst_record, dict) else getattr(dst_record, 'id', None)
                    except Exception:
                        dst_id = None
                    if not dst_id:
                        raise ValueError("Missing destination id for update")
                    # RPC write signature: write([ids], vals) -> True
                    dst_model.write([dst_id], data)
                    x_new_id = dst_id

                if x_new_id is not None:
                    self.update_tracking_ids(
                        x_new_id=x_new_id,
                        record=src_record
                    )
            except Exception as e:
                logging.error(f"Error processing {entity_label} '{label}': {str(e)}")
                # Continue with next record instead of failing completely
                continue

    def _update_tracking_id(self, connection_type, model_name, record_id, field_name, field_value):
        try:
            conn = self._db_provider.get_connection(connection_type)
            conn.autocommit = True
            table_name = model_name.replace('.', '_')

            # Check column existence before updating to avoid noisy errors
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = %s AND column_name = %s
                    LIMIT 1
                    """,
                    (table_name, field_name)
                )
                exists = cur.fetchone() is not None

            if not exists:
                _logger.debug(f"Skipping tracking update: column '{field_name}' not found on table '{table_name}'")
                return False

            with conn.cursor() as cursor:
                sql = f'UPDATE {table_name} SET {field_name} = %s WHERE id = %s'
                cursor.execute(sql, (field_value, record_id))
            return True
        except Exception as ex:
            _logger.error(f"Failed to update tracking id: {ex}")
            return False

    def update_tracking_ids(self, x_new_id: int, record: Any):
        result = self._update_tracking_id(
            connection_type=SOURCE,
            model_name=self.src_model_name,
            field_name='x_new_id',
            field_value=x_new_id,
            record_id=record.id
        )
        if result:
            self._update_tracking_id(
                connection_type=DESTINATION,
                model_name=self.get_dst_model_name(),
                field_name='x_old_id',
                field_value=record.id,
                record_id=x_new_id
            )
        return result
