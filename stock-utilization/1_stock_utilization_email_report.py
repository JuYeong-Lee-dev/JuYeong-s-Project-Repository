import pandas as pd
import warnings
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

warnings.filterwarnings('ignore')

load_dotenv()


# ── Configuration ─────────────────────────────────────────────────────────────

FILE_DATE = "260216"   # ← Change this to today's date (YYMMDD)

INPUT_DIR  = os.getenv("INPUT_DIR",  "input")   # folder containing the daily ERP export
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")  # folder for generated reports

INPUT_FILE  = os.path.join(INPUT_DIR,  f"{FILE_DATE}_공사진행.xlsx")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{FILE_DATE}_email_summary.xlsx")

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
        -- Segment 1: Orders eligible by NL stock coverage threshold
        SELECT
            "HMS-EU Order No",
            "Unnamed: 5"                    AS "Customer Name",
            SUM("Unnamed: 27"::NUMERIC)     AS "Total Sales",
            'EXB'                           AS "납품조건",
            "담당자"
        FROM "{TABLE_NAME}"
        WHERE
            "HMS-EU Order No" IS NOT NULL
            AND "HMS-EU Order No" NOT LIKE '%X%'
            AND "수주유형"      NOT LIKE '%Repair%'
            AND "담당자"        NOT LIKE '%Tech%'
        GROUP BY "HMS-EU Order No", "Customer Name", "담당자"
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

        UNION

        -- Segment 2: Special case — critical component orders (U17H2100000, EXB)
        SELECT
            "HMS-EU Order No",
            "Unnamed: 5"                    AS "Customer Name",
            SUM("Unnamed: 27"::NUMERIC)     AS "Total Sales",
            'EXB'                           AS "납품조건",
            "담당자"
        FROM "{TABLE_NAME}"
        WHERE "HMS-EU Order No" IN (
            SELECT DISTINCT "HMS-EU Order No"
            FROM "{TABLE_NAME}"
            WHERE "U-CODE" = 'U17H2100000'
              AND "납품조건" = 'EXB'
        )
        GROUP BY "HMS-EU Order No", "Customer Name", "담당자"
        """)

        result_df = pd.read_sql_query(query, engine)
        print(f"  → {len(result_df):,} orders flagged.")

        result_df.to_excel(OUTPUT_FILE, index=False)
        print(f"\nEmail summary saved: {OUTPUT_FILE}")

except FileNotFoundError:
    print(f"\n[ERROR] Input file not found: {INPUT_FILE}")
except KeyError:
    print("\n[ERROR] DB_URL not set. Copy .env.example to .env and fill in your credentials.")
except Exception as e:
    print(f"\n[ERROR] {e}")
