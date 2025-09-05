#!/usr/bin/env python3
"""
Create x_old_id and x_new_id fields in both databases
Must be run BEFORE applying the tracking data
"""
import sys
import psycopg2
import os
from configparser import ConfigParser
from .db_connection import DBConnectionProvider
from typing import Dict, Tuple, Any


def create_tracking_fields(config: ConfigParser):

    connection_provider = DBConnectionProvider(config)

    # Tables to add fields to
    src_tables = [
        'res_partner',
        'res_users',
        'res_partner',
        'product_category',
        'product_attribute',
        'product_attribute_value',
        'product_attribute_line',
        'product_template',
        'product_product'
    ]

    # Create x_new_id in Odoo 11 (source)
    try:
        conn = connection_provider.get_connection('source')
        conn.autocommit = True
        cursor = conn.cursor()
        
        for table in src_tables:
            try:
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS x_new_id INTEGER"
                cursor.execute(sql)
            except Exception as e:
                print(f"  ⚠️ Could not add x_new_id to {table}: {e}")
        
        cursor.close()

    except Exception as e:
        print(f"❌ Failed to connect to Odoo 11: {e}")
        return False

    dst_tables = [
        'res_partner',

        'res_users',
        'res_partner',
        'product_category',
        'product_attribute',
        'product_attribute_value',
        # 'product_template_attribute_value',
        'product_template_attribute_line',
        'product_template',
        'product_product',

    ]
    
    # Create x_old_id in Odoo 17 (destination)
    try:
        dst_conn = connection_provider.get_connection('destination')
        dst_conn.autocommit = True
        dst_cursor = dst_conn.cursor()
        
        for table in dst_tables:
            try:
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS x_old_id INTEGER"
                dst_cursor.execute(sql)
            except Exception as e:
                print(f"  ⚠️ Could not add x_old_id to {table}: {e}")
        
        dst_cursor.close()
        
    except Exception as e:
        print(f"❌ Failed to connect to Odoo 17: {e}")
        return False
    
    return True
