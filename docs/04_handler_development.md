# Handler Development Guide

## Handler Structure

All handlers extend `DomainHandler` from `app/migration/handlers/base.py`.

### Base Class Methods

```python
class DomainHandler:
    def __init__(self, odoo_provider, db_provider, model_name):
        self._odoo_provider = odoo_provider
        self._db_provider = db_provider
        self.src_model_name = model_name

    def get_src_model(self, model_name=None)  # Get source model with active_test=False
    def get_dst_model(self, model_name=None)  # Get destination model with active_test=False
    def get_dst_model_name()                   # Returns destination model name
    def fetch_items(odoo, model_name, ...)     # Fetch records with pagination
    def apply_transformations(record)          # MUST override - transform logic
    def save_into_destination(records)         # MUST override - persistence logic
    def save_records(records, ...)             # Generic create/update helper
    def update_tracking_ids(x_new_id, record)  # Update x_old_id/x_new_id columns
```

## Creating a New Handler

### Step 1: Create the Handler File

```python
# app/migration/handlers/my_model.py
import logging
from typing import Dict, List, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id

_logger = logging.getLogger(__name__)


class MyModelHandler(DomainHandler):

    def __init__(
        self,
        odoo_provider: OdooConnectionProvider,
        db_provider: DBConnectionProvider,
        model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)
```

### Step 2: Implement apply_transformations()

This method receives a source record and returns a list of transformed records.

```python
def apply_transformations(self, src_record: Any) -> List[Dict]:
    # 1. Log processing start (FAIL FAST - never use getattr for expected properties!)
    _logger.info(
        "Processing %s src_id=%s",
        self.src_model_name,
        src_record.id,
    )

    # 2. Check if record already exists in destination
    conn = self._db_provider.get_connection(DESTINATION)
    table_name = self.get_dst_model_name().replace('.', '_')
    dst_id = find_id_by_old_id(conn, table_name, src_record.id)

    # 3. If exists, get the destination record for update
    dst_record = None
    if dst_id:
        dst_record = self.get_dst_model().browse(dst_id)

    # 4. Build transformed data (adapt Odoo 11 → Odoo 17 schema)
    data = {
        'name': src_record.name,
        # Map other fields...
        # Handle renamed fields:
        # 'new_field_name': src_record.old_field_name,
        # Handle foreign keys:
        # 'parent_id': find_id_by_old_id(conn, 'parent_table', src_record.parent_id.id),
        'x_old_id': src_record.id,  # Always include for tracking
    }

    # 5. Return transformation result
    return [{
        'action': 'update' if dst_id else 'create',
        'model': self.get_dst_model_name(),
        'src_record': src_record,
        'dst_record': dst_record,
        'data': data,
    }]
```

### Step 3: Implement save_into_destination()

```python
def save_into_destination(self, transformed_records: List[Dict]):
    for tr in transformed_records:
        model_name = tr['model']
        data = tr['data']
        action = tr['action']
        src_record = tr['src_record']

        try:
            if action == 'create':
                # FAIL FAST - access properties directly, never use getattr!
                _logger.info(
                    "Creating %s src_id=%s name=%s",
                    model_name,
                    src_record.id,
                    src_record.name,
                )
                dst_model = self.get_dst_model()
                x_new_id = dst_model.create(data)

            elif action == 'update':
                dst_record = tr['dst_record']
                _logger.info(
                    "Updating %s dst_id=%s src_id=%s",
                    model_name,
                    dst_record.id,
                    src_record.id,
                )
                dst_record.write(data)
                x_new_id = dst_record.id

            # Update tracking IDs
            self.update_tracking_ids(x_new_id=x_new_id, record=src_record)

        except Exception as e:
            _logger.error(f"Error processing {model_name} {src_record.id}: {e}")
            continue  # Don't stop migration
```

### Step 4: Register in Executor

Edit `app/migration/executor.py`:

```python
from .handlers.my_model import MyModelHandler

class Migration:
    def __init__(self, configs, mappings_dir):
        # ...
        self.models_to_migrate = [
            # ... existing models
            'my.model',  # Add to migration sequence
        ]

        self.models_handlers = {
            # ... existing handlers
            'my.model': MyModelHandler(self._odoo_provider, self._db_provider, 'my.model'),
        }
```

## Common Patterns

### Foreign Key Resolution

```python
# Resolve related record ID using x_old_id mapping
def _resolve_related_id(self, src_related_record):
    if not src_related_record:
        return None
    conn = self._db_provider.get_connection(DESTINATION)
    return find_id_by_old_id(conn, 'related_table', src_related_record.id)
```

### Name-Based Lookup (for master data)

```python
# For records that exist in both systems (countries, currencies, etc.)
def _find_by_name(self, model_name, name):
    if not name:
        return None
    model = self.get_dst_model(model_name)
    ids = model.search([('name', '=', name)], limit=1)
    return ids[0] if ids else None
```

### Two-Phase Migration (for self-referencing)

Some models like `res.partner` have `parent_id` that references the same model. Use two handlers:

1. **Phase 1**: Migrate records without parent_id
2. **Phase 2**: Update parent_id relationships after all records exist

```python
# res_partner_parent.py - Second phase handler
class ResPartnerParentHandler(DomainHandler):
    def apply_transformations(self, src_record):
        # Only handle parent_id update
        if not src_record.parent_id:
            return []  # Skip records without parent

        conn = self._db_provider.get_connection(DESTINATION)
        dst_parent_id = find_id_by_old_id(conn, 'res_partner', src_record.parent_id.id)

        return [{
            'action': 'update',
            'data': {'parent_id': dst_parent_id},
            # ...
        }]
```

### Handling One2many Lines

```python
# For records with child lines (invoices, orders, etc.)
def apply_transformations(self, src_record):
    # ... header data ...

    # Build line commands
    line_commands = []
    for line in src_record.line_ids:
        line_data = self._transform_line(line)
        line_commands.append((0, 0, line_data))  # Create command

    data['line_ids'] = line_commands
```

### Using Generic save_records()

For simpler handlers, use the base class helper:

```python
def save_into_destination(self, transformed_records):
    self.save_records(
        transformed_records,
        entity_label='product category',
        name_field='name',
    )
```

## Testing a Handler

1. Comment out other models in `models_to_migrate`
2. Set a small batch size for testing
3. Run migration and check logs
4. Verify records in destination database
5. Check tracking IDs are set correctly
