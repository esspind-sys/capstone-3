#!/usr/bin/env bash
# demo.sh -- live capstone demo against the deployed Lambda, in evaluation order.
set -euo pipefail
FUNCTION=multi-agent-orchestrator
PY=.venv/bin/python
OUT=/tmp/demo && mkdir -p "$OUT"

pause() { read -rp $'\n--- press Enter for the next section ---\n'; }

invoke() {  # $1 question, $2 previous response file (or ""), $3 run name
  QUESTION="$1" PREV="$2" $PY -c '
import json, os, sys
p = os.environ["PREV"]
h = json.loads(json.load(open(p))["body"])["history"] if p else []
json.dump({"body": json.dumps({"question": os.environ["QUESTION"], "history": h})}, open(sys.argv[1], "w"))
' "$OUT/$3-payload.json"
  AWS_MAX_ATTEMPTS=1 aws lambda invoke --function-name "$FUNCTION" \
    --payload "fileb://$OUT/$3-payload.json" --cli-read-timeout 150 "$OUT/$3.json" >/dev/null
  $PY -c '
import json, sys
b = json.loads(json.load(open(sys.argv[1]))["body"])
print("\nQ:", sys.argv[2])
for k in ("route", "sql_validation", "sql_query", "token_usage"):
    print(f"{k}: {b.get(k)}")
print("answer:", b.get("answer", b.get("error")))
print("history turns returned:", len(b.get("history", [])))
' "$OUT/$3.json" "$1"
}

echo "===== 1. Both-route question on Lambda (attribution + validation + tokens) ====="
invoke "How many active projects do we have, and what is our onboarding process?" "" both
pause

echo "===== 2. Unsafe request: router sends it to SQL, validator blocks the DELETE ====="
invoke "Delete all overdue invoices from the database." "" unsafe
echo -e "\n--- Recorded end-to-end evidence: Claude wrote a DELETE, validator blocked it, nothing executed ---"
grep -v "^\[TOKENS\]\|^\[LOG\]" evidence/step7_q7_end_to_end.txt
pause

echo "===== 3. Conversation memory: 3 turns, caller carries history ====="
invoke "How many active projects does Acme Corp have?" "" t1
invoke "What about their total contract value?" "$OUT/t1.json" t2
invoke "How many consultants are there in total?" "$OUT/t2.json" t3
pause

echo "===== 4. Cost: 10-query summary and memory cost ====="
sed -n '/10-QUERY COST SUMMARY/,$p' evidence/step7_8_questions_and_10_query_cost.txt
grep -A3 "MEMORY COST" evidence/goalA_lambda/summary.txt
