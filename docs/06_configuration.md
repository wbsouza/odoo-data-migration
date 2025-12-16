# Configuration Reference

## Configuration File

Location: `migration.conf` (in project root, copied to `app/migration.conf`)

## Sections

### [source] - Odoo 11 Connection

```ini
[source]
odoo_host = localhost      # Odoo XML-RPC/JSON-RPC host
odoo_port = 8071           # Odoo port (typically 8069, here 8071 for Odoo 11)
odoo_user = admin          # Odoo login username
odoo_pass = admin          # Odoo login password
db_name = dqweb            # PostgreSQL database name
db_host = localhost        # PostgreSQL host
db_port = 5432             # PostgreSQL port
db_user = odoo             # PostgreSQL username
db_pass = odoo             # PostgreSQL password
```

### [destination] - Odoo 17 Connection

```ini
[destination]
odoo_host = localhost      # Odoo XML-RPC/JSON-RPC host
odoo_port = 8069           # Odoo port
odoo_user = admin          # Odoo login username
odoo_pass = admin          # Odoo login password
db_name = dq17             # PostgreSQL database name
db_host = localhost        # PostgreSQL host
db_port = 5432             # PostgreSQL port
db_user = odoo             # PostgreSQL username
db_pass = odoo             # PostgreSQL password
```

### [settings] - General Settings

```ini
[settings]
log_file = ./logs/migration.log    # Log file path
log_level = INFO                    # Logging level: DEBUG, INFO, WARNING, ERROR
language = en_US                    # Default language for translations
company_id = 1                      # Default company ID in destination
```

## Environment Variables

The database connection can also use environment variables as fallbacks:

- `DB_HOST` - Database host
- `DB_PORT` - Database port
- `DB_NAME` - Database name
- `DB_USER` - Database username
- `DB_PASS` - Database password

## Connection Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Migration Script                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   ┌─────────────────────┐       ┌─────────────────────┐         │
│   │   OdooRPC (Source)  │       │  OdooRPC (Dest)     │         │
│   │   Port: 8071        │       │  Port: 8069         │         │
│   │   For: read records │       │  For: create/update │         │
│   └─────────┬───────────┘       └─────────┬───────────┘         │
│             │                             │                      │
│   ┌─────────▼───────────┐       ┌─────────▼───────────┐         │
│   │  Odoo 11 Server     │       │  Odoo 17 Server     │         │
│   │  (dqweb database)   │       │  (dq17 database)    │         │
│   └─────────┬───────────┘       └─────────┬───────────┘         │
│             │                             │                      │
│   ┌─────────▼───────────┐       ┌─────────▼───────────┐         │
│   │   psycopg2 (Source) │       │   psycopg2 (Dest)   │         │
│   │   For: x_new_id     │       │   For: x_old_id     │         │
│   │   tracking updates  │       │   lookups & updates │         │
│   └─────────────────────┘       └─────────────────────┘         │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## Running the Migration

### Prerequisites

1. Both Odoo instances must be running and accessible
2. PostgreSQL databases must allow direct connections
3. Python environment with dependencies installed

### Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure migration.conf with your connection details
cp migration.conf.example migration.conf
# Edit migration.conf
```

### Execution

```bash
# From project root
cd app
python main.py
```

### Logs

Logs are written to:
- Console (stdout)
- File: `./logs/migration.log` (configurable)

Log format:
```
2024-01-15 10:30:45,123 INFO Starting migration process...
2024-01-15 10:30:45,456 INFO Processing product.template src_id=1 default_code=PROD001
```

## Migration Sequence

The order of models in `executor.py` matters due to foreign key dependencies:

```python
self.models_to_migrate = [
    'product.category',           # 1. Categories (no dependencies)
    'product.template',           # 2. Templates (depends on categories)
    'product.attribute',          # 3. Attributes
    'product.attribute.value',    # 4. Attribute values (depends on attributes)
    'product.attribute.line',     # 5. Attribute lines (depends on templates, attributes)
    'product.attribute.price',    # 6. Attribute prices
    'product.product',            # 7. Variants (depends on templates)
    'res.partner',                # 8. Partners
    'res.partner.parent',         # 9. Partner parent relationships (2nd phase)
    'res.users',                  # 10. Users (depends on partners)
    'account.move',               # 11. Invoices (depends on partners, products)
    'account.payment',            # 12. Payments (depends on invoices)
]
```

To migrate specific models only, comment out others in the list.

## Batch Size

Default batch size is 500 records. To change:

```python
# In executor.py migrate_model()
batch_size = 500  # Adjust as needed
```

Larger batches = faster but more memory. Smaller = slower but safer for large records.
