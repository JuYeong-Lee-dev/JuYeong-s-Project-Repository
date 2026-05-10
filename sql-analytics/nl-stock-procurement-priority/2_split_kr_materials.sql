-- ============================================================
-- Step 2: Within SPLIT orders — identify materials shipped via KR
-- ============================================================
-- Focuses on orders classified as SPLIT in Step 1.
-- Extracts the specific line items that were fulfilled from KR
-- (general stock) rather than NL (revolving stock).
--
-- These materials represent demand that NL stock could not cover —
-- candidates for expanding NL revolving stock holdings.
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
),

split_orders AS (
    SELECT order_no
    FROM order_classification
    WHERE fulfillment_type = 'SPLIT'
)

-- KR-fulfilled line items within SPLIT orders
SELECT *
FROM "납품현황_정제_분류_완료_final"
WHERE
    "수통번호" IN (SELECT order_no FROM split_orders)
    AND "Stock 구분" = '일반'           -- KR general stock lines only
    AND "수통번호" NOT LIKE '%X%'
    AND "수통번호" NOT LIKE '%W%'
    AND (
        "수주유형" LIKE 'Bulk Order - for HIMSEN(Spare)'
        OR "수주유형" LIKE 'Bulk Order - without HIMSEN(Spare)'
        OR "수주유형" LIKE '%General Spare%'
    )
    AND "수주일자" BETWEEN '2021-01-01' AND '2024-12-31';
