BEGIN;

-- change the product_id
UPDATE account_invoice_line SET product_id = 10185 WHERE product_id = 102656;
UPDATE account_invoice_line SET product_id = 10153 WHERE product_id = 2444;
UPDATE account_invoice_line SET product_id = 10164 WHERE product_id = 2456;
UPDATE account_invoice_line SET product_id = 10131 WHERE product_id = 10211;

UPDATE PRODUCT_PRODUCT set DEFAULT_CODE = NULL WHERE DEFAULT_CODE IN ('OTHER', 'OTH');
UPDATE PRODUCT_TEMPLATE set DEFAULT_CODE = 'OTHER' WHERE name = 'Other';

-- empty product variant
delete from product_product where id = 2117;

-- disable cron and change the password for the admin user
update res_users set login = 'admin', password_crypt = '$pbkdf2-sha512$600000$.5.zFmIMQeg9RwhhDCHkXA$lqJ0bIu5CAA12pmbgo1ha25lEqK5qc0xUerbklo2gmFDb2Q/lIYcZrynhWhjO3rVzjPGWMiw1bbQtCq7EAc5Tg' where login in ('admin', 'sysadmin@disposal-queen.com');
update optimiser_optimiser oo set enable_recaptcha = false where oo.id = 1;
update ir_cron set active = false;


-- Variant templates: ensure variant codes live on product.product. If a variant is missing a code,
-- copy it from product.template before we clear the template code.
UPDATE product_product pp
SET default_code = pt.default_code
FROM product_template pt
WHERE pt.id = pp.product_tmpl_id
  AND COALESCE(BTRIM(pp.default_code), '') = ''
  AND COALESCE(BTRIM(pt.default_code), '') <> ''
  AND (
    EXISTS (
      SELECT 1
      FROM product_attribute_line pal
      WHERE pal.product_tmpl_id = pt.id
    )
    OR pt.id IN (
      SELECT product_tmpl_id
      FROM product_product
      GROUP BY product_tmpl_id
      HAVING COUNT(*) > 1
    )
  );


-- For variant templates, do not keep default_code on product.template.
-- Variants should use product.product.default_code; non-variants keep it on product.template.
UPDATE product_template pt
SET default_code = NULL
WHERE pt.default_code IS NOT NULL
  AND (
    EXISTS (
      SELECT 1
      FROM product_attribute_line pal
      WHERE pal.product_tmpl_id = pt.id
    )
    OR pt.id IN (
      SELECT product_tmpl_id
      FROM product_product
      GROUP BY product_tmpl_id
      HAVING COUNT(*) > 1
    )
  );


-- Non-variant templates (single variant + no attribute lines): canonical code is product.template.default_code.
-- If template code is empty, fill it from the single product.product; then force product.product to match.
WITH single_variant_templates AS (
    SELECT product_tmpl_id
    FROM product_product
    GROUP BY product_tmpl_id
    HAVING COUNT(*) = 1
),
non_variant_pairs AS (
    SELECT
        pt.id AS product_template_id,
        pt.default_code AS template_default_code,
        pp.id AS product_product_id,
        pp.default_code AS product_default_code
    FROM product_template pt
    JOIN product_product pp ON pp.product_tmpl_id = pt.id
    JOIN single_variant_templates sv ON sv.product_tmpl_id = pt.id
    WHERE NOT EXISTS (
        SELECT 1
        FROM product_attribute_line pal
        WHERE pal.product_tmpl_id = pt.id
    )
)
UPDATE product_template pt
SET default_code = nvp.product_default_code
FROM non_variant_pairs nvp
WHERE pt.id = nvp.product_template_id
  AND COALESCE(BTRIM(pt.default_code), '') = ''
  AND COALESCE(BTRIM(nvp.product_default_code), '') <> '';

WITH single_variant_templates AS (
    SELECT product_tmpl_id
    FROM product_product
    GROUP BY product_tmpl_id
    HAVING COUNT(*) = 1
),
non_variant_pairs AS (
    SELECT
        pt.id AS product_template_id,
        pt.default_code AS template_default_code,
        pp.id AS product_product_id,
        pp.default_code AS product_default_code
    FROM product_template pt
    JOIN product_product pp ON pp.product_tmpl_id = pt.id
    JOIN single_variant_templates sv ON sv.product_tmpl_id = pt.id
    WHERE NOT EXISTS (
        SELECT 1
        FROM product_attribute_line pal
        WHERE pal.product_tmpl_id = pt.id
    )
)
UPDATE product_product pp
SET default_code = nvp.template_default_code
FROM non_variant_pairs nvp
WHERE pp.id = nvp.product_product_id
  AND COALESCE(BTRIM(nvp.template_default_code), '') <> ''
  AND COALESCE(BTRIM(pp.default_code), '') <> BTRIM(nvp.template_default_code);

WITH candidate_products AS (
    SELECT pp.id AS product_product_id,
           pp.product_tmpl_id AS product_template_id
    FROM product_product pp
    WHERE
        NOT EXISTS (SELECT 1 FROM account_invoice_line ail WHERE ail.product_id = pp.id)
        AND pp.product_tmpl_id IN (
            SELECT product_tmpl_id FROM product_product GROUP BY product_tmpl_id HAVING COUNT(*) = 1
        )
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pp.product_tmpl_id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_value_product_product_rel rel WHERE rel.product_product_id = pp.id)
),
orphan_templates AS (
    SELECT pt.id AS product_template_id
    FROM product_template pt
    WHERE
        NOT EXISTS (SELECT 1 FROM product_product pp WHERE pp.product_tmpl_id = pt.id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pt.id)
),
candidate_templates AS (
    SELECT product_template_id FROM candidate_products
    UNION
    SELECT product_template_id FROM orphan_templates
)
DELETE FROM product_product
WHERE id IN (SELECT product_product_id FROM candidate_products);

WITH candidate_products AS (
    SELECT pp.id AS product_product_id,
           pp.product_tmpl_id AS product_template_id
    FROM product_product pp
    WHERE
        NOT EXISTS (SELECT 1 FROM account_invoice_line ail WHERE ail.product_id = pp.id)
        AND pp.product_tmpl_id IN (
            SELECT product_tmpl_id FROM product_product GROUP BY product_tmpl_id HAVING COUNT(*) = 1
        )
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pp.product_tmpl_id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_value_product_product_rel rel WHERE rel.product_product_id = pp.id)
),
orphan_templates AS (
    SELECT pt.id AS product_template_id
    FROM product_template pt
    WHERE
        NOT EXISTS (SELECT 1 FROM product_product pp WHERE pp.product_tmpl_id = pt.id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pt.id)
),
candidate_templates AS (
    SELECT product_template_id FROM candidate_products
    UNION
    SELECT product_template_id FROM orphan_templates
)
DELETE FROM product_template
WHERE id IN (SELECT product_template_id FROM candidate_templates);


WITH candidate_products AS (
    SELECT pp.id AS product_product_id,
           pp.product_tmpl_id AS product_template_id
    FROM product_product pp
    WHERE
        NOT EXISTS (SELECT 1 FROM account_invoice_line ail WHERE ail.product_id = pp.id)
        AND pp.product_tmpl_id IN (
            SELECT product_tmpl_id FROM product_product GROUP BY product_tmpl_id HAVING COUNT(*) = 1
        )
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pp.product_tmpl_id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_value_product_product_rel rel WHERE rel.product_product_id = pp.id)
),
orphan_templates AS (
    SELECT pt.id AS product_template_id
    FROM product_template pt
    WHERE
        NOT EXISTS (SELECT 1 FROM product_product pp WHERE pp.product_tmpl_id = pt.id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pt.id)
),
candidate_templates AS (
    SELECT product_template_id FROM candidate_products
    UNION
    SELECT product_template_id FROM orphan_templates
)
DELETE FROM product_product
WHERE id IN (SELECT product_product_id FROM candidate_products);

WITH candidate_products AS (
    SELECT pp.id AS product_product_id,
           pp.product_tmpl_id AS product_template_id
    FROM product_product pp
    WHERE
        NOT EXISTS (SELECT 1 FROM account_invoice_line ail WHERE ail.product_id = pp.id)
        AND pp.product_tmpl_id IN (
            SELECT product_tmpl_id FROM product_product GROUP BY product_tmpl_id HAVING COUNT(*) = 1
        )
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pp.product_tmpl_id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_value_product_product_rel rel WHERE rel.product_product_id = pp.id)
),
orphan_templates AS (
    SELECT pt.id AS product_template_id
    FROM product_template pt
    WHERE
        NOT EXISTS (SELECT 1 FROM product_product pp WHERE pp.product_tmpl_id = pt.id)
        AND NOT EXISTS (SELECT 1 FROM product_attribute_line pal WHERE pal.product_tmpl_id = pt.id)
),
candidate_templates AS (
    SELECT product_template_id FROM candidate_products
    UNION
    SELECT product_template_id FROM orphan_templates
)
DELETE FROM product_template
WHERE id IN (SELECT product_template_id FROM candidate_templates);

-- If counts look correct:
COMMIT;

-- If anything looks wrong:
-- ROLLBACK;

