"""ИИ-помощник: выводы, прогнозы, разбор отчётов, вопросы о заводе."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


def ai(request: Request):
    return request.app.state.runtime.ai


class SuggestIn(BaseModel):
    equipment_id: str
    description: str = Field("", max_length=2000)
    actions_taken: str = Field("", max_length=2000)
    reason: str | None = None
    use_llm: bool = False


class AskIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    area_id: str | None = None


@router.get("/ai/status")
def status(request: Request) -> dict[str, Any]:
    """Какие провайдеры LLM подключены, какие модели загружены и как они проверены."""
    return ai(request).status()


@router.get("/insights")
def insights(request: Request, area: str | None = None) -> dict[str, Any]:
    """Выводы ИИ за 30 дней: доказательства, рекомендации, эффект в авто/месяц."""
    st = ai(request).insights()
    if area:
        st = {**st, "items": [i for i in st["items"] if i["area_id"] == area]}
    return st


@router.post("/insights/refresh")
async def insights_refresh(request: Request, force: bool = False) -> dict[str, Any]:
    """Пересчитать выводы и переписать их LLM. force=true — не брать ответ LLM из кэша."""
    return await ai(request).refresh(force=force)


@router.get("/predictions")
def predictions(request: Request) -> dict[str, Any]:
    """Риск отказа в ближайшие 2 часа по каждому станку и фактор риска."""
    return ai(request).predictions()


@router.get("/plan/forecast")
def plan_forecast(request: Request) -> dict[str, Any]:
    """Прогноз выпуска за месяц: медиана, интервал 10–90%, вероятность цели, по моделям, по дням."""
    return ai(request).plan_forecast()


@router.get("/reports/analysis")
def reports_analysis(request: Request, days: float = 30, area: str | None = None) -> dict[str, Any]:
    """Сводка ИИ по отчётам рабочих: незаполненные, неверные причины, повторяющиеся проблемы."""
    return ai(request).reports_analysis(days, area)


@router.post("/reports/suggest")
async def reports_suggest(request: Request, body: SuggestIn) -> dict[str, Any]:
    """Подсказка причины по тексту формы. use_llm=true — разбор языковой моделью (если есть ключ)."""
    svc = ai(request)
    sim = request.app.state.runtime.world.sim
    if body.equipment_id not in sim.equipment:
        raise HTTPException(404, "Оборудование не найдено")
    if body.use_llm and svc.llm.available:
        drafts = request.app.state.runtime.db.list_reports(equipment=body.equipment_id, status="draft", limit=1)
        machine = drafts[0]["machine_reason_text"] if drafts else ""
        return await svc.suggest_llm(body.equipment_id, body.description, body.actions_taken, body.reason, machine)
    return svc.suggest(body.equipment_id, body.description, body.actions_taken, body.reason)


@router.post("/assistant/ask")
async def ask(request: Request, body: AskIn) -> dict[str, Any]:
    """Вопрос о заводе простыми словами — отвечает LLM по данным двойника."""
    return await ai(request).ask(body.question, body.area_id)
