import logging

import traceback
from configparser import ConfigParser

from .handlers.base import ResourceNotFoundException, HandlerNotFoundException
from .handlers.res_users import ResUsersHandler
from .handlers.res_partner import ResPartnerHandler
from .handlers.res_partner_parent import ResPartnerParentHandler
from .handlers.product_category import ProductCategoryHandler
from .handlers.product_attribute import ProductAttributeHandler
from .handlers.product_template import ProductTemplateHandler
from .handlers.product_attribute_value import ProductAttributeValueHandler
from .handlers.product_attribute_line import ProductAttributeLineHandler
from .handlers.product_attribute_price import ProductAttributePriceHandler
from .handlers.product_product import ProductProductHandler
from .handlers.account_move import AccountMoveHandler
from .handlers.account_payment import AccountPaymentHandler
from .core.mapping import MappingProvider
from .core.odoo_connection import OdooConnectionProvider, SOURCE
from .core.database import DBConnectionProvider
from .core.database import create_tracking_fields

_logger = logging.getLogger(__name__)

class Migration:

    def __init__(self, configs: ConfigParser, mappings_dir: str):
        """
        Initialize the Migration class with the source and destination Odoo connections.
        :param configs: Application configs.
        :param src_odoo: OdooConnection instance for the source Odoo system.
        :param dst_odoo: OdooConnection instance for the destination Odoo system.
        :param mappings_dir: Mappings directory.
        """
        self._configs = configs
        self._odoo_provider = OdooConnectionProvider(configs)
        self._db_provider = DBConnectionProvider(configs)
        self._mappings_provider = MappingProvider(configs, self._odoo_provider, mappings_dir)
        self._mappings_provider.load_mappings_from_database("res.groups", "name")
        create_tracking_fields(self._configs)
        self.models_to_migrate = [
            # 'product.category',
            # 'product.template',
            # 'product.attribute',
            # 'product.attribute.value',
            # 'product.attribute.line',
            # 'product.attribute.price',
            'product.product',
            # 'res.partner',
            # 'res.partner.parent',  # Second phase for parent_id relationships
            # 'res.users',
            # 'account.move',
            # 'account.payment',
        ]

        self.models_handlers = {
            'product.category': ProductCategoryHandler(self._odoo_provider, self._db_provider, 'product.category'),
            'product.template': ProductTemplateHandler(self._odoo_provider, self._db_provider, 'product.template'),
            'product.attribute': ProductAttributeHandler(self._odoo_provider, self._db_provider, self._mappings_provider, 'product.attribute'),
            'product.attribute.value': ProductAttributeValueHandler(self._odoo_provider, self._db_provider, 'product.attribute.value'),
            'product.attribute.line': ProductAttributeLineHandler(self._odoo_provider, self._db_provider, 'product.attribute.line'),
            'product.attribute.price': ProductAttributePriceHandler(self._odoo_provider, self._db_provider, 'product.attribute.price'),
            'product.product': ProductProductHandler(self._odoo_provider, self._db_provider, 'product.product'),
            'res.partner': ResPartnerHandler(self._odoo_provider, self._db_provider, 'res.partner'),
            'res.partner.parent': ResPartnerParentHandler(self._odoo_provider, self._db_provider, 'res.partner'),
            'res.users': ResUsersHandler(self._odoo_provider, self._db_provider, 'res.users'),
            'account.move': AccountMoveHandler(self._odoo_provider, self._db_provider, 'account.move'),
            'account.payment': AccountPaymentHandler(self._odoo_provider, self._db_provider, 'account.payment'),
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
            eof = False
            offset = 0
            batch_size = 500
            while not eof:

                src_odoo = self._odoo_provider.get_odoo_connection(SOURCE)

                # Include both active and archived records in migration
                source_model_name = model_name
                if model_name == 'res.partner.parent':
                    source_model_name = 'res.partner'
                # Odoo 11 source model for invoices is 'account.invoice'
                if model_name == 'account.move':
                    source_model_name = 'account.invoice'

                domain = None

                if model_name == 'product.attribute.value':
                    domain = []

                if model_name == 'account.move':
                    # Odoo 11 account.invoice: exclude draft invoices
                    domain = [('type', '=', 'out_invoice'), ('state', '!=', 'draft')]
                # elif model_name == 'account.payment':
                #     # Migrate only confirmed payments to guarantee correctness of associations
                #     domain = [('state', '!=', 'draft')]

                records = handler.fetch_items(
                    odoo=src_odoo,
                    model_name=source_model_name,
                    domain=domain,
                    offset=offset,
                    limit=batch_size,
                    order="id"
                )

                eof = records is not None and len(records) < 1
                if not eof:
                    _logger.info(f"Fetched {len(records)} records for {model_name}. Applying transformations...")
                    # Apply transformations
                    transformed_records = []
                    for record in records:
                        transformed_records += handler.apply_transformations(record)

                    _logger.info(f"Transformations complete for {model_name}. Saving into destination...")

                    # Insert transformed records into the destination
                    handler.save_into_destination(transformed_records)
                offset += batch_size

            _logger.info(f"Migration complete for {model_name}.")
        except ResourceNotFoundException as e:
            _logger.error(f"Error during migration of {model_name}: {str(e)}")
        except Exception as e:
            _logger.error(f"Unexpected error during migration of {model_name}: {str(e)}")
            _logger.error(traceback.format_exc())


    def run(self):
        """
        Run the migration process by migrating models in the correct sequence.
        """
        _logger.info("Starting migration process...")

        # Migrate each model in the correct sequence
        for model_name in self.models_to_migrate:
            self.migrate_model(model_name)

        _logger.info("Migration process completed successfully.")