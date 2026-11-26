# Benchmark & Observability Report — Day 14

**Họ tên:** Trinh Gia Huy
**Ngày chạy:** 2026-11-27 (Part 7 Bước 1 — develop)
**Môi trường:** Laptop Intel Core i7-12700H, Windows 11 + WSL2 Ubuntu (20 vCPU, 7.6 GiB RAM cấp cho WSL), Python 3.11.18 (conda env `day14-lab`), Docker Desktop 28.1.1. Agent (1 process uvicorn) và load generator chạy trên cùng máy; log JSON của agent ghi ra file trên filesystem của WSL (`/tmp`).

Report JSON: `06-lab-complete/benchmark-observability/develop/reports/` (khi nộp chép ra `reports/` ở gốc repo).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency bình thường của một request khoảng 190–220 ms (p50/p95 khi không tải, mục 2.2 dòng `0`), ngưỡng 500 ms chừa ~2,3 lần headroom cho lúc tải cao mà người dùng vẫn thấy "tức thì" cho một câu trả lời ngắn. Đặt theo p95 (không theo average) để bắt được tail latency — xem mục 2.2. Trùng ngưỡng mặc định `--slo-p95-ms 500` của `load_test.py`. |
| Error rate `/ask` | < 2 % | Mock LLM có tỉ lệ lỗi upstream nền 1% (`MOCK_ERROR_RATE=0.01`), nên 2% là error budget cho phép gấp đôi mức nền trước khi coi là sự cố. Ngưỡng mặc định `--slo-error-rate 0.02`. |
| Accuracy trên golden dataset | ≥ 85 % | Dùng làm quality gate trong CI (`.github/workflows/eval.yml`, `--min-accuracy 0.85`): cho phép sai tối đa 3/23 câu để gate không quá khắt khe với keyword matching, nhưng vẫn chặn được regression lớn (v1 chỉ đạt 4,3%). Khi sửa KB thì yêu cầu chặt hơn: 100% và không regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (cấu hình mock mặc định: `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.86 | 188.8 | 227.4 | 1694.5 | 2.00% (6/300 × 503) | PASS |
| 10 | 34.71 | 190.0 | 222.1 | 1703.6 | 0.67% (2/300 × 503) | PASS |
| 50 | 103.36 | 195.6 | 278.8 | 1714.5 | 1.33% (4/300 × 503) | PASS |
| 100 | 87.19 | 344.9 | 2566.6 | 2733.1 | 1.00% (3/300 × 503) | **FAIL** (p95) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Từ 1 → 10: gần tuyến tính** (3.86 → 34.71 req/s, ×9,0 với ×10 concurrency) và p50/p95 gần như không đổi (~190/~225 ms). Mỗi request chủ yếu là `await asyncio.sleep(...)` mô phỏng chờ LLM, nên event loop xử lý được nhiều request song song mà gần như không tốn CPU. Với concurrency 1, RPS ≈ 1000 / latency trung bình (~250 ms tính cả request chậm, lỗi và overhead client).
- **Từ 10 → 50: tăng chậm lại** (34.71 → 103.36, chỉ ×3,0 với ×5 concurrency), p95 bắt đầu tăng (222.1 → 278.8 ms) — request đã phải chờ CPU.
- **Từ 50 → 100: bão hoà và tụt** (103.36 → 87.19 req/s), p50 tăng gấp ~1,8 (195.6 → 344.9 ms), **p95 vọt lên 2566.6 ms, vi phạm SLO**. Agent chỉ có **1 process uvicorn / 1 event loop**: phần CPU của mỗi request (parse/validate Pydantic, serialize JSON, cập nhật Prometheus metrics, ghi log JSON đồng bộ) chạy tuần tự trên một core, nên khi số request đồng thời vượt khả năng xử lý thì request xếp hàng — latency tăng thay vì throughput tăng (định luật Little: in-flight = RPS × latency). Load generator chạy cùng máy cũng tranh CPU, và 300 request với 100 kết nối chỉ là ~3 "vòng", nên chi phí mở 100 kết nối mới dồn vào cùng lúc.
- **p99 ~1,7 s ở mọi mức** là do 3% request bị chậm thêm 1500 ms (`MOCK_SLOW_RATE=0.03`) — không phải do tải.
- Quan sát thêm về phương pháp đo: lần chạy đầu, log của agent ghi vào file nằm trên ổ Windows (`/mnt/c`, đi qua lớp 9p chậm) → ở concurrency 100 chỉ đạt 54.08 req/s, p95 3924.1 ms. Chuyển log sang filesystem của WSL thì lên 87.19 req/s, p95 2566.6 ms (số trong bảng). Ghi log đồng bộ trong event loop là một nút thắt thật: production nên dùng log handler bất đồng bộ / ghi ra stdout để agent của platform thu gom.
- **Cách tăng throughput:** chạy nhiều worker (`uvicorn --workers N`) hoặc nhiều instance sau load balancer (Part 5, mục 5 của báo cáo này ở CP8).

### 2.2 Tail latency

Lệnh: khởi động lại agent v2 với `MOCK_SLOW_RATE=<x>`, rồi `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 191.4 | 219.7 | 225.2 |
| 0.03 (mặc định) | 227.5 | 223.6 | 1690.0 |
| 0.1 | 377.5 | 1693.1 | 1716.0 |

(Thêm: p90 lần lượt 214.6 / 217.4 / 1668.4 ms; SLO p95 ≤ 500 ms: PASS / PASS / **FAIL**.)

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **0 → 0.03 (3% request chậm thêm 1500 ms):** avg chỉ tăng **36.1 ms** (+19%, đúng cỡ 3% × 1500 ms ≈ 45 ms), p95 gần như không đổi (+3.9 ms) vì 3% < 5%, nhưng **p99 tăng từ 225.2 lên 1690.0 ms (×7,5)** — 1% request chậm nhất rơi đúng vào nhóm bị chậm. → **p99 là chỉ số nhạy nhất**.
- **0.1 (10% > 5%):** nhóm request chậm đã lấn qua cả p95 và p90 → **p95 = 1693.1 ms, vi phạm SLO**, trong khi avg = 377.5 ms vẫn trông "dưới 500 ms, ổn".
- **Vì sao không đặt SLO theo average:** average bị số đông request nhanh kéo xuống nên che giấu tail latency. Với `MOCK_SLOW_RATE=0.03`, avg 227.5 ms trông tốt nhưng cứ 100 người dùng thì ~3 người phải chờ ~1,7 s; với 0.1 thì avg vẫn < 500 ms dù 10% người dùng chờ gần 2 giây. SLO đặt theo **p95/p99** phản ánh trải nghiệm của nhóm người dùng tệ nhất — và với một người dùng gửi nhiều request, xác suất gặp ít nhất một request "p99" là rất cao.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Lệnh:
```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json
# sửa KNOWLEDGE_BASE, tắt rồi bật lại v2
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
```

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.4 | 108.8 | 113.7 |
| Tổng cost (USD) | 0.000409 | 0.000757 | 0.00079 |
| Cost / câu đúng (USD) | 0.00040875 | 0.00003607 | 0.00003436 |
| Latency p50 / p95 (ms) | 173.2 / 189.2 | 185.8 / 213.7 | 187.1 / 221.2 |
| Quality gate | FAIL (accuracy < 80%) | PASS (≥ 80%, 0 regression so với v1) | PASS (≥ 100%, 0 regression so với v2) |

v1 chỉ đúng `basic-01` (câu "Deploy nghĩa là gì?" trùng câu trả lời có sẵn); v2 cải thiện 20 câu, không câu nào bị regression.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` — "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | `KNOWLEDGE_BASE` không có tài liệu nào về JWT → retrieval trả rỗng, agent trả lời chung chung. Thêm entry kích hoạt bằng từ khoá `jwt`: *"API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database."* |
| `scaling-03` — "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Thêm entry kích hoạt bằng `hpa` / `kubernetes` / `autoscal`: *"Kubernetes HPA (Horizontal Pod Autoscaler) scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi."* |

Để **không có regression**: từ khoá kích hoạt mới (`jwt`, `hpa`, `kubernetes`, `autoscal`) không xuất hiện trong câu hỏi nào khác của golden dataset, nên không câu nào khác bị lấy nhầm tài liệu (eval cuối: "Câu bị regression: 0"). Không sửa `golden_dataset.jsonl`. Hai entry cũng được chép sang `production/utils/mock_llm.py` để stack Docker ở Part 7 Bước 2 trả lời giống bản develop.

**Quality gate trong CI:** `.github/workflows/eval.yml` chạy trên mỗi pull request: cài dependencies, bật agent v2 với `MOCK_ERROR_RATE=0` (tránh fail ngẫu nhiên), rồi `python eval/run_eval.py --min-accuracy 0.85`. `run_eval.py` trả **exit code 1** khi accuracy < ngưỡng hoặc có regression so với `--baseline` → step fail → job fail; đặt job làm *required status check* trong branch protection thì PR không merge được. Đã chạy thử đúng các lệnh của job ở local: accuracy 100% (23/23), exit code 0.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 tăng accuracy từ 4.35% lên 91.3% (+87 điểm %) nhờ bước retrieval (RAG) đưa đúng tài liệu vào prompt.
- **Chi phí:** prompt của v2 dài hơn vì chứa tài liệu → avg tokens/câu tăng 89.5% (57.4 → 108.8), tổng cost tăng 85% (0.000409 → 0.000757 USD).
- **Latency:** v2 chậm hơn không đáng kể — p95 +24.5 ms (189.2 → 213.7 ms), do thêm bước retrieval (~20 ms) và prompt dài hơn (latency mock tăng theo số token input) — vẫn xa ngưỡng SLO 500 ms.
- **Kết luận:** tính theo **cost / câu đúng**, v2 rẻ hơn v1 **~11,3 lần** (0.00040875 → 0.00003607 USD), và sau khi sửa KB còn 0.00003436 USD. "Cost / câu" chỉ ra v1 rẻ hơn, nhưng câu trả lời sai thì rẻ đến đâu cũng là lãng phí — nên khi so 2 phiên bản phải dùng cost / câu đúng, đặt cạnh accuracy và p95.

---

## 4. Observability stack (production)

_(Part 7 Bước 2 — điền ở CP8.)_

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

_(Điền ở CP8 từ `production/benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`.)_

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

_(Hoàn thiện sau CP8.)_

- 3 điều bạn học được về benchmark & observability:
  1. Average che giấu tail latency: với 3% request chậm, avg chỉ tăng 36 ms nhưng p99 tăng ×7,5 — SLO phải đặt theo p95/p99.
  2. Throughput của một process async không tăng mãi theo concurrency: agent bão hoà ở khoảng 50–100 request đồng thời (RPS tụt từ 103 xuống 87, p95 vọt lên 2,6 s); ngay cả việc ghi log đồng bộ ra đĩa chậm cũng làm giảm throughput rõ rệt.
  3. So sánh phiên bản phải nhìn cả chất lượng lẫn chi phí: v2 tốn gần gấp đôi token mỗi câu nhưng cost / câu đúng rẻ hơn ~11 lần; eval + quality gate trong CI chặn regression trước khi deploy.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...

---

## Phụ lục — Exercise 7.1: Đọc metrics của agent

Output thật của `curl -s http://localhost:8002/metrics | grep -v "^#"` (trích):

| Loại | Ví dụ | Ý nghĩa |
|---|---|---|
| Counter | `http_requests_total{method="POST",route="/ask",status="200"} 1189.0`, `llm_tokens_total`, `llm_cost_usd_total` | Chỉ tăng; tính tốc độ bằng `rate()` |
| Gauge | `agent_in_flight_requests`, `agent_info{model="mock-llm-small",version="v2"} 1.0` | Lên xuống được (số request đang xử lý) |
| Histogram | `http_request_duration_seconds_bucket{le="0.2",...}` + `_sum` + `_count` | Đếm request theo bucket latency → `histogram_quantile(0.95, ...)` ra p95 |

**Cardinality:** gửi thử 4 URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`, `/phpmyadmin`) → tất cả gộp vào **một** series `http_requests_total{method="GET",route="unmatched",status="404"} 4.0`. Nếu label dùng `request.url.path`, mỗi URL lạ của bot tạo series mới (nhân với method × status × 11 bucket latency) → hàng nghìn URL thành hàng chục nghìn time series, Prometheus tốn RAM và query chậm, có thể sập.

**Metric mới `agent_question_length_chars`** (thêm vào `develop/app.py`, Histogram buckets 20/50/100/200/500/1000/2000 ký tự, observe ở đầu `/ask`). Sau các bài load test: `_count 1204`, `_sum 47623` → câu hỏi trung bình ~39.6 ký tự; 1021/1204 câu ≤ 50 ký tự, tất cả ≤ 100 ký tự. Dùng Histogram thay vì label `length=...` vì độ dài có vô số giá trị → label sẽ làm cardinality bùng nổ.
