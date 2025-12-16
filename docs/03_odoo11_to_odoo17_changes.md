# Odoo 11 to Odoo 17 - Model Changes

This document describes the key schema and API changes between Odoo 11 and Odoo 17 that affect this migration.

## Product Models

### product.template

| Odoo 11 Field | Odoo 17 Field | Notes |
|---------------|---------------|-------|
| `type` | `detailed_type` | Product type field renamed |
| `uom_id` | `uom_id` | Same, but UoM model is now `uom.uom` (was `product.uom`) |
| `uom_po_id` | `uom_po_id` | Same, but UoM model is now `uom.uom` |
| `website_meta_title` | `website_meta_title` | Same |
| `website_meta_description` | `website_meta_description` | Same |
| `website_meta_keywords` | `website_meta_keywords` | Same |

**Transformation applied:**
```python
'detailed_type': src_record.type,  # 'type' → 'detailed_type'
```

### product.product

| Odoo 11 Field | Odoo 17 Field | Notes |
|---------------|---------------|-------|
| `product_tmpl_id` | `product_tmpl_id` | Same |
| `default_code` | `default_code` | Same |
| `active` | `active` | Same |

**Key constraint in Odoo 17:**
- `product_product_combination_unique`: Variants are uniquely identified by `(product_tmpl_id, combination_indices)`
- Cannot create multiple variants with empty combination for the same template
- Migration handles this by updating the existing single variant instead of creating

### product.attribute.line → product.template.attribute.line

| Odoo 11 | Odoo 17 | Notes |
|---------|---------|-------|
| `product.attribute.line` | `product.template.attribute.line` | Model renamed |
| `product_tmpl_id` | `product_tmpl_id` | Same |
| `attribute_id` | `attribute_id` | Same |
| N/A | `value_ids` | Now uses Many2many instead of separate price records |

### product.attribute.price (Odoo 11 only)

This model **does not exist** in Odoo 17. Attribute pricing is now handled differently:
- Odoo 17 uses `product.template.attribute.value` with `price_extra` field
- Migration must transform price data to the new structure

## Account/Invoice Models

### account.invoice (Odoo 11) → account.move (Odoo 17)

| Odoo 11 | Odoo 17 | Notes |
|---------|---------|-------|
| `account.invoice` | `account.move` | Model renamed/merged |
| `account.invoice.line` | `account.move.line` | Lines model renamed |
| `type` | `move_type` | Field renamed |
| `number` | `name` | Invoice number field |
| `date_invoice` | `invoice_date` | Date field renamed |
| `invoice_line_ids` | `invoice_line_ids` | Same (One2many to lines) |

**Line fields:**
| Odoo 11 | Odoo 17 | Notes |
|---------|---------|-------|
| `product_uom_id` | `product_uom_id` | Same |
| `invoice_id` | `move_id` | Parent link renamed |

## Partner Models

### res.partner

Mostly unchanged between versions. Key considerations:
- `parent_id` requires two-phase migration (partners first, then parent relationships)
- Country and state lookups by name

## UoM Models

| Odoo 11 | Odoo 17 |
|---------|---------|
| `product.uom` | `uom.uom` |
| `product.uom.categ` | `uom.category` |

**Migration approach:**
- Resolve UoM by name lookup in destination
- Fallback to 'Unit(s)' if not found

## General API Changes

### Field Access
- Odoo 17 is stricter about field access via RPC
- Access properties directly (FAIL FAST principle - never use `getattr` to mask missing properties)
- Avoid passing callables or recordsets as values

### JSON Field Storage
- Some fields (like `name` in multi-language setups) are stored as JSONB
- DB queries may need `name->>'en_US'` syntax

### Context
- Use `with_context(active_test=False)` to include archived records
- This is critical for complete data migration

## Tracking Fields

Custom columns added for migration:

**Source (Odoo 11):**
- `x_new_id INTEGER` - Stores destination record ID

**Destination (Odoo 17):**
- `x_old_id INTEGER` - Stores source record ID

Tables with tracking:
- `res_partner`
- `res_users`
- `product_category`
- `product_attribute`
- `product_attribute_value`
- `product_template`
- `product_product`
- `product_template_attribute_line`
- `account_move`
- `account_move_line`
