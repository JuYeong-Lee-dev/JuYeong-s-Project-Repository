-- Priority materials for NL stock expansion
-- Criteria: appeared in SPLIT orders via KR, no NL shipping history, 3+ occurrences
-- Ranked by split_order_count descending

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

nl_stock_history AS (
    SELECT DISTINCT COALESCE(u_code, material_no) AS code_key
    FROM delivery_history
    WHERE stock_source = 'NL'
)

SELECT
    COALESCE(d.u_code, d.material_no)  AS material_code,
    CASE WHEN d.u_code IS NOT NULL THEN 'U-CODE' ELSE 'MATERIAL NO.' END AS code_type,
    d.material_subcategory,
    COUNT(DISTINCT d.order_no)          AS split_order_count
FROM delivery_history d
JOIN order_classification c USING (order_no)
WHERE
    c.fulfillment_type = 'SPLIT'
    AND d.stock_source = 'KR'
    AND COALESCE(d.u_code, d.material_no) NOT IN (SELECT code_key FROM nl_stock_history)
    AND d.order_no NOT LIKE '%X%'
    AND d.order_no NOT LIKE '%W%'
    AND d.order_type IN (
        'Bulk Order - for HIMSEN(Spare)',
        'Bulk Order - without HIMSEN(Spare)',
        'General Spare'
    )
    AND d.order_date BETWEEN '2021-01-01' AND '2024-12-31'
GROUP BY 1, 2, 3
HAVING COUNT(DISTINCT d.order_no) >= 3
ORDER BY split_order_count DESC;
