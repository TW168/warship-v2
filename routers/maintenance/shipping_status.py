"""
routers/maintenance/shipping_status.py — Shipping Status CRUD routes.

Provides a full Create / Read / Update / Delete API for the ``shipping_status``
table, plus the HTML page that hosts the CRUD interface.

Routes:
    GET    /shipping-status               — CRUD page (Jinja2 template)
    GET    /api/shipping-status           — List rows (optional date filters)
    POST   /api/shipping-status           — Create a new row
    PUT    /api/shipping-status/{row_id}  — Update an existing row by id
    DELETE /api/shipping-status/{row_id}  — Delete a row by id

Table schema (shipping_status):
    id          INT AUTO_INCREMENT PK
    Date        DATE
    Customer    DECIMAL
    Con_Hou     DECIMAL
    Con_Rem     DECIMAL
    Con_PHO     DECIMAL
    Con_CHA     DECIMAL
    Total       DECIMAL
    Hou_ship    DECIMAL
    Rem_ship    DECIMAL
    Con         DECIMAL
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from database import connect_to_database
from schemas.shipping_status import (
    ShippingStatusCreateRequest,
    ShippingStatusDeleteResponse,
    ShippingStatusRow,
    ShippingStatusUpdateRequest,
)

router = APIRouter(tags=["Maintenance"])
templates = Jinja2Templates(directory="templates")

# One shared engine for this module (created at import time)
_engine = connect_to_database()

# SQL fragment — reused in every SELECT to guarantee a consistent column order
_SELECT_COLUMNS = """
    id,
    `Date`      AS date,
    Customer    AS customer,
    Con_Hou     AS con_hou,
    Con_Rem     AS con_rem,
    Con_PHO     AS con_pho,
    Con_CHA     AS con_cha,
    Total       AS total,
    Hou_ship    AS hou_ship,
    Rem_ship    AS rem_ship,
    `Con`       AS con
"""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_model(row) -> ShippingStatusRow:
    """Map one SQLAlchemy result row to a ``ShippingStatusRow`` Pydantic model.

    Args:
        row: A SQLAlchemy ``Row`` with the columns listed in ``_SELECT_COLUMNS``.

    Returns:
        A populated ``ShippingStatusRow`` instance.
    """
    return ShippingStatusRow(
        id=int(row.id),
        date=row.date,
        customer=float(row.customer) if row.customer is not None else None,
        con_hou=float(row.con_hou)  if row.con_hou  is not None else None,
        con_rem=float(row.con_rem)  if row.con_rem  is not None else None,
        con_pho=float(row.con_pho)  if row.con_pho  is not None else None,
        con_cha=float(row.con_cha)  if row.con_cha  is not None else None,
        total=float(row.total)      if row.total     is not None else None,
        hou_ship=float(row.hou_ship) if row.hou_ship is not None else None,
        rem_ship=float(row.rem_ship) if row.rem_ship is not None else None,
        con=float(row.con)          if row.con       is not None else None,
    )


def _fetch_by_id(conn, row_id: int) -> ShippingStatusRow | None:
    """Fetch one ``shipping_status`` row by primary key.

    Args:
        conn:   An open SQLAlchemy connection.
        row_id: The primary key to look up.

    Returns:
        A ``ShippingStatusRow`` model, or ``None`` when not found.
    """
    row = conn.execute(
        text(f"SELECT {_SELECT_COLUMNS} FROM shipping_status WHERE id = :id"),
        {"id": row_id},
    ).fetchone()
    return _row_to_model(row) if row else None


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get(
    "/shipping-status",
    response_class=HTMLResponse,
    summary="Shipping Status CRUD Page",
    description=(
        "Maintenance page for creating, viewing, updating, and deleting records "
        "in the ``shipping_status`` table. Uses HTMX for in-place updates."
    ),
)
async def shipping_status_page(request: Request) -> HTMLResponse:
    """Render the Shipping Status CRUD maintenance page."""
    return templates.TemplateResponse(
        "maintenance/shipping_status.html",
        {"request": request, "active_page": "shipping_status"},
    )


# ---------------------------------------------------------------------------
# JSON API routes
# ---------------------------------------------------------------------------

@router.get(
    "/api/shipping-status",
    response_model=list[ShippingStatusRow],
    summary="List Shipping Status Rows",
    description=(
        "Returns ``shipping_status`` rows ordered by Date desc then id desc. "
        "Optional query params: ``date_from`` and ``date_to`` (YYYY-MM-DD), "
        "``limit`` (default 200, max 1000)."
    ),
)
async def shipping_status_list(
    date_from: Optional[str] = Query(None, description="Include rows with Date ≥ this value"),
    date_to:   Optional[str] = Query(None, description="Include rows with Date ≤ this value"),
    limit:     int           = Query(200, ge=1, le=1000, description="Maximum rows to return"),
) -> list[ShippingStatusRow]:
    """Return shipping_status rows with optional date-range filtering."""
    conditions: list[str] = []
    params: dict = {"limit": limit}

    if date_from:
        try:
            params["date_from"] = datetime.fromisoformat(date_from.strip()).date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date_from: {exc}") from exc
        conditions.append("`Date` >= :date_from")

    if date_to:
        try:
            params["date_to"] = datetime.fromisoformat(date_to.strip()).date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date_to: {exc}") from exc
        conditions.append("`Date` <= :date_to")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM shipping_status
                {where}
                ORDER BY `Date` DESC, id DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()

    return [_row_to_model(r) for r in rows]


@router.post(
    "/api/shipping-status",
    response_model=ShippingStatusRow,
    summary="Create Shipping Status Row",
    description="Creates a new row in ``shipping_status`` and returns the inserted record.",
)
async def shipping_status_create(body: ShippingStatusCreateRequest) -> ShippingStatusRow:
    """Insert one new shipping_status row and return it."""
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO shipping_status (
                    `Date`, Customer, Con_Hou, Con_Rem, Con_PHO, Con_CHA,
                    Total, Hou_ship, Rem_ship, `Con`
                ) VALUES (
                    :date, :customer, :con_hou, :con_rem, :con_pho, :con_cha,
                    :total, :hou_ship, :rem_ship, :con
                )
                """
            ),
            {
                "date":     body.date,
                "customer": body.customer,
                "con_hou":  body.con_hou,
                "con_rem":  body.con_rem,
                "con_pho":  body.con_pho,
                "con_cha":  body.con_cha,
                "total":    body.total,
                "hou_ship": body.hou_ship,
                "rem_ship": body.rem_ship,
                "con":      body.con,
            },
        )
        new_id = int(result.lastrowid) if result.lastrowid else None
        if new_id is None:
            new_id = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())

        created = _fetch_by_id(conn, new_id)

    if not created:
        raise HTTPException(status_code=500, detail="Created row could not be retrieved")
    return created


@router.put(
    "/api/shipping-status/{row_id}",
    response_model=ShippingStatusRow,
    summary="Update Shipping Status Row",
    description="Updates an existing ``shipping_status`` row by id and returns the updated record.",
)
async def shipping_status_update(
    row_id: int,
    body: ShippingStatusUpdateRequest,
) -> ShippingStatusRow:
    """Update one shipping_status row by primary key and return the updated record."""
    with _engine.begin() as conn:
        if not conn.execute(
            text("SELECT id FROM shipping_status WHERE id = :id"), {"id": row_id}
        ).fetchone():
            raise HTTPException(status_code=404, detail=f"Row not found: {row_id}")

        conn.execute(
            text(
                """
                UPDATE shipping_status
                SET
                    `Date`   = :date,
                    Customer = :customer,
                    Con_Hou  = :con_hou,
                    Con_Rem  = :con_rem,
                    Con_PHO  = :con_pho,
                    Con_CHA  = :con_cha,
                    Total    = :total,
                    Hou_ship = :hou_ship,
                    Rem_ship = :rem_ship,
                    `Con`    = :con
                WHERE id = :id
                """
            ),
            {
                "id":       row_id,
                "date":     body.date,
                "customer": body.customer,
                "con_hou":  body.con_hou,
                "con_rem":  body.con_rem,
                "con_pho":  body.con_pho,
                "con_cha":  body.con_cha,
                "total":    body.total,
                "hou_ship": body.hou_ship,
                "rem_ship": body.rem_ship,
                "con":      body.con,
            },
        )
        updated = _fetch_by_id(conn, row_id)

    if not updated:
        raise HTTPException(status_code=500, detail="Updated row could not be retrieved")
    return updated


@router.delete(
    "/api/shipping-status/{row_id}",
    response_model=ShippingStatusDeleteResponse,
    summary="Delete Shipping Status Row",
    description="Deletes one ``shipping_status`` row by id.",
)
async def shipping_status_delete(row_id: int) -> ShippingStatusDeleteResponse:
    """Delete one shipping_status row by primary key."""
    with _engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM shipping_status WHERE id = :id"), {"id": row_id}
        )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Row not found: {row_id}")

    return ShippingStatusDeleteResponse(deleted_id=row_id, message="Row deleted")
