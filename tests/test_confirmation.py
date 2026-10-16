"""Offline tests for Stretch Goal B: unusual-query review and signed confirmations.
No AWS, RDS or Bedrock needed."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.sql_review import review_sql
from confirmation import make_confirmation, verify_confirmation, TTL_SECONDS

PLAN = {"route": "sql", "sql_question": "List every invoice"}
checks = []


def check(label, ok):
    checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")


def rejected(conf, now=None):
    try:
        verify_confirmation(conf, now)
        return False
    except ValueError:
        return True


# --- review_sql: what counts as unusual ---
check("SELECT * with no WHERE/LIMIT is flagged", review_sql("SELECT * FROM invoices")["unusual"])
check("4-table join is flagged", review_sql(
    "SELECT 1 FROM a JOIN b ON 1=1 JOIN c ON 1=1 JOIN d ON 1=1 WHERE a.x = 1")["unusual"])
check("filtered query is routine", not review_sql("SELECT * FROM projects WHERE status = 'active'")["unusual"])
check("LIMIT makes it routine", not review_sql("SELECT * FROM clients ORDER BY contract_value DESC LIMIT 1")["unusual"])
check("bare COUNT(*) is routine", not review_sql("SELECT COUNT(*) FROM consultants")["unusual"])
check("3-table join with WHERE is routine", not review_sql(
    "SELECT i.id FROM invoices i JOIN projects p ON i.project_id = p.id "
    "JOIN clients c ON p.client_id = c.id WHERE i.status = 'overdue'")["unusual"])
check("'WHERE' inside a literal does not count", review_sql("SELECT 'WHERE' FROM clients")["unusual"])

# --- confirmation tokens: only the exact flagged query can run ---
conf = make_confirmation("List every invoice", "SELECT * FROM invoices", PLAN, now=1000)
check("untouched confirmation verifies", verify_confirmation(conf, now=1001)["sql"] == "SELECT * FROM invoices")
check("altered SQL is rejected", rejected({**conf, "sql": "SELECT * FROM clients"}, 1001))
check("altered question is rejected", rejected({**conf, "question": "something else"}, 1001))
check("altered plan is rejected", rejected({**conf, "plan": {"route": "both"}}, 1001))
check("forged token is rejected", rejected({**conf, "token": "0" * 64}, 1001))
check("missing token is rejected", rejected({k: v for k, v in conf.items() if k != "token"}, 1001))
check("expired confirmation is rejected", rejected(conf, 1000 + TTL_SECONDS + 1))
check("extended expiry is rejected", rejected({**conf, "exp": conf["exp"] + 9999}, 1001))

print(f"{sum(checks)}/{len(checks)} passed")
sys.exit(0 if all(checks) else 1)