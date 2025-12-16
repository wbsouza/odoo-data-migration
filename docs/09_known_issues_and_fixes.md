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
