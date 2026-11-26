"""
Rate limiting (tiêu chí 7).

- Sliding window 60 giây trên Redis Sorted Set theo từng API key.
- Vượt RATE_LIMIT_PER_MINUTE → HTTP 429 kèm header Retry-After.
- State lưu trong Redis để mọi worker dùng chung và giữ nguyên sau restart.
"""
import math
import time
import uuid
from collections import defaultdict

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60
_memory_windows: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str) -> None:
    """Kiểm tra và ghi nhận request theo sliding window 60 giây."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS

    if r is not None:
        redis_key = f"ratelimit:{key}"
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = pipe.execute()

            if count >= limit:
                oldest = r.zrange(redis_key, 0, 0, withscores=True)
                retry_after = (
                    max(1, math.ceil(WINDOW_SECONDS - (now - oldest[0][1])))
                    if oldest
                    else WINDOW_SECONDS
                )
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

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS)
            pipe.execute()
            return
        except HTTPException:
            raise
        except Exception:
            # Nếu Redis tạm lỗi, fallback về bộ nhớ cục bộ để không crash request
            pass

    timestamps = [ts for ts in _memory_windows[key] if ts > window_start]
    if len(timestamps) >= limit:
        retry_after = max(1, math.ceil(WINDOW_SECONDS - (now - timestamps[0])))
        _memory_windows[key] = timestamps
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
    timestamps.append(now)
    _memory_windows[key] = timestamps
