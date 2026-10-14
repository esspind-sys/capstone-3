import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.sql_validator import validate_sql

# (label, query, expected_valid, expected_check)
TEST_CASES = [
    ("REQ-1 valid SELECT", "SELECT name, contract_value FROM clients WHERE region = 'North'", True, "passed"),
    ("REQ-2 destructive", "DROP TABLE clients", False, "keyword"),
    ("REQ-3 blocked word in column", "SELECT id, deleted_at FROM projects", True, "passed"),
    ("REQ-4 stacked + keyword", "SELECT * FROM projects; DROP TABLE clients;", False, "keyword"),
    ("REQ-5 stacked, no keyword", "SELECT * FROM clients; SELECT * FROM invoices", False, "stacking"),
    ("delete", "DELETE FROM invoices", False, "keyword"),
    ("update", "UPDATE projects SET status = 'completed' WHERE status = 'active'", False, "keyword"),
    ("insert", "INSERT INTO invoices (amount) VALUES (100)", False, "keyword"),
    ("mixed case SELECT", "sElEcT COUNT(*) fRoM projects", True, "passed"),
    ("newline/tab evasion", "SELECT 1;\n\tdrop TABLE clients", False, "keyword"),
    ("SELECT INTO (write)", "SELECT name INTO backup_clients FROM clients", False, "keyword"),
    ("more substring cols", "SELECT is_deleted, last_updated FROM projects", True, "passed"),
    ("trailing semicolon", "SELECT * FROM clients;", True, "passed"),
    ("CTE allowed", "WITH a AS (SELECT * FROM projects WHERE status = 'active') SELECT COUNT(*) FROM a", True, "passed"),
    ("EXPLAIN ANALYZE runs query", "EXPLAIN ANALYZE SELECT * FROM clients", False, "statement_type"),
]

print("=" * 96)
print("SQL VALIDATOR TEST SUITE")
print("=" * 96)
failures = 0
for label, query, exp_valid, exp_check in TEST_CASES:
    r = validate_sql(query)
    ok = r["valid"] == exp_valid and r["check"] == exp_check
    failures += not ok
    shown = query.replace("\n", "\\n").replace("\t", "\\t")[:48]
    print(f"[{'PASS' if ok else 'FAIL'}] {label:<28} valid={str(r['valid']):<5} "
          f"check={r['check']:<14} | {shown}")
print("=" * 96)
print(f"{len(TEST_CASES) - failures}/{len(TEST_CASES)} passed")
sys.exit(1 if failures else 0)
