# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được đo trực tiếp và khớp với các file JSON trong `reports/` và CSV trong `benchmark-results/`.

**Họ tên:** LeHienHieu (MSSV: 2A202603940)
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 + WSL2 (Ubuntu-24.04, Python 3.12.3) + Docker Desktop 29.9.2

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | 95% người dùng nhận phản hồi dưới nửa giây (trải nghiệm tương tác mượt); tránh để average che giấu tail latency |
| Error rate `/ask` | ≤ 2.0 % | Cho phép error budget 2% để chịu được lỗi upstream LLM ngẫu nhiên (~1%), nhưng chặn sự cố hệ thống lan rộng |
| Accuracy trên golden dataset | ≥ 80 % (mục tiêu 100%, 0 regression) | Đảm bảo chất lượng câu trả lời không suy giảm khi thay đổi prompt/model/knowledge base trước khi deploy |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 requests/mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.41 | 186.3 | 218.8 | 1698.7 | 1.00% | ✅ PASS |
| 10 | 44.57 | 185.8 | 218.8 | 1676.5 | 1.33% | ✅ PASS |
| 50 | 120.13 | 192.4 | 243.1 | 1679.7 | 1.67% | ✅ PASS |
| 100 | 67.41 | 314.7 | 2442.1 | 2687.5 | 1.67% | ❌ FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency:
- Từ concurrency `1 → 10`: RPS tăng gần như tuyến tính (`4.41 → 44.57 req/s`, ~10x) vì agent async xử lý tốt I/O song song và chưa chạm ngưỡng bão hòa.
- Lên `50`: RPS tăng chậm lại (`120.13 req/s`, chỉ tăng ~2.7x thay vì 5x), `p95` bắt đầu nhích lên `243.1 ms`.
- Lên `100`: hệ thống rơi vào trạng thái **bão hòa (saturation)** và xếp hàng (queuing) trên 1 worker uvicorn; RPS **tụt xuống** còn `67.41 req/s`, `p50` nhảy lên `314.7 ms`, `p95` vọt lên **`2442.1 ms`** → vi phạm SLO `p95 ≤ 500ms` (`FAIL`).

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.5 | 218.6 | 226.2 |
| 0.03 (mặc định) | 259.8 | 230.7 | 1696.8 |
| 0.1 | 310.9 | 1686.9 | 1703.4 |

**Nhận xét:**
- **Chỉ số nhạy nhất với request chậm là các percentile cao (`p99`, rồi tới `p95`)**:
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request chậm), `avg` chỉ tăng nhẹ `+70.3 ms` (`189.5 → 259.8 ms`) và `p95` hầu như không đổi (`230.7 ms`), nhưng **`p99` nhảy vọt hơn 7 lần** (`226.2 → 1696.8 ms`).
  - Khi `MOCK_SLOW_RATE = 0.1` (10% > 5% request chậm), `avg` mới chỉ là `310.9 ms` (trông vẫn dưới 500 ms!), nhưng **`p95` đã vọt lên `1686.9 ms`** (vi phạm SLO).
- **Vì sao SLO không nên đặt theo average?** Giá trị trung bình bị 90–97% request nhanh kéo xuống nên **che giấu trải nghiệm tệ của nhóm người dùng ở phần đuôi (tail latency)**. Đặt SLO theo `p95`/`p99` đảm bảo 95% hoặc 99% người dùng thực sự nhận được phản hồi nhanh.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | **100.0% (23/23)** |
| Avg tokens / câu | 57.1 | 109.0 | 115.2 |
| Tổng cost (USD) | $0.000404 | $0.000760 | $0.000804 |
| Cost / câu đúng (USD) | $0.00040395 | $0.00003619 | **$0.00003495** |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS (≥ 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`) với từ khóa `["jwt", "api key", "xác thực"]` giải thích JWT là token có chữ ký số và thời gian hết hạn so với API key tĩnh |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khóa `["kubernetes", "hpa"]` mô tả Kubernetes HPA tự động scale theo `CPU`, `memory` và `custom metrics` |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- `v2` thêm bước retrieval và đưa context vào prompt nên tốn **gấp ~2 lần số token mỗi câu** (`109.0–115.2` vs `57.1` tokens), tổng chi phí cao hơn ~2 lần (`$0.000804` vs `$0.000404`) và `p95` latency nhỉnh hơn ~16–30 ms (`200.4–214.7 ms` vs `184.4 ms`).
- Tuy nhiên, accuracy nhảy từ **4.3% → 100%**, kéo **cost / câu trả lời đúng giảm hơn 11 lần** (`$0.00040395` xuống `$0.00003495`). Vì vậy `cost / câu đúng` là thước đo chính xác hơn `cost / câu` khi so sánh hai phiên bản agent.

**Quality gate trong CI (Exercise 7.3):**
`eval/run_eval.py` trả về **exit code `0`** khi đạt `accuracy >= --min-accuracy` và không có câu nào regression so với `--baseline`, ngược lại trả về **exit code `1`**. Nhờ đó có thể gắn trực tiếp vào GitHub Actions để tự động chặn merge Pull Request khi chất lượng đi xuống:

```yaml
name: Agent Eval Quality Gate
on: [pull_request]
jobs:
  eval-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r 06-lab-complete/benchmark-observability/develop/requirements.txt
      - name: Start agent v2 and run quality gate
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          AGENT_VERSION=v2 PORT=8002 MOCK_ERROR_RATE=0 python app.py &
          PID=$!
          sleep 3
          python eval/run_eval.py --url http://localhost:8002 \
            --min-accuracy 0.95 --baseline reports/eval_v2.json
          EC=$?
          kill $PID
          exit $EC
```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [x] Trang Alerts của Prometheus với **3 alert cùng đang firing** (`screenshots/prometheus-alert-firing.png`)

**Trả lời Exercise 7.4 (Grafana & Nginx):**
- **Khoảng cách giữa `avg` và `p95`/`p99`:** Trên biểu đồ Latency, `avg` luôn nằm thấp hơn nhiều so với `p99` (và `p95` khi `MOCK_SLOW_RATE=0.3`) vì phần lớn request hoàn thành nhanh kéo trung bình xuống, còn phần đuôi tail latency phản ánh rõ nhóm request chậm (~1.7–1.9s).
- **Vì sao `input_tokens` > `output_tokens`:** Ở agent `v2` (RAG), prompt gửi tới LLM phải ghép thêm `SYSTEM_PROMPT` + tài liệu context lấy từ `KNOWLEDGE_BASE` + câu hỏi của user (~74–83 input tokens), trong khi câu trả lời ngắn gọn hơn (~37–46 output tokens).
- **Vì sao `/metrics` bị chặn ở Nginx (`404`):** Endpoint `/metrics` chứa thông tin nhạy cảm về nội bộ hệ thống (tên service, phiên bản, lưu lượng, chi phí, tỉ lệ lỗi) và chỉ nên cho Prometheus trong mạng nội bộ Docker scrape, không bao giờ để public ra Internet.

### 4.2 Thí nghiệm "phá hệ thống"

*(Chạy fault injection kết hợp trên stack `-p k5-day14-observability` với Locust 30 users; ghi nhận cả 3 alert cùng chuyển sang `FIRING` tại `http://localhost:9090/alerts`)*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, đạt **20.88%** > 5%) | **~112 giây** (~1p52s) | Golden Signals → **Error rate** (đỏ) & Requests/s theo status code (5xx tăng vọt) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, đạt **1.935s** > 1s) | **~160 giây** (~2p40s) | Golden Signals → **Latency p95** (đỏ) & Latency `/ask` p50/p95/p99 |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, đạt **$19.97/giờ** > $2/giờ) | **~22 giây** (từ lúc đổi model khi đã có tải trước đó; ~2p nếu chạy từ 0) | Golden Signals → **LLM cost** & LLM → Cost USD/giờ, LLM p95 |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`up{job="agent"} == 0`, `for: 30s`) | **~35–45 giây** (khi pause container, DNS vẫn giữ IP nhưng Prometheus không scrape được) | Golden Signals → **Instances** giảm; lưu ý lỗi 504 ở Nginx không hiện trên metric của agent vì request chưa tới/hoàn tất ở agent |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không firing | LLM → Retrieval hit ratio giảm về 0, tokens/s giảm, bảng `agent_info` đổi sang `v1` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
- Các alert hạ tầng (error rate, latency, instance up, cost) đều **xanh** vì agent `v1` vẫn trả HTTP `200` nhanh và thậm chí còn rẻ hơn `v2`, nhưng **chất lượng câu trả lời tụt từ 100% xuống 4.3%**.
- Để phát hiện trong production cần kết hợp:
  1. **Eval quality gate tự động trong CI/CD** (`eval/run_eval.py --baseline ...`) chặn deploy trước khi ra production.
  2. **Online evaluation & giám sát chất lượng (AI Observability):** chạy LLM-as-judge trên mẫu traffic thực tế, theo dõi `retrieval_hit_ratio` (đặt alert nếu tụt bất thường), và thu thập phản hồi người dùng (thumbs up/down, tỉ lệ hỏi lại).

### 4.3 Debug bằng trace

Chọn 1 trace chậm thực tế trong Jaeger (`http://localhost:16686/trace/e7f1334192992c7f97ee8a138ff18f31`):

- `trace_id`: `e7f1334192992c7f97ee8a138ff18f31`
- Tổng thời gian (`POST /ask`): **1906.7 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-large` (**1886.2 ms**, chiếm **98.9%** tổng thời gian request → nút thắt nằm ở upstream LLM, không phải code FastAPI hay retrieval ~20 ms).
- Dòng log JSON tương ứng (lấy từ `docker compose -p k5-day14-observability logs agent | grep e7f1334192992c7f97ee8a138ff18f31`):

```json
{"ts": "2026-11-26T09:23:54.931409+00:00", "level": "INFO", "service": "observable-agent", "instance": "55241ea41d71", "event": "llm_call", "trace_id": "e7f1334192992c7f97ee8a138ff18f31", "span_id": "d1abe1b9a8c84dce", "request_id": "87698614ef89", "model": "mock-llm-large", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 0.000555, "llm_ms": 1886.2}
{"ts": "2026-11-26T09:23:54.931671+00:00", "level": "INFO", "service": "observable-agent", "instance": "55241ea41d71", "event": "http_request", "trace_id": "e7f1334192992c7f97ee8a138ff18f31", "span_id": "d1abe1b9a8c84dce", "request_id": "87698614ef89", "method": "POST", "route": "/ask", "status": 200, "ms": 1906.7}
```

*(Trace lỗi tham khảo trong Jaeger: `trace_id = 921d5dd9b69bac44bc64023b37bd61b1`, event `llm_error`: `Upstream LLM error: 503 Service Unavailable (mock)`.)*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu khớp 100% với `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`, hàng `POST /ask` — tổng `Aggregated` đạt `65.51` và `65.99 req/s`)*

| Số instance | RPS (`POST /ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.41 | 190 | 220 | 1700 | 61 / 7099 (0.86%) |
| 3 | 60.22 | 190 | 220 | 1700 | 84 / 7197 (1.17%) |

**Giải thích kết quả:**
- Scale từ **1 lên 3 instance** giữ nguyên gần như hoàn toàn `p50` (`190 ms`), `p95` (`220 ms`), `p99` (`1700 ms`) và chỉ tăng nhẹ RPS (`59.41 → 60.22 req/s`).
- **Nút thắt nằm ở đâu?** Nút thắt nằm ở **upstream LLM latency** (IO-bound chờ `mock-llm` mất ~120–180 ms + 3% request chậm ~1500 ms) và tốc độ sinh tải của 100 Locust user có `wait_time`, chưa làm bão hòa CPU/event loop của 1 instance FastAPI async. Scale ngang chỉ cải thiện độ trễ khi nút thắt là CPU/queuing ở tầng agent (như ở mức `concurrency=100` không có `wait_time` trong CP7), còn để giảm latency do LLM thì cần tối ưu prompt, cache kết quả (Redis), streaming hoặc đổi model nhanh hơn.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Tail latency (`p95`/`p99`) quan trọng hơn `average`:** 3–10% request chậm hầu như không làm thay đổi giá trị trung bình nhưng phá vỡ trải nghiệm người dùng và làm vi phạm SLO.
  2. **Đo chất lượng (`eval`) là bắt buộc song hành với đo hạ tầng:** Metric/alert hạ tầng hoàn toàn không phát hiện được regression chất lượng (như thí nghiệm E đổi sang `v1`); cần golden dataset + quality gate trong CI và so sánh theo `cost / câu đúng`.
  3. **3 trụ cột Metrics – Traces – Logs liên kết chặt chẽ:** Prometheus/Grafana báo *có vấn đề*, Jaeger chỉ rõ *chậm/lỗi ở span nào* (`chat mock-llm-*` chiếm 98.9%), và `trace_id` giúp grep ngay dòng JSON log chi tiết.
- **Nếu đưa agent này lên production thật, sẽ thêm các metric / alert:**
  - **Nginx / Load Balancer metrics** (tỉ lệ `502`/`504`, upstream timeout) để bắt các lỗi mà chính agent không nhìn thấy.
  - **Redis & Rate-limit / Cost-guard metrics** (`rate_limit_hits_total`, `budget_exceeded_total`, Redis latency) để phát hiện sớm lạm dụng API hoặc chạm trần ngân sách.
  - **AI Quality metrics** (`retrieval_hit_ratio` alert khi tụt dưới ngưỡng, điểm online LLM-as-judge và tỉ lệ feedback tiêu cực của người dùng).
