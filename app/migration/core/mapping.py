import json
import os
import abc

from configparser import ConfigParser

from ..core.odoo import OdooConnection


class MappingLoader:
    def __init__(self, configs:ConfigParser, odoo_src: OdooConnection, odoo_dst: OdooConnection, mapping_dir: str):
        self.configs = configs
        self.odoo_src = odoo_src
        self.odoo_dst = odoo_dst
        self.mapping_dir = mapping_dir
        self.cache = {}

    def load_mapping_by_field_from_database(self, model_name: str, field_name: str):
        if model_name not in self.cache:
            self.cache[model_name] = {}

        cache_model = self.cache.get(model_name)
        eof = False
        offset = 0
        while not eof:
            src_items = self.odoo_src.fetch_items(model_name, offset=offset, limit=100, order="id")
            eof = (src_items is None or len(src_items) == 0)
            if not eof:
                for src_item in src_items:
                    item_value = getattr(src_item, field_name)
                    dst_items = self.odoo_src.search_by_field(
                        model_name=model_name,
                        field_name="name",
                        value=item_value,
                        limit=1)

                    if dst_items and len(dst_items) > 0:
                        cache_model[src_item['id']] = dst_items[0]

            offset += 100

    def load_mapping_by_name_from_database(self, model_name: str):
        field_name = "name"
        self.load_mapping_by_field_from_database(model_name, field_name)


class MappingProvider:

    def __init__(self, configs: ConfigParser, odoo_src: OdooConnection, odoo_dst: OdooConnection, mapping_dir: str):
        """
        Initialize the MappingProvider to handle caching and file-based mappings.
        Ensure it only runs once.
        """
        if not hasattr(self, 'initialized'):  # Ensure initialization runs only once
            self.configs = configs
            self.odoo_src = odoo_src
            self.odoo_dst = odoo_dst
            self.mapping_dir = mapping_dir
            self.cache = {}  # In-memory cache for model mappings
            os.makedirs(self.mapping_dir, exist_ok=True)
            self.initialized = True  # Mark as initialized

    def load_mappings_from_files(self, model_name: str):
        """
        Load mappings from file into the in-memory cache for the given model if not already loaded.
        :param model_name: The model name (e.g., 'res.groups', 'res.users').
        """
        mapping_file = os.path.join(self.mapping_dir, f"{model_name}.map")
        if model_name not in self.cache:
            self.cache[model_name] = {}

        model_cache = self.cache[model_name]
        if not os.path.exists(mapping_file):
            with open(mapping_file, 'r') as f:
                for line in f:
                    source_id, dest_id = line.strip().split('=')
                    self.cache[model_name][int(source_id.strip())] = int(dest_id.strip())

    def load_mappings_from_database(self, model_name: str, field_name: str):
        mapping_loader = MappingLoader(configs=self.configs, odoo_src=self.odoo_src, odoo_dst=self.odoo_dst,
                                       mapping_dir=self.mapping_dir)
        if field_name.lower() == "name":
            mapping_loader.load_mapping_by_name_from_database(model_name)
        else:
            mapping_loader.load_mapping_by_field_from_database(model_name, field_name)

    def save_mappings(self, model_name: str):
        """
        Save the in-memory mappings to a file for the given model.
        :param model_name: The model name (e.g., 'res.groups', 'res.users').
        """
        mapping_file = os.path.join(self.mapping_dir, f"{model_name}.map")
        with open(mapping_file, 'w') as f:
            for source_id, dest_id in self.cache[model_name].items():
                f.write(f"{source_id}->{dest_id}\n")

    def save_all_mappings(self):
        for model_name in self.cache:
            self.save_mappings(model_name)

    def get_mapping(self, model_name: str, source_id: int) -> int:
        """
        Get the destination ID for a given source ID in a specific model.
        :param model_name: The model name (e.g., 'res.groups', 'res.users').
        :param source_id: The source ID.
        :return: The destination ID, or None if not found.
        """
        if model_name not in self.cache:
            self.cache[model_name] = {}
        mapped_model = self.cache.get(model_name)
        return mapped_model.get(source_id)

    def set_mapping(self, model_name: str, source_id: int, dest_id: int):
        """
        Set a mapping from source ID to destination ID for a specific model.
        This can overwrite an existing mapping if necessary.
        :param model_name: The model name (e.g., 'res.groups', 'res.users').
        :param source_id: The source ID.
        :param dest_id: The destination ID.
        """
        if model_name not in self.cache:
            self.cache[model_name] = {}
        self.cache[model_name][source_id] = dest_id