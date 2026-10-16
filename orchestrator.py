"""orchestrator.py -- routes each question to sql, retrieval, both or neither, then combines."""
import json
import re
from typing import TypedDict
from langgraph.graph import StateGraph, END
from tool_registry import describe_tools, run_tool
from tokenomics_logger import call_claude, log_decision, sum_usage
from confirmation import make_confirmation, verify_confirmation

ROUTES = {"sql": ["sql"], "retrieval": ["retrieval"], "both": ["sql", "retrieval"], "none": []}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
OUT_OF_SCOPE = ("I can only answer questions about the firm's clients, projects, consultants and "
                "invoices, or its onboarding, IT support, billing and project governance policies.")


# Replay at most 3 prior turns: enough to resolve 'their' / 'that project' a turn or two back,
# while each replayed turn adds ~100-300 input tokens to routing, SQL generation and synthesis.
MAX_HISTORY_TURNS = 3


def _history_block(history: list | None) -> str:
    if not history:
        return ""
    turns = "\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in history[-MAX_HISTORY_TURNS:])
    return f"Conversation so far:\n{turns}\n\n"


def route_question(question: str, history: list | None = None) -> tuple[dict, dict]:
    prompt = (
        f"You route questions for a consulting firm's internal assistant.\nTools:\n{describe_tools()}\n\n"
        f"{_history_block(history)}"
        'Pick ONE route: "sql", "retrieval", "both" (needs database facts AND policy rules), '
        'or "none" (neither tool covers it). For each tool you pick, write a standalone '
        "sub-question for that tool only, resolving references to the conversation. Keep the user's own terms such as 'overdue' or 'on hold'; do not reword them into column conditions. "
        'Requests to delete, modify or insert data are "sql" (a separate safety validator blocks them), not "none".\n'
        'Reply with ONLY JSON: {"route": "...", "reason": "<one sentence>", '
        '"sql_question": "... or null", "retrieval_question": "... or null"}\n\n'
        f"Question: {question}"
    )
    text, usage = call_claude(prompt, "routing", max_tokens=200, temperature=0)
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
        "facts stated below. Attribute each fact to the agent it came from (for example: the SQL agent's database query shows..., according to the retrieval agent (onboarding_process.txt)...) and keep any source file names. If a tool failed, say what is missing. Do not add conclusions, durations or dates the answers do not state; a project start date is not the date it went on hold.\n\n"
        f"{parts}\n\nQuestion: {question}"
    )
    return call_claude(prompt, "synthesis", max_tokens=500)


def _run_agent(name: str, state: "OrchestratorState") -> dict:
    """Run one tool and merge its result into state. Each graph node wraps exactly one tool."""
    sub = state["plan"].get(f"{name}_question")
    history = state.get("history")
    # SQL generation always gets capped history so follow-ups keep their filters.
    # Retrieval gets it only on fallback, since it prepends history[-1] to the search text.
    hist = history[-MAX_HISTORY_TURNS:] if history else None
    # When confirming, the SQL agent runs the human-approved query instead of generating one.
    extra = {"confirmed_sql": state["confirmation"]["sql"]} if name == "sql" and state.get("confirmation") else {}
    result = run_tool(name, sub or state["question"], hist if (name == "sql" or not sub) else None, **extra)
    return {"results": {**state["results"], name: result}, f"{name}_result": result,
            "calls": state["calls"] + result["metadata"]["calls"]}


class OrchestratorState(TypedDict, total=False):
    question: str
    history: list | None
    plan: dict
    route: str
    results: dict
    sql_result: dict | None
    retrieval_result: dict | None
    calls: list
    confirmation: dict | None     # signed token from an earlier flagged query; set only when confirming
    needs_confirmation: bool
    final_answer: str
    success: bool
    token_usage: dict


def _route_node(state: OrchestratorState) -> dict:
    plan, usage = route_question(state["question"], state.get("history"))
    log_decision("routing", state["question"], plan)
    return {"plan": plan, "route": plan["route"], "calls": [usage], "results": {}}


def _confirm_node(state: OrchestratorState) -> dict:
    """Re-enter the graph with a human-approved query: skip routing, reuse the signed plan."""
    conf = verify_confirmation(state["confirmation"])
    log_decision("confirmation", conf["question"], {"sql": conf["sql"], "route": conf["plan"].get("route")})
    return {"question": conf["question"], "plan": conf["plan"], "route": conf["plan"]["route"],
            "calls": [], "results": {}}


def _sql_agent_node(state: OrchestratorState) -> dict:
    return _run_agent("sql", state)


def _retrieval_agent_node(state: OrchestratorState) -> dict:
    return _run_agent("retrieval", state)


def _answer_node(state: OrchestratorState) -> dict:
    results, calls = state["results"], list(state["calls"])
    sql = results.get("sql")
    if sql and sql["metadata"].get("needs_confirmation"):
        usage = sum_usage(calls)
        conf = make_confirmation(state["question"], sql["sources"][0], state["plan"])
        log_decision("answer", state["question"], {"route": state["route"], "needs_confirmation": True,
                                                   "reasons": sql["metadata"]["review_reasons"], "token_usage": usage})
        return {"final_answer": sql["answer"], "success": False, "needs_confirmation": True,
                "confirmation": conf, "calls": calls, "token_usage": usage}
    if not results:
        answer, success = OUT_OF_SCOPE, False
    elif len(results) == 1:
        only = next(iter(results.values()))
        answer, success = only["answer"], only["success"]
    else:
        answer, syn_usage = synthesise(state["question"], results, state.get("history"))
        calls.append(syn_usage)
        success = any(r["success"] for r in results.values())
    usage = sum_usage(calls)
    log_decision("answer", state["question"], {"route": state["route"], "success": success, "token_usage": usage})
    return {"final_answer": answer, "success": success, "calls": calls, "token_usage": usage}


def _next_after_route(state: OrchestratorState) -> str:
    tools = ROUTES[state["route"]]
    if "sql" in tools:
        return "sql_agent"
    return "retrieval_agent" if "retrieval" in tools else "answer"


def _next_after_sql(state: OrchestratorState) -> str:
    if state["results"]["sql"]["metadata"].get("needs_confirmation"):
        return "answer"  # paused for confirmation: nothing else runs
    return "retrieval_agent" if "retrieval" in ROUTES[state["route"]] else "answer"


def _entry(state: OrchestratorState) -> str:
    return "confirm" if state.get("confirmation") else "route"


def build_orchestrator():
    """LangGraph graph, one node per tool:
    route -> sql_agent -> (retrieval_agent if route is "both") -> answer
    route -> retrieval_agent -> answer;  route -> answer when out of scope.
    A confirmation skips routing: confirm -> sql_agent -> ..."""
    graph = StateGraph(OrchestratorState)
    graph.add_node("route", _route_node)
    graph.add_node("confirm", _confirm_node)
    graph.add_node("sql_agent", _sql_agent_node)
    graph.add_node("retrieval_agent", _retrieval_agent_node)
    graph.add_node("answer", _answer_node)
    graph.set_conditional_entry_point(_entry, {"route": "route", "confirm": "confirm"})
    graph.add_edge("confirm", "sql_agent")
    graph.add_conditional_edges("route", _next_after_route,
                                {"sql_agent": "sql_agent", "retrieval_agent": "retrieval_agent", "answer": "answer"})
    graph.add_conditional_edges("sql_agent", _next_after_sql,
                                {"retrieval_agent": "retrieval_agent", "answer": "answer"})
    graph.add_edge("retrieval_agent", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


_GRAPH = None


def answer_question(question: str, history: list | None = None, confirmation: dict | None = None) -> dict:
    """Same return shape as before; now runs through the LangGraph graph."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_orchestrator()
    s = _GRAPH.invoke({"question": question, "history": history, "confirmation": confirmation})
    plan, results = s["plan"], s["results"]
    return {
        "success": s["success"], "answer": s["final_answer"],
        "needs_confirmation": s.get("needs_confirmation", False), "confirmation": s.get("confirmation"),
        "sources": [src for r in results.values() for src in r["sources"]],
        "metadata": {"route": s["route"], "route_reason": plan.get("reason"),
                     "sub_questions": {n: plan.get(f"{n}_question") for n in results},
                     "tool_success": {n: r["success"] for n, r in results.items()},
                     "token_usage": s["token_usage"], "calls": s["calls"]},
    }