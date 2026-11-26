"""
Cost guard (tiêu chí 8).

- Cộng dồn chi phí LLM (tính theo token) vào Redis.
- Tổng chi phí vượt DAILY_BUDGET_USD (hoặc MONTHLY_BUDGET_USD) → HTTP 402.
"""
import time
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_memory_daily_cost: dict[str, float] = {}


def _today_key() -> str:
    return f"cost:daily:{time.strftime('%Y-%m-%d', time.gmtime())}"


def _current_cost() -> float:
    key = _today_key()
    if r is not None:
        try:
            val = r.get(key)
            return float(val) if val is not None else 0.0
        except Exception:
            pass
    return _memory_daily_cost.get(key, 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    used = _current_cost()
    budget = settings.daily_budget_usd
    if used >= budget:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Budget exceeded",
                "used_usd": round(used, 6),
                "budget_usd": budget,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K
    key = _today_key()

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(key, cost)
            pipe.expire(key, 86400 * 2)
            pipe.execute()
            return round(cost, 6)
        except Exception:
            pass

    _memory_daily_cost[key] = _memory_daily_cost.get(key, 0.0) + cost
    return round(cost, 6)
