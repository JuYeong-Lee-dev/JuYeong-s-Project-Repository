"""
Step 3: Generate a formatted Excel report of slow-moving stock items (≥ USD 500)
present in today's quote file.

Filters for items classified as 'Excess' or 'Malignity' inventory,
excludes items tied to construction orders, and outputs a styled Excel report
ready for team distribution.
"""

import pandas as pd
import warnings

warnings.filterwarnings("ignore")

# ── Configuration ────────────────────────────────────────────────────────────
QUOTE_FILE  = "daily_quote.xlsx"          # Today's quote export (with 부진재고 column)
MIN_VALUE_USD = 500
# ─────────────────────────────────────────────────────────────────────────────

output_file = f"{QUOTE_FILE.replace('.xlsx', '')}_slow_moving_report.xlsx"

df = pd.read_excel(QUOTE_FILE)

# Filter: Excess or Malignity inventory, no construction order attached, value >= threshold
filtered_df = df[df["부진재고"].isin(["Excess", "Malignity"])]
filtered_df = filtered_df[(filtered_df["공사번호"].isna()) | (filtered_df["공사번호"] == "")]
filtered_df = filtered_df[filtered_df["USD환산금액"] >= MIN_VALUE_USD]

output_columns = [
    "HMS-HQ QTN. NO", "거래선", "견적회신일", "품명", "U-CODE",
    "구매단가", "수량", "견적단가", "견적금액", "팀", "담당자"
]
final_df = filtered_df[output_columns]

# ── Excel formatting ──────────────────────────────────────────────────────────
with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
    final_df.to_excel(writer, index=False, sheet_name="Sheet1")

    wb  = writer.book
    ws  = writer.sheets["Sheet1"]

    header_fmt = wb.add_format({
        "bold": True, "align": "center", "valign": "vcenter",
        "fg_color": "#B8CCE4", "border": 1
    })
    center_fmt = wb.add_format({"align": "center", "valign": "vcenter", "border": 1})
    num_fmt    = wb.add_format({
        "align": "center", "valign": "vcenter", "border": 1, "num_format": "#,##0"
    })
    highlight_fmt = wb.add_format({
        "align": "center", "valign": "vcenter", "border": 1,
        "fg_color": "#FDE9D9", "num_format": "#,##0"
    })

    for col_num, col_name in enumerate(final_df.columns):
        ws.write(0, col_num, col_name, header_fmt)

    ws.set_column("A:A", 15, center_fmt)
    ws.set_column("B:B", 25, center_fmt)
    ws.set_column("C:C", 12, center_fmt)
    ws.set_column("D:D", 40, center_fmt)
    ws.set_column("E:E", 15, center_fmt)
    ws.set_column("F:F", 12, num_fmt)
    ws.set_column("G:G", 10, highlight_fmt)
    ws.set_column("H:H", 12, num_fmt)
    ws.set_column("I:I", 15, highlight_fmt)
    ws.set_column("J:K", 15, center_fmt)

print(f"[✓] {len(final_df)} item(s) → {output_file}")
