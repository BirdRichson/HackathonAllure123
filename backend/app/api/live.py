"""Живой завод: состояние, KPI, цеха, оборудование, ТО, инциденты, управление симуляцией."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import views

router = APIRouter(prefix="/api")


def rt(request: Request):
    return request.app.state.runtime


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    """Полный снимок завода — то же, что приходит первым сообщением по WebSocket."""
    return views.snapshot(rt(request))


@router.get("/kpi")
def kpi(request: Request) -> dict[str, Any]:
    """KPI текущей смены, суток и месяца по участкам и заводу."""
    return views.kpi_now(rt(request))


@router.get("/kpi/history")
def kpi_history(request: Request, area: str, shifts: int = 12) -> list[dict]:
    return views.shift_history(rt(request), area, shifts)


@router.get("/areas/{area_id}")
def area(request: Request, area_id: str) -> dict[str, Any]:
    res = views.area_view(rt(request), area_id)
    if res is None:
        raise HTTPException(404, "Участок не найден")
    return res


@router.get("/equipment/{eq_id}")
def equipment(request: Request, eq_id: str, hours: float = 8) -> dict[str, Any]:
    res = views.equipment_view(rt(request), eq_id, hours)
    if res is None:
        raise HTTPException(404, "Оборудование не найдено")
    return res


@router.get("/maintenance")
def maintenance(request: Request) -> list[dict]:
    return views.maintenance(rt(request))


@router.get("/downtime/pareto")
def downtime_pareto(request: Request, area: str | None = None, days: float = 30) -> dict[str, Any]:
    return views.pareto(rt(request), area, days)


@router.get("/incidents")
def incidents(request: Request, status: Literal["open", "closed"] | None = None, area: str | None = None,
              limit: int = 100) -> list[dict]:
    return rt(request).db.list_incidents(status=status, area=area, limit=limit)


@router.get("/reconciliation")
def reconciliation(request: Request, days: float = 7) -> list[dict]:
    return views.reconciliation(rt(request), days)


class SimControl(BaseModel):
    speed: int | None = None
    paused: bool | None = None
    reset: bool = False
    seed: int | None = None


@router.post("/sim/control")
async def sim_control(request: Request, body: SimControl) -> dict[str, Any]:
    runtime = rt(request)
    if body.reset:
        return await runtime.reset(body.seed)
    try:
        status = runtime.control(body.speed, body.paused)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await runtime.broadcast({"type": "status", "payload": status})
    return status
