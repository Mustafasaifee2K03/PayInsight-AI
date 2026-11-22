"""SQL safety validation using the SQLGlot AST (defence layer 1 of 3).

Layers: (1) this AST validator, (2) a SQLite authorizer callback that only
permits SELECT/READ/FUNCTION actions, (3) a read-only (``mode=ro`` +
``PRAGMA query_only``) connection. Every statement — compiled or sandbox — passes
through all three before execution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ..database.schema import ANALYTICS_TABLES

MAX_SQL_LENGTH = 20_000
FORBIDDEN_NODE_NAMES = {
    "Insert", "Update", "Delete", "Drop", "Alter", "AlterTable", "Create", "Command", "Pragma", "Attach", "Detach",
    "Transaction", "Commit", "Rollback", "Merge", "Into", "Set", "Use", "Copy", "LoadData", "TruncateTable", "Analyze",
}
FORBIDDEN_FUNCTIONS = {
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "randomblob", "zeroblob", "sqlite_compileoption_get",
    "sqlite_compileoption_used", "sqlite_offset", "unlikely_sleep", "sleep",
}
FORBIDDEN_KEYWORDS = re.compile(r"\b(attach|detach|pragma|vacuum|reindex|load_extension)\b", re.IGNORECASE)
# Hardening iteration 1: resource-abuse guards.
MAX_NESTING_DEPTH = 64                     # parenthesis depth; deeper input crashed the recursive-descent parser
FORMAT_FUNCTIONS = {"printf", "format"}    # width/precision can allocate up to SQLITE_MAX_LENGTH (1 GB) in one call
MAX_FORMAT_WIDTH = 1_000
_FORMAT_SPEC = re.compile(r"%[-+ 0#,!]*(\*|\d+)?(?:\.(\*|\d+))?")


@dataclass
class ValidationResult:
    valid: bool
    sql: str
    tables: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    limit_applied: int | None = None

    def as_dict(self) -> dict:
        return {"valid": self.valid, "tables": self.tables, "reasons": self.reasons, "limit_applied": self.limit_applied}


def _strip_strings(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _max_depth(bare: str) -> int:
    depth = peak = 0
    for ch in bare:
        if ch == "(":
            depth += 1
            peak = max(peak, depth)
        elif ch == ")":
            depth -= 1
    return peak


def _format_problem(node: exp.Anonymous) -> str | None:
    """printf/format may only use a literal format string with small widths/precisions."""
    args = node.expressions
    fmt = args[0] if args else None
    if not (isinstance(fmt, exp.Literal) and fmt.is_string):
        return f"Function '{node.name}' requires a literal format string."
    for m in _FORMAT_SPEC.finditer(fmt.this):
        for part in m.groups():
            if part == "*" or (part and int(part) > MAX_FORMAT_WIDTH):
                return f"Function '{node.name}' width/precision must be a literal of at most {MAX_FORMAT_WIDTH}."
    return None


def validate_sql(sql: str, *, max_rows: int, enforce_limit: bool = True) -> ValidationResult:
    """Validation is a pure function of its inputs, so results are memoised (copies returned)."""
    r = _validate_cached(sql, max_rows, enforce_limit)
    return ValidationResult(r.valid, r.sql, list(r.tables), list(r.reasons), r.limit_applied)


@lru_cache(maxsize=1024)
def _validate_cached(sql: str, max_rows: int, enforce_limit: bool) -> ValidationResult:
    reasons: list[str] = []
    text = (sql or "").strip()
    if not text:
        return ValidationResult(False, sql, reasons=["Empty query."])
    if len(text) > MAX_SQL_LENGTH:
        return ValidationResult(False, sql, reasons=[f"Query exceeds {MAX_SQL_LENGTH} characters."])
    text = text.rstrip(";").strip()
    bare = _strip_strings(text)
    if ";" in bare:
        return ValidationResult(False, sql, reasons=["Multiple statements are not allowed (found ';' separating statements)."])
    if "--" in bare or "/*" in bare:
        return ValidationResult(False, sql, reasons=["SQL comments are not allowed in executed queries."])
    if FORBIDDEN_KEYWORDS.search(bare):
        kw = FORBIDDEN_KEYWORDS.search(bare).group(0).upper()
        return ValidationResult(False, sql, reasons=[f"{kw} statements are not allowed."])

    if _max_depth(bare) > MAX_NESTING_DEPTH:
        return ValidationResult(False, sql, reasons=[f"Expression nesting deeper than {MAX_NESTING_DEPTH} levels is not allowed."])

    try:
        statements = [s for s in sqlglot.parse(text, read="sqlite") if s is not None]
    except ParseError as exc:
        msg = str(exc).splitlines()[0][:200]
        return ValidationResult(False, sql, reasons=[f"SQL could not be parsed: {msg}"])
    except RecursionError:
        return ValidationResult(False, sql, reasons=["Query is too deeply nested to analyse safely."])
    if len(statements) != 1:
        return ValidationResult(False, sql, reasons=["Exactly one SELECT statement is allowed."])
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        kind = type(tree).__name__.upper()
        return ValidationResult(False, sql, reasons=[f"Only SELECT queries are allowed (received {kind})."])

    for node in tree.walk():
        name = type(node).__name__
        if name in FORBIDDEN_NODE_NAMES:
            reasons.append(f"Forbidden operation in query: {name.upper()}.")
        if isinstance(node, exp.Anonymous) and str(node.name).lower() in FORBIDDEN_FUNCTIONS:
            reasons.append(f"Function '{node.name}' is not allowed.")
        if isinstance(node, exp.Anonymous) and str(node.name).lower() in FORMAT_FUNCTIONS:
            problem = _format_problem(node)
            if problem:
                reasons.append(problem)
        if isinstance(node, exp.Func) and getattr(node, "sql_name", lambda: "")().lower() in FORBIDDEN_FUNCTIONS:
            reasons.append(f"Function '{node.sql_name()}' is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = sorted({t.name.lower() for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in cte_names})
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            reasons.append(f"Table-valued functions are not allowed ({t.this.sql(dialect='sqlite')}).")
        if t.args.get("db") or t.args.get("catalog"):
            reasons.append(f"Schema-qualified table references are not allowed ({t.sql()}).")
    disallowed = [t for t in tables if t not in ANALYTICS_TABLES]
    if disallowed:
        reasons.append(f"Table(s) not in the approved allowlist: {', '.join(disallowed)}.")
    if not tables:
        reasons.append("Query must read from at least one approved table.")
    if reasons:
        return ValidationResult(False, sql, tables=tables, reasons=sorted(set(reasons)))

    limit_applied = None
    out_sql = text
    if enforce_limit:
        limit_node = tree.args.get("limit")
        current = None
        if limit_node is not None:
            lit = limit_node.args.get("expression")
            if isinstance(lit, exp.Literal) and lit.is_int:
                current = int(lit.this)
        if current is None or current > max_rows:
            out_sql = f"SELECT * FROM ({text}) AS limited_result LIMIT {max_rows}"
            limit_applied = max_rows
    return ValidationResult(True, out_sql, tables=tables, limit_applied=limit_applied)
