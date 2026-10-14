import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv("RDS_HOST"), port=int(os.getenv("RDS_PORT")),
    dbname=os.getenv("RDS_DATABASE"), user=os.getenv("RDS_USER"),
    password=os.getenv("RDS_PASSWORD"), sslmode="require", connect_timeout=10,
)
cur = conn.cursor()
for table in ["clients", "projects", "consultants", "invoices"]:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    cur.execute(f"SELECT * FROM {table} LIMIT 1")
    print(f"{table:<12} rows={count}  sample={cur.fetchone()}")
    assert count > 0, f"{table} is empty"
conn.close()
print("RDS CHECK PASSED: every table returns rows")
