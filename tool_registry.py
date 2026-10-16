"""tool_registry.py -- single list of tools; enforces the standard output shape."""
from agents.sql_agent import run_sql_agent
from agents.retrieval_agent import run_retrieval_agent
from tokenomics_logger import sum_usage

REQUIRED_KEYS = ["success", "answer", "sources", "metadata"]

TOOLS = {
    "sql": {
        "function": run_sql_agent,
        "description": "The firm database: clients, projects, consultants and invoices. Use for "
                       "counts, totals, rankings, statuses, dates, budgets and billable hours. "
                       "Not for policies, procedures, rules or how-to questions.",
    },
    "retrieval": {
        "function": run_retrieval_agent,
        "description": "Firm policy and process documents: onboarding, IT support, invoice and "
                       "billing policy, project governance. Use for rules, procedures, deadlines "
                       "and escalation steps. Not for counts, totals or any specific client, "
                       "project, consultant or invoice figure.",
    },
}


def describe_tools() -> str:
    return "\n".join(f"- {name}: {t['description']}" for name, t in TOOLS.items())


def _error_result(message: str) -> dict:
    return {"success": False, "answer": message, "sources": [],
            "metadata": {"token_usage": sum_usage([]), "calls": []}}


def run_tool(name: str, question: str, history: list | None = None, **kwargs) -> dict:
    """kwargs (e.g. confirmed_sql for the SQL agent) are forwarded to the tool function."""
    if name not in TOOLS:
        result = _error_result(f"Unknown tool '{name}'.")
    else:
        try:
            result = TOOLS[name]["function"](question, history, **kwargs)
        except Exception as e:  # a crashing tool must not crash the orchestrator
            result = _error_result(f"{name} tool error: {e}")
    missing = [k for k in REQUIRED_KEYS if k not in result]
    if missing:
        raise ValueError(f"Tool '{name}' returned non-standard output; missing {missing}")
    result["metadata"]["tool"] = name
    return result