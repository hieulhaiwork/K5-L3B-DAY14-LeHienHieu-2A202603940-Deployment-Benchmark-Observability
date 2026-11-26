"""Sliding window theo API key, dùng chung giữa các worker."""
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException

from app.config import settings
from app.redis_client import require_redis

WINDOW_SECONDS = 60

_SLIDING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local window = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    if not oldest[2] then return window end
    return math.max(1, math.ceil(window - (now - tonumber(oldest[2]))))
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('EXPIRE', KEYS[1], window)
return 0
"""


def check_rate_limit(key: str) -> None:
    """Xóa lượt hết hạn, kiểm tra và ghi lượt mới trong một thao tác Redis."""
    limit = settings.rate_limit_per_minute
    redis_key = f"ratelimit:sha256:{sha256(key.encode()).hexdigest()}"
    retry_after = require_redis().eval(
        _SLIDING_WINDOW, 1, redis_key, WINDOW_SECONDS, limit, uuid4().hex,
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window_seconds": WINDOW_SECONDS,
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
