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

- [ ] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`)
- [ ] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [ ] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [ ] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

*(Điền sau CP8)*

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: *(điền sau CP8)*
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

*(Điền sau CP8)*

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. *(Điền sau CP8)*
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

*(Điền sau CP8)*
