-- ============================================================
-- Step 4: Rank priority materials for NL stock expansion
-- ============================================================
-- Final output: materials that are the strongest candidates for
-- adding to NL revolving stock.
--
-- Qualification criteria (all must be met):
--   1. Appeared in a SPLIT order and was shipped from KR
--   2. Has NO history of ever being shipped from NL stock
--   3. Appeared in 3 or more distinct SPLIT orders
--
-- Ranked by frequency (highest SPLIT order count first).
-- This gives procurement a data-driven priority list rather than
-- relying on intuition or ad hoc requests.
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

-- All materials ever shipped from NL revolving stock
nl_revolving_parts AS (
    SELECT DISTINCT COALESCE("U Code", "자재번호") AS code_key
    FROM "납품현황_정제_분류_완료_final"
    WHERE "Stock 구분" = '리볼빙'
)

-- Priority list: SPLIT/KR materials with no NL history, appearing in 3+ orders
SELECT
    COALESCE(a."U Code", a."자재번호")   AS material_code,
    CASE
        WHEN a."U Code" IS NOT NULL THEN 'U-CODE'
        ELSE 'MATERIAL NO.'
    END                                   AS code_type,
    a."소분류 (대)"                       AS material_category,
    COUNT(DISTINCT a."수통번호")          AS split_order_count   -- frequency rank
FROM "납품현황_정제_분류_완료_final" a
JOIN order_classification b ON a."수통번호" = b.order_no
WHERE
    b.fulfillment_type = 'SPLIT'
    AND a."Stock 구분" = '일반'
    -- Exclude materials that already have any NL shipping history
    AND COALESCE(a."U Code", a."자재번호") NOT IN (SELECT code_key FROM nl_revolving_parts)
    AND a."수통번호" NOT LIKE '%X%'
    AND a."수통번호" NOT LIKE '%W%'
    AND (
        a."수주유형" LIKE 'Bulk Order - for HIMSEN(Spare)'
        OR a."수주유형" LIKE 'Bulk Order - without HIMSEN(Spare)'
        OR a."수주유형" LIKE '%General Spare%'
    )
    AND a."수주일자" BETWEEN '2021-01-01' AND '2024-12-31'
GROUP BY 1, 2, 3
HAVING COUNT(DISTINCT a."수통번호") >= 3   -- minimum 3 SPLIT occurrences
ORDER BY split_order_count DESC;
