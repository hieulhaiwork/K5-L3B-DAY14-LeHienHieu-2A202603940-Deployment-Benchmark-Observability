"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.
"""
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _daily_budget() -> float | None:
    daily = os.getenv("DAILY_BUDGET_USD")
    if daily:
        return float(daily)
    return None if os.getenv("MONTHLY_BUDGET_USD") else 10.0


def _monthly_budget() -> float | None:
    monthly = os.getenv("MONTHLY_BUDGET_USD")
    return float(monthly) if monthly else None


@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
    )
    daily_budget_usd: float | None = field(default_factory=_daily_budget)
    monthly_budget_usd: float | None = field(default_factory=_monthly_budget)


settings = Settings()
