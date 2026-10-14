import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tool_registry import REQUIRED_KEYS, describe_tools, run_tool

CASES = [
    ("retrieval", "What is our onboarding process for new consultants?"),
    ("retrieval", "How quickly must a critical IT ticket be resolved, and who is it escalated to?"),
    ("retrieval", "What happens when an invoice is 30 days overdue?"),
    ("retrieval", "What is the CEO's favourite colour?"),
    ("sql", "How many consultants are at Manager grade?"),
]

print("REGISTERED TOOLS:\n" + describe_tools())
for tool, q in CASES:
    r = run_tool(tool, q)
    m = r["metadata"]
    print("=" * 80)
    print(f"[{tool}] Q: {q}")
    print(f"standard shape: {list(r.keys()) == REQUIRED_KEYS}  success: {r['success']}")
    if tool == "retrieval":
        print(f"reason: {m['reason']}  top_score: {m['top_score']}  min_score: {m['min_score']}")
        print(f"chunks used: {m['chunks']}")
    print(f"sources: {r['sources']}")
    print(f"answer: {r['answer']}")
    print(f"token_usage: {m['token_usage']}")
