"""
Cost Guard — Bảo Vệ Budget LLM

Mục tiêu: Tránh bill bất ngờ từ LLM API.
- Đếm tokens đã dùng mỗi ngày
- Cảnh báo khi gần hết budget
- Block khi vượt budget

Exercise 4.4: ngân sách tháng theo user được lưu trong Redis khi có REDIS_URL.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from redis import Redis, RedisError, WatchError

logger = logging.getLogger(__name__)


# Giá token (tham khảo, thay đổi theo model)
PRICE_PER_1K_INPUT_TOKENS = 0.00015   # GPT-4o-mini: $0.15/1M input
PRICE_PER_1K_OUTPUT_TOKENS = 0.0006   # GPT-4o-mini: $0.60/1M output


def token_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * PRICE_PER_1K_INPUT_TOKENS +
            output_tokens * PRICE_PER_1K_OUTPUT_TOKENS) / 1000


def _month_window(user_id: str) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (first_day + timedelta(days=32)).replace(day=1)
    return f"gateway:cost:monthly:{now:%Y-%m}:{user_id}", next_month


@dataclass
class UsageRecord:
    user_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    day: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))

    @property
    def total_cost_usd(self) -> float:
        return round(token_cost(self.input_tokens, self.output_tokens), 6)


class CostGuard:
    def __init__(
        self,
        daily_budget_usd: float = 1.0,       # $1/ngày per user
        global_daily_budget_usd: float = 10.0, # $10/ngày tổng cộng
        warn_at_pct: float = 0.8,              # Cảnh báo khi dùng 80%
        redis_client: Redis | None = None,
        monthly_budget_usd: float = 10.0,
    ):
        self.daily_budget_usd = daily_budget_usd
        self.global_daily_budget_usd = global_daily_budget_usd
        self.warn_at_pct = warn_at_pct
        self.redis = redis_client
        self.monthly_budget_usd = monthly_budget_usd
        self._records: dict[str, UsageRecord] = {}
        self._global_today = time.strftime("%Y-%m-%d")
        self._global_cost = 0.0

    def _get_record(self, user_id: str) -> UsageRecord:
        today = time.strftime("%Y-%m-%d")
        record = self._records.get(user_id)
        if not record or record.day != today:
            self._records[user_id] = UsageRecord(user_id=user_id, day=today)
        return self._records[user_id]

    def check_budget(self, user_id: str, estimated_cost: float = 0.0) -> None:
        """
        Kiểm tra budget trước khi gọi LLM.
        Raise 402 nếu vượt budget.
        """
        record = self._get_record(user_id)

        # Global budget check
        if self._global_cost >= self.global_daily_budget_usd:
            logger.critical(f"GLOBAL BUDGET EXCEEDED: ${self._global_cost:.4f}")
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable due to budget limits. Try again tomorrow.",
            )

        # Per-user budget check
        if record.total_cost_usd >= self.daily_budget_usd:
            raise HTTPException(
                status_code=402,  # Payment Required
                detail={
                    "error": "Daily budget exceeded",
                    "used_usd": record.total_cost_usd,
                    "budget_usd": self.daily_budget_usd,
                    "resets_at": "midnight UTC",
                },
            )

        if self.redis is not None:
            key, resets_at = _month_window(user_id)
            try:
                used = float(self.redis.get(key) or 0)
            except RedisError as exc:
                raise HTTPException(503, "Monthly budget storage unavailable") from exc
            self._check_monthly_limit(used, estimated_cost, resets_at)

        # Warning khi gần hết budget
        if record.total_cost_usd >= self.daily_budget_usd * self.warn_at_pct:
            logger.warning(
                f"User {user_id} at {record.total_cost_usd/self.daily_budget_usd*100:.0f}% budget"
            )

    def _check_monthly_limit(self, used: float, additional_cost: float, resets_at: datetime):
        if used >= self.monthly_budget_usd or used + additional_cost > self.monthly_budget_usd:
            raise HTTPException(402, detail={
                "error": "Monthly budget exceeded",
                "used_usd": used,
                "budget_usd": self.monthly_budget_usd,
                "resets_at": resets_at.isoformat(),
            })

    def _charge_monthly(self, user_id: str, cost: float) -> None:
        key, resets_at = _month_window(user_id)
        try:
            with self.redis.pipeline() as pipe:
                while True:
                    try:
                        pipe.watch(key)
                        used = float(pipe.get(key) or 0)
                        self._check_monthly_limit(used, cost, resets_at)
                        pipe.multi()
                        pipe.incrbyfloat(key, cost)
                        pipe.expireat(key, resets_at)
                        pipe.execute()
                        return
                    except WatchError:
                        continue
        except RedisError as exc:
            raise HTTPException(503, "Monthly budget storage unavailable") from exc

    def record_usage(
        self, user_id: str, input_tokens: int, output_tokens: int
    ) -> UsageRecord:
        """Ghi nhận usage sau khi gọi LLM xong."""
        cost = token_cost(input_tokens, output_tokens)
        if self.redis is not None:
            self._charge_monthly(user_id, cost)

        record = self._get_record(user_id)
        record.input_tokens += input_tokens
        record.output_tokens += output_tokens
        record.request_count += 1

        self._global_cost += cost

        logger.info(
            f"Usage: user={user_id} req={record.request_count} "
            f"cost=${record.total_cost_usd:.4f}/{self.daily_budget_usd}"
        )
        return record

    def get_usage(self, user_id: str) -> dict:
        record = self._get_record(user_id)
        return {
            "user_id": user_id,
            "date": record.day,
            "requests": record.request_count,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cost_usd": record.total_cost_usd,
            "budget_usd": self.daily_budget_usd,
            "budget_remaining_usd": max(0, self.daily_budget_usd - record.total_cost_usd),
            "budget_used_pct": round(record.total_cost_usd / self.daily_budget_usd * 100, 1),
        }


redis_url = os.getenv("REDIS_URL")
cost_guard = CostGuard(
    redis_client=Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    if redis_url else None,
    monthly_budget_usd=float(os.getenv("MONTHLY_BUDGET_USD", "10")),
)
