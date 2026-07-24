import re

from app.schema import ALLOWED_TABLES

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|copy|"
    r"into|execute|call|do|vacuum|explain|pg_sleep|pg_read_file|dblink)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*\.)?([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    pass


def validate_select_only(sql: str) -> str:
    """Defense-in-depth guard on top of the chatbot_readonly DB role's grants.

    The DB role can only SELECT from the catalog tables regardless of what
    passes here, but rejecting bad queries before they hit the DB gives
    cleaner error messages to feed back into the self-heal step.
    """
    cleaned = sql.strip()

    if cleaned.count(";") > 1 or (cleaned.count(";") == 1 and not cleaned.rstrip().endswith(";")):
        raise UnsafeQueryError("Only a single statement is allowed.")
    cleaned = cleaned.rstrip(";").strip()

    if "--" in cleaned or "/*" in cleaned:
        raise UnsafeQueryError("SQL comments are not allowed.")

    if not re.match(r"^\s*select\b", cleaned, re.IGNORECASE):
        raise UnsafeQueryError("Only SELECT statements are allowed.")

    if _FORBIDDEN_KEYWORDS.search(cleaned):
        raise UnsafeQueryError("Query contains a forbidden keyword.")

    referenced_tables = {m[1].lower() for m in _TABLE_REF.findall(cleaned)}
    if not referenced_tables:
        raise UnsafeQueryError("Could not determine referenced tables.")
    if not referenced_tables.issubset(ALLOWED_TABLES):
        disallowed = referenced_tables - ALLOWED_TABLES
        raise UnsafeQueryError(f"Query references disallowed table(s): {', '.join(disallowed)}")

    return cleaned
