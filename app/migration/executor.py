import logging

from configparser import ConfigParser

from .handlers.base import ResourceNotFoundException, HandlerNotFoundException
from .handlers.users import ResUsersHandler
from .core.mapping import MappingProvider
from .core.odoo import OdooConnection


_logger = logging.getLogger(__name__)


class Migration:

    def __init__(self, configs: ConfigParser, src_odoo: OdooConnection, dst_odoo: OdooConnection, mappings_dir: str):
        """
        Initialize the Migration class with the source and destination Odoo connections.
        :param configs: Application configs.
        :param src_odoo: OdooConnection instance for the source Odoo system.
        :param dst_odoo: OdooConnection instance for the destination Odoo system.
        :param mappings_dir: Mappings directory.
        """
        self.configgs = configs
        self.src_odoo = src_odoo
        self.dst_odoo = dst_odoo
        self.mappings_provider = MappingProvider(configs, src_odoo, dst_odoo, mappings_dir)
        self.mappings_provider.load_mappings_from_database("res.groups", "name")

        self.models_to_migrate = [
            'res.users',
        ]
        self.models_handlers = {
            'res.users': ResUsersHandler(self.src_odoo, self.dst_odoo, self.mappings_provider),
        }


    def migrate_model(self, model_name: str):
        """
        Migrate a specific model from the source Odoo system to the destination Odoo system.
        :param model_name: The name of the model (e.g., 'res.groups', 'res.users').
        """
        try:
            _logger.info(f"Starting migration for {model_name}...")
            handler = self.models_handlers.get(model_name)
            if handler is None or not handler:
                raise HandlerNotFoundException(f"There is no handler for the model {model_name}!")

            # Fetch records from the source system
            records = handler.fetch_items(handler.src_odoo, model_name, order="id")
            _logger.info(f"Fetched {len(records)} records for {model_name}. Applying transformations...")

            # Apply transformations
            transformed_records = []
            for record in records:
                transformed_records += handler.apply_transformations(record)

            _logger.info(f"Transformations complete for {model_name}. Saving into destination...")

            # Insert transformed records into the destination
            handler.save_into_destination(transformed_records)
            _logger.info(f"Migration complete for {model_name}.")
        except ResourceNotFoundException as e:
            _logger.error(f"Error during migration of {model_name}: {str(e)}")
        except Exception as e:
            _logger.error(f"Unexpected error during migration of {model_name}: {str(e)}")

    def run(self):
        """
        Run the migration process by migrating models in the correct sequence.
        """
        _logger.info("Starting migration process...")

        # Migrate each model in the correct sequence
        for model_name in self.models_to_migrate:
            self.migrate_model(model_name)

        _logger.info("Migration process completed successfully.")
