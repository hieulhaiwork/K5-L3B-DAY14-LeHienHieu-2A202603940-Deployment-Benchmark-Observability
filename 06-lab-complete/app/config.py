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


def _get_budget() -> float:
    daily = os.getenv("DAILY_BUDGET_USD")
    monthly = os.getenv("MONTHLY_BUDGET_USD")
    values = []
    if daily is not None and daily != "":
        values.append(float(daily))
    if monthly is not None and monthly != "":
        values.append(float(monthly))
    return min(values) if values else 10.0


@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
    )
    daily_budget_usd: float = field(default_factory=_get_budget)
    monthly_budget_usd: float = field(
        default_factory=lambda: float(os.getenv("MONTHLY_BUDGET_USD", "10.0"))
    )


settings = Settings()
