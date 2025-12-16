# ID Tracking System

## Purpose

The tracking system maintains bidirectional mappings between source (Odoo 11) and destination (Odoo 17) record IDs. This enables:

1. **Idempotent migrations** - Re-running migration updates existing records instead of creating duplicates
2. **Foreign key resolution** - Lookup destination IDs for related records
3. **Audit trail** - Know which destination record corresponds to which source record

## Tracking Columns

### Source Database (Odoo 11)

Column: `x_new_id INTEGER`

- Added to tables being migrated
- Stores the **destination** record ID after successful migration
- Populated by `update_tracking_ids()` after create/update

### Destination Database (Odoo 17)

Column: `x_old_id INTEGER`

- Added to tables receiving migrated data
- Stores the **source** record ID
- Used for lookups: "Does this source record already exist in destination?"

## Tables with Tracking

**Source (Odoo 11) - x_new_id:**
- `res_partner`
- `res_users`
- `product_category`
- `product_attribute`
- `product_attribute_value`
- `product_attribute_line`
- `product_template`
- `product_product`

**Destination (Odoo 17) - x_old_id:**
- `res_partner`
- `res_users`
- `product_category`
- `product_attribute`
- `product_attribute_value`
- `product_template_attribute_line`
- `product_template`
- `product_product`
- `account_move`
- `account_move_line`

## Initialization

Tracking columns are created automatically at migration startup:

```python
# app/migration/core/database.py
def create_tracking_fields(config: ConfigParser):
    # Source: Add x_new_id
    sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS x_new_id INTEGER"
    
    # Destination: Add x_old_id
    sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS x_old_id INTEGER"
```

## Lookup Functions

### find_record_by_old_id()

Returns full record dict from destination by source ID:

```python
from ..core.database import find_record_by_old_id

conn = self._db_provider.get_connection(DESTINATION)
dst_record = find_record_by_old_id(conn, 'product_template', src_record.id)
# Returns: {'id': 123, 'name': '...', ...} or None
```

### find_id_by_old_id()

Returns only the destination ID (more efficient):

```python
from ..core.database import find_id_by_old_id

conn = self._db_provider.get_connection(DESTINATION)
dst_id = find_id_by_old_id(conn, 'product_template', src_record.id)
# Returns: 123 or None
```

## Updating Tracking IDs

After successfully creating/updating a record, call `update_tracking_ids()`:

```python
# In handler save_into_destination():
x_new_id = dst_model.create(data)  # or dst_record.id for updates

self.update_tracking_ids(
    x_new_id=x_new_id,      # Destination record ID
    record=src_record        # Source record (needs .id attribute)
)
```

This does two things:
1. Sets `x_new_id = destination_id` in source table
2. Sets `x_old_id = source_id` in destination table

## Implementation Details

```python
# app/migration/handlers/base.py

def update_tracking_ids(self, x_new_id: int, record: Any):
    # Update source: x_new_id
    result = self._update_tracking_id(
        connection_type=SOURCE,
        model_name=self.src_model_name,
        field_name='x_new_id',
        field_value=x_new_id,
        record_id=record.id
    )
    
    # Update destination: x_old_id
    if result:
        self._update_tracking_id(
            connection_type=DESTINATION,
            model_name=self.get_dst_model_name(),
            field_name='x_old_id',
            field_value=record.id,
            record_id=x_new_id
        )

def _update_tracking_id(self, connection_type, model_name, record_id, field_name, field_value):
    conn = self._db_provider.get_connection(connection_type)
    table_name = model_name.replace('.', '_')
    
    # Check column exists before updating
    # ... (see base.py for full implementation)
    
    sql = f'UPDATE {table_name} SET {field_name} = %s WHERE id = %s'
    cursor.execute(sql, (field_value, record_id))
```

## Special Cases

### Multiple Source Records → Single Destination

For product variants, multiple source `product.product` records may collapse into a single destination variant (due to Odoo 17's `combination_unique` constraint).

In this case, don't overwrite `x_old_id`:

```python
# In ProductProductHandler
existing_old_id = dst_record.x_old_id
if existing_old_id and existing_old_id != src_record.id:
    vals.pop('x_old_id', None)  # Don't overwrite existing mapping
```

### Model Name Changes

When source and destination model names differ (e.g., `account.invoice` → `account.move`), the handler must handle table name conversion:

```python
def get_dst_model_name(self) -> str:
    return 'account.move'  # Override if different from src_model_name
```

## Querying Tracking Data

### Find all migrated records

```sql
-- Source: Records that have been migrated
SELECT id, name, x_new_id FROM product_template WHERE x_new_id IS NOT NULL;

-- Destination: Records that came from migration
SELECT id, name, x_old_id FROM product_template WHERE x_old_id IS NOT NULL;
```

### Find unmigrated records

```sql
-- Source: Records not yet migrated
SELECT id, name FROM product_template WHERE x_new_id IS NULL;
```

### Verify mapping integrity

```sql
-- Cross-check mappings
SELECT 
    src.id as src_id, 
    src.x_new_id as expected_dst_id,
    dst.id as actual_dst_id,
    dst.x_old_id as dst_points_to
FROM source_db.product_template src
JOIN dest_db.product_template dst ON dst.id = src.x_new_id
WHERE dst.x_old_id != src.id;  -- Should return 0 rows if consistent
```
