"""lambda_handler.py -- wraps the orchestrator in the format Lambda expects.
Lambda keeps no memory between invocations, so the caller carries the conversation:
send "history" (a list of {question, answer}) in the body and get the updated list back.
Flagged queries come back with needs_confirmation + a signed "confirmation" object;
send that object back unchanged as "confirmation" to run exactly that query."""
import json
from orchestrator import build_orchestrator, MAX_HISTORY_TURNS
from tokenomics_logger import run_traced_query
from confirmation import verify_confirmation

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
        confirmation = body.get("confirmation")  # echo of the object returned with needs_confirmation
        question = str(body.get("question", "")).strip()
        if confirmation is not None:
            try:  # an edited query or plan is rejected before anything runs
                question = verify_confirmation(confirmation)["question"]
            except ValueError as e:
                return {"statusCode": 403, "body": json.dumps({"error": str(e)})}
        if not question:
            return _bad_request("question is required")
        try:
            history = _clean_history(body.get("history"))
        except ValueError as e:
            return _bad_request(str(e))

        result = run_traced_query(orchestrator, question, history or None, confirmation)

        sql = result.get("sql_result") or {}
        paused = bool(result.get("needs_confirmation"))
        # A paused question has no answer yet, so it is not added to the conversation.
        turn = [] if paused else [{"question": question, "answer": result["final_answer"]}]
        out = {
            "answer": result["final_answer"],
            "route": result["route"],
            "sql_validation": sql.get("metadata", {}).get("validation"),
            "sql_query": (sql.get("sources") or [None])[0],
            "token_usage": result.get("token_usage", {}),
            "history": (history + turn)[-MAX_HISTORY_TURNS:],
        }
        if paused:
            out.update({"needs_confirmation": True, "confirmation": result["confirmation"],
                        "review_reasons": sql["metadata"]["review_reasons"]})
        return {"statusCode": 200, "body": json.dumps(out)}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}