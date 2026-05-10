"""
Step 1: Detect vessels in today's quote file where slow-moving stock can be applied.

For each vessel with a total quoted value >= USD 10,000, the script checks whether
any quoted items (by U-CODE) overlap with the slow-moving stock list.
Outputs a summary Excel file flagging matched and potential matches.
"""

import pandas as pd
import os

# ── Configuration ────────────────────────────────────────────────────────────
SLOW_MOVING_STOCK_FILE = "slow_moving_stock_list.xlsx"   # Update to your file path
QUOTE_FILE             = "daily_quote.xlsx"              # Today's quote export
THRESHOLD_USD          = 10_000                          # Minimum vessel quote value
# ─────────────────────────────────────────────────────────────────────────────

slow_moving_df = pd.read_excel(SLOW_MOVING_STOCK_FILE)
quote_df       = pd.read_excel(QUOTE_FILE)

output_file = f"{os.path.splitext(QUOTE_FILE)[0]}_detection.xlsx"


def detect(quote_df, slow_moving_df, output_file, threshold=THRESHOLD_USD):
    """
    For each vessel exceeding the USD threshold in today's quotes,
    check whether any quoted U-CODEs appear in the slow-moving stock list.

    Output columns:
      - Vessel No., total quote value (USD), match flag
      - If matched   → U-CODE(s), part name(s), unit price(s) of matched items
      - If unmatched → all applicable slow-moving items for that vessel
    """
    results = []

    # Aggregate total quote value per vessel
    vessel_totals = quote_df.groupby("호선번호")["USD환산금액"].sum().reset_index()
    qualified_vessels = vessel_totals.loc[
        vessel_totals["USD환산금액"] >= threshold, "호선번호"
    ]

    for vessel in qualified_vessels:
        # Slow-moving items applicable to this vessel
        applicable = slow_moving_df.loc[
            slow_moving_df["적용 호선"] == vessel, ["U-CODE", "품명", "단가"]
        ]
        if applicable.empty:
            continue

        applicable_map = {
            row["U-CODE"]: (row["품명"], row["단가"])
            for _, row in applicable.iterrows()
        }

        # U-CODEs present in today's quote for this vessel
        quoted_ucodes  = quote_df.loc[quote_df["호선번호"] == vessel, "U-CODE"].unique()
        matched_ucodes = [u for u in quoted_ucodes if u in applicable_map]
        match_flag     = "MATCHED" if matched_ucodes else "APPLICABLE — NOT QUOTED"

        total_value = vessel_totals.loc[
            vessel_totals["호선번호"] == vessel, "USD환산금액"
        ].values[0]

        row = {
            "Vessel No.":              vessel,
            "Total Quote Value (USD)": total_value,
            "Slow-Moving Stock Match": match_flag,
        }

        if matched_ucodes:
            for i, ucode in enumerate(matched_ucodes, start=1):
                part_name, unit_price = applicable_map[ucode]
                row[f"Matched U-CODE_{i}"]      = ucode
                row[f"Matched Part Name_{i}"]   = part_name
                row[f"Matched Unit Price (USD)_{i}"] = unit_price
        else:
            for i, (ucode, (part_name, unit_price)) in enumerate(applicable_map.items(), start=1):
                row[f"Applicable U-CODE_{i}"]      = ucode
                row[f"Applicable Part Name_{i}"]   = part_name
                row[f"Applicable Unit Price (USD)_{i}"] = unit_price

        results.append(row)

    result_df = pd.DataFrame(results)

    if not result_df.empty:
        result_df.to_excel(output_file, index=False)
        print(f"[✓] {len(result_df)} vessel(s) flagged → {output_file}")
    else:
        print("[–] No applicable vessels found in today's quotes.")

    return result_df


detect(quote_df, slow_moving_df, output_file)
