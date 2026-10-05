"""Отчёты рабочих о простоях: журнал, новая запись с формы, дополнение черновика от станка."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import reasons_config

router = APIRouter(prefix="/api")


class ReportIn(BaseModel):
    equipment_id: str
    reason: str
    description: str = Field("", max_length=2000)
    actions_taken: str = Field("", max_length=2000)
    reporter_role: Literal["оператор", "наладчик", "мастер"] = "оператор"
    duration_min: float | None = None
    complete_draft: bool = True       # дополнить свежий черновик от станка, если он есть
    report_id: str | None = None      # дополнить конкретную запись журнала
    source: Literal["operator_form", "telegram"] = "operator_form"


class ReportPatch(BaseModel):
    reason: str | None = None
    description: str | None = None
    actions_taken: str | None = None
    reporter_role: str | None = None


@router.get("/reasons")
def reasons() -> dict[str, Any]:
    """Справочник причин для формы рабочего."""
    return {code: v["label"] for code, v in reasons_config()["codes"].items()}


@router.get("/reports")
def list_reports(request: Request, area: str | None = None, equipment: str | None = None,
                 status: Literal["draft", "completed"] | None = None, limit: int = 100) -> list[dict]:
    return request.app.state.runtime.db.list_reports(area=area, equipment=equipment, status=status, limit=limit)


@router.post("/reports")
def create_report(request: Request, body: ReportIn) -> dict[str, Any]:
    runtime = request.app.state.runtime
    if body.equipment_id not in runtime.world.sim.equipment:
        raise HTTPException(404, "Оборудование не найдено")
    if body.reason not in reasons_config()["codes"]:
        raise HTTPException(400, "Неизвестная причина")
    return runtime.submit_report(body.model_dump())


@router.patch("/reports/{report_id}")
def patch_report(request: Request, report_id: str, body: ReportPatch) -> dict[str, Any]:
    if body.reason is not None and body.reason not in reasons_config()["codes"]:
        raise HTTPException(400, "Неизвестная причина")
    res = request.app.state.runtime.complete_report(report_id, body.model_dump())
    if res is None:
        raise HTTPException(404, "Отчёт не найден")
    return res
