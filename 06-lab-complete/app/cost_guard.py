"""Theo dõi chi phí theo ngày/tháng UTC trong Redis."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import require_redis

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _budget_periods(now: datetime):
    if settings.daily_budget_usd is not None:
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        yield "daily", f"cost:daily:{now:%Y-%m-%d}", settings.daily_budget_usd, tomorrow
    if settings.monthly_budget_usd is not None:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        yield "monthly", f"cost:monthly:{now:%Y-%m}", settings.monthly_budget_usd, next_month


def check_budget() -> datetime:
    """Kiểm tra ngân sách trước khi gọi LLM và giữ mốc kỳ cho lượt gọi này."""
    now = datetime.now(timezone.utc)
    periods = list(_budget_periods(now))
    values = require_redis().mget([key for _, key, _, _ in periods])
    for (period, _, budget, resets_at), value in zip(periods, values):
        used = float(value or 0)
        if used >= budget:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Budget exceeded",
                    "period": period,
                    "used_usd": round(used, 6),
                    "budget_usd": budget,
                    "resets_at": resets_at.isoformat(),
                },
            )
    return now


def record_cost(input_tokens: int, output_tokens: int, started_at: datetime) -> float:
    """Cộng chi phí vào các kỳ đang cấu hình, dựa theo thời điểm bắt đầu request."""
    cost = (input_tokens * PRICE_INPUT_PER_1K + output_tokens * PRICE_OUTPUT_PER_1K) / 1000
    with require_redis().pipeline() as pipe:
        for _, key, _, resets_at in _budget_periods(started_at):
            pipe.incrbyfloat(key, cost)
            pipe.expireat(key, resets_at + timedelta(days=1))
        pipe.execute()
    return round(cost, 6)
