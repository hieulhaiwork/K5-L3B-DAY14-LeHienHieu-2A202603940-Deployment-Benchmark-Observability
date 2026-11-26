# Deployment Information

## Public URL
https://k5-l3b-day14-lehienhieu-2a202603940.onrender.com

## Platform
Render (Web Service — Docker runtime từ `06-lab-complete/Dockerfile` + Render Key Value / Redis)

## Test Commands

Đặt URL và nhập API key hợp lệ trực tiếp vào terminal. Lệnh `read -s` dùng Bash và ẩn giá trị khi nhập.

```bash
BASE="https://k5-l3b-day14-lehienhieu-2a202603940.onrender.com"
read -r -s -p 'Render API key: ' AGENT_API_KEY
printf '\n'
```

### 1. Health Check (Liveness — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200
```

### 2. Readiness Check (Redis connected — mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200
```

### 3. API Test — Không có API Key (mong đợi `401`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Expected: 401
```

### 4. API Test — Có API Key hợp lệ (mong đợi `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Expected: 200
```

## Environment Variables Set (trên Render Dashboard)
- `ENVIRONMENT` (`production`)
- `REDIS_URL` (Internal Key Value URL của Render Key Value)
- `AGENT_API_KEY` (secret đặt trực tiếp trên Render Dashboard)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10.0`)
- `PORT` (Render tự động inject)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

Ảnh test giữ bốn mã HTTP của lần chạy CP6. Dòng chứa giá trị key đã được che toàn bộ.
