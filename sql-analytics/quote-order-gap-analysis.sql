-- ============================================================
-- Quote-to-Order Gap Analysis (2025)
-- ============================================================
-- Identifies vessel/material combinations where a quote was issued
-- in 2025 but no contract followed — representing missed conversion
-- opportunities.
--
-- Logic:
--   Step 1 (UncontractedPairs): find all [material category, vessel]
--          pairs that received a quote in 2025 but have no 2025
--          contract on record (set difference via EXCEPT).
--
--   Step 2: pull full quote detail for those pairs — aggregated by
--          quote date, vessel, customer, and material category —
--          including total contracted and quoted amounts, and
--          distinct quote/order counts for volume context.
--
-- Excludes internal HQ placeholder vessel (HOTHR999-NL).
-- Joined with vessel info table for vessel name lookup.
--
-- Output used to prioritise follow-up with customers who received
-- quotes but did not place orders.
-- ============================================================

WITH UncontractedPairs AS (
    -- Vessel/material pairs with a 2025 quote but no 2025 contract
    SELECT DISTINCT "소분류 (중)" AS material_sub_category, "Hull No."
    FROM 정제견적_인도일_포함
    WHERE "QTN Date" LIKE '2025-%'

    EXCEPT

    SELECT DISTINCT "소분류 (중)", "Hull No."
    FROM 정제견적_인도일_포함
    WHERE "Contract Date" LIKE '2025-%'
)

SELECT
    T1."QTN Date"                           AS quote_date,
    T1."선박인도일"                          AS vessel_delivery_date,
    Info."호선명"                            AS vessel_name,
    T1."Tech. Mangager"                     AS tech_manager,
    T1."제품구분"                            AS product_type,
    T1."소분류 (중)"                         AS material_sub_category,
    T1."Hull No."                           AS vessel_no,
    T1."Customer",
    SUM(T1."Contract Amount")               AS total_contracted_amount,
    SUM(T1."QTN Amount")                    AS total_quoted_amount,
    COUNT(DISTINCT T1."QTN No.")            AS quote_count,
    COUNT(DISTINCT T1."Sales Order No")     AS order_count
FROM 정제견적_인도일_포함 AS T1
JOIN UncontractedPairs AS T2
    ON (T1."소분류 (중)" = T2.material_sub_category
        OR (T1."소분류 (중)" IS NULL AND T2.material_sub_category IS NULL))
   AND (T1."Hull No." = T2."Hull No."
        OR (T1."Hull No." IS NULL AND T2."Hull No." IS NULL))
LEFT JOIN 호선정보모음 AS Info
    ON T1."Hull No." = Info."호선번호"
WHERE
    T1."QTN Date" LIKE '2025-%'
    AND T1."Hull No." != 'HOTHR999-NL'
GROUP BY
    T1."QTN Date",
    T1."선박인도일",
    Info."호선명",
    T1."Tech. Mangager",
    T1."제품구분",
    T1."소분류 (중)",
    T1."Hull No.",
    T1."Customer"
ORDER BY
    T1."Hull No.",
    T1."소분류 (중)",
    T1."Customer",
    T1."QTN Date";
