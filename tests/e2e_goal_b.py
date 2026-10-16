"""Goal B end-to-end, local: real Bedrock + RDS, no Lambda."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from orchestrator import answer_question
from confirmation import make_confirmation

checks = []


def check(label, ok, detail=""):
    checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")


# 1. Unusual query pauses and runs nothing
r1 = answer_question("List every invoice")
conf = r1["confirmation"]
check("flagged: needs_confirmation", r1["needs_confirmation"] and conf is not None)
check("flagged: nothing executed", r1["success"] is False and not r1["metadata"]["tool_success"].get("sql"))
print("   SQL:", conf["sql"], "\n   reasons:", r1["answer"].splitlines()[0])

# 2. Confirming runs exactly that query
r2 = answer_question(conf["question"], None, conf)
check("confirmed: executed", r2["success"] and not r2["needs_confirmation"])
check("confirmed: same SQL", r2["sources"] == [conf["sql"]])
print("   answer:", r2["answer"][:150])

# 3. Altered SQL is rejected
try:
    answer_question(conf["question"], None, {**conf, "sql": "SELECT * FROM clients"})
    check("tampered SQL rejected", False)
except ValueError as e:
    check("tampered SQL rejected", True, f"({e})")

# 4. Normal question is unaffected
r4 = answer_question("How many active projects do we have?")
check("normal question: no pause", r4["success"] and not r4["needs_confirmation"])

# 5. A signed-but-unsafe query is still blocked by the validator
bad = make_confirmation("x", "DROP TABLE invoices", {"route": "sql", "sql_question": "x"})
r5 = answer_question("x", None, bad)
check("confirmed unsafe SQL still blocked", not r5["success"] and "BLOCKED" in str(r5["metadata"]["tool_success"]) or
      "blocked" in r5["answer"].lower(), f"({r5['answer'][:80]})")

# 6. Gold: memory + confirmation together
t1 = answer_question("How many active projects does Acme Corp have?")
hist = [{"question": "How many active projects does Acme Corp have?", "answer": t1["answer"]}]
t2 = answer_question("Show the consultants and invoices for their projects.", hist)
print("   follow-up SQL:", (t2["confirmation"] or {}).get("sql"))
check("follow-up flagged", t2["needs_confirmation"])
check("flagged SQL reflects Acme context", "acme" in (t2["confirmation"]["sql"].lower()))
t3 = answer_question(t2["confirmation"]["question"], hist, t2["confirmation"])
check("confirming runs exactly that query", t3["success"] and t3["sources"] == [t2["confirmation"]["sql"]])

print(f"{sum(checks)}/{len(checks)} passed")