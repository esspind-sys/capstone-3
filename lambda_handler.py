"""lambda_handler.py -- wraps the orchestrator in the format Lambda expects.
Lambda keeps no memory between invocations, so the caller carries the conversation:
send "history" (a list of {question, answer}) in the body and get the updated list back."""
import json
from orchestrator import build_orchestrator, MAX_HISTORY_TURNS
from tokenomics_logger import run_traced_query

orchestrator = build_orchestrator()


def _bad_request(msg: str) -> dict:
    return {"statusCode": 400, "body": json.dumps({"error": msg})}


def _clean_history(raw) -> list:
    """Accept only a list of {question: str, answer: str}; keep the last MAX_HISTORY_TURNS."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(
            isinstance(t, dict) and isinstance(t.get("question"), str) and isinstance(t.get("answer"), str)
            for t in raw):
        raise ValueError("history must be a list of {question, answer} strings")
    return [{"question": t["question"], "answer": t["answer"]} for t in raw][-MAX_HISTORY_TURNS:]


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
        question = str(body.get("question", "")).strip()
        if not question:
            return _bad_request("question is required")
        try:
            history = _clean_history(body.get("history"))
        except ValueError as e:
            return _bad_request(str(e))

        result = run_traced_query(orchestrator, question, history or None)

        sql = result.get("sql_result") or {}
        turn = {"question": question, "answer": result["final_answer"]}
        return {"statusCode": 200, "body": json.dumps({
            "answer": result["final_answer"],
            "route": result["route"],
            "sql_validation": sql.get("metadata", {}).get("validation"),
            "sql_query": (sql.get("sources") or [None])[0],
            "token_usage": result.get("token_usage", {}),
            "history": (history + [turn])[-MAX_HISTORY_TURNS:],
        })}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
