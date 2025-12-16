# Troubleshooting Guide

## Common Issues

### Connection Errors

#### OdooRPC Connection Failed

```
Failed to connect on Odoo source at localhost:8071
```

**Causes:**
- Odoo server not running
- Wrong port number
- Firewall blocking connection

**Solutions:**
1. Verify Odoo is running: `curl http://localhost:8071/web/database/selector`
2. Check port in `migration.conf`
3. Ensure no firewall rules blocking the port

#### PostgreSQL Connection Failed

```
Failed to connect to database: connection refused
```

**Causes:**
- PostgreSQL not accepting connections
- Wrong credentials
- pg_hba.conf not configured for the connection

**Solutions:**
1. Check PostgreSQL is running: `pg_isready`
2. Verify credentials in `migration.conf`
3. Check pg_hba.conf allows connections from migration host

---

### Migration Errors

#### Handler Not Found

```
HandlerNotFoundException: There is no handler for the model my.model!
```

**Cause:** Model added to `models_to_migrate` but no handler registered.

**Solution:** Create handler class and register in `models_handlers` dict in `executor.py`.

---

#### Resource Not Found

```
ResourceNotFoundException: The requested resource was not found
```

**Cause:** Trying to read a record that doesn't exist.

**Solution:** Check source data integrity. The record may have been deleted.

---

#### Foreign Key Not Resolved

```
ValueError: Product template 'X' (old_id=123) not found in destination
```

**Cause:** Trying to migrate a record whose dependency hasn't been migrated yet.

**Solutions:**
1. Check migration order in `models_to_migrate`
2. Ensure parent records are migrated before children
3. Verify the parent record exists in source and was successfully migrated

---

#### Duplicate Key Violation

```
IntegrityError: duplicate key value violates unique constraint
```

**Cause:** Trying to create a record that already exists.

**Solutions:**
1. Check `x_old_id` lookup is working correctly
2. Verify tracking columns exist in destination
3. May need to clear destination data and re-run

---

#### Product Variant Combination Unique

```
product_product_combination_unique constraint violation
```

**Cause:** Odoo 17 enforces unique (product_tmpl_id, combination_indices).

**Solution:** The `ProductProductHandler` handles this by updating existing variant instead of creating. If still failing:
1. Check if template has multiple variants in destination
2. May need to manually clean up destination variants

---

### Performance Issues

#### Slow Migration

**Causes:**
- Large batch sizes with complex records
- Too many RPC calls per record
- No caching

**Solutions:**
1. Reduce batch size: `batch_size = 100`
2. Use caching for repeated lookups (see `CacheService`)
3. Use `model.read(ids, fields)` instead of `browse()` for specific fields
4. Use DB queries instead of RPC where possible

---

#### RPC Timeout

```
odoorpc.error.RPCError: ... timeout
```

**Cause:** Complex records taking too long to fetch.

**Solution:** Use fast path with explicit fields:
```python
if model_name == 'product.attribute.value':
    fields = ['name', 'attribute_id', 'sequence']
    rows = model.read(ids, fields)
    return rows
```

---

#### Memory Issues

**Cause:** Too many records loaded at once.

**Solutions:**
1. Reduce batch size
2. Don't cache entire recordsets
3. Process records one at a time in `save_into_destination()`

---

### Data Issues

#### Missing Tracking Columns

```
column "x_old_id" does not exist
```

**Cause:** Tracking fields not created.

**Solution:** The `create_tracking_fields()` function should run at startup. If not:
```sql
ALTER TABLE product_template ADD COLUMN IF NOT EXISTS x_old_id INTEGER;
```

---

#### Wrong Data Types

```
TypeError: Object of type X is not JSON serializable
```

**Cause:** Passing recordsets or callables instead of primitive values.

**Solutions:**
1. Extract `.id` from Many2one fields
2. Extract `.ids` from Many2many fields
3. Access properties directly (FAIL FAST - never use `getattr` to mask missing properties)
4. Convert dates to strings: `date.strftime('%Y-%m-%d')`

---

#### Name Lookup Fails

```
UoM 'Unit(s)' not found
```

**Cause:** Master data names differ between versions.

**Solutions:**
1. Check exact name in destination (case-sensitive)
2. Use `ilike` for fuzzy matching
3. Implement fallback logic

---

## Debugging Tips

### Enable Debug Logging

```ini
# migration.conf
[settings]
log_level = DEBUG
```

### Add Temporary Logging

```python
def apply_transformations(self, src_record):
    _logger.debug(f"Source record: {src_record.read()}")
    # ... transformation logic
```

### Test Single Record

```python
# Temporarily limit to specific record
domain = [('id', '=', 123)]
records = handler.fetch_items(odoo, model_name, domain=domain, limit=1)
```

### Check Database Directly

```sql
-- Source: What's been migrated?
SELECT id, name, x_new_id FROM product_template WHERE x_new_id IS NOT NULL LIMIT 10;

-- Destination: What came from migration?
SELECT id, name, x_old_id FROM product_template WHERE x_old_id IS NOT NULL LIMIT 10;
```

### Interactive Testing

```python
# Start Python shell
python -i app/main.py

# After migration setup, test manually:
handler = migration.models_handlers['product.template']
src_record = handler.get_src_model().browse(123)
result = handler.apply_transformations(src_record)
print(result)
```

## Recovery Procedures

### Re-run Migration for Specific Model

1. Comment out other models in `models_to_migrate`
2. Run migration
3. Existing records will be updated (not duplicated) due to `x_old_id` tracking

### Clear and Restart

If destination data is corrupted:

```sql
-- WARNING: Destructive! Backup first!
DELETE FROM product_product WHERE x_old_id IS NOT NULL;
DELETE FROM product_template WHERE x_old_id IS NOT NULL;

-- Also clear source tracking
UPDATE product_product SET x_new_id = NULL;
UPDATE product_template SET x_new_id = NULL;
```

### Fix Broken Mappings

```sql
-- Find broken mappings (destination points to non-existent source)
SELECT dst.id, dst.x_old_id 
FROM dest_db.product_template dst
LEFT JOIN source_db.product_template src ON src.id = dst.x_old_id
WHERE dst.x_old_id IS NOT NULL AND src.id IS NULL;
```
