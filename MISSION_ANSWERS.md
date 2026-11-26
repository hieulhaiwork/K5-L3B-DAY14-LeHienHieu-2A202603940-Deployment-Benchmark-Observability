# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
Trong `01-localhost-vs-production/develop/app.py`, phát hiện các anti-patterns sau:

1. **Hardcoded secrets trong source code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub, secret sẽ bị lộ ngay lập tức và nằm vĩnh viễn trong lịch sử git.
2. **Không có config management tập trung** (dòng 21–22): Hardcode `DEBUG = True`, `MAX_TOKENS = 500`, không đọc từ biến môi trường nên không thể thay đổi cấu hình giữa các môi trường `dev / staging / production` mà không sửa code.
3. **Dùng `print()` thay cho structured logging và in cả secret ra log** (dòng 33–38): Đặc biệt dòng 34 `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm lộ API key ra log hệ thống; `print()` không có timestamp, log level hay định dạng JSON để công cụ giám sát (Loki, Datadog…) phân tích.
4. **Không có Health Check / Readiness endpoint** (dòng 42–43): Thiếu `/health` và `/ready`, nên nền tảng cloud hoặc load balancer không biết container còn sống hay đã sẵn sàng nhận traffic để tự động restart hoặc định tuyến.
5. **Hardcode `host="localhost"`, `port=8000` và bật `reload=True`** (dòng 49–54): Bind `localhost` khiến container không nhận được kết nối từ bên ngoài; port cứng `8000` không tương thích với biến `PORT` do Railway/Render cấp phát; `reload=True` gây tốn tài nguyên và không an toàn trên production.
6. **Không có Graceful Shutdown**: Khi nhận tín hiệu `SIGTERM` (ví dụ lúc deploy bản mới hoặc tắt container), app dừng đột ngột, làm đứt ngang các request đang xử lý và có thể gây mất dữ liệu.
7. **Không validate input JSON & không cấu hình CORS**: Endpoint `POST /ask` nhận `question` qua query string thay vì JSON body có kiểm tra rõ ràng, không xử lý lỗi thân thiện.

**Ví dụ đối chiếu đã sửa trong bản production:** Hardcoded secrets & config ở `develop/app.py` (dòng 17–22) đã được chuyển sang đọc từ biến môi trường bằng dataclass `Settings` và `os.getenv(...)` trong `production/config.py` (dòng 14–50), kèm `validate()` kiểm tra `AGENT_API_KEY` khi `environment == "production"`.

### Exercise 1.2: Test results

**Bản `develop`** (`curl -X POST "http://localhost:8000/ask?question=Hello"`):
```json
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

**Bản `production`:**
- `curl http://localhost:8000/health`:
```json
{"status":"ok","uptime_seconds":30.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:21:10.357831+00:00"}
```
- `curl http://localhost:8000/ready`:
```json
{"ready":true}
```
- `curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'`:
```json
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Comparison table

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Why Important? |
|---------|----------------------------|------------------------------------------------|----------------|
| **Config & Secrets** | Hardcode trực tiếp trong code (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`) | Đọc toàn bộ từ biến môi trường qua `Settings` (`os.getenv`), có `validate()` fail-fast (`config.py` L14–50) | Tránh lộ secret lên Git, dễ đổi cấu hình giữa dev/staging/prod theo nguyên lý 12-Factor App |
| **Health & Readiness** | Không có | Có `GET /health` (liveness, trả uptime/version) và `GET /ready` (readiness, trả 503 khi chưa sẵn sàng) (`app.py` L135–161) | Cloud/orchestrator biết khi nào cần restart container bị treo (`/health`) và khi nào mới route traffic vào (`/ready`) |
| **Logging** | Dùng `print()`, in cả `OPENAI_API_KEY` ra stdout | Structured JSON logging qua `logging` + `json.dumps()`, chỉ log metadata (`question_length`, `client_ip`), không log secret (`app.py` L28–32, L111–122) | Dễ parse, tìm kiếm, cảnh báo trên log aggregator và tránh rò rỉ dữ liệu nhạy cảm |
| **Shutdown** | Tắt đột ngột | Có `lifespan` context manager + `signal.signal(signal.SIGTERM, handle_sigterm)` (`app.py` L39–68, L180–189) | Cho phép hoàn tất các request đang xử lý (in-flight requests) và đóng kết nối sạch sẽ trước khi tắt, đạt zero-downtime deploy |
| **Server binding & Reload** | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=settings.port` (env `PORT`), `reload=settings.debug` (`app.py` L194–199) | `0.0.0.0` cho phép truy cập từ ngoài container; đọc `PORT` để chạy được trên Railway/Render; tắt `reload` để ổn định & tối ưu hiệu năng |
| **API & Middleware** | Query param `?question=...`, không có CORS hay `/metrics` | JSON body có validate (`422` nếu thiếu `question`), có `CORSMiddleware` giới hạn origin và endpoint `/metrics` (`app.py` L77–82, L102–108, L164–173) | An toàn hơn cho dữ liệu đầu vào, kiểm soát truy cập cross-origin và hỗ trợ giám sát |

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. Base image: [Your answer]
2. Working directory: [Your answer]
...

### Exercise 2.3: Image size comparison
- Develop: [X] MB
- Production: [Y] MB
- Difference: [Z]%

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- URL: https://your-app.railway.app
- Screenshot: [Link to screenshot in repo]

## Part 4: API Security

### Exercise 4.1-4.3: Test results
[Paste your test outputs]

### Exercise 4.4: Cost guard implementation
[Explain your approach]

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes
[Your explanations and test results]

## Part 6: Final Project — Checklist Deliverable
[Paste output phần "📋 Checklist Deliverable" của `python check_production_ready.py` khi đạt PASS 12/12]

## AI Log
- **CP0 & CP1:** Hỏi AI tóm tắt mục tiêu bài lab, lộ trình theo các checkpoint K5, cách thiết lập virtualenv trong WSL2, và hỗ trợ tổng hợp bảng so sánh Part 1 dựa trên code trong `01-localhost-vs-production/` và output `curl` tự chạy trên máy. Tự kiểm tra bằng cách chạy cả hai bản `develop` và `production` trong WSL2 và đối chiếu lại các dòng code trong `app.py` và `config.py`.
