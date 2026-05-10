import pandas as pd
import warnings
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

warnings.filterwarnings('ignore')

load_dotenv()


# ── Configuration ─────────────────────────────────────────────────────────────

FILE_DATE = "260211"   # ← Change this to today's date (YYMMDD)

INPUT_DIR  = os.getenv("INPUT_DIR",  "input")   # folder containing the daily ERP export
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")  # folder for generated reports

INPUT_FILE  = os.path.join(INPUT_DIR,  f"{FILE_DATE}_공사진행.xlsx")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{FILE_DATE}_detail_report.xlsx")

DB_URL     = os.environ["DB_URL"]
TABLE_NAME = FILE_DATE


# ── Setup ─────────────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Pipeline ──────────────────────────────────────────────────────────────────

try:
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        print("Database connection established.")

        print(f"Reading input file: {INPUT_FILE}")
        df = pd.read_excel(INPUT_FILE)
        print(f"  → {len(df):,} rows loaded.")

        df.to_sql(TABLE_NAME, engine, if_exists="replace", index=False)
        print(f"  → Written to table: {TABLE_NAME}")

        query = text(f"""
        WITH "Caution_needed" AS (
            -- Orders where NL stock covers a meaningful share of order value:
            --   ≥50% for HD spare orders (RKB prefix), ≥30% for main engine spares
            SELECT
                "HMS-EU Order No",
                SUM("Unnamed: 27"::NUMERIC) AS "Total Sales",
                'EXB' AS "납품조건"
            FROM "{TABLE_NAME}"
            WHERE
                "HMS-EU Order No" IS NOT NULL
                AND "HMS-EU Order No" NOT LIKE '%X%'
                AND "수주유형"      NOT LIKE '%Repair%'
                AND "담당자"        NOT LIKE '%Tech%'
            GROUP BY "HMS-EU Order No"
            HAVING
                -- Minimum order value threshold
                SUM("Unnamed: 27"::NUMERIC) >= 5000

                -- All lines must be EXB delivery (NL-fulfillable)
                AND COUNT(CASE WHEN "납품조건" != 'EXB' THEN 1 END) = 0

                -- NL stock value must cover the required threshold
                AND SUM(
                    CASE WHEN "Stock"::NUMERIC > "수주"::NUMERIC
                         THEN "Unnamed: 27"::NUMERIC
                         ELSE 0
                    END
                ) >= SUM("Unnamed: 27"::NUMERIC) * (
                    CASE
                        WHEN "HMS-EU Order No" LIKE 'RKB%' THEN 0.5  -- HD spares: 50%
                        ELSE 0.3                                      -- Main engine: 30%
                    END
                )
        ),
        "Special_Case" AS (
            -- Critical component orders: always flagged regardless of value thresholds
            SELECT "HMS-EU Order No"
            FROM "{TABLE_NAME}"
            WHERE "U-CODE" = 'U17H2100000'
              AND "납품조건" = 'EXB'
        )

        SELECT
            "HMS-EU Order No",
            "거래선",
            "Unnamed: 5"     AS "Customer Name",
            "호선번호",
            "호선명",
            "Description",
            "U-CODE",
            "Stock",
            "납품조건",
            "수주유형",
            "수주",
            "Unnamed: 27"    AS "Amount",
            "POR No",
            "담당자"
        FROM "{TABLE_NAME}"
        WHERE
            "HMS-EU Order No" IN (SELECT "HMS-EU Order No" FROM "Caution_needed")
            OR "HMS-EU Order No" IN (SELECT "HMS-EU Order No" FROM "Special_Case")
        ORDER BY "HMS-EU Order No" DESC
        """)

        result_df = pd.read_sql_query(query, engine)
        print(f"  → {len(result_df):,} rows matched.")

        result_df.to_excel(OUTPUT_FILE, index=False)
        print(f"\nDetail report saved: {OUTPUT_FILE}")

except FileNotFoundError:
    print(f"\n[ERROR] Input file not found: {INPUT_FILE}")
except KeyError:
    print("\n[ERROR] DB_URL not set. Copy .env.example to .env and fill in your credentials.")
except Exception as e:
    print(f"\n[ERROR] {e}")
