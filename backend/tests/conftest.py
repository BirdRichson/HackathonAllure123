"""Общие настройки тестов: без сети и без реальных ключей LLM."""

import os
import tempfile

# Тесты не ходят в Groq/Gemini и не пишут в кэш ответов проекта, даже если в .env есть ключи.
os.environ["ALLUR_LLM_PROVIDER"] = "off"
os.environ["ALLUR_AI_CACHE_DIR"] = tempfile.mkdtemp(prefix="allur-ai-cache-")
