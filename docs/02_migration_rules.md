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

## Product Code (`default_code`) Authority Rule

Odoo models the product domain like class inheritance at the database level:

- `product.template` is the base record (shared fields)
- `product.product` is the specialized record (variant-specific fields)

For migration, audits, and any data-prep scripts, `default_code` must follow this rule:

- For **non-variant products** (single variant and no attribute lines), the canonical code is `product.template.default_code`.
- For **variant products** (template has attribute lines or has multiple variants), the canonical code is `product.product.default_code`.

Classification (Odoo 11 source):

- A template is considered **variant** if:
  - it has at least one `product_attribute_line` for the template, OR
  - it has more than one `product_product` row.
- Otherwise it is considered **non-variant**.

Implications:

- Data-prep must not create duplicate `product.product.default_code` values if the source DB has a uniqueness constraint.
- For variant templates, the migration should not depend on `product.template.default_code` being populated.
- For non-variant templates, the migration should keep `product.template.default_code` populated and may keep `product.product.default_code` consistent with it.

## Product Pricing Rules

### Base price (`list_price`) authority

- The canonical **base sale price** is `product.template.list_price`.
- `product.product` does not store a canonical base price in standard Odoo; variant pricing is derived from the template plus variant adjustments.

### Variant pricing adjustments

- Odoo 11 `product.attribute.price` represents **variant adjustments** (e.g. plus/multiple), not the template base price.
- This project must keep the existing **plus-price addon** behavior. Do not remove or rename fields used by that addon.

### Avoid guessing custom fields

- Do not write to custom or addon-specific per-variant price fields on `product.product` unless explicitly requested and confirmed as the field used by the target deployment.
- If per-variant base prices must be preserved in Odoo 17, the correct approach must be agreed first (e.g., a specific custom field used by a known addon, or `product.pricelist.item` rules).

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
