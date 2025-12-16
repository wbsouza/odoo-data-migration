# Model Handlers Reference

## Overview

Each handler is responsible for transforming and migrating a specific Odoo model. This document provides a quick reference for all implemented handlers.

## Handler List

| Model | Handler Class | File | Notes |
|-------|--------------|------|-------|
| `product.category` | `ProductCategoryHandler` | `product_category.py` | Categories with parent hierarchy |
| `product.template` | `ProductTemplateHandler` | `product_template.py` | Product templates |
| `product.product` | `ProductProductHandler` | `product_product.py` | Product variants |
| `product.attribute` | `ProductAttributeHandler` | `product_attribute.py` | Attributes (Size, Color, etc.) |
| `product.attribute.value` | `ProductAttributeValueHandler` | `product_attribute_value.py` | Attribute values (S, M, L, Red, Blue) |
| `product.attribute.line` | `ProductAttributeLineHandler` | `product_attribute_line.py` | Template-attribute mappings |
| `product.attribute.price` | `ProductAttributePriceHandler` | `product_attribute_price.py` | Attribute price extras (Odoo 11) |
| `res.partner` | `ResPartnerHandler` | `res_partner.py` | Contacts and companies |
| `res.partner` (parent) | `ResPartnerParentHandler` | `res_partner_parent.py` | Parent relationships (phase 2) |
| `res.users` | `ResUsersHandler` | `res_users.py` | Users |
| `account.move` | `AccountMoveHandler` | `account_move.py` | Invoices (from account.invoice) |
| `account.payment` | `AccountPaymentHandler` | `account_payment.py` | Payments |

---

## Product Models

### ProductCategoryHandler

**Source model:** `product.category`  
**Destination model:** `product.category`

**Fields migrated:**
- `name`
- `complete_name`
- `parent_id` (resolved by name lookup)

**Special handling:**
- Parent categories resolved by name (not ID)
- Creates parent path hierarchy

---

### ProductTemplateHandler

**Source model:** `product.template`  
**Destination model:** `product.template`

**Fields migrated:**
- `name`, `active`, `default_code`
- `categ_id` → resolved via `x_old_id`
- `uom_id`, `uom_po_id` → resolved by name lookup
- `detailed_type` ← `type` (field renamed)
- `sale_ok`, `purchase_ok`
- `list_price`, `volume`, `weight`
- `invoice_policy`, `expense_policy`, `tracking`
- `description`, `description_purchase`, `description_sale`
- `website_meta_title`, `website_meta_description`, `website_meta_keywords`
- `product_summary`

**Special handling:**
- UoM resolved by name with fallback to "Unit(s)"
- SEO fields with auto-update flag

---

### ProductProductHandler

**Source model:** `product.product`  
**Destination model:** `product.product`

**Fields migrated:**
- `product_tmpl_id` → resolved via `x_old_id`
- `default_code`
- `product_description`
- `description_sale`

**Special handling:**
- Handles Odoo 17 `product_product_combination_unique` constraint
- Multiple source variants may collapse into single destination variant
- Avoids overwriting `x_old_id` when collapsing

---

### ProductAttributeHandler

**Source model:** `product.attribute`  
**Destination model:** `product.attribute`

**Fields migrated:**
- `name`
- `sequence`
- `create_variant` (if exists)

---

### ProductAttributeValueHandler

**Source model:** `product.attribute.value`  
**Destination model:** `product.attribute.value`

**Fields migrated:**
- `name`
- `attribute_id` → resolved via `x_old_id`
- `sequence`

**Special handling:**
- Fast path with explicit field list to avoid RPC timeouts

---

### ProductAttributeLineHandler

**Source model:** `product.attribute.line`  
**Destination model:** `product.template.attribute.line`

**Fields migrated:**
- `product_tmpl_id` → resolved via `x_old_id`
- `attribute_id` → resolved via `x_old_id`

**Special handling:**
- Model renamed in Odoo 17
- Fast path for fetching

---

### ProductAttributePriceHandler

**Source model:** `product.attribute.price`  
**Destination model:** N/A (handled differently in Odoo 17)

**Fields migrated:**
- `product_tmpl_id`
- `value_id`
- `price_plus`
- `price_multiple`

**Special handling:**
- This model doesn't exist in Odoo 17
- Prices now on `product.template.attribute.value.price_extra`

---

## Partner/User Models

### ResPartnerHandler

**Source model:** `res.partner`  
**Destination model:** `res.partner`

**Fields migrated:**
- `name`, `display_name`, `ref`
- `date`, `lang`, `tz`
- `vat`, `website`, `comment`, `function`
- `type`, `street`, `street2`, `zip`, `city`
- `email`, `phone`, `mobile`
- `is_company`, `company_id`
- `country_id` → resolved by name
- `state_id` → resolved by name + country

**NOT migrated (phase 1):**
- `parent_id` (handled in phase 2)

---

### ResPartnerParentHandler

**Source model:** `res.partner`  
**Destination model:** `res.partner`

**Purpose:** Second-phase migration to set `parent_id` relationships after all partners exist.

**Fields migrated:**
- `parent_id` only → resolved via `x_old_id`

---

### ResUsersHandler

**Source model:** `res.users`  
**Destination model:** `res.users`

**Fields migrated:**
- `login`, `name`
- `partner_id` → resolved via `x_old_id`
- `company_id`, `company_ids`

---

## Accounting Models

### AccountMoveHandler

**Source model:** `account.invoice` (Odoo 11)  
**Destination model:** `account.move` (Odoo 17)

**Header fields migrated:**
- `name` ← `number`
- `move_type` ← `type`
- `company_id`, `partner_id`, `partner_shipping_id`
- `currency_id`, `journal_id`
- `user_id` → resolved via `x_old_id`
- `invoice_date` ← `date_invoice`
- `start_date`, `end_date`
- `ref`, `narration`

**Line fields migrated:**
- `account_id` (derived from product or defaults)
- `name`, `product_id`, `product_uom_id`
- `price_unit`, `quantity`, `discount`
- `tax_ids` (from product taxes)

**Special handling:**
- Model renamed: `account.invoice` → `account.move`
- Lines renamed: `account.invoice.line` → `account.move.line`
- Filters out draft invoices
- Auto-posts invoices after creation
- Caches taxes, accounts, products for performance

---

### AccountPaymentHandler

**Source model:** `account.payment`  
**Destination model:** `account.payment`

**Fields migrated:**
- Payment details
- Partner and invoice references

---

## Handler Inheritance

All handlers inherit from `DomainHandler`:

```
DomainHandler (base.py)
├── ProductCategoryHandler
├── ProductTemplateHandler
├── ProductProductHandler
├── ProductAttributeHandler
├── ProductAttributeValueHandler
├── ProductAttributeLineHandler
├── ProductAttributePriceHandler
├── ResPartnerHandler
├── ResPartnerParentHandler
├── ResUsersHandler
├── AccountMoveHandler
└── AccountPaymentHandler
```
