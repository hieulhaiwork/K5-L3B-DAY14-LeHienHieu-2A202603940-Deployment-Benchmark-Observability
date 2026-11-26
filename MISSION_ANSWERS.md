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
*(Tham chiếu `02-docker/develop/Dockerfile`)*
1. **Base image là gì?** `python:3.11` — image Python bản đầy đủ (gồm hệ điều hành Debian + Python runtime + nhiều build tools, dung lượng lớn ~1 GB+).
2. **Working directory là gì?** `/app` (`WORKDIR /app`) — thư mục làm việc mặc định bên trong container nơi code được copy vào và lệnh `CMD` thực thi.
3. **Tại sao `COPY requirements.txt` trước `COPY` source code?** Để tận dụng **Docker layer cache**: khi chỉ sửa code trong `app.py` mà không đổi `requirements.txt`, Docker tái sử dụng layer `RUN pip install ...` đã cache, không phải tải và cài lại toàn bộ thư viện → tốc độ rebuild nhanh hơn rất nhiều.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `CMD`: định nghĩa lệnh/tham số **mặc định** khi chạy container, **có thể bị ghi đè** dễ dàng khi truyền tham số sau `docker run <image> <command>`.
   - `ENTRYPOINT`: cố định executable chính của container (khó bị ghi đè, phải dùng cờ `--entrypoint`); tham số truyền vào `docker run` sẽ được nối thêm làm đối số cho `ENTRYPOINT`.

### Exercise 2.2: Build và chạy container bản develop
- Build từ gốc repo: `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`
- Chạy container: `docker run -d --name test-dev -p 8000:8000 my-agent:develop`
- Kết quả test (`curl -X POST "http://localhost:8000/ask?question=What+is+Docker"`):
```json
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & Image size comparison
- **Stage 1 (`builder`, `FROM python:3.11-slim AS builder`):** Cài build tools (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`, `FROM python:3.11-slim AS runtime`):** Tạo non-root user `appuser`, chỉ copy các package đã cài từ `/root/.local` của `builder` sang `/home/appuser/.local`, copy `main.py` và `utils/mock_llm.py`, thêm `HEALTHCHECK` và chạy `uvicorn`.
- **Tại sao image nhỏ hơn?** Dùng base image `-slim` thay vì bản đầy đủ, đồng thời loại bỏ hoàn toàn trình biên dịch (`gcc`, `libpq-dev`), cache tải về và công cụ build ở Stage 1 khỏi image cuối cùng.

**Kích thước đo thực tế bằng `docker images my-agent`:**
- **Develop (`my-agent:develop`):** `1.67 GB` (1670 MB Disk Usage · Content Size: `426 MB`)
- **Production (`my-agent:advanced`):** `240 MB` (Disk Usage · Content Size: `57.4 MB`)
- **Chênh lệch:** Giảm **~85.6%** Disk Usage (từ 1670 MB xuống 240 MB, nhẹ hơn ~7 lần; Content Size giảm **~86.5%** từ 426 MB xuống 57.4 MB).

### Exercise 2.4: Docker Compose stack
- **Các service được khởi động** (cùng nằm trong bridge network `internal`, chỉ `nginx` mở cổng ra ngoài `80`/`443`):
  - `nginx` (`nginx:alpine`): Reverse proxy & load balancer nhận request từ client ở cổng 80.
  - `agent` (build từ `02-docker/production/Dockerfile`, target `runtime`): FastAPI AI Agent lắng nghe nội bộ cổng 8000, `depends_on` `redis` và `qdrant` ở trạng thái `service_healthy`.
  - `redis` (`redis:7-alpine`): Lưu session cache & rate limiting (cổng 6379, volume `redis_data`).
  - `qdrant` (`qdrant/qdrant:v1.9.0`): Vector database cho RAG (cổng 6333, volume `qdrant_data`).

**Sơ đồ kiến trúc:**
```text
Client ──► Nginx (:80) ──► Agent (:8000) ──► Redis (:6379)
                                    └───► Qdrant (:6333)
                  [internal Docker bridge network]
```

**Kết quả test qua Nginx:**
- `curl http://localhost/health`:
```json
{"status":"ok","uptime_seconds":35.4,"version":"2.0.0","timestamp":"2026-11-26T07:46:36.279177"}
```
- `curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "What is Docker?"}'`:
```json
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Render deployment (agent Part 6 trong `06-lab-complete/`)
- **Platform:** Render (Web Service Docker + Redis / Key Value)
- **URL:** https://k5-l3b-day14-lehienhieu-2a202603940.onrender.com
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` vs `render.yaml` (3 điểm)
| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
| :--- | :--- | :--- |
| **Định dạng & phạm vi** | TOML, cấu hình cho **1 service** duy nhất (`[build]`, `[deploy]`). | YAML (Infrastructure as Code), có thể khai báo **nhiều services + Redis/DB** trong cùng 1 file (`services:`). |
| **Cách chỉ định build** | `builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"`. | `type: web`, `runtime: docker`, `dockerfilePath: ./Dockerfile`, chọn luôn `plan: free`. |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries`. | `healthCheckPath: /health` (Render tự quản lý restart & zero-downtime deploy). |
| **Biến môi trường & Secret** | Quản lý trực tiếp trên Railway Dashboard hoặc CLI (`railway variables set`), không khai báo trong `railway.toml`. | Khai báo ngay trong `envVars:` với `value:` cho biến thường, `generateValue: true` (Render tự sinh secret ngẫu nhiên) hoặc `sync: false` (nhập tay trên dashboard, không lộ secret trong git). |

### Exercise 3.3: GCP Cloud Run CI/CD Pipeline (1 điểm)
Đọc `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` và `service.yaml`, pipeline CI/CD tự động khi push lên `main` đi qua 4 bước tuần tự:
1. **Test (`python:3.11-slim`):** Cài `requirements.txt` + `pytest` và chạy `pytest tests/` — nếu fail sẽ dừng pipeline ngay.
2. **Build (`docker`):** Build Docker image gắn tag theo `$COMMIT_SHA` và `latest`, tận dụng `--cache-from` từ image `latest` để tăng tốc.
3. **Push (`docker`):** Đẩy các tag image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`gcloud run deploy`):** Triển khai bản `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình autoscaling `minScale=1` (tránh cold start) đến `maxScale=10`, giới hạn `512Mi RAM / 1 CPU`, concurrency 80, lấy secret (`OPENAI_API_KEY`, `AGENT_API_KEY`) từ **Secret Manager** thay vì hardcode, và gắn `livenessProbe` (`/health`) + `startupProbe` (`/ready`) như định nghĩa trong `service.yaml`.

## Part 4: API Security

### Exercise 4.1-4.3: Test results

#### Exercise 4.1 — API Key Authentication (`04-api-gateway/develop`, chạy với `AGENT_API_KEY=secret-key-123`)
- **Không có API key → `401 Unauthorized`:**
```http
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 07:52:23 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```
- **Có API key hợp lệ (`X-API-Key: secret-key-123`) → `200 OK`:**
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:52:39 GMT
server: uvicorn
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

#### Exercise 4.2 & 4.3 — JWT Authentication + Rate Limiting (`04-api-gateway/production`)
- Lấy JWT token qua `POST /auth/token` với tài khoản `student` / `demo123` (role `user`, giới hạn **10 req/phút**, ngân sách `$1/ngày`), lưu vào biến `$TOKEN` (đã che token).
- **Request đầu tiên với `Authorization: Bearer <REDACTED>` → `200 OK`** (kèm security headers `x-content-type-options: nosniff`, `x-frame-options: DENY`, `x-xss-protection: 1; mode=block`, `referrer-policy: strict-origin-when-cross-origin`):
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:53:43 GMT
server: uvicorn
content-length: 196
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"What is Docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```
- **Vòng lặp 11 request liên tiếp** (cộng 1 request trước đó = 10 request đầu `200 OK`, từ request thứ 11 trở đi trả `429 Too Many Requests`):
```text
=== Request 1 ===  HTTP/1.1 200 OK
...
=== Request 9 ===  HTTP/1.1 200 OK
=== Request 10 === HTTP/1.1 429 Too Many Requests
=== Request 11 === HTTP/1.1 429 Too Many Requests
```
- **Chi tiết response `429 Too Many Requests`:**
```http
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 07:54:07 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795679708
retry-after: 36
content-length: 98
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":36}}
```

### Exercise 4.4: Cost guard implementation
- **Cơ chế hoạt động** (tham chiếu `04-api-gateway/production/cost_guard.py`):
  1. **Theo dõi usage theo ngày (`UsageRecord`):** Lưu số `input_tokens`, `output_tokens`, `request_count` của từng `user_id` trong ngày hiện tại (`YYYY-MM-DD`) và tính chi phí dựa trên đơn giá token (`PRICE_PER_1K_INPUT_TOKENS`, `PRICE_PER_1K_OUTPUT_TOKENS`), đồng thời cộng dồn `_global_cost` toàn hệ thống.
  2. **Kiểm tra trước khi gọi LLM (`check_budget`):**
     - Nếu `_global_cost >= global_daily_budget_usd` ($10/ngày) → log `CRITICAL` và trả **`503 Service Unavailable`** để bảo vệ toàn dịch vụ.
     - Nếu `record.total_cost_usd >= daily_budget_usd` ($1/ngày/user) → trả **`402 Payment Required`** kèm chi tiết `used_usd`, `budget_usd`, `resets_at`.
     - Khi đạt ≥ 80% ngân sách (`warn_at_pct = 0.8`) → ghi log `WARNING`.
  3. **Ghi nhận sau khi gọi LLM (`record_usage`):** Cộng thêm input/output tokens và chi phí phát sinh cho user và global.
  4. **Lưu ý production:** Thay `dict` in-memory bằng **Redis** (`INCRBYFLOAT` + TTL đến hết ngày/tháng) để đồng bộ giữa nhiều instance và không mất dữ liệu khi restart.
- **Tại sao cần cả Rate Limiting và Cost Guard?**
  - **Rate Limiting** bảo vệ **tốc độ/tài nguyên** (chống spam, DDoS, quá tải CPU/concurrency bằng giới hạn req/phút → `429`).
  - **Cost Guard** bảo vệ **tiền/ngân sách LLM** (tránh hóa đơn tăng vọt từ các prompt/response cực dài dù tốc độ gọi thấp → `402`). Chỉ dùng 1 trong 2 vẫn có lỗ hổng: user gửi chậm nhưng prompt dài vẫn đốt hết tiền nếu thiếu Cost Guard; ngược lại user gửi prompt ngắn với tốc độ cao vẫn làm sập server nếu thiếu Rate Limiting.

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes

- **Exercise 5.1 — Liveness (`/health`) vs Readiness (`/ready`)** (`05-scaling-reliability/develop/app.py`):
  - `GET /health` (**Liveness probe**): Kiểm tra *"process có còn sống không?"*. Nền tảng (Docker/K8s/Railway/Render) gọi định kỳ; nếu trả non-200 hoặc timeout thì **restart container**. Cần luôn trả `200` khi process còn hoạt động (tránh tự restart dây chuyền chỉ vì dependency ngoài bị chập chờn).
  - `GET /ready` (**Readiness probe**): Kiểm tra *"instance đã sẵn sàng nhận traffic chưa?"*. Load balancer dùng để quyết định có định tuyến request tới instance này không. Trả **`503 Service Unavailable`** khi đang khởi động (`_is_ready = False`), đang shutdown, hoặc dependency quan trọng (như Redis) mất kết nối — nhờ đó load balancer tạm ngừng gửi traffic mới vào instance này mà không giết container.

- **Exercise 5.2 — Graceful Shutdown (`SIGTERM`)** (`05-scaling-reliability/develop/app.py`):
  - Khi deploy bản mới hoặc scale down, nền tảng gửi tín hiệu **`SIGTERM`** (khác `SIGKILL` không thể bắt).
  - App theo dõi `_in_flight_requests` qua middleware; khi vào nhánh shutdown của `lifespan`, đặt `_is_ready = False` (để `/ready` trả 503, ngừng nhận request mới), chờ toàn bộ request đang xử lý hoàn tất (tối đa `timeout_graceful_shutdown=30s`), rồi mới thoát sạch → không cắt ngang request của user, đạt zero-downtime deployment.

- **Exercise 5.3 — Thiết kế Stateless với Redis** (`05-scaling-reliability/production/app.py`):
  - **Vì sao lưu state trong RAM bị hỏng khi chạy nhiều instance?** Khi có 3 instance sau Load Balancer (round-robin), request 1 của user A vào Instance 1 (lưu session trong RAM của Instance 1), nhưng request 2 lại được điều phối sang Instance 2 → Instance 2 không có session của user A, làm mất ngữ cảnh hội thoại (và nếu restart 1 instance thì mất sạch state).
  - **Giải pháp:** Đưa toàn bộ session/conversation history ra **Redis** (`save_session` dùng `SETEX session:<id> <ttl> <json>`, `load_session` dùng `GET`), giúp mọi instance đều đọc/ghi chung một nguồn dữ liệu nhất quán.

- **Exercise 5.4 & 5.5 — Kết quả chạy Load Balanced Stack (`--scale agent=3`) & `test_stateless.py`:**
  - Khởi động stack trong `05-scaling-reliability/production/` bằng `docker compose -p k5-day14-scaling up -d --build --scale agent=3` (gồm 1 `redis`, 3 `agent`, 1 `nginx` mở cổng `8080`).
  - Kết quả chạy `python test_stateless.py` (5 request liên tiếp trên cùng `Session ID: 79d62270-8a38-48a6-a41a-15ffb7e69b61`):
```text
Session ID: 79d62270-8a38-48a6-a41a-15ffb7e69b61

Request 1: [instance-24afe9]  Q: What is Docker?
Request 2: [instance-90198e]  Q: Why do we need containers?
Request 3: [instance-cc5794]  Q: What is Kubernetes?
Request 4: [instance-24afe9]  Q: How does load balancing work?
Request 5: [instance-90198e]  Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-24afe9', 'instance-90198e', 'instance-cc5794'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10 (5 user + 5 assistant)
✅ Session history preserved across all instances via Redis!
```
  - **Giải thích kết quả:** Nginx phân phối lần lượt 5 request tới cả 3 instance khác nhau (`instance-24afe9`, `instance-90198e`, `instance-cc5794`), nhưng khi truy vấn `GET /chat/{session_id}/history` vẫn nhận đủ **10 messages** theo đúng thứ tự nhờ state được lưu tập trung trong Redis. Sau đó đã dọn stack bằng `docker compose -p k5-day14-scaling down`.

## Part 6: Final Project — Checklist Deliverable

Kết quả chạy `python check_production_ready.py` trong `06-lab-complete/` (WSL2 + Docker):

```text
🔎 Kiểm tra /mnt/d/project/ai20k-vin/lab14/K5-L3B-DAY14-LeHienHieu-2A202603940-Deployment-Benchmark-Observability/06-lab-complete
  ⏳ Kiểm tra tĩnh: file, Dockerfile, compose, config, code...
  ⏳ Chuẩn bị Redis cho bài test stateless...
  ⏳ Khởi động agent: uvicorn app.main:app --workers 2 (Redis: container redis:7-alpine tạm thời)
  ⏳ Restart agent để kiểm tra stateless...
  ⏳ Kiểm tra readiness khi Redis mất kết nối...
  ⏳ Kiểm tra cost guard (budget ≈ 0)...
  ⏳ Kiểm tra graceful shutdown (SIGTERM)...
  ⏳ Build Docker image prod-check:ff696321 (Docker 29.9.2) — lần đầu có thể mất vài phút...

================================================================
  Production Readiness Check — Day 14 Lab
================================================================

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 4s
     ✅ Docker: image < 500 MB — 297 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 12 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.6s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 42/42 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

- Kích thước Docker image thực tế: **297 MB** (< 500 MB), thời gian build 34s, `docker stop` thoát êm với exit code 0 trong **0.6s**.

## AI Log
- **CP1:** Hỏi AI tóm tắt mục tiêu bài lab, lộ trình theo các checkpoint K5 và hỗ trợ tổng hợp bảng so sánh Part 1 dựa trên code trong `01-localhost-vs-production/` và output `curl` tự chạy trên máy. Tự kiểm tra bằng cách chạy cả hai bản `develop` và `production` trong WSL2 và đối chiếu lại các dòng code trong `app.py` và `config.py`.
- **CP2:** Hỏi AI xử lý lỗi `permission denied` khi kết nối `docker.sock` trên WSL2 (`newgrp docker`) và tổng hợp câu trả lời Part 2 từ output build, `docker images`, `curl` container và stack Docker Compose tự chạy trên máy. Tự kiểm tra số liệu dung lượng image (`1.67GB` vs `240MB`) và test thực tế qua Nginx.
- **CP3:** Hỏi AI hướng dẫn lệnh test Part 4 (API Key, JWT `/auth/token`, vòng lặp kích hoạt 429) và tóm tắt cơ chế Cost Guard từ `04-api-gateway/production/cost_guard.py`. Tự chạy cả hai bản `develop` và `production` trong WSL2, xác minh mã HTTP 401/200/429 và che token trước khi lưu vào báo cáo.
- **CP4:** Hỏi AI hướng dẫn lệnh chạy stack scaling 3 instances và tổng hợp giải thích Part 5 (liveness/readiness, graceful shutdown, stateless Redis). Tự chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py` trên WSL2, xác nhận 5 request đi qua cả 3 instance và giữ đủ 10 message trong Redis.
- **CP5 (Part 6):** Tự triển khai phần lớn nhưng chỗ nào không hiểu vẫn phải nhờ AI hỗ trợ trong các file trong `06-lab-complete/`. Nhờ AI tóm tắt so sánh `railway.toml` vs `render.yaml` + pipeline Cloud Run. Tự kiểm tra toàn bộ bằng `python check_production_ready.py` (đầy đủ tĩnh + runtime + Docker trong WSL2) và xác nhận đạt `PASS 12/12 (42/42 checks passed)`.
- **CP6:** Nhờ AI hướng dẫn các bước tạo và triển khai bài Lab lên Render.
- **CP7 & CP8:** Nhờ AI hỗ trợ chạy chuỗi benchmark/eval trong WSL2, bổ sung 2 entry `security-02` và `scaling-03` vào `KNOWLEDGE_BASE` trong `mock_llm.py` (đạt `23/23 = 100%, 0 regression`), sửa lỗi `PYTHONUSERBASE` trong `production/Dockerfile`, chạy Locust scaling (`scale_1` / `scale_3`) & fault injection kích hoạt 3 alert firing, và tổng hợp số liệu thật từ JSON/CSV/logs vào `BENCHMARK_REPORT.md`. Tự đối chiếu số liệu trong `BENCHMARK_REPORT.md` với file report và chụp ảnh Grafana, Jaeger, Prometheus Alerts.
