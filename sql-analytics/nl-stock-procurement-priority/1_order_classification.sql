-- Classify each order by fulfillment source: NL_FULFILLED, KR_FULFILLED, or SPLIT
-- Period: 2021–2024 · Bulk and General Spare orders only

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
)

SELECT
    d.*,
    c.fulfillment_type
FROM delivery_history d
JOIN order_classification c USING (order_no)
WHERE
    d.order_no NOT LIKE '%X%'
    AND d.order_no NOT LIKE '%W%'
    AND d.stock_source IN ('NL', 'KR')
    AND d.order_type IN (
        'Bulk Order - for HIMSEN(Spare)',
        'Bulk Order - without HIMSEN(Spare)',
        'General Spare'
    )
    AND d.order_date BETWEEN '2021-01-01' AND '2024-12-31';
