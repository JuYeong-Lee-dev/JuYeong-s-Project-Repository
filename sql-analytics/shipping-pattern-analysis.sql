-- ============================================================
-- Shipping Company Demand Pattern Analysis
-- ============================================================
-- Identifies high-value shipping companies (거래선) whose vessels
-- have placed multiple qualifying orders over time.
--
-- Qualifying criteria per order:
--   - Order value ≥ USD 20,000
--   - Bulk or General Spare order type only
--   - Excludes cancelled (%X%, %W%), repair, and tech orders
--   - Vessel must have ordered in more than one distinct month
--
-- Output: full delivery line-item detail for qualifying vessels,
-- joined with RFM customer grade and vessel delivery date.
-- Used to identify reliable high-value accounts for targeted
-- sales and stocking strategies.
-- ============================================================

WITH FilteredData AS (
    SELECT
        "거래선명"                              AS customer_name,
        "호선번호"                              AS vessel_no,
        "수통번호"                              AS order_no,
        "자재번호"                              AS material_no,
        "중분류"                                AS material_category,
        "품명"                                  AS part_name,
        "출고수량"                              AS shipped_qty,
        "출고금액(USD)"                         AS shipped_value_usd,
        "매출금액"                              AS sales_amount,
        TO_CHAR("수주일자"::DATE, 'YYYY-MM')   AS order_month
    FROM "납품현황_분류"
    WHERE
        "수통번호" NOT LIKE '%X%'
        AND "수통번호" NOT LIKE '%W%'
        AND "수주금액(USD)" != 0.00
        AND "자재번호" NOT LIKE 'RCFRP'
        AND "담당자명" NOT LIKE '%Tech%'
        AND ("수주유형" LIKE '%Bulk%' OR "수주유형" LIKE '%General%')
),

-- Orders meeting the minimum value threshold (≥ USD 20,000)
ValuableOrders AS (
    SELECT order_no
    FROM FilteredData
    GROUP BY order_no
    HAVING SUM(sales_amount) >= 20000
),

-- Vessels with qualifying orders in more than one distinct month
MultiOrderVessels AS (
    SELECT vessel_no
    FROM FilteredData
    WHERE order_no IN (SELECT order_no FROM ValuableOrders)
    GROUP BY vessel_no
    HAVING COUNT(DISTINCT order_month) > 1
)

SELECT
    f.vessel_no,
    rfm.customer_name,
    f.material_category,
    rfm."등급"                  AS customer_grade,
    info."선박인도일"           AS vessel_delivery_date,
    f.order_no,
    f.material_no,
    f.part_name,
    f.shipped_qty,
    f.shipped_value_usd,
    f.sales_amount,
    f.order_month
FROM FilteredData f
LEFT JOIN "RFM_분류_호선별" rfm
    ON f.vessel_no = rfm."호선번호"
   AND f.customer_name = rfm."거래선명"
LEFT JOIN "호선정보모음" info
    ON f.vessel_no = info."호선번호"
WHERE
    f.vessel_no IN (SELECT vessel_no FROM MultiOrderVessels)
    AND f.order_no IN (SELECT order_no FROM ValuableOrders)
ORDER BY f.vessel_no, f.order_no, f.material_no, f.order_month;
