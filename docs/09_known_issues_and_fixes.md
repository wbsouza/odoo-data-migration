# Known Issues and Fixes

## Issue #1: product.product Migration Data Loss (Fixed)

### Problem Description

When migrating `product.product` records from Odoo 11 to Odoo 17, many records were being silently skipped or failing with "duplicate combination" errors.

**Symptoms observed in logs:**
- 468 products processed
- Only ~131 successfully written
- ~47 skipped due to "duplicate combination"
- ~290 products processed with no action logged

### Root Cause

**Odoo 11 vs Odoo 17 difference:**
- **Odoo 11**: Multiple `product.product` records can exist for the same `product.template` with different `default_code` values but no variant attributes (flat product list)
- **Odoo 17**: When creating a `product.template` without attributes, Odoo auto-creates exactly ONE `product.product` with:
  - Empty `combination_indices`
  - **No `default_code`** (empty/False)

**The bug in `find_dst_product()`:**
```python
# OLD CODE - BUG
domain = [('product_tmpl_id', '=', dst_product_tmpl_id)]
if src_record.default_code:
    domain.append(('default_code', '=', src_record.default_code))  # <-- Problem!
```

When searching for destination product:
1. Source has `default_code='3YD MCONT'`
2. Destination auto-created variant has `default_code=False`
3. Search `[('product_tmpl_id', '=', X), ('default_code', '=', '3YD MCONT')]` returns **nothing**
4. Migration thinks no destination exists → tries to create
5. Create fails due to `product_product_combination_unique` constraint
6. Fallback `_find_single_variant_for_template` only works if exactly 1 variant exists

### The Fix

**New lookup strategy in `find_dst_product()`:**

```python
def find_dst_product(self, src_record) -> Optional[Any]:
    """
    Find destination product by template mapping.
    
    Strategy:
    1. First try exact match by (template + default_code) if default_code exists
    2. If not found AND template has only one variant, return that variant
       (Odoo 17 auto-creates one variant with no default_code)
    3. If multiple variants exist, try to find by template only
    """
    dst_product_tmpl_id = self._resolve_dst_template_id(src_record)
    model = self._dst_model_including_archived('product.product')

    # Strategy 1: Try exact match with default_code if present
    if src_record.default_code:
        domain = [('product_tmpl_id', '=', dst_product_tmpl_id), 
                  ('default_code', '=', src_record.default_code)]
        product_ids = model.search(domain, limit=1)
        if product_ids:
            return model.browse(product_ids[0])

    # Strategy 2: Find the single auto-created variant (common case)
    single_variant = self._find_single_variant_for_template(dst_product_tmpl_id)
    if single_variant:
        return single_variant

    # Strategy 3: Find any variant for this template
    return self._find_any_variant_for_template(dst_product_tmpl_id)
```

**New helper method `_find_any_variant_for_template()`:**
```python
def _find_any_variant_for_template(self, dst_product_tmpl_id: int) -> Optional[Any]:
    """Find any variant for a template. Used when we need to update an existing variant."""
    model = self._dst_model_including_archived('product.product')
    ids = model.search([('product_tmpl_id', '=', dst_product_tmpl_id)], limit=1)
    if ids:
        return model.browse(ids[0])
    return None
```

### Behavior After Fix

1. **First source product for a template**: 
   - Finds the auto-created variant (even without matching `default_code`)
   - Updates it with source data including `default_code`
   - Sets `x_old_id` tracking

2. **Subsequent source products for same template**:
   - Finds the same variant (now has a different `default_code`)
   - Updates variant data BUT **does not overwrite `x_old_id`**
   - Logs warning about collapse scenario
   - Still updates source `x_new_id` for audit trail

### Important Note: Data Model Mismatch

This is a **fundamental data model mismatch** between Odoo versions:
- Odoo 11 allowed "flat" products (multiple products per template without attributes)
- Odoo 17 enforces variant uniqueness via `(product_tmpl_id, combination_indices)`

**When multiple source products collapse to one destination variant:**
- Only the **first** source product's `x_old_id` is preserved in destination
- All source products get their `x_new_id` set (pointing to same destination)
- Warning logged for each collapse occurrence

**To fully preserve all source products as separate entities, you would need to:**
1. Create product attributes in destination
2. Assign attribute values to differentiate variants
3. This requires additional migration logic specific to your data structure

### Files Modified

- `app/migration/handlers/product_product.py`:
  - Added `_find_any_variant_for_template()` method
  - Rewrote `find_dst_product()` with 3-strategy lookup
  - Updated `save_into_destination()` with better collapse logging

## Issue #2: Missing `res.partner` records (Archived records skipped)

### Problem Description

During partner migration, only a subset of `res.partner` records were migrated (e.g., ~2000 instead of ~6000+).
This caused downstream failures:

- `res.partner.parent`: warnings like `Destination partner not found for source ID ... Skipping parent update.`
- `res.users`: errors like `Partner 'Webmaster' ... not found in destination`.

### Root Cause

Odoo `search()` defaults to context `active_test=True`, which filters out archived records (`active=False`).
As a result, many archived partners were never fetched from the source and therefore never created/updated in the destination.

### The Fix

- Force source model access to use `active_test=False` so `search()` includes active and archived records.
- Ensure `res.partner.active` is migrated so archived state is preserved in destination.

Files:

- `app/migration/handlers/base.py`: source model access uses `with_context(active_test=False)`.
- `app/migration/handlers/res_partner.py`: migrates `active` field.

### If it still happens (Troubleshooting)

- Verify pagination is deterministic:
  - Always fetch with `order='id'`.
- Verify source counts:
  - Compare `res.partner` counts in source vs destination (including archived).
- Check for domain filters:
  - Ensure no implicit domain is applied to `res.partner` migration.

## Issue #3: `res.partner` migration interrupted by VAT validation

### Problem Description

Partner migration may stop early with an RPC error during `res.partner` create/update when the source `vat` value
does not match the destination validation rules.

Symptoms in logs:

- `Unexpected error during migration of res.partner: The GST/HST number ... does not seem to be valid`

This can cause downstream failures (e.g., `res.users` partner not found) because the migration stops before all
partners are created.

### Root Cause

Odoo 17 validates VAT format more strictly (often expecting `CC##` where `CC` is a country code).
Some source records contain non-VAT strings in the VAT field (e.g., PO numbers), causing destination create/write
to fail.

### The Fix

Retry the same create/update without the `vat` field when the RPC error indicates VAT/GST validation.
This keeps the migration moving and preserves the rest of the partner data.

Files:

- `app/migration/handlers/res_partner.py`: on VAT/GST validation RPC errors, retry create/write with `vat=None`.

### Behavior After Fix

- The migration does not abort the full `res.partner` model migration when a single partner has invalid VAT.
- The partner record is created/updated after clearing `vat`.

Log markers:

- `VAT validation failed on create ...`
- `Retrying res.partner create without vat ...`
- `Retry succeeded (vat cleared) ...`

### Related improvement: Empty-message exceptions

Some exceptions can have an empty `str(e)` which makes logs look like:

- `Unexpected error during migration of <model>:`

To improve diagnostics, the executor now also logs `repr(e)` for unexpected errors.

Files:

- `app/migration/executor.py`: logs `repr(e)` for unexpected migration errors.

## Issue #4: `res.users` create fails with `'NoneType' object does not support item assignment`

### Problem Description

During `res.users` migration, many users may log errors like:

- `Error processing user '<name>': 'NoneType' object does not support item assignment`

The migration loop continues, but most user creates fail.

### Root Cause

The generic helper `save_records()` in `app/migration/handlers/base.py` attempted to set
`dst_record['id'] = x_new_id` after a create.

For create actions, handlers commonly pass `dst_record=None`, so assigning into it raises a `TypeError`.

### The Fix

In `save_records()` create path:

- If `dst_record` is a dict, assign `dst_record['id'] = x_new_id`
- Otherwise, store the created id back into the transformed record as `tr['dst_record'] = {'id': x_new_id}`

Files:

- `app/migration/handlers/base.py`: fixed create path in `save_records()` to avoid assigning into `None`.

### Behavior After Fix

- `res.users` create operations no longer fail due to `NoneType` assignment.
- Remaining failures (if any) should be genuine RPC/data issues and will be logged per user.
