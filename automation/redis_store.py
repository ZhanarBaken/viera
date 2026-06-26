"""Хранение переписки в Redis. Ключ: wazzup:chat:{phone}"""
import json
import redis
from django.conf import settings

# Максимум сообщений на один чат
MAX_MESSAGES = 1000

_client = None


def _redis():
    global _client
    if _client is None:
        _client = redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    return _client


def save_message(phone: str, message: dict):
    key = f"wazzup:chat:{phone}"
    _redis().lpush(key, json.dumps(message, ensure_ascii=False))
    _redis().ltrim(key, 0, MAX_MESSAGES - 1)


def get_messages(phone: str, limit: int = 50) -> list[dict]:
    key = f"wazzup:chat:{phone}"
    raw = _redis().lrange(key, 0, limit - 1)
    return [json.loads(m) for m in raw]
