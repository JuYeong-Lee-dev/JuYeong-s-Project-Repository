-- Find vessel/material pairs quoted in 2025 with no resulting contract
-- Used to prioritise sales follow-up on unconverted opportunities

WITH uncontracted_pairs AS (
    -- Pairs with a 2025 quote but no 2025 contract (set difference)
    SELECT DISTINCT material_subcategory, vessel_no
    FROM quote_history
    WHERE quote_date LIKE '2025-%'

    EXCEPT

    SELECT DISTINCT material_subcategory, vessel_no
    FROM quote_history
    WHERE contract_date LIKE '2025-%'
)

SELECT
    q.quote_date,
    q.vessel_delivery_date,
    v.vessel_name,
    q.tech_manager,
    q.product_type,
    q.material_subcategory,
    q.vessel_no,
    q.customer,
    SUM(q.contract_amount)          AS total_contracted_amount,
    SUM(q.quote_amount)             AS total_quoted_amount,
    COUNT(DISTINCT q.quote_no)      AS quote_count,
    COUNT(DISTINCT q.sales_order_no) AS order_count
FROM quote_history q
JOIN uncontracted_pairs u
    ON (q.material_subcategory = u.material_subcategory
        OR (q.material_subcategory IS NULL AND u.material_subcategory IS NULL))
   AND (q.vessel_no = u.vessel_no
        OR (q.vessel_no IS NULL AND u.vessel_no IS NULL))
LEFT JOIN vessel_info v ON q.vessel_no = v.vessel_no
WHERE
    q.quote_date LIKE '2025-%'
    AND q.vessel_no != 'HOTHR999-NL'
GROUP BY
    q.quote_date,
    q.vessel_delivery_date,
    v.vessel_name,
    q.tech_manager,
    q.product_type,
    q.material_subcategory,
    q.vessel_no,
    q.customer
ORDER BY q.vessel_no, q.material_subcategory, q.customer, q.quote_date;
