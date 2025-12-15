# Migration Rules

## Language

- All comments, commits, and code must be written in English.

## Scope of Changes

- Only the migrations for `product.product` and `product.template` may be changed.
- Do not modify migrations for other models.

## Logging Requirements

- Add logs in all relevant places to ensure we are processing all products.
- Logs must include:
  - Source record `id`
  - `default_code` (when available)
- Add logs when records are being written to the destination system:
  - When creating
  - When updating (`write`)
