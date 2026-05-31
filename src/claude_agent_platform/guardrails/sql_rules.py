"""Shared SQL guardrail rules (Hook + MCP)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import DML

BLOCKLIST_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
    "COPY",
    "CALL",
    "DO",
    "EXECUTE",
    "VACUUM",
    "SET",
    "RESET",
    "LOAD",
}

BLOCKLIST_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_write_file",
    "lo_import",
    "lo_export",
    "dblink",
}

MAX_SQL_LENGTH = 32 * 1024


@dataclass
class SqlValidationResult:
    ok: bool
    reason: str = ""
    normalized_sql: str = ""
    action: Literal["allow", "deny", "rewrite"] = "allow"


def _strip_comments(sql: str) -> str:
    return str(sqlparse.format(sql, strip_comments=True)).strip()


def _has_semicolon_outside_strings(sql: str) -> bool:
    cleaned = _strip_comments(sql)
    # Simple check: semicolon with content after
    parts = cleaned.split(";")
    parts = [p.strip() for p in parts if p.strip()]
    return len(parts) > 1


def _statement_root_type(stmt: Statement) -> str | None:
    for token in stmt.tokens:
        if token.ttype is DML:
            return token.value.upper()
        if token.value.upper() in ("SELECT", "WITH"):
            return token.value.upper()
    text = stmt.value.upper().lstrip()
    if text.startswith("WITH"):
        return "WITH"
    if text.startswith("SELECT"):
        return "SELECT"
    return None


def _contains_blocklist_keyword(sql: str) -> str | None:
    upper = sql.upper()
    for kw in BLOCKLIST_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return kw
    lower = sql.lower()
    for fn in BLOCKLIST_FUNCTIONS:
        if fn in lower:
            return fn
    return None


def _extract_limit(sql: str) -> int | None:
    match = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _inject_or_cap_limit(sql: str, max_rows: int) -> tuple[str, bool]:
    """Returns (sql, rewritten)."""
    limit = _extract_limit(sql)
    if limit is None:
        trimmed = sql.rstrip().rstrip(";")
        return f"{trimmed} LIMIT {max_rows}", True
    if limit > max_rows:
        return re.sub(r"\bLIMIT\s+\d+\b", f"LIMIT {max_rows}", sql, count=1, flags=re.IGNORECASE), True
    return sql, False


def validate_sql(sql: str, *, max_rows: int = 10000) -> SqlValidationResult:
    if not sql or not sql.strip():
        return SqlValidationResult(ok=False, reason="SQL must not be empty", action="deny")

    if len(sql) > MAX_SQL_LENGTH:
        return SqlValidationResult(
            ok=False, reason=f"SQL exceeds {MAX_SQL_LENGTH} characters", action="deny"
        )

    if _has_semicolon_outside_strings(sql):
        return SqlValidationResult(ok=False, reason="Only single statements allowed", action="deny")

    blocked = _contains_blocklist_keyword(sql)
    if blocked:
        return SqlValidationResult(
            ok=False, reason=f"Blocked keyword or function: {blocked}", action="deny"
        )

    parsed = sqlparse.parse(_strip_comments(sql))
    if not parsed or len(parsed) != 1:
        return SqlValidationResult(ok=False, reason="Could not parse SQL as single statement", action="deny")

    root = _statement_root_type(parsed[0])
    if root not in ("SELECT", "WITH"):
        return SqlValidationResult(
            ok=False, reason="Only SELECT / WITH ... SELECT allowed", action="deny"
        )

    normalized, rewritten = _inject_or_cap_limit(_strip_comments(sql), max_rows)
    action: Literal["allow", "deny", "rewrite"] = "rewrite" if rewritten else "allow"
    return SqlValidationResult(ok=True, normalized_sql=normalized, action=action)
