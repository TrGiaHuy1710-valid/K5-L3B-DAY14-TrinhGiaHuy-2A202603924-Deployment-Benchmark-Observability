"""
Production AI Agent — Part 6 Final Project.
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng log là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)  # json.dumps escape \n → vẫn 1 dòng
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [_handler]
logger.setLevel(settings.log_level)
logger.propagate = False  # không đi qua root logger (tránh in trùng dạng text)


def log(event: str, level: int = logging.INFO, **fields):
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


# ── Lifespan: startup / graceful shutdown ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, redis_ok=redis_healthy())
    yield
    # Tới đây uvicorn đã ngừng nhận request mới và chờ request đang chạy xong
    log("shutdown")
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    log("request", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - start) * 1000, 1))
    return response


# ── Xử lý lỗi: trả JSON rõ ràng, không lộ stack trace ──
@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    log("redis_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc,
                 extra={"fields": {"event": "unhandled_error", "path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Endpoints ──
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, KHÔNG phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 503 khi Redis không kết nối được."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "redis": "unavailable"})
    return {"ready": True, "redis": "ok"}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # 429
    check_budget()                     # 402 — trước khi tốn tiền gọi LLM
    answer = llm_ask(body.question)
    cost = record_cost(_estimate_tokens(body.question), _estimate_tokens(answer))
    log("llm_call", question_chars=len(body.question), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}