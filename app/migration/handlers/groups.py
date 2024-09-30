from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo import OdooConnection


class ResGroupsHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'res.groups')
        self.language = dst_odoo.language
        self.company_id = dst_odoo.company_id
        self.mapping_provider = mapping_provider

    def find_category_id(self, source_category_id: int, category_name: str) -> int:
        """
        Find the matching category ID in the destination Odoo (Odoo 16) based on the source category ID from Odoo 11.
        First check the mappings cache, and if not found, perform a lookup.
        :param source_category_id: The category ID from the source Odoo.
        :param category_name: The category name from the source Odoo.
        :return: The destination category ID.
        """
        # First, check if there's already a mapping for the category_id
        destination_category_id = self.mapping_provider.get_mapping('ir.module.category', source_category_id)
        if destination_category_id:
            return destination_category_id

    def find_dest_category_id(self, src_category: Any) -> int:
        """
        Find the matching category ID in the destination Odoo (Odoo 16) based on the source category ID from Odoo 11.
        First check the mappings cache, and if not found, perform a lookup.
        :param src_category: The source category
        :return: The destination category ID.
        """

        if src_category is not None:
            domain = [('name', '=', src_category['name'])]
            resp = self.dst_odoo.fetch_ids('ir.module.category', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
            else:
                raise ResourceNotFoundException(f"Was not found a category with name = \"{src_category['name']}\"")
        else:
            raise ResourceNotFoundException("The category can't be empty")

    def group_exists(self, group_name: str) -> bool:
        """
        Check if the group with the given name (in JSON format) already exists in the destination Odoo system.
        :param group_name: The name of the group in the source system.
        :return: True if the group exists, False otherwise.
        """
        group_model = self.dst_odoo.session.env['res.groups']
        domain = [('name->>' + self.language, '=', group_name)]
        return bool(group_model.search(domain, limit=1))

    def apply_transformations(self, record: Dict) -> List[Dict]:
        """
        Apply transformations to the res.groups records.
        The 'name' field is converted to a JSON format with the configured language.
        """
        transformed_records = []

        # Prepare data for res.groups table
        group_data = {
            'name': record['name'],
            'company_id': record['company_id']['id'],
            'comment': record['comment'],
        }
        # Find the matching category ID in the destination Odoo
        category_id = self.find_dest_category_id(record['category_id'])
        if category_id:
            group_data['category_id'] = category_id

        transformed_records.append({'model': 'res.groups', 'data': group_data})

        return transformed_records

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Create the transformed records in the destination system.
        This handles creating res.groups in the destination Odoo (Odoo 16).
        """
        for record in transformed_records:
            model_name = record['model']
            data = record['data']

            # Extract the name from the JSON format to check if the group already exists
            group_name = data['name'][self.language]

            # Check if the group already exists before attempting to create it
            if self.group_exists(group_name):
                print(f"Group '{group_name}' already exists in the destination system. Skipping creation.")
                continue

            # Destination model handling is specific to this handler, no generic method
            destination_model = self.dst_odoo.session.env[model_name]

            # Create the record in the appropriate model/table
            new_id = destination_model.create(data)
            print(f"Created new group in {model_name} with ID {new_id}")
