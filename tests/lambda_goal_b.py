"""Goal B on the deployed Lambda, via `aws lambda invoke`. Saves payloads/responses as evidence."""
import json
import os
import subprocess

FN = "multi-agent-orchestrator"
OUT = "evidence/goalB_lambda"
os.makedirs(OUT, exist_ok=True)
checks = []


def check(label, ok, show=None):
    ok = bool(ok)
    checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok and show is not None:  # on failure, print what the Lambda actually returned
        text = json.dumps(show, indent=2)
        print("   response:", text[:1500])


def invoke(name, body):
    pay, resp = f"{OUT}/{name}-payload.json", f"{OUT}/{name}-response.json"
    json.dump({"body": json.dumps(body)}, open(pay, "w"))
    subprocess.run(["aws", "lambda", "invoke", "--function-name", FN, "--payload", f"fileb://{pay}",
                    "--cli-read-timeout", "150", resp], check=True, capture_output=True,
                   env={**os.environ, "AWS_MAX_ATTEMPTS": "1"})
    r = json.load(open(resp))
    return r["statusCode"], json.loads(r["body"])


# Normal question: no pause
code, b = invoke("normal", {"question": "How many active projects do we have?"})
check("normal: runs, no confirmation",
      code == 200 and not b.get("needs_confirmation") and b.get("sql_validation") == "PASSED", b)

# Flagged, then tampered, then confirmed
code, flagged = invoke("flagged", {"question": "List every invoice"})
check("flagged: needs_confirmation with SQL + reasons",
      code == 200 and flagged.get("needs_confirmation") and flagged.get("sql_query")
      and flagged.get("review_reasons"), flagged)

code, b = invoke("tampered", {"confirmation": {**flagged["confirmation"], "sql": "SELECT * FROM clients"}})
check("tampered SQL rejected (403)", code == 403, b)

code, b = invoke("confirmed", {"confirmation": flagged["confirmation"]})
check("confirmed: runs the flagged query only",
      code == 200 and not b.get("needs_confirmation")
      and b.get("sql_query") == flagged["sql_query"] and b.get("sql_validation") == "PASSED",
      {"status": code, "body": b, "flagged_sql": flagged["sql_query"]})

# Gold: memory + confirmation through Lambda
code, t1 = invoke("gold-turn1", {"question": "How many active projects does Acme Corp have?"})
code, t2 = invoke("gold-turn2-flagged", {"question": "Show the consultants and invoices for their projects.",
                                         "history": t1["history"]})
check("gold: follow-up flagged", t2.get("needs_confirmation"), t2)
check("gold: flagged SQL reflects Acme", "acme" in (t2.get("sql_query") or "").lower(), t2)

code, t3 = invoke("gold-turn3-confirmed", {"confirmation": t2["confirmation"], "history": t1["history"]})
check("gold: confirmation runs exactly that SQL",
      code == 200 and t3.get("sql_query") == t2.get("sql_query"),
      {"status": code, "body": t3, "flagged_sql": t2.get("sql_query")})
check("gold: history now has both turns", len(t3.get("history", [])) == 2, t3)

print(f"{sum(checks)}/{len(checks)} passed")