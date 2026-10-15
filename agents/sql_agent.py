"""
agents/sql_agent.py -- validated SQL agent.
execute_query() is the ONLY function that opens a database connection, and its
first action is validate_sql(), so no path to RDS skips the validator.
"""
import os
import re
import psycopg2
from dotenv import load_dotenv
from agents.sql_validator import validate_sql
from tokenomics_logger import call_claude, sum_usage

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"), override=True)  # no-op on Lambda (no .env there)

SCHEMA_CONTEXT = """
Tables available:
- clients(id, name, industry, region, contract_value, created_date)
  - region is one of: 'North', 'South', 'East', 'West'
  - contract_value is in USD. It is the client's total contract value, one value per client.
    "Contract value" always means clients.contract_value.
- projects(id, client_id, name, status, start_date, end_date, budget)
  - status is one of: 'active', 'completed', 'on-hold'
  - budget is in USD. It is a per-project budget, not a contract value.
    Never sum budgets to answer a contract-value question.
  - client_id references clients.id
  - start_date is when the project began. No column records when a project went on hold.
- consultants(id, name, grade, specialisation, project_id, billable_hours)
  - grade is one of: 'Analyst', 'Senior', 'Manager', 'Director'
  - project_id references projects.id
- invoices(id, project_id, amount, status, due_date, paid_date)
  - status is one of: 'paid', 'pending', 'overdue'
  - an invoice is overdue only if status = 'overdue'. Never decide overdue or unpaid by comparing due_date to CURRENT_DATE.
  - amount is in USD
  - project_id references projects.id
All dates are in ISO 8601 format (YYYY-MM-DD).
"""

CANNOT_ANSWER = "CANNOT_ANSWER"
_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE)


def _history_block(history: list | None) -> str:
    if not history:
        return ""
    turns = "\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in history)
    return f"Conversation so far:\n{turns}\n\n"


def generate_sql(question: str, history: list | None = None) -> tuple[str, dict]:
    prompt = (
        f"{SCHEMA_CONTEXT}\n\n{_history_block(history)}"
        f"Generate a PostgreSQL query to answer: {question}\n\n"
        "Use ILIKE when matching client, project or consultant names. "
        f"If these tables cannot answer the question, return exactly {CANNOT_ANSWER}. "
        "Return ONLY the SQL query. No explanation, no markdown, no backticks."
    )
    text, usage = call_claude(prompt, "sql_generation", max_tokens=512, temperature=0)
    return _FENCE_RE.sub("", text.strip()).strip(), usage


def _connect():
    return psycopg2.connect(
        host=os.environ["RDS_HOST"], port=int(os.getenv("RDS_PORT", "5432")),
        dbname=os.environ["RDS_DATABASE"], user=os.environ["RDS_USER"],
        password=os.environ["RDS_PASSWORD"], sslmode="require",
        connect_timeout=10, options="-c statement_timeout=5000",
    )


def execute_query(sql: str) -> dict:
    """The only database entry point. Validation always runs first."""
    validation = validate_sql(sql)
    if not validation["valid"]:
        return {"success": False, "validation": validation, "error": validation["reason"]}
    conn = None
    try:
        conn = _connect()
        conn.set_session(readonly=True)  # defence in depth: the DB itself refuses writes
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(50)
        return {"success": True, "validation": validation, "columns": columns, "rows": rows}
    except psycopg2.Error as e:
        return {"success": False, "validation": validation, "error": str(e).strip()}
    finally:
        if conn:
            conn.close()


def interpret_results(question: str, sql: str, result: dict) -> tuple[str, dict]:
    prompt = (
        f"Question: {question}\nSQL used: {sql}\nColumns: {result['columns']}\n"
        f"Rows: {result['rows'][:20]}\n\n"
        "Answer the question concisely using ONLY this data, in plain text: at most 3 sentences or a short bullet list, no tables or emoji. Describe each column only as its name says (start_date is when a project began); never infer dates or events the data does not record. "
        "If there are no rows, say no matching records were found."
    )
    return call_claude(prompt, "sql_interpretation", max_tokens=400)


def _result(success, answer, sql, validation, reason, row_count, calls) -> dict:
    return {
        "success": success, "answer": answer, "sources": [sql] if sql else [],
        "metadata": {"validation": validation, "validation_reason": reason,
                     "row_count": row_count, "token_usage": sum_usage(calls), "calls": calls},
    }


def run_sql_agent(question: str, history: list | None = None) -> dict:
    sql, gen_usage = generate_sql(question, history)
    calls = [gen_usage]
    if sql.upper() == CANNOT_ANSWER:
        return _result(False, "The database does not contain information that answers this question.",
                       None, "NOT_RUN", "Model reported the schema cannot answer this.", 0, calls)

    result = execute_query(sql)
    status = "PASSED" if result["validation"]["valid"] else "BLOCKED"
    if not result["success"]:
        prefix = "Query blocked by validation" if status == "BLOCKED" else "Query failed"
        return _result(False, f"{prefix}: {result['error']}", sql, status,
                       result["validation"]["reason"], 0, calls)

    answer, interp_usage = interpret_results(question, sql, result)
    calls.append(interp_usage)
    return _result(True, answer, sql, status, "OK", len(result["rows"]), calls)
