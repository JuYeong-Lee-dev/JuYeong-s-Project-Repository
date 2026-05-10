-- Within SPLIT orders, extract line items fulfilled from KR stock
-- These are materials NL could not cover — candidates for NL stock expansion

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

split_orders AS (
    SELECT order_no
    FROM order_classification
    WHERE fulfillment_type = 'SPLIT'
)

SELECT *
FROM delivery_history
WHERE
    order_no IN (SELECT order_no FROM split_orders)
    AND stock_source = 'KR'
    AND order_no NOT LIKE '%X%'
    AND order_no NOT LIKE '%W%'
    AND order_type IN (
        'Bulk Order - for HIMSEN(Spare)',
        'Bulk Order - without HIMSEN(Spare)',
        'General Spare'
    )
    AND order_date BETWEEN '2021-01-01' AND '2024-12-31';
