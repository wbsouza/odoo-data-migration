# Migration Rules

## Language Standards

- All code, comments, and commit messages **must be in English**
- Log messages must be in English

## Fail Fast Principle

**NEVER use `getattr()` just to guarantee a property exists!**

We want **FAIL FAST** behavior - if a property doesn't exist, the code should fail immediately with a clear error, not silently return `None` and cause confusing bugs downstream.

```python
# BAD - Silent failure, hard to debug
_logger.info("Processing src_id=%s", getattr(src_record, 'id', None))

# GOOD - Fails immediately if 'id' doesn't exist
_logger.info("Processing src_id=%s", src_record.id)
```

**Rationale:**
- Silent `None` values propagate through the system causing mysterious failures
- Debugging becomes extremely difficult ("why is my code not doing what it's supposed to do?")
- Explicit failures with stack traces point directly to the problem

## Current Migration Scope

Only the following model migrations may be modified:
- `product.product`
- `product.template`

**Do not modify migrations for other models** unless explicitly requested.

## Logging Requirements

All handlers must include comprehensive logging:

### Required Log Points

1. **Processing start**: Log when starting to process a record
   ```python
   _logger.info(
       "Processing product.template src_id=%s default_code=%s",
       src_record.id,
       src_record.default_code,
   )
   ```

2. **Create operations**: Log before creating records
   ```python
   _logger.info(
       "Creating product.template src_id=%s default_code=%s name=%s",
       src_record.id,
       src_record.default_code,
       src_record.name,
   )
   ```

3. **Update operations**: Log before updating records
   ```python
   _logger.info(
       "Updating product.template dst_id=%s src_id=%s default_code=%s name=%s",
       dst_record.id,
       src_record.id,
       src_record.default_code,
       src_record.name,
   )
   ```

4. **Tracking ID updates**: Log when saving tracking mappings
   ```python
   _logger.info(
       "Saving tracking mapping: src_id=%s -> dst_id=%s",
       src_record.id,
       x_new_id,
   )
   ```

### Required Log Fields

- Source record `id` (always)
- `default_code` (when available, especially for products)
- Destination `id` (when updating)
- Record `name` (for human readability)

## Error Handling

- Use `try/except` blocks around individual record processing
- Log errors with full context but **continue** processing remaining records
- Never let a single record failure stop the entire migration

```python
try:
    # process record
except Exception as e:
    _logger.error(f"Error processing record {src_record.id}: {e}")
    continue  # Don't stop the whole migration
```

## Idempotency

Migrations must be idempotent (safe to re-run):

1. Always check for existing records using `x_old_id` first
2. Use `find_id_by_old_id()` or `find_record_by_old_id()` before creating
3. If record exists → update; if not → create
4. Never create duplicates

## Batch Processing

- Default batch size: **500 records**
- Fetch records ordered by `id` for deterministic processing
- Include both active and archived records (`active_test=False`)
