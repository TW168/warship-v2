"""
utils/db_serializer.py — Shared SQLAlchemy → JSON serialization helper.

When SQLAlchemy returns rows from MySQL the values can include Python types
that are not JSON-serializable by default (Decimal, date, datetime).
Use ``serialize_value`` to convert a single value, or ``serialize_row`` to
convert an entire SQLAlchemy RowMapping in one call.

Example
-------
    from utils.db_serializer import serialize_row

    rows = conn.execute(query).mappings().all()
    return JSONResponse(content={"data": [serialize_row(r) for r in rows]})
"""

import decimal
from datetime import date, datetime


def serialize_value(v: object) -> object:
    """Convert a single SQLAlchemy result value to a JSON-safe Python type.

    Conversions applied:
    - ``datetime`` / ``date`` → ISO-8601 string via ``.isoformat()``
    - ``decimal.Decimal``    → ``float``
    - All other types are returned unchanged.

    Args:
        v: Any value returned from a SQLAlchemy ``execute`` call.

    Returns:
        A JSON-serializable Python primitive.
    """
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def serialize_row(row: dict) -> dict:
    """Convert all values in a SQLAlchemy RowMapping to JSON-safe types.

    Args:
        row: A dict-like SQLAlchemy ``RowMapping`` (or plain dict).

    Returns:
        A new plain dict where every value has been passed through
        ``serialize_value``.
    """
    return {k: serialize_value(v) for k, v in row.items()}
