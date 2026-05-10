-- Cross-reference SPLIT/KR materials against NL shipping history
-- Flags each material: ALREADY IN NL STOCK vs NOT IN NL STOCK

WITH order_classification AS (
    SELECT
        order_no,
        CASE
            WHEN COUNT(DISTINCT stock_source) = 1 AND MAX(stock_source) = 'NL' THEN 'NL_FULFILLED'
            WHEN COUNT(DISTINCT stock_source) = 1 AND MAX(stock_source) = 'KR' THEN 'KR_FULFILLED'
            WHEN COUNT(DISTINCT stock_source) > 1                               THEN 'SPLIT'
        END AS fulfillment_type
    FROM delivery_history
    WHERE
        order_no NOT LIKE '%X%'
        AND order_no NOT LIKE '%W%'
        AND order_no IS NOT NULL
        AND stock_source IN ('NL', 'KR')
        AND order_type IN (
            'Bulk Order - for HIMSEN(Spare)',
            'Bulk Order - without HIMSEN(Spare)',
            'General Spare'
        )
        AND order_date BETWEEN '2021-01-01' AND '2024-12-31'
    GROUP BY order_no
),

split_kr_materials AS (
    SELECT DISTINCT d.u_code, d.material_no, d.material_subcategory
    FROM delivery_history d
    JOIN order_classification c USING (order_no)
    WHERE
        c.fulfillment_type = 'SPLIT'
        AND d.stock_source = 'KR'
        AND d.order_no NOT LIKE '%X%'
        AND d.order_no NOT LIKE '%W%'
        AND d.order_type IN (
            'Bulk Order - for HIMSEN(Spare)',
            'Bulk Order - without HIMSEN(Spare)',
            'General Spare'
        )
        AND d.order_date BETWEEN '2021-01-01' AND '2024-12-31'
),

nl_stock_history AS (
    SELECT DISTINCT u_code, material_no, material_subcategory
    FROM delivery_history
    WHERE stock_source = 'NL'
)

SELECT DISTINCT
    s.u_code,
    s.material_no,
    s.material_subcategory,
    CASE
        WHEN n.u_code IS NOT NULL THEN 'ALREADY IN NL STOCK'
        ELSE 'NOT IN NL STOCK'
    END AS nl_stock_status
FROM split_kr_materials s
LEFT JOIN nl_stock_history n
    ON COALESCE(s.u_code, s.material_no) = COALESCE(n.u_code, n.material_no)
   AND s.material_subcategory = n.material_subcategory;
