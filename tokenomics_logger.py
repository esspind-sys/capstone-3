"""tokenomics_logger.py -- per-call token/cost logging and decision logging."""
import json
import os
import time
from datetime import datetime, timezone
from bedrock_client import invoke_claude

# Claude Sonnet 4.6 on Bedrock, USD per 1K tokens ($3 / $15 per million).
# Verify against https://aws.amazon.com/bedrock/pricing/ before submitting.
COST_PER_1K_INPUT = 0.003
COST_PER_1K_OUTPUT = 0.015

# Lambda's filesystem is read-only except /tmp.
LOG_PATH = "/tmp/agent_decisions.jsonl" if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else "agent_decisions.jsonl"


def token_cost(input_tokens: int, output_tokens: int) -> float:
    return round(input_tokens / 1000 * COST_PER_1K_INPUT + output_tokens / 1000 * COST_PER_1K_OUTPUT, 6)


def log_decision(stage: str, question: str, details: dict) -> None:
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "stage": stage,
             "question": question, "details": details}
    print(f"[LOG] {stage}: {json.dumps(details, default=str)}")
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def call_claude(prompt: str, component: str, max_tokens: int = 500,
                temperature: float | None = None) -> tuple[str, dict]:
    """Every Claude call goes through here so each one is logged with its cost."""
    r = invoke_claude(prompt, max_tokens, temperature)
    record = {"component": component, "input_tokens": r["input_tokens"],
              "output_tokens": r["output_tokens"],
              "cost_usd": token_cost(r["input_tokens"], r["output_tokens"])}
    print(f"[TOKENS] {json.dumps(record)}")
    return r["text"], record


def sum_usage(records: list[dict]) -> dict:
    inp = sum(r["input_tokens"] for r in records)
    out = sum(r["output_tokens"] for r in records)
    return {"input_tokens": inp, "output_tokens": out, "cost_usd": token_cost(inp, out)}


def run_traced_query(orchestrator, question: str, history: list | None = None,
                     confirmation: dict | None = None) -> dict:
    """Run one question through the compiled graph and log latency plus token usage."""
    start = time.perf_counter()
    state = orchestrator.invoke({"question": question, "history": history, "confirmation": confirmation})
    log_decision("trace", question, {"route": state.get("route"), "success": state.get("success"),
                                      "needs_confirmation": state.get("needs_confirmation", False),
                                      "elapsed_s": round(time.perf_counter() - start, 2),
                                      "token_usage": state.get("token_usage", {})})
    return state