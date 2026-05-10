"""
Step 2: Pull full quote line-item detail for vessels flagged in Step 1.

Reads the detection output from Step 1, extracts the flagged vessel list,
and filters the full daily quote file to only those vessels.
Output is used for targeted follow-up and sales action.
"""

import pandas as pd
import os

# ── Configuration ────────────────────────────────────────────────────────────
QUOTE_FILE      = "daily_quote.xlsx"           # Same quote file used in Step 1
DETECTION_FILE  = "daily_quote_detection.xlsx" # Output from Step 1
# ─────────────────────────────────────────────────────────────────────────────

quote_df     = pd.read_excel(QUOTE_FILE)
detection_df = pd.read_excel(DETECTION_FILE)

# Extract flagged vessel numbers from Step 1 output
flagged_vessels = detection_df["Vessel No."].unique()

# Filter full quote data to flagged vessels only
targeted_df = quote_df[quote_df["호선번호"].isin(flagged_vessels)]

output_file = f"{os.path.splitext(QUOTE_FILE)[0]}_targeted_vessels.xlsx"
targeted_df.to_excel(output_file, index=False)

print(f"[✓] {len(flagged_vessels)} vessel(s) | {len(targeted_df)} line(s) → {output_file}")
