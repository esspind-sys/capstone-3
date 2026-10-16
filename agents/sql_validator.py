"""
agents/sql_validator.py -- mechanical safety gate for Claude-generated SQL.
Independent checks: (0) no dollar-quoting, (1) whole-word blocked keywords,
(2) read-only statement type, (3) stacked statements. Keywords and ';' are checked
outside string literals. Check 3 runs on its own so two harmless-looking SELECTs
chained with ';' are still blocked.
"""
import re

BLOCKED_KEYWORDS = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
                    "EXEC", "EXECUTE", "GRANT", "REVOKE", "CREATE", "COPY",
                    "MERGE", "CALL", "INTO"]  # INTO: SELECT ... INTO creates a table

# \b = word boundary: matches DELETE but not deleted_at; works across newlines/tabs
_KEYWORD_RE = re.compile(r"\b(" + "|".join(BLOCKED_KEYWORDS) + r")\b", re.IGNORECASE)
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")  # quoted string literal; '' is an escaped quote
_ALLOWED_START_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def _blocked(reason: str, check: str) -> dict:
    return {"valid": False, "reason": f"Blocked: {reason}", "check": check}


def validate_sql(query: str) -> dict:
    """Must run before every database call -- no exceptions."""
    if not query or not query.strip():
        return _blocked("empty query.", "empty")

    # Dollar-quoting ($$...$$) could hide a statement from the literal stripping below.
    if "$" in query:
        return _blocked("dollar-quoted strings are not permitted.", "dollar_quote")

    # Check keywords and ';' outside string literals, so 'Update Co' or 'a;b' are not false positives.
    query = _LITERAL_RE.sub("''", query)

    match = _KEYWORD_RE.search(query)
    if match:
        return _blocked(f"'{match.group(1).upper()}' is not permitted. Only read-only "
                        "SELECT queries are allowed.", "keyword")

    if not _ALLOWED_START_RE.match(query):
        return _blocked("query must begin with SELECT or WITH.", "statement_type")

    body = query.strip()
    if body.endswith(";"):          # one trailing semicolon is fine
        body = body[:-1]
    if ";" in body:
        return _blocked("multiple statements detected (stacked query).", "stacking")

    return {"valid": True, "reason": "OK", "check": "passed"}