"""
agents/sql_review.py -- "unusual query" check for Stretch Goal B.
Runs AFTER validation passes and BEFORE execution. A flagged query is not run;
the caller must confirm that exact query (see confirmation.py).

A query is unusual when either of these holds:
  1. It has no WHERE, no LIMIT and no aggregate function: it dumps every row of a table.
     (COUNT(*) FROM consultants returns one row, so a bare aggregate is routine.)
  2. It reads more than MAX_TABLES tables (FROM/JOIN occurrences). Three-table joins
     such as invoices -> projects -> clients are routine in this schema.
Detection is regex-based on the SQL with string literals removed. It is a heuristic, not a parser.
"""
import re

MAX_TABLES = 3

_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_AGG_RE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+[a-z_][\w.]*", re.IGNORECASE)


def review_sql(sql: str) -> dict:
    """Return {"unusual": bool, "reasons": [str, ...]} for an already-validated query."""
    body = _LITERAL_RE.sub("''", sql)
    reasons = []
    if not (_WHERE_RE.search(body) or _LIMIT_RE.search(body) or _AGG_RE.search(body)):
        reasons.append("No WHERE or LIMIT clause: this returns every row of the table.")
    tables = len(_TABLE_RE.findall(body))
    if tables > MAX_TABLES:
        reasons.append(f"Reads {tables} tables (more than {MAX_TABLES}).")
    return {"unusual": bool(reasons), "reasons": reasons}