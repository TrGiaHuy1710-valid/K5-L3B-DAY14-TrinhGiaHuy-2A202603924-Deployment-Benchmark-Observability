"""
Rate limiting (tiêu chí 7) — sliding window bằng Redis sorted set.
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    now = time.time()
    # Không lưu API key thô trong Redis, chỉ lưu hash
    rkey = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    member = f"{now}:{uuid.uuid4().hex}"
    limit = settings.rate_limit_per_minute

    # MULTI/EXEC: 4 lệnh chạy liền một khối
    pipe = r.pipeline()
    pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)  # bỏ request cũ hơn 60s
    pipe.zadd(rkey, {member: now})                        # ghi request này
    pipe.zcard(rkey)                                      # đếm (đã gồm request này)
    pipe.expire(rkey, WINDOW_SECONDS + 1)                 # key tự xoá khi user ngừng gọi
    _, _, count, _ = pipe.execute()

    if count > limit:
        r.zrem(rkey, member)  # request bị từ chối thì không tính
        oldest = r.zrange(rkey, 0, 0, withscores=True)
        retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now)) if oldest else WINDOW_SECONDS
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )