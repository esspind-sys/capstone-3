"""orchestrator.py -- routes each question to sql, retrieval, both or neither, then combines."""
import json
import re
from tool_registry import describe_tools, run_tool
from tokenomics_logger import call_claude, log_decision, sum_usage

ROUTES = {"sql": ["sql"], "retrieval": ["retrieval"], "both": ["sql", "retrieval"], "none": []}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
OUT_OF_SCOPE = ("I can only answer questions about the firm's clients, projects, consultants and "
                "invoices, or its onboarding, IT support, billing and project governance policies.")


def _history_block(history: list | None) -> str:
    if not history:
        return ""
    turns = "\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in history[-3:])
    return f"Conversation so far:\n{turns}\n\n"


def route_question(question: str, history: list | None = None) -> tuple[dict, dict]:
    prompt = (
        f"You route questions for a consulting firm's internal assistant.\nTools:\n{describe_tools()}\n\n"
        f"{_history_block(history)}"
        'Pick ONE route: "sql", "retrieval", "both" (needs database facts AND policy rules), '
        'or "none" (neither tool covers it). For each tool you pick, write a standalone '
        "sub-question for that tool only, resolving references to the conversation.\n"
        'Reply with ONLY JSON: {"route": "...", "reason": "<one sentence>", '
        '"sql_question": "... or null", "retrieval_question": "... or null"}\n\n'
        f"Question: {question}"
    )
    text, usage = call_claude(prompt, "routing", max_tokens=200)
    try:
        plan = json.loads(_JSON_RE.search(text).group(0))
        if plan.get("route") not in ROUTES:
            raise ValueError(f"unknown route {plan.get('route')!r}")
    except (AttributeError, ValueError) as e:
        plan = {"route": "both", "reason": f"Router output unusable ({e}); trying both tools."}
    return plan, usage


def synthesise(question: str, results: dict, history: list | None) -> tuple[str, dict]:
    parts = "\n\n".join(f"[{n} tool, success={r['success']}]\n{r['answer']}" for n, r in results.items())
    prompt = (
        f"{_history_block(history)}Combine these tool answers into one concise plain-text answer (under 150 words, no tables or emoji). Use only "
        "facts stated below and keep any source file names. If a tool failed, say what is missing.\n\n"
        f"{parts}\n\nQuestion: {question}"
    )
    return call_claude(prompt, "synthesis", max_tokens=500)


def _run_tools(plan: dict, question: str, history: list | None) -> dict:
    results = {}
    for name in ROUTES[plan["route"]]:
        sub = plan.get(f"{name}_question")
        # Standalone sub-questions need no history; the fallback path keeps it.
        results[name] = run_tool(name, sub or question, None if sub else history)
    return results


def answer_question(question: str, history: list | None = None) -> dict:
    plan, route_usage = route_question(question, history)
    log_decision("routing", question, plan)
    results = _run_tools(plan, question, history)
    calls = [route_usage] + [c for r in results.values() for c in r["metadata"]["calls"]]

    if not results:
        answer, success = OUT_OF_SCOPE, False
    elif len(results) == 1:
        only = next(iter(results.values()))
        answer, success = only["answer"], only["success"]
    else:
        answer, syn_usage = synthesise(question, results, history)
        calls.append(syn_usage)
        success = any(r["success"] for r in results.values())

    usage = sum_usage(calls)
    log_decision("answer", question, {"route": plan["route"], "success": success, "token_usage": usage})
    return {
        "success": success, "answer": answer,
        "sources": [s for r in results.values() for s in r["sources"]],
        "metadata": {"route": plan["route"], "route_reason": plan.get("reason"),
                     "tool_success": {n: r["success"] for n, r in results.items()},
                     "token_usage": usage, "calls": calls},
    }
