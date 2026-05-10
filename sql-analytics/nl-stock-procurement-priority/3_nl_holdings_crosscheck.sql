-- ============================================================
-- Step 3: Cross-reference SPLIT/KR materials against NL stock history
-- ============================================================
-- Takes the KR-fulfilled materials from SPLIT orders (Step 2)
-- and checks whether each item has ever been shipped from NL
-- revolving stock in the same period.
--
-- Output flags each material as:
--   'ALREADY IN NL STOCK' → NL has shipped this before; a stocking issue
--   'NOT IN NL STOCK'     → NL has never held this; a procurement gap
--
-- This distinction separates two different problems:
--   1. Items NL holds but couldn't cover (availability/quantity issue)
--   2. Items NL doesn't hold at all (procurement scope issue)
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

-- KR-fulfilled lines in SPLIT orders
split_kr_materials AS (
    SELECT DISTINCT a."U Code", a."자재번호", a."소분류 (대)"
    FROM "납품현황_정제_분류_완료_final" a
    JOIN order_classification b ON a."수통번호" = b.order_no
    WHERE b.fulfillment_type = 'SPLIT'
      AND a."Stock 구분" = '일반'
      AND a."수통번호" NOT LIKE '%X%'
      AND a."수통번호" NOT LIKE '%W%'
      AND (
          a."수주유형" LIKE 'Bulk Order - for HIMSEN(Spare)'
          OR a."수주유형" LIKE 'Bulk Order - without HIMSEN(Spare)'
          OR a."수주유형" LIKE '%General Spare%'
      )
      AND a."수주일자" BETWEEN '2021-01-01' AND '2024-12-31'
),

-- All materials ever shipped from NL revolving stock
nl_revolving_parts AS (
    SELECT DISTINCT "U Code", "자재번호", "소분류 (대)"
    FROM "납품현황_정제_분류_완료_final"
    WHERE
        "Stock 구분" = '리볼빙'
        AND "수통번호" NOT LIKE '%X%'
        AND "수통번호" NOT LIKE '%W%'
        AND (
            "수주유형" LIKE 'Bulk Order - for HIMSEN(Spare)'
            OR "수주유형" LIKE 'Bulk Order - without HIMSEN(Spare)'
            OR "수주유형" LIKE '%General Spare%'
        )
        AND "수주일자" BETWEEN '2021-01-01' AND '2024-12-31'
)

-- Cross-reference: flag NL stock status for each SPLIT/KR material
SELECT DISTINCT
    s."U Code",
    s."자재번호",
    s."소분류 (대)",
    CASE
        WHEN r."U Code" IS NOT NULL THEN 'ALREADY IN NL STOCK'
        ELSE 'NOT IN NL STOCK'
    END AS nl_stock_status
FROM split_kr_materials s
LEFT JOIN nl_revolving_parts r
    ON COALESCE(s."U Code", s."자재번호") = COALESCE(r."U Code", r."자재번호")
   AND s."소분류 (대)" = r."소분류 (대)";
