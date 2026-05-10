-- ============================================================
-- Step 1: Classify each order by fulfillment source (2021–2024)
-- ============================================================
-- Each order (수통번호) is classified into one of three types:
--   NL_FULFILLED  → all lines shipped from NL revolving stock
--   KR_FULFILLED  → all lines shipped from KR general stock
--   SPLIT         → lines shipped from both NL and KR stock
--
-- Excludes: cancelled orders (%X%, %W%), repair/tech orders,
--           orders outside the Bulk/General Spare types.
-- ============================================================

WITH order_classification AS (
    SELECT
        "수통번호"                          AS order_no,
        CASE
            WHEN COUNT(DISTINCT "Stock 구분") = 1
                 AND MAX("Stock 구분") = '리볼빙' THEN 'NL_FULFILLED'
            WHEN COUNT(DISTINCT "Stock 구분") = 1
                 AND MAX("Stock 구분") = '일반'   THEN 'KR_FULFILLED'
            WHEN COUNT(DISTINCT "Stock 구분") > 1  THEN 'SPLIT'
        END AS fulfillment_type
    FROM "납품현황_정제_분류_완료_final"
    WHERE
        "수통번호" NOT LIKE '%X%'
        AND "수통번호" NOT LIKE '%W%'
        AND "수통번호" IS NOT NULL
        AND "Stock 구분" IN ('리볼빙', '일반')
        AND (
            "수주유형" LIKE 'Bulk Order - for HIMSEN(Spare)'
            OR "수주유형" LIKE 'Bulk Order - without HIMSEN(Spare)'
            OR "수주유형" LIKE '%General Spare%'
        )
        AND "수주일자" BETWEEN '2021-01-01' AND '2024-12-31'
    GROUP BY "수통번호"
)

-- Join classification back to the full delivery table
SELECT
    a.*,
    b.fulfillment_type
FROM "납품현황_정제_분류_완료_final" a
JOIN order_classification b ON a."수통번호" = b.order_no
WHERE
    a."수통번호" NOT LIKE '%X%'
    AND a."수통번호" NOT LIKE '%W%'
    AND a."Stock 구분" IN ('리볼빙', '일반')
    AND (
        a."수주유형" LIKE 'Bulk Order - for HIMSEN(Spare)'
        OR a."수주유형" LIKE 'Bulk Order - without HIMSEN(Spare)'
        OR a."수주유형" LIKE '%General Spare%'
    )
    AND a."수주일자" BETWEEN '2021-01-01' AND '2024-12-31';
