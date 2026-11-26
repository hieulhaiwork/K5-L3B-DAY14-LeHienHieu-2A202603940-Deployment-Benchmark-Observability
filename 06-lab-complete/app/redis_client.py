"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

- Đọc REDIS_URL từ config.
- Khởi tạo lazy (không ping lúc import) để app vẫn khởi động được khi Redis chưa sẵn sàng.
- redis_healthy() dùng cho GET /ready.
"""
import redis
from fastapi import HTTPException
from app.config import settings

r = (
    redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    if settings.redis_url
    else None
)

def require_redis() -> redis.Redis:
    if r is None:
        raise HTTPException(status_code=503, detail="Redis not available")
    return r


def redis_healthy() -> bool:
    """Ping Redis; trả False nếu chưa cấu hình hoặc mất kết nối."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
