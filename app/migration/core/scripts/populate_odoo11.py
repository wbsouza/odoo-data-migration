#!/usr/bin/env python3
"""
🚀 ODOO 11 DATA POPULATION VIA ORM
Based on existing project addon patterns
Uses Odoo ORM to ensure integrity and compatibility
"""

import sys
import os
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

import odoorpc

def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )

def connect_to_odoo():
    """Connect to Odoo 11."""
    try:
        print("🔌 Connecting to Odoo 11 (localhost:8071, database: odoo11)...")
        odoo = odoorpc.ODOO('localhost', port=8071)
        odoo.login('odoo11', 'admin', 'admin')
        print("✅ Connected to Odoo 11 successfully!")
        return odoo
    except Exception as e:
        print(f"❌ Failed to connect to Odoo 11: {e}")
        return None

def check_existing_data(odoo):
    """Check existing data in the database."""
    print("🔍 Checking existing data...")
    
    models_to_check = [
        ('res.partner', 'Partners'),
        ('res.users', 'Users'),
        ('product.category', 'Categories'),
        ('product.template', 'Product Templates'),
        ('product.attribute', 'Attributes'),
        ('product.attribute.value', 'Attribute Values')
    ]
    
    for model, name in models_to_check:
        try:
            count = odoo.env[model].search_count([])
            print(f"   📊 {name}: {count} records")
        except Exception as e:
            print(f"   ❌ Error checking {name}: {e}")

def create_partners(odoo):
    """Create partner records."""
    print("🤝 Creating partners...")
    
    partners_data = [
        {
            'name': 'ABC Corporation Ltd',
            'is_company': True,
            'street': '123 Business Ave',
            'city': 'Vancouver',
            'email': 'info@abc-corp.com',
            'phone': '+1-604-123-4567',
            'customer': True,
            'supplier': False,
        },
        {
            'name': 'John Smith',
            'is_company': False,
            'street': '456 Residential St',
            'city': 'Vancouver',
            'email': 'john.smith@email.com',
            'phone': '+1-604-234-5678',
            'customer': True,
            'supplier': False,
        },
        {
            'name': 'Maria Santos',
            'is_company': False,
            'street': '789 Oak Street',
            'city': 'Richmond',
            'email': 'maria.santos@email.com',
            'phone': '+1-604-345-6789',
            'customer': True,
            'supplier': False,
        },
        {
            'name': 'XYZ Suppliers Inc',
            'is_company': True,
            'street': '321 Industrial Blvd',
            'city': 'Burnaby',
            'email': 'sales@xyz-suppliers.com',
            'phone': '+1-604-456-7890',
            'customer': False,
            'supplier': True,
        },
        {
            'name': 'Premium Client Services',
            'is_company': True,
            'street': '654 Premium Plaza',
            'city': 'Vancouver',
            'email': 'contact@premium-client.com',
            'phone': '+1-604-567-8901',
            'customer': True,
            'supplier': False,
        },
        {
            'name': 'North Distribution Co',
            'is_company': True,
            'street': '987 Distribution Way',
            'city': 'North Vancouver',
            'email': 'orders@north-dist.com',
            'phone': '+1-604-678-9012',
            'customer': True,
            'supplier': True,
        },
        {
            'name': 'Pedro Costa',
            'is_company': False,
            'street': '147 Maple Drive',
            'city': 'Surrey',
            'email': 'pedro.costa@email.com',
            'phone': '+1-604-789-0123',
            'customer': True,
            'supplier': False,
        },
        {
            'name': 'Ana Oliveira',
            'is_company': False,
            'street': '258 Pine Avenue',
            'city': 'Coquitlam',
            'email': 'ana.oliveira@email.com',
            'phone': '+1-604-890-1234',
            'customer': True,
            'supplier': False,
        }
    ]
    
    created_count = 0
    for partner_data in partners_data:
        try:
            # Check if partner already exists
            existing = odoo.env['res.partner'].search([('name', '=', partner_data['name'])])
            if not existing:
                partner_id = odoo.env['res.partner'].create(partner_data)
                created_count += 1
                print(f"   ✅ Created partner: {partner_data['name']} (ID: {partner_id})")
            else:
                print(f"   ⚠️  Partner already exists: {partner_data['name']}")
        except Exception as e:
            print(f"   ❌ Error creating partner {partner_data['name']}: {e}")
    
    print(f"✅ Created {created_count} new partners")
    return created_count

def create_categories(odoo):
    """Create product categories."""
    print("📂 Creating product categories...")
    
    categories_data = [
        {'name': 'Electronics', 'parent_id': False},
        {'name': 'Clothing', 'parent_id': False},
        {'name': 'Home & Garden', 'parent_id': False},
        {'name': 'Books', 'parent_id': False},
        {'name': 'Sports', 'parent_id': False},
        {'name': 'Office Supplies', 'parent_id': False},
    ]
    
    created_count = 0
    for category_data in categories_data:
        try:
            # Check if category already exists
            existing = odoo.env['product.category'].search([('name', '=', category_data['name'])])
            if not existing:
                category_id = odoo.env['product.category'].create(category_data)
                created_count += 1
                print(f"   ✅ Created category: {category_data['name']} (ID: {category_id})")
            else:
                print(f"   ⚠️  Category already exists: {category_data['name']}")
        except Exception as e:
            print(f"   ❌ Error creating category {category_data['name']}: {e}")
    
    print(f"✅ Created {created_count} new categories")
    return created_count

def create_attributes_and_values(odoo):
    """Create product attributes and their values."""
    print("🏷️ Creating product attributes and values...")
    
    attributes_data = [
        {
            'name': 'Color',
            'values': ['Red', 'Blue', 'Green', 'Black', 'White', 'Yellow']
        },
        {
            'name': 'Size',
            'values': ['XS', 'S', 'M', 'L', 'XL', 'XXL']
        },
        {
            'name': 'Material',
            'values': ['Cotton', 'Polyester', 'Leather', 'Plastic', 'Metal', 'Wood']
        }
    ]
    
    created_attrs = 0
    created_values = 0
    
    for attr_data in attributes_data:
        try:
            # Check if attribute already exists
            existing_attr = odoo.env['product.attribute'].search([('name', '=', attr_data['name'])])
            if not existing_attr:
                attr_id = odoo.env['product.attribute'].create({'name': attr_data['name']})
                created_attrs += 1
                print(f"   ✅ Created attribute: {attr_data['name']} (ID: {attr_id})")
            else:
                attr_id = existing_attr[0]
                print(f"   ⚠️  Attribute already exists: {attr_data['name']} (ID: {attr_id})")
            
            # Create attribute values
            for value_name in attr_data['values']:
                try:
                    existing_value = odoo.env['product.attribute.value'].search([
                        ('name', '=', value_name),
                        ('attribute_id', '=', attr_id)
                    ])
                    if not existing_value:
                        value_id = odoo.env['product.attribute.value'].create({
                            'name': value_name,
                            'attribute_id': attr_id
                        })
                        created_values += 1
                        print(f"     ✅ Created value: {value_name} (ID: {value_id})")
                    else:
                        print(f"     ⚠️  Value already exists: {value_name}")
                except Exception as e:
                    print(f"     ❌ Error creating value {value_name}: {e}")
                    
        except Exception as e:
            print(f"   ❌ Error creating attribute {attr_data['name']}: {e}")
    
    print(f"✅ Created {created_attrs} new attributes and {created_values} new values")
    return created_attrs + created_values

def create_products(odoo):
    """Create product templates."""
    print("📦 Creating product templates...")
    
    # Get a category for products
    categories = odoo.env['product.category'].search([], limit=6)
    if not categories:
        print("   ⚠️  No categories found, creating default category...")
        default_cat = odoo.env['product.category'].create({'name': 'General'})
        categories = [default_cat]
    
    products_data = [
        {
            'name': 'Smartphone Galaxy Pro',
            'type': 'service',
            'list_price': 1299.99,
            'standard_price': 800.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Laptop Dell Inspiron',
            'type': 'service',
            'list_price': 2499.99,
            'standard_price': 1800.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Polo Shirt Premium',
            'type': 'service',
            'list_price': 89.99,
            'standard_price': 45.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Running Shoes Sport',
            'type': 'service',
            'list_price': 299.99,
            'standard_price': 150.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Python Programming Book',
            'type': 'service',
            'list_price': 45.99,
            'standard_price': 25.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Office Desk Executive',
            'type': 'service',
            'list_price': 449.99,
            'standard_price': 250.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Ergonomic Chair Pro',
            'type': 'service',
            'list_price': 379.99,
            'standard_price': 200.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Wireless Mouse Gaming',
            'type': 'service',
            'list_price': 74.99,
            'standard_price': 35.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': 'Mechanical Keyboard RGB',
            'type': 'service',
            'list_price': 249.99,
            'standard_price': 120.00,
            'sale_ok': True,
            'purchase_ok': True,
        },
        {
            'name': '24-inch Monitor 4K',
            'type': 'service',
            'list_price': 649.99,
            'standard_price': 400.00,
            'sale_ok': True,
            'purchase_ok': True,
        }
    ]
    
    created_count = 0
    for i, product_data in enumerate(products_data):
        try:
            # Assign category cyclically
            product_data['categ_id'] = categories[i % len(categories)]
            
            # Check if product already exists
            existing = odoo.env['product.template'].search([('name', '=', product_data['name'])])
            if not existing:
                product_id = odoo.env['product.template'].create(product_data)
                created_count += 1
                print(f"   ✅ Created product: {product_data['name']} (ID: {product_id})")
            else:
                print(f"   ⚠️  Product already exists: {product_data['name']}")
        except Exception as e:
            print(f"   ❌ Error creating product {product_data['name']}: {e}")
    
    print(f"✅ Created {created_count} new products")
    return created_count

def create_users(odoo):
    """Create additional users."""
    print("👥 Creating additional users...")
    
    users_data = [
        {
            'name': 'Demo User',
            'login': 'demo',
            'password': 'demo',
            'email': 'demo@example.com',
        },
        {
            'name': 'Test Manager',
            'login': 'manager',
            'password': 'manager',
            'email': 'manager@example.com',
        },
        {
            'name': 'Sales Representative',
            'login': 'sales',
            'password': 'sales',
            'email': 'sales@example.com',
        }
    ]
    
    created_count = 0
    for user_data in users_data:
        try:
            # Check if user already exists
            existing = odoo.env['res.users'].search([('login', '=', user_data['login'])])
            if not existing:
                user_id = odoo.env['res.users'].create(user_data)
                created_count += 1
                print(f"   ✅ Created user: {user_data['name']} (login: {user_data['login']}, ID: {user_id})")
            else:
                print(f"   ⚠️  User already exists: {user_data['login']}")
        except Exception as e:
            print(f"   ❌ Error creating user {user_data['login']}: {e}")
    
    print(f"✅ Created {created_count} new users")
    return created_count

def main():
    """Main function."""
    print("=" * 70)
    print("🚀 ROBUST ODOO 11 DATA POPULATION VIA ORM")
    print("=" * 70)
    print(f"🕒 Start: {datetime.now().strftime('%H:%M:%S')}")
    print("🎯 Using Odoo ORM for maximum compatibility")
    print("=" * 70)
    
    setup_logging()
    
    # Connect to Odoo
    odoo = connect_to_odoo()
    if not odoo:
        print("❌ Failed to connect to Odoo!")
        return False
    
    try:
        # Check existing data
        check_existing_data(odoo)
        print()
        
        # Create data
        total_created = 0
        
        total_created += create_partners(odoo)
        total_created += create_categories(odoo)
        total_created += create_attributes_and_values(odoo)
        total_created += create_products(odoo)
        total_created += create_users(odoo)
        
        print()
        print("=" * 70)
        print("🎉 DATA POPULATION COMPLETED SUCCESSFULLY!")
        print(f"📊 Total records created: {total_created}")
        print(f"🕒 End: {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        
        # Check final data
        print("\n🔍 Final data in database:")
        check_existing_data(odoo)
        
        return True
        
    except Exception as e:
        print(f"❌ Error during population: {e}")
        logging.exception("Population error")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
