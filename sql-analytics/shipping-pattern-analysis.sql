-- Identify high-value shipping companies with repeat qualifying orders
-- Criteria: order value ≥ USD 20,000, active across more than one month

WITH base AS (
    SELECT
        customer_name,
        vessel_no,
        order_no,
        material_no,
        material_category,
        part_name,
        shipped_qty,
        shipped_value_usd,
        sales_amount,
        TO_CHAR(order_date::DATE, 'YYYY-MM') AS order_month
    FROM delivery_history
    WHERE
        order_no NOT LIKE '%X%'
        AND order_no NOT LIKE '%W%'
        AND order_amount_usd != 0
        AND material_no NOT LIKE 'RCFRP'
        AND manager_name NOT LIKE '%Tech%'
        AND (order_type LIKE '%Bulk%' OR order_type LIKE '%General%')
),

valuable_orders AS (
    SELECT order_no
    FROM base
    GROUP BY order_no
    HAVING SUM(sales_amount) >= 20000
),

-- Vessels with qualifying orders spanning more than one month
repeat_vessels AS (
    SELECT vessel_no
    FROM base
    WHERE order_no IN (SELECT order_no FROM valuable_orders)
    GROUP BY vessel_no
    HAVING COUNT(DISTINCT order_month) > 1
)

SELECT
    b.vessel_no,
    b.customer_name,
    b.material_category,
    r.grade                     AS customer_grade,
    v.delivery_date             AS vessel_delivery_date,
    b.order_no,
    b.material_no,
    b.part_name,
    b.shipped_qty,
    b.shipped_value_usd,
    b.sales_amount,
    b.order_month
FROM base b
LEFT JOIN rfm_customer_grades r
    ON b.vessel_no = r.vessel_no AND b.customer_name = r.customer_name
LEFT JOIN vessel_info v
    ON b.vessel_no = v.vessel_no
WHERE
    b.vessel_no IN (SELECT vessel_no FROM repeat_vessels)
    AND b.order_no IN (SELECT order_no FROM valuable_orders)
ORDER BY b.vessel_no, b.order_no, b.material_no, b.order_month;
