import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from orchestrator import answer_question

CASES = [
    ("sql", "How many active projects do we have?", None),
    ("retrieval", "What is the escalation process for critical IT tickets?", None),
    ("both", "Which invoices are overdue, and what does our billing policy say happens next?", None),
    ("both", "Which projects are on hold, and what does project governance require for them?", None),
    ("none", "What's the weather in London today?", None),
    ("sql", "Which of them has the biggest budget?",
     [{"question": "How many active projects do we have?", "answer": "There are 4 active projects."}]),
]

total, correct = 0.0, 0
for expected, q, history in CASES:
    r = answer_question(q, history)
    m = r["metadata"]
    correct += m["route"] == expected
    total += m["token_usage"]["cost_usd"]
    print("=" * 80)
    print(f"Q: {q}" + ("   (follow-up)" if history else ""))
    print(f"route: {m['route']} (expected {expected})  reason: {m['route_reason']}")
    print(f"sub-questions: {m['sub_questions']}")
    print(f"success: {r['success']}  tools: {m['tool_success']}  sources: {r['sources']}")
    print(f"calls: {[c['component'] for c in m['calls']]}  token_usage: {m['token_usage']}")
    print(f"answer: {r['answer']}")
print("=" * 80)
print(f"routing correct: {correct}/{len(CASES)}   total cost: ${total:.4f}")
