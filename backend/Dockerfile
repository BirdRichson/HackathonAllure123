# Сборка из корня репозитория: docker build -f backend/Dockerfile .
FROM python:3.12-slim

# libgomp1 нужен LightGBM
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY config config
COPY data data

ENV ALLUR_ROOT=/app PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
