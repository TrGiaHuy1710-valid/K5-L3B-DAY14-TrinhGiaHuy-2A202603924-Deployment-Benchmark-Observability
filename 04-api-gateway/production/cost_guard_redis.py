"""
Exercise 4.4 — Cost guard lưu trong Redis (budget theo tháng).

Yêu cầu:
  - Mỗi user có budget $10/tháng (đổi bằng env MONTHLY_BUDGET_USD)
  - Track spending trong Redis (nhiều instance dùng chung, không mất khi restart)
  - Reset đầu tháng

Thiết kế:
  - Key theo tháng UTC: budget:<user_id>:<YYYY-MM>. Sang tháng mới là key mới,
    tức tự "reset" mà không cần cron job.
  - TTL 32 ngày để key tháng cũ tự bị Redis xoá, không phình bộ nhớ.
  - Kiểm tra + cộng tiền trong MỘT Lua script → atomic. Bản "GET rồi INCRBYFLOAT"
    có race condition: 2 request đồng thời cùng đọc được số dư cũ và cùng qua,
    làm vượt budget.
  - Dùng `>` (không phải `>=`): tiêu đúng bằng budget vẫn được phép.

Dùng trong endpoint:
    if not check_budget(user_id, estimated_cost):
        raise HTTPException(402, "Monthly budget exceeded")
"""
import os
from datetime import datetime, timezone
from typing import Optional

import redis

MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))
KEY_TTL_SECONDS = 32 * 24 * 3600

r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

# KEYS[1] = key budget tháng này; ARGV = [cost, budget, ttl]
# Trả 1 nếu còn budget (đã ghi nhận chi phí), 0 nếu vượt (không ghi gì).
_RESERVE_SCRIPT = r.register_script(
    """
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    local cost = tonumber(ARGV[1])
    local budget = tonumber(ARGV[2])
    if current + cost > budget then
        return 0
    end
    redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    return 1
    """
)


def month_key(user_id: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"budget:{user_id}:{now:%Y-%m}"


def check_budget(user_id: str, estimated_cost: float) -> bool:
    """
    Return True nếu còn budget (và ghi nhận estimated_cost), False nếu vượt.
    """
    if estimated_cost < 0:
        raise ValueError("estimated_cost must be >= 0")
    allowed = _RESERVE_SCRIPT(
        keys=[month_key(user_id)],
        args=[estimated_cost, MONTHLY_BUDGET_USD, KEY_TTL_SECONDS],
    )
    return bool(allowed)


def get_spent(user_id: str) -> float:
    """Số tiền user đã tiêu trong tháng hiện tại."""
    return float(r.get(month_key(user_id)) or 0)
