# Цифровой двойник АЛЛЮР. Команды: make help
PY_SYS ?= python3
VENV   := .venv
PY     := $(VENV)/bin/python

.PHONY: help install dev test build demo seed train clean

help:
	@echo "make install  — установить зависимости (Python venv + npm)"
	@echo "make dev      — бэкенд :8000 + фронтенд :5173 с автоперезагрузкой"
	@echo "make test     — тесты бэкенда и проверка типов фронтенда"
	@echo "make build    — собрать фронтенд в frontend/dist"
	@echo "make demo     — собрать и запустить всё одним процессом на :8000 (для показа, без интернета)"
	@echo "make seed     — сгенерировать историю симулятора (этап 1)"
	@echo "make train    — обучить и проверить модели ИИ (~3 мин), отчёт в docs/ML_REPORT.md"

$(PY):
	$(PY_SYS) -m venv $(VENV)

install: $(PY)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r backend/requirements-dev.txt
	cd frontend && npm install

dev:
	./scripts/dev.sh

test:
	cd backend && ../$(PY) -m pytest -q
	cd frontend && npm run typecheck

build:
	cd frontend && npm run build

demo: build
	@echo "Откройте http://localhost:8000"
	cd backend && ../$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

seed:
	cd backend && ../$(PY) -m app.sim.history

train:
	cd backend && ../$(PY) -m ml_train.train

clean:
	rm -rf frontend/dist backend/.pytest_cache
