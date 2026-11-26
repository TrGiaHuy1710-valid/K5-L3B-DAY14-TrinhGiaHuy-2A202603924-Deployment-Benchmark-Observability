# Day 14 Lab - Mission Answers

> Môi trường chạy: Windows 11 + Docker Desktop 28.1.1 (engine dùng chung với WSL2 Ubuntu 22.04), Docker Compose v2.35.1, Python 3.11 (FastAPI 0.139, uvicorn 0.51 ở local).
> Mọi output dưới đây là kết quả chạy thật ngày 2026-11-26.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | **Hardcode secret**: `OPENAI_API_KEY = "sk-hardcoded-..."` | 17 | Push lên GitHub là lộ key; đổi key phải sửa code và deploy lại |
| 2 | **Hardcode connection string có mật khẩu**: `DATABASE_URL = "postgresql://admin:password123@..."` | 18 | Lộ mật khẩu DB; trỏ cứng vào `localhost` nên lên cloud không kết nối được |
| 3 | **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log, ai đọc được log là có key (đã thấy thật ở log Exercise 1.2) |
| 4 | **Dùng `print()` thay vì logging có cấu trúc**, không có level, không có timestamp | 33, 34, 38 | Không lọc/tìm kiếm được trong log aggregator; không tắt được log debug ở production |
| 5 | **Debug bật cứng**: `DEBUG = True`, `reload=True` | 21, 53 | Reloader theo dõi file, tốn tài nguyên và có thể restart giữa chừng ở production |
| 6 | **Bind `host="localhost"`** | 51 | Trong container/cloud không nhận được kết nối từ bên ngoài (phải là `0.0.0.0`) |
| 7 | **Port cứng `port=8000`**, không đọc biến `PORT` | 52 | Railway/Render cấp port qua `PORT` → app nghe sai cổng, healthcheck fail |
| 8 | **Không có health check** (`/health`, `/ready`) | — | Platform không biết app còn sống/sẵn sàng để restart hay route traffic (thực tế `GET /health` → 404) |
| 9 | **Không xử lý shutdown** (không lifespan, không bắt SIGTERM) | — | Khi platform tắt/redeploy, request đang chạy bị cắt ngang |
| 10 | **Không có config management**: `MAX_TOKENS = 500` và các config khác rải trong code | 22 | Mỗi môi trường (dev/staging/prod) phải sửa code |

### Exercise 1.2: Chạy basic version

Bản develop nhận `question` qua **query string** (`def ask_agent(question: str)`), nên lệnh JSON trong `CODE_LAB.md` trả 422:

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
```

Log server — **secret bị in thẳng ra log**:

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12304] using StatReload
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
INFO:     127.0.0.1:52151 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Nhận xét:** app chạy được, nhưng chưa production-ready: lộ key trong log, chỉ nghe `localhost:8000`, chạy reloader, không có `/health`.

### Exercise 1.3: Comparison table

Bản production (`01-localhost-vs-production/production/`) chạy với `PORT=8010`:

```text
$ curl -i http://localhost:8010/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":3.2,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:19:31.010533+00:00"}

$ curl -i http://localhost:8010/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://localhost:8010/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}

$ curl -i -X POST http://localhost:8010/ask -H "Content-Type: application/json" -d '{}'
HTTP/1.1 422 Unprocessable Entity
{"detail":"question field is required"}
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode trong code (dòng 17–22) | Đọc env qua `config.py` (dataclass + `os.getenv`), có `.env.example` | Cùng một code chạy được ở dev/staging/prod chỉ bằng đổi env; secret không bao giờ vào Git |
| **Secrets** | Key nằm trong code và bị in ra log | Lấy từ env; `validate()` **fail fast** khi `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` (`config.py:43`) | Lộ key = mất tiền/bị lạm dụng; fail fast giúp phát hiện cấu hình thiếu ngay lúc start chứ không phải lúc có user |
| **Health check** | Không có (`/health` → 404) | `/health` (liveness, `app.py:136`) + `/ready` (readiness, `app.py:153`) | Platform dùng `/health` để quyết định restart, load balancer dùng `/ready` để quyết định có gửi traffic vào không |
| **Logging** | `print()` | `logging` với format JSON, không log secret, chỉ log độ dài câu hỏi | Log có cấu trúc thì parse/search/alert được trong Datadog, Loki; không log dữ liệu nhạy cảm |
| **Shutdown** | Đột ngột | `lifespan` (startup/shutdown, `app.py:40`) + handler SIGTERM (`app.py:189`) | Khi redeploy/scale down, request đang xử lý được hoàn thành, connection được đóng sạch |
| **Host / Port** | `localhost:8000` cứng | `HOST=0.0.0.0`, `PORT` từ env (`app.py:196–197`) | Container và cloud bắt buộc nghe `0.0.0.0` và đúng port platform cấp |
| **Debug / reload** | `reload=True` luôn bật | `reload=settings.debug`, mặc định `false` | Reloader chỉ dành cho dev; ở production tốn tài nguyên và có thể restart bất ngờ |
| **Input API** | Query string `?question=` | JSON body `{"question": ...}`, thiếu field → 422 | JSON body là chuẩn cho REST API, mở rộng thêm field (user_id, …) dễ hơn |
| **CORS** | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ cho frontend được phép gọi API |

**Hai điểm bản production vẫn chưa ổn (phát hiện khi chạy thử):**

1. **Log JSON của app không hiện ra.** `config.py:45` gọi `logging.warning(...)` lúc import, trước khi `app.py:28` gọi `logging.basicConfig(...)`. Lần gọi `logging.warning` đầu tiên đã tự cấu hình root logger (level WARNING, format mặc định), nên `basicConfig` sau đó không còn tác dụng. Kết quả: log chỉ có `WARNING:root:OPENAI_API_KEY not set — using mock LLM`, các dòng `logger.info(...)` dạng JSON bị nuốt. Cách sửa: gọi `basicConfig(..., force=True)` hoặc cấu hình logging trước khi import `config`.
2. **Body không phải JSON → 500.** Gọi `POST /ask?question=Hello` (body rỗng) thì `await request.json()` (`app.py:104`) ném `JSONDecodeError`, không được bắt nên trả `500 Internal Server Error`. Nên dùng Pydantic model cho body để FastAPI tự trả 422.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

File: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (dòng 8) — bản Python đầy đủ trên Debian, có sẵn compiler và nhiều thư viện hệ thống, nên rất nặng.
2. **Working directory:** `/app` (dòng 11). Các lệnh `COPY`, `RUN`, `CMD` sau đó chạy tương đối với thư mục này.
3. **Tại sao `COPY requirements.txt` trước `COPY app.py`:** Docker cache theo từng layer, layer nào thay đổi thì nó và mọi layer sau phải build lại. `requirements.txt` ít thay đổi, còn code thay đổi liên tục. Copy requirements + `pip install` trước (dòng 14, 17) thì khi chỉ sửa code, layer cài dependencies vẫn lấy từ cache, build chỉ mất vài giây thay vì cài lại toàn bộ package.
4. **CMD vs ENTRYPOINT:**
   - `CMD` là lệnh/tham số **mặc định**, bị ghi đè hoàn toàn khi chạy `docker run image <lệnh khác>`.
   - `ENTRYPOINT` là lệnh **cố định** của container; tham số truyền vào `docker run image <args>` được nối vào sau ENTRYPOINT (chỉ đổi được bằng `--entrypoint`).
   - Hay dùng kết hợp: `ENTRYPOINT ["uvicorn"]` + `CMD ["main:app", "--port", "8000"]` → CMD đóng vai tham số mặc định.
   - Nên dùng exec form (`["python", "app.py"]`) để process là PID 1 và nhận được SIGTERM khi `docker stop`.

### Exercise 2.2: Build và run

Build **từ gốc repo** (Dockerfile `COPY` theo đường dẫn tính từ gốc):

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --rm --name p2dev -p 8011:8000 my-agent:develop

$ curl -i -X POST "http://localhost:8011/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8011/health
{"status":"ok","uptime_seconds":6.2,"container":true}

$ docker exec p2dev whoami
root
```

(App develop của Part 2 cũng nhận `question` qua query string. Container chạy bằng **root**.)

### Exercise 2.3: Multi-stage build và image size comparison

**Lỗi gặp khi build bản production và cách xử lý:**

- Build từ trong `02-docker/production/` (`docker build -f Dockerfile .`) → lỗi `"/02-docker/production/requirements.txt": not found`, vì build context là thư mục con còn Dockerfile `COPY` theo đường dẫn từ gốc repo. Sửa: build từ gốc repo.
- Bước `RUN apt-get update` lỗi `401 VG-AuthenticationRequired [IP: 10.140.122.12 9090]`: mạng đang dùng có gateway chặn HTTP, mà apt của `python:3.11-slim` (Debian trixie) tải qua `http://deb.debian.org`. Kiểm tra từ host: HTTP trả 302 (chuyển sang trang đăng nhập), HTTPS trả 200. Sửa: thêm `sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources` trước `apt-get update` (`02-docker/production/Dockerfile:22`).

**Stage 1 (`builder`, dòng 16–31):** từ `python:3.11-slim`, cài build tools (`gcc`, `libpq-dev`), rồi `pip install --user` vào `/root/.local`. Stage này chỉ để build, **không được ship**.

**Stage 2 (`runtime`, dòng 38–74):** bắt đầu lại từ một `python:3.11-slim` sạch, tạo user `appuser` (non-root), **chỉ copy** thư mục package đã cài (`COPY --from=builder /root/.local ...`) và source code, chạy bằng `USER appuser`, có `HEALTHCHECK`, `CMD` dạng exec form chạy uvicorn 2 workers.

**Tại sao image nhỏ hơn:**
- Base `python:3.11-slim` (125.1 MB) thay vì `python:3.11` full: bỏ compiler, header, tài liệu, nhiều thư viện hệ thống.
- `gcc`, `libpq-dev`, apt cache và pip cache chỉ nằm ở stage builder, bị bỏ lại; stage runtime chỉ nhận layer package 37.8 MB (đo bằng `docker history my-agent:advanced`).
- Bonus bảo mật: chạy bằng `appuser`, image ít package hơn → ít lỗ hổng (CVE) hơn.

```text
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
$ docker images my-agent
REPOSITORY   TAG        IMAGE ID       CREATED          SIZE
my-agent     advanced   f41fac004990   3 minutes ago    163MB
my-agent     develop    f6894c2f712a   17 minutes ago   1.15GB

$ docker image inspect my-agent:develop  --format '{{.Size}}'   → 1154311927 bytes
$ docker image inspect my-agent:advanced --format '{{.Size}}'   → 162882434 bytes
```

| Image | Size |
|---|---:|
| Develop (`python:3.11`, single-stage) | **1154.3 MB** |
| Production (`python:3.11-slim`, multi-stage) | **162.9 MB** |
| Chênh lệch | **giảm 85.9%** (nhỏ hơn ~7.1 lần) |

Cách tính: `(1154.3 − 162.9) / 1154.3 = 85.9%`.

Chạy container production:

```text
$ docker run -d --rm --name p2adv -p 8012:8000 my-agent:advanced
$ curl -i -X POST http://localhost:8012/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ docker ps   → p2adv   Up 6 seconds (healthy)     ← HEALTHCHECK hoạt động
$ docker exec p2adv whoami
appuser
```

Nhận xét log: dòng `{"time":"...","level":"INFO","msg":"{"event": "request", "q_len": 15}"}` **không phải JSON hợp lệ**, vì `json.dumps(...)` được nhét vào trong `"msg":"%(message)s"` mà không escape dấu `"`. Muốn log JSON đúng chuẩn phải dùng formatter tự `json.dumps` cả record (sẽ làm ở Part 6).

### Exercise 2.4: Docker Compose stack

Chạy trong `02-docker/production/` (compose tự đặt `context: ../..`):

```text
$ touch .env.local
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 15 seconds (healthy)   8000/tcp
nginx     nginx:alpine            Up 15 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 26 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 26 seconds (healthy)   6379/tcp
```

**Architecture diagram:**

```text
                    Host (máy của bạn)
                         │  :80 / :443  (cổng DUY NHẤT được publish)
                         ▼
 ┌──────────────── network "internal" (bridge, 172.21.0.0/16) ────────────────┐
 │                                                                            │
 │   ┌──────────────────┐    proxy_pass       ┌──────────────────────────┐    │
 │   │ nginx            │ ──────────────────► │ agent  (FastAPI, :8000)  │    │
 │   │ 172.21.0.5       │  upstream           │ 172.21.0.4               │    │
 │   │ reverse proxy,   │  agent_backend      │ uvicorn --workers 2      │    │
 │   │ rate limit 10r/s,│  (round-robin)      │ user appuser, healthcheck│    │
 │   │ security headers │                     └──────┬─────────────┬─────┘    │
 │   └──────────────────┘          REDIS_URL         │             │ QDRANT_URL
 │                          redis://redis:6379/0     ▼             ▼          │
 │                              ┌────────────────────────┐ ┌───────────────┐  │
 │                              │ redis (:6379)          │ │ qdrant (:6333)│  │
 │                              │ 172.21.0.2             │ │ 172.21.0.3    │  │
 │                              │ cache/session/ratelimit│ │ vector DB/RAG │  │
 │                              │ volume redis_data      │ │ volume        │  │
 │                              └────────────────────────┘ │ qdrant_data   │  │
 │                                                         └───────────────┘  │
 └────────────────────────────────────────────────────────────────────────────┘
```

**Services và cách chúng giao tiếp:**
- **4 service**: `nginx`, `agent`, `redis`, `qdrant`, cùng nằm trong network bridge `internal`. Các container gọi nhau bằng **tên service** nhờ DNS nội bộ của Docker (`agent:8000`, `redis:6379`, `qdrant:6333`).
- Chỉ **nginx** publish cổng ra host (80/443). `agent`, `redis`, `qdrant` không publish cổng (`docker port k5-day14-docker-agent-1` không trả gì) → bên ngoài không gọi thẳng vào agent hay DB được.
- **Thứ tự khởi động:** `agent` có `depends_on` với `condition: service_healthy` → đợi `redis` (`redis-cli ping`) và `qdrant` healthy rồi mới start (thấy rõ trong log `up`: redis/qdrant `Healthy` → agent `Started` → nginx `Started`).
- Agent nhận địa chỉ Redis/Qdrant qua env (`REDIS_URL`, `QDRANT_URL`), secret đọc từ `.env.local` (nằm trong `.gitignore`).
- Ghi chú: `main.py` của bài mẫu chưa thực sự dùng Redis/Qdrant (requirements chỉ có `fastapi`, `uvicorn`); hai service này minh hoạ kiến trúc đầy đủ. Part 6 mới dùng Redis thật cho rate limit và cost guard.

**Test qua Nginx:**

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
{"status":"ok","uptime_seconds":19.7,"version":"2.0.0","timestamp":"2026-11-26T08:21:47.664964"}

$ curl -i http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Các header `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection` do Nginx thêm vào → chứng minh request đi qua Nginx rồi mới tới agent. Log agent cho thấy request đến từ IP của nginx (`172.21.0.5`), không phải từ host.

Dọn stack: `docker compose -p k5-day14-docker down`.

---

## Part 3: Cloud Deployment

Theo lịch K5, Part 3 làm sau Part 6 và deploy luôn agent Part 6 (`06-lab-complete/`), không deploy app mẫu trong `03-cloud-deployment/`. Chi tiết cấu hình, biến môi trường, lệnh test và ảnh: [DEPLOYMENT.md](DEPLOYMENT.md).

### Exercise 3.1: Railway deployment (nền tảng chính)

- **URL:** https://k5-l3b-day14-trinhgiahuy-2a202603924-deployment-production.up.railway.app
- **Cách deploy:** Railway → New Project → GitHub Repository (repo này) → Settings: Root Directory = `06-lab-complete`, Railway Config File = `/06-lab-complete/railway.toml` → thêm Database Redis → Variables: `AGENT_API_KEY` (secret), `REDIS_URL=${{Redis.REDIS_URL}}`, `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`, `LOG_LEVEL=INFO` (không đặt `PORT`) → Deploy → Networking → Generate Domain.
- **Bốn lệnh tự kiểm của CP6:**

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200
```

```text
$ curl "$BASE/health"   → {"status":"ok","environment":"production"}
$ curl "$BASE/ready"    → {"ready":true,"redis":"ok"}
$ python check_production_ready.py --public-url "$BASE"
     ✅ Public URL: GET https://k5-l3b-day14-trinhgiahuy-2a202603924-deployment-production.up.railway.app/health → 200
```

- **Screenshots:** [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)

**Sự cố gặp khi deploy:**
1. Lần deploy đầu build lỗi vì Railway lấy `Dockerfile` ví dụ Go ở gốc repo → đặt Root Directory `06-lab-complete`. Railway **không** tự tìm `railway.toml` theo Root Directory nên phải khai báo đường dẫn đầy đủ `/06-lab-complete/railway.toml`.
2. `/ask` có key trả **500**: biến `AGENT_API_KEY` trên Railway bị điền nhầm chuỗi mẫu có dấu tiếng Việt. `hmac.compare_digest(str, str)` ném `TypeError` với chuỗi non-ASCII → 500. Không gửi key thì vẫn 401 vì code trả 401 trước khi tới bước so sánh, nên lỗi chỉ lộ ra khi có key. Sửa: đặt lại key hex thật, và đổi `app/auth.py` sang so sánh bytes (`compare_digest(a.encode(), b.encode())`) để mọi key sai — kể cả có dấu — đều trả 401. Sau khi sửa, gửi `X-API-Key: khóa-sai` lên URL public trả 401.

### Exercise 3.2: So sánh `railway.toml` với `render.yaml` (nền tảng còn lại)

So sánh `06-lab-complete/railway.toml` (file mình dùng để deploy) với `03-cloud-deployment/render/render.yaml` (Blueprint mẫu của Render):

| Khía cạnh | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng | TOML | YAML (Render Blueprint) |
| Phạm vi | Cấu hình **một service**: cách build và deploy service đó | **Toàn bộ hạ tầng** của project: liệt kê nhiều service (`type: web` + `type: redis`) |
| Cách build | `builder = "DOCKERFILE"` → dùng Dockerfile multi-stage, môi trường giống hệt lúc chạy local / Docker Compose | `runtime: python` + `buildCommand: pip install ...` + `startCommand: uvicorn ...` → Render tự dựng môi trường Python, không cần Dockerfile (muốn dùng Docker phải đổi `runtime: docker`) |
| Lệnh chạy | Không có `startCommand`, dùng `CMD` trong Dockerfile (`--port ${PORT:-8000}`) | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 60` | `healthCheckPath: /health` |
| Tự khởi động lại | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Do Render quản lý, không khai báo trong file |
| Redis | **Không** khai báo trong file — thêm bằng dashboard (Database → Redis) và nối bằng reference variable `${{Redis.REDIS_URL}}` | Khai báo ngay trong file (`type: redis`, `plan: free`, `maxmemoryPolicy`) |
| Biến môi trường / secret | Không có trong file; tất cả đặt ở tab Variables | Khai báo trong `envVars`: giá trị thường ghi thẳng (`ENVIRONMENT`), secret dùng `sync: false` (điền tay trên dashboard) hoặc `generateValue: true` (Render tự sinh ngẫu nhiên, như `AGENT_API_KEY`) |
| Region / plan | Chọn trên dashboard | Ghi trong file (`region: singapore`, `plan: free`) |
| Auto deploy khi push | Bật mặc định khi nối GitHub | `autoDeploy: true` |

**Vì sao khác nhau:** Railway đi theo hướng *dashboard-first*: hạ tầng (service, database, biến) tạo trên giao diện, `railway.toml` chỉ mô tả cách build/deploy một service. Render đi theo hướng *Infrastructure as Code*: cả hạ tầng nằm trong một file commit vào git, review được qua pull request và dựng lại y hệt bằng một lần "New → Blueprint".

**Nếu deploy `06-lab-complete` lên Render** thì `render.yaml` mẫu phải sửa: đổi sang `runtime: docker` (hoặc `startCommand: uvicorn app.main:app ...` vì entrypoint là `app.main:app` chứ không phải `app:app`), đặt `rootDir: 06-lab-complete`, và thêm `REDIS_URL` lấy từ service Redis (`fromService: {type: redis, name: agent-cache, property: connectionString}`). File mẫu hiện khai báo Redis nhưng **không nối** nó vào web service, nên `/ready` sẽ trả 503.

### Exercise 3.3: Pipeline CI/CD trên Cloud Run (`03-cloud-deployment/production-cloud-run/`)

1. **Trigger:** push lên nhánh `main` → Cloud Build chạy `cloudbuild.yaml`; các step nối nhau bằng `waitFor`, step nào lỗi thì pipeline dừng, không deploy.
2. **Test:** container `python:3.11-slim` cài `requirements.txt` + `pytest` rồi chạy `pytest tests/` — chặn code lỗi trước khi build.
3. **Build & push:** build Docker image gắn 2 tag `:$COMMIT_SHA` và `:latest` (dùng `--cache-from :latest` để tận dụng layer cache), rồi `docker push --all-tags` lên Container Registry `gcr.io/$PROJECT_ID/ai-agent`.
4. **Deploy:** `gcloud run deploy` image theo **tag commit SHA** (bản deploy truy ngược được về commit, rollback bằng cách deploy lại SHA cũ) tại `asia-southeast1`: `min-instances=1` (tránh cold start), `max-instances=10`, 512 MiB / 1 CPU, timeout 60 s; secret `OPENAI_API_KEY` lấy từ **Secret Manager**, không nằm trong image hay repo.
5. **`service.yaml`** mô tả cùng service theo kiểu khai báo (Knative): `containerConcurrency: 80`, autoscale 1–10, liveness probe `/health`, startup probe `/ready`, `AGENT_API_KEY` và `OPENAI_API_KEY` qua `secretKeyRef` — áp dụng bằng `gcloud run services replace service.yaml`.

Nhận xét khi đọc: repo không có thư mục `tests/` nên step test sẽ fail nếu chạy nguyên trạng; `service.yaml` dùng image `:latest` và chuỗi `PROJECT_ID` cứng, nên trong pipeline thật nên deploy bằng tag SHA như `cloudbuild.yaml` để biết chính xác đang chạy bản nào.

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/`)

**API key được check ở đâu?**
- Key đọc từ env: `API_KEY = os.getenv("AGENT_API_KEY", ...)` (`app.py:35`).
- Header được khai báo bằng `APIKeyHeader(name="X-API-Key", auto_error=False)` (`app.py:36`).
- Hàm dependency `verify_api_key` (`app.py:39`) được gắn vào endpoint bằng `Depends(verify_api_key)` (`app.py:70`). FastAPI chạy hàm này **trước** khi vào thân `/ask`, nên request không hợp lệ bị chặn trước khi tốn tiền gọi LLM. `/` và `/health` không gắn dependency nên vẫn public.

**Sai key thì sao?**
- Thiếu header → **401** `Missing API key` (`app.py:46`).
- Có header nhưng sai key → **403** `Invalid API key.` (`app.py:51`).
- Lưu ý: Part 6 yêu cầu cả thiếu lẫn sai key đều trả **401**, nên khi làm `06-lab-complete/app/auth.py` phải gộp hai trường hợp.

**Rotate key thế nào?**
- Key nằm trong env, không nằm trong code → đổi `AGENT_API_KEY` trên platform (Railway/Render Variables) rồi restart/redeploy, **không cần sửa code**.
- Muốn rotate không downtime: cho phép nhiều key cùng lúc (ví dụ `AGENT_API_KEYS=old,new`). Phát key mới cho client, đợi tất cả chuyển sang, rồi bỏ key cũ khỏi danh sách.
- So sánh nên dùng `hmac.compare_digest(api_key, API_KEY)` để tránh timing attack.

**Test** (chạy `AGENT_API_KEY=secret-key-123 PORT=8013 python app.py`):

```text
$ curl -i -X POST http://localhost:8013/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8013/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8013/ask -H "X-API-Key: ***" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i http://localhost:8013/health
HTTP/1.1 200 OK
{"status":"ok"}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

**JWT flow** (`auth.py`):
1. Client gửi `POST /auth/token` với username/password → `authenticate_user` kiểm tra với `DEMO_USERS` (`auth.py:72`), sai → 401.
2. Server tạo token bằng `create_token` (`auth.py:35`): payload `{sub, role, iat, exp}` (hết hạn sau 60 phút), ký bằng **HS256** với `JWT_SECRET` từ env (`auth.py:22`).
3. Client gửi lại token ở header `Authorization: Bearer <token>` cho mỗi request.
4. `verify_token` (`auth.py:46`) gọi `jwt.decode` (`auth.py:59`) để kiểm tra chữ ký và hạn dùng, rồi lấy `username`, `role` từ payload. **Không cần tra DB mỗi request** (stateless) → scale ngang dễ, instance nào cũng verify được nếu dùng chung secret.
5. Lỗi: không có token → 401 (kèm `WWW-Authenticate: Bearer`); token hết hạn → 401; token giả/sai chữ ký → 403.

Token chỉ được **ký**, không được **mã hoá**: ai cũng decode được payload (base64), nên không được để thông tin nhạy cảm trong payload. Đổi `JWT_SECRET` thì mọi token cũ mất hiệu lực ngay.

**Test** (chạy `PORT=8014 python app.py`; tài khoản `admin/secret` trong `CODE_LAB.md` không tồn tại, dùng `student/demo123`):

```text
$ curl -i -X POST http://localhost:8014/auth/token -H "Content-Type: application/json" -d '{"username":"admin","password":"secret"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -i -X POST http://localhost:8014/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN>..."}

# Decode token (3 phần header.payload.signature):
header : {"alg":"HS256","typ":"JWT"}
payload: {"sub":"student","role":"user","iat":1795682517,"exp":1795686117}     ← exp - iat = 3600 s

$ curl -i -X POST http://localhost:8014/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

$ curl -i -X POST http://localhost:8014/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8014/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i -X POST http://localhost:8014/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":""}'
HTTP/1.1 422 Unprocessable Entity          ← Pydantic AskRequest: min_length=1, max_length=1000
```

Phân quyền theo role: `GET /admin/stats` với token `student` → `403 {"detail":"Admin only"}`; với token `teacher` (role admin) → 200.

### Exercise 4.3: Rate limiting

**Algorithm:** **Sliding window log** (file ghi là "Sliding Window Counter" nhưng thực chất lưu từng timestamp). Mỗi user có một `deque` timestamp (`rate_limiter.py:27`). Mỗi request:
1. Xoá timestamp cũ hơn 60 giây khỏi đầu deque (`rate_limiter.py:39`).
2. Nếu số timestamp còn lại `>= max_requests` → **429** kèm `Retry-After` = thời gian tới khi request cũ nhất rời cửa sổ (`rate_limiter.py:45`).
3. Ngược lại thêm `now` vào deque (`rate_limiter.py:65`).

So với fixed window: không bị lỗi "dồn 2x request ở ranh giới phút". So với token bucket: không cho burst, đơn giản hơn nhưng tốn bộ nhớ O(số request) mỗi user.

**Limit:** user thường **10 request/phút**; admin **100 request/phút** (`rate_limiter.py:86-87`).

**Bypass cho admin:** không bypass hoàn toàn mà chọn limiter theo role trong JWT: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user` (`app.py:141`). Muốn bypass hẳn thì `if role == "admin": skip check`, nhưng không nên, vì token admin bị lộ thì không còn lớp nào chặn.

**Hạn chế:** state nằm trong RAM của process → chạy nhiều instance thì mỗi instance đếm riêng (user được 10 × N request/phút), restart là mất. Production phải dùng Redis (Part 6: sorted set `ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE`).

**Test** (vòng lặp 20 request bằng token `student`, sau 1 request ở 4.2):

```text
$ for i in $(seq 1 20); do curl -i -X POST http://localhost:8014/ask -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" -d "{\"question\": \"Test $i\"}"; done

req  1: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":8, ...}
req  2: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":7, ...}
req  3: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":6, ...}
req  4: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":5, ...}
req  5: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":4, ...}
req  6: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":3, ...}
req  7: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":2, ...}
req  8: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":1, ...}
req  9: HTTP/1.1 200 OK  ... "usage":{"requests_remaining":0, ...}
req 10: HTTP/1.1 429 Too Many Requests
        x-ratelimit-limit: 10
        x-ratelimit-remaining: 0
        x-ratelimit-reset: 1795682583
        retry-after: 56
        {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
req 11: HTTP/1.1 429 Too Many Requests  retry-after: 55  ...
...
req 20: HTTP/1.1 429 Too Many Requests  retry-after: 52  ...
```

→ Đúng 10 request thành công trong 60 giây (1 ở bước 4.2 + 9 trong vòng lặp), request thứ 11 bị **429**. `Retry-After` giảm dần (56 → 52) vì cửa sổ trượt theo thời gian.

Token `teacher` (admin) gửi 12 request liên tiếp → cả 12 đều `200`, request thứ 13 trả `"requests_remaining":87` (limit 100).

### Exercise 4.4: Cost guard

**Bản có sẵn (`production/cost_guard.py`):**
- Budget theo **ngày**: $1/user, $10 toàn hệ thống (`cost_guard.py:128`).
- `check_budget` được gọi **trước** khi gọi LLM (`app.py:145`): user vượt → **402 Payment Required** (`cost_guard.py:78`); tổng hệ thống vượt → **503** (`cost_guard.py:71`). `record_usage` gọi **sau** khi có response để cộng chi phí thật theo token (`app.py:153`).
- State trong dict RAM (`cost_guard.py:49`) → mất khi restart, không chia sẻ giữa instance.
- **Bug phát hiện khi test:** response `/ask` trả `"budget_remaining_usd": usage.total_cost_usd` (`app.py:160`) — đây là số **đã tiêu**, không phải số còn lại. Sau 10 request, `/ask` báo `0.000184` trong khi `/me/usage` báo đúng `budget_remaining_usd: 0.999816`:

```text
$ curl http://localhost:8014/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-26","requests":10,"input_tokens":40,"output_tokens":296,
 "cost_usd":0.000184,"budget_usd":1.0,"budget_remaining_usd":0.999816,"budget_used_pct":0.0}
```

Với mock LLM, 10 request chỉ tốn $0.000184 (~$0.0000184/request) → cần ~54.000 request mới chạm $1, trong khi rate limit chỉ cho 10 request/phút (~90 giờ). Vì vậy không thể thấy 402 qua HTTP với bản demo; mình kiểm tra 402 bằng bản Redis tự viết bên dưới.

**Bản tự implement với Redis** — [`04-api-gateway/production/cost_guard_redis.py`](04-api-gateway/production/cost_guard_redis.py), theo đề: $10/tháng/user, lưu Redis, reset đầu tháng.

```python
_RESERVE_SCRIPT = r.register_script("""
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    local cost = tonumber(ARGV[1])
    local budget = tonumber(ARGV[2])
    if current + cost > budget then
        return 0
    end
    redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    return 1
""")

def month_key(user_id, now=None):
    now = now or datetime.now(timezone.utc)
    return f"budget:{user_id}:{now:%Y-%m}"

def check_budget(user_id: str, estimated_cost: float) -> bool:
    return bool(_RESERVE_SCRIPT(keys=[month_key(user_id)],
                                args=[estimated_cost, MONTHLY_BUDGET_USD, KEY_TTL_SECONDS]))
```

Cách làm:
- **Key theo tháng UTC** `budget:<user>:<YYYY-MM>` → sang tháng mới là key mới, tự reset mà không cần cron job.
- **TTL 32 ngày** → key tháng cũ tự bị Redis xoá.
- **Kiểm tra + cộng tiền trong một Lua script → atomic.** Lời giải mẫu trong `CODE_LAB.md` làm `GET` rồi mới `INCRBYFLOAT` (hai lệnh riêng) nên có race condition: nhiều request đồng thời cùng đọc số dư cũ và cùng qua, làm vượt budget. Redis chạy Lua script nguyên khối, không request nào chen vào giữa.
- Dùng `>` chứ không `>=`: tiêu đúng bằng $10 vẫn được phép.
- Budget đọc từ env `MONTHLY_BUDGET_USD`, Redis từ `REDIS_URL`.
- Trong endpoint: `if not check_budget(user, est_cost): raise HTTPException(402, ...)`.

**Test** ([`test_cost_guard_redis.py`](04-api-gateway/production/test_cost_guard_redis.py), Redis tạm `docker run -d --rm --name p4-redis -p 6380:6379 redis:7-alpine`):

```text
$ REDIS_URL=redis://localhost:6380/0 python test_cost_guard_redis.py
Budget: $10.0/tháng, key: budget:alice:2026-11

[1] alice tiêu dần:
  spent=$ 0.00 + $3.00 → OK    spent sau=$3.00
  spent=$ 3.00 + $3.00 → OK    spent sau=$6.00
  spent=$ 6.00 + $3.00 → OK    spent sau=$9.00
  spent=$ 9.00 + $3.00 → DENY (→ 402)  spent sau=$9.00
  spent=$ 9.00 + $1.00 → OK    spent sau=$10.00
  spent=$10.00 + $0.01 → DENY (→ 402)  spent sau=$10.00

[2] bob (budget riêng): check $5 → True, spent=$5.0

[3] TTL key alice: 2764800 giây (~32 ngày)

[4] Key tháng sau: budget:alice:2026-12 (chưa tồn tại → spent=0: True)

[5] 50 request đồng thời x $0.5: OK=20, DENY=30, spent=$10.00 (không vượt $10.0)
```

Kết quả [5] chứng minh tính atomic: 50 request song song, đúng 20 × $0.5 = $10 được qua, không request nào lọt khi đã hết budget.

**Vì sao cần cả rate limit lẫn cost guard:**
- **Rate limit bảo vệ tốc độ / tài nguyên** (chống spam, DoS, một user chiếm hết server) — đơn vị là *số request / thời gian*.
- **Cost guard bảo vệ tiền** — đơn vị là *USD*. Một request có thể rẻ (câu ngắn) hoặc rất đắt (prompt dài, nhiều token output); 10 request/phút với prompt dài vẫn có thể đốt hàng chục USD/ngày. Ngược lại cost guard một mình không chặn được spam request rẻ làm quá tải server.
- Thứ tự trong `/ask`: auth → rate limit → cost guard → gọi LLM → ghi chi phí. Chặn càng sớm càng đỡ tốn.

## Part 5: Scaling & Reliability

Part 5 gồm hai nửa: `develop/` (5.1, 5.2) chạy app Python đơn lẻ để quan sát health check và SIGTERM; `production/` (5.3–5.5) chạy bằng Docker Compose: 3 agent + Redis + Nginx.

**Lỗi gặp khi build và cách xử lý:** `05-scaling-reliability/production/Dockerfile` cũng `apt-get update` qua HTTP nên bị gateway mạng chặn (`401 VG-AuthenticationRequired`, như Part 2) → thêm `sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources` trước `apt-get`. Compose cần file `.env.local` → `touch .env.local` (để trống, đã nằm trong `.gitignore`).

### Exercise 5.1: Health checks (`develop/app.py`)

Bản develop đã có sẵn hai endpoint. Chạy app trong container Linux (`python:3.11-slim`, cổng 8015) để có môi trường POSIX giống WSL:

```text
$ curl http://localhost:8015/health
{"status":"ok","uptime_seconds":113.1,"version":"1.0.0","environment":"development",
 "timestamp":"2026-11-26T10:30:04.175449+00:00","checks":{"memory":{"status":"ok","used_percent":25.1}}}

$ curl http://localhost:8015/ready
{"ready":true,"in_flight_requests":1}
```

(`in_flight_requests` = 1 vì chính request `/ready` đang được middleware đếm.)

| | `/health` — **liveness** | `/ready` — **readiness** |
|---|---|---|
| Câu hỏi | Process còn sống không? | Có nhận traffic được không? |
| Ai dùng | Platform (Docker `HEALTHCHECK`, Railway, K8s liveness probe) | Load balancer / K8s readiness probe |
| Fail thì | **Restart** container | **Ngừng gửi request** vào instance đó, không restart |
| Trong code | Trả uptime, version, kiểm tra RAM bằng `psutil` (>90% → `degraded`), luôn HTTP 200 khi process còn chạy | 503 khi `_is_ready = False`: đang khởi động (lifespan chưa xong) hoặc đang shutdown |

**Vì sao `/health` không được phụ thuộc Redis:** nếu Redis chết mà `/health` trả lỗi, platform sẽ restart agent liên tục, nhưng restart không làm Redis sống lại → vòng lặp restart vô ích, và còn làm rơi các request đang chạy. Lỗi dependency phải báo qua `/ready` để load balancer tạm bỏ qua instance đó.

Middleware `track_requests` (`develop/app.py:76`) tăng/giảm `_in_flight_requests` quanh mỗi request; lúc shutdown, lifespan dùng biến này để chờ request đang chạy (tối đa 30 giây).

### Exercise 5.2: Graceful shutdown

Mock LLM của bản develop mất **3 giây** mỗi câu trả lời. Gửi một request, 0,5 giây sau gửi SIGTERM cho process:

```bash
python app.py &                     # (chạy trong container Linux: docker kill -s TERM <container>)
PID=$!
curl -s -w '  -> HTTP %{http_code}\n' -X POST "http://localhost:8015/ask?question=Long%20task" &
sleep 0.5
kill -TERM $PID
wait
```

Kết quả:

```text
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}  -> HTTP 200
exit code: 0

INFO:     Shutting down
INFO:     172.17.0.1:36904 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 10:32:25,213 INFO 🔄 Graceful shutdown initiated...
2026-11-26 10:32:25,213 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
2026-11-26 10:32:25,214 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Phân tích:**
- Request nhận SIGTERM giữa chừng (sau 0,5/3 giây) **vẫn trả 200**, process thoát với **exit code 0**.
- Thứ tự: uvicorn nhận SIGTERM → `Shutting down` (ngừng nhận request mới) → **chờ request đang chạy xong** (`POST /ask ... 200`) → chạy phần shutdown của `lifespan` (đóng kết nối, cleanup) → thoát.
- `timeout_graceful_shutdown=30` (`develop/app.py:198`): chờ tối đa 30 giây rồi mới cắt request.
- Dòng `Received signal 15` của `handle_sigterm` in ra **cuối cùng**: khi server chạy, uvicorn cài handler của chính nó thay cho handler app đăng ký ở `app.py:186`; shutdown xong uvicorn mới trả lại handler cũ và gọi lại signal. Tức là uvicorn mới là bên thực hiện graceful shutdown, `handle_sigterm` chỉ ghi log.
- **SIGTERM** bắt được → tắt từ từ. **SIGKILL** (`kill -9`) không bắt được → chết ngay, request đang chạy mất. `docker stop` gửi SIGTERM, chờ 10 giây rồi mới gửi SIGKILL → app phải tắt xong trong 10 giây, và uvicorn phải là PID 1 (`CMD` dạng exec) để nhận được SIGTERM.

### Exercise 5.3: Stateless design (`production/app.py`)

- **Anti-pattern:** `conversation_history = {}` trong RAM → mỗi instance có một dict riêng. Request 1 vào instance A, request 2 vào instance B thì B không thấy history; restart/redeploy là mất sạch.
- **Cách làm trong code:** mọi session lưu trong Redis bằng `SETEX session:<session_id> 3600 <json>` (TTL 1 giờ, tự xoá session bỏ dở). `load_session` / `save_session` / `append_to_history` đều đọc-ghi Redis → instance nào cũng phục vụ được bất kỳ user nào. History cắt còn 20 tin nhắn gần nhất (10 lượt) để key không phình.
- Response có `served_by` (= `INSTANCE_ID`) để thấy request đi vào instance nào.
- **Điểm yếu:** `production/app.py:40-44` — nếu lúc khởi động không ping được Redis, app **lặng lẽ chuyển sang lưu trong RAM** (`USE_REDIS = False`, `_memory_store = {}`) và chỉ in một dòng cảnh báo. Khi chạy nhiều instance, instance đó quay lại đúng lỗi stateful, và `/ready` của nó luôn trả 200 (không còn kiểm tra Redis). Production nên fail-fast hoặc để `/ready` trả 503 cho tới khi kết nối được Redis.
- Hạn chế nhỏ khác: `append_to_history` làm GET → sửa → SETEX (không atomic), hai request cùng session gửi đồng thời có thể ghi đè nhau; dùng Redis list (`RPUSH` + `LTRIM`) sẽ an toàn hơn.

### Exercise 5.4: Load balancing

```text
$ cd 05-scaling-reliability/production
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 13 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 13 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 12 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 12 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 23 seconds (healthy)   6379/tcp
```

```text
Host :8080 → nginx (upstream agent:8000, round-robin) → agent-1 / agent-2 / agent-3 → redis:6379
```

- 3 agent không publish port (tránh đụng cổng 8000 trên host); chỉ Nginx mở cổng 8080. Docker DNS trả 3 IP cho tên service `agent`, Nginx chia lần lượt.
- `depends_on: redis: condition: service_healthy` → agent chỉ start khi Redis đã healthy. Mỗi agent bị giới hạn 0,5 CPU / 256 MB.

**Tắt 1 instance — traffic chuyển sang instance còn lại:**

```text
$ docker stop k5-day14-scaling-agent-2
$ for i in $(seq 1 6); do curl -s -o /dev/null -w '%{http_code} ' -X POST http://localhost:8080/chat \
    -H "Content-Type: application/json" -d '{"question":"hi"}'; done
200 200 200 200 200 200

# served_by của 6 request tiếp theo:
      3 "served_by":"instance-97266d"
      3 "served_by":"instance-c8e9ea"
```

Không request nào lỗi: `nginx.conf:23` có `proxy_next_upstream error timeout http_503` + `proxy_next_upstream_tries 3` → instance không trả lời thì Nginx thử instance kế tiếp.

**Tắt Redis — `/health` vẫn 200, `/ready` 503** (gọi thẳng vào từng container, không qua Nginx để Nginx không che kết quả bằng cách thử instance khác):

```text
$ docker compose -p k5-day14-scaling stop redis
agent-1 /health: 200 {"status":"degraded","instance_id":"instance-ddc6e8","uptime_seconds":25.2,"storage":"redis","redis_connected":false}
agent-1 /ready : HTTP Error 503: Service Unavailable
agent-2 /health: 200 {"status":"degraded","instance_id":"instance-74a46c","uptime_seconds":42.7,"storage":"redis","redis_connected":false}
agent-2 /ready : HTTP Error 503: Service Unavailable
agent-3 /health: 200 {"status":"degraded","instance_id":"instance-732aa7","uptime_seconds":59.6,"storage":"redis","redis_connected":false}
agent-3 /ready : HTTP Error 503: Service Unavailable

$ curl -w '  -> %{http_code}\n' http://localhost:8080/ready
{"detail":"Redis not available"}  -> 503
```

Đúng hành vi mong muốn: process vẫn sống nên platform không restart; load balancer biết không instance nào phục vụ được.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: 18e76a88-4ef3-4830-b333-7c07f9377a69

Request 1: [instance-eac499]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...
Request 2: [instance-c8e9ea]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....
Request 3: [instance-97266d]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....
Request 4: [instance-eac499]
  Q: How does load balancing work?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....
Request 5: [instance-c8e9ea]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-c8e9ea', 'instance-eac499', 'instance-97266d'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  ...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu hỏi trong **cùng một session** được 3 instance khác nhau xử lý theo vòng A → B → C → A → B (round-robin của Nginx). History vẫn đủ **10 tin nhắn** (5 hỏi + 5 đáp) đúng thứ tự, vì không instance nào giữ state riêng: tất cả đọc-ghi cùng key `session:18e76a88-...` trong Redis. Nếu lưu trong RAM, request 2 ở instance B sẽ không thấy câu hỏi 1 đã gửi tới A, và history trả về sẽ thiếu.

Lưu ý: `CODE_LAB.md` mô tả script "kill random instance", nhưng script thật không tắt instance nào; phần chịu lỗi khi mất instance được thể hiện ở thí nghiệm tắt `agent-2` trong Exercise 5.4.

Dọn stack: `docker compose -p k5-day14-scaling down`.

---

## Part 6: Final Project

Code trong `06-lab-complete/` (đã sửa hết TODO). Kiểm tra bằng script chấm, chạy trong WSL có Docker:

```text
$ cd 06-lab-complete && python check_production_ready.py

<<< DÁN PHẦN "📋 Checklist Deliverable" VÀ DÒNG "Result: ..." TỪ OUTPUT CỦA BẠN VÀO ĐÂY >>>
```

Deploy: xem Part 3 và [DEPLOYMENT.md](DEPLOYMENT.md).

---

## AI log

| # | Hỏi AI (Claude Code) | Nhận được | Tự kiểm tra |
|---|---|---|---|
| 1 | Tổng quan dự án và lộ trình làm bài | Tóm tắt các Part, checkpoint, rubric | Đối chiếu với `README.md`, `CHECKPOINTS.md`, `RUBRIC.md` |
| 2 | Bản production Part 1 bị lỗi khi gọi `/ask` | Nguyên nhân: gọi bằng query string trong khi bản production đọc JSON body → `JSONDecodeError` → 500 | Chạy lại cả hai cách gọi, xem traceback trong log server |
| 3 | `docker build` Part 2 lỗi ở bước `apt-get update` | Nguyên nhân: gateway mạng chặn HTTP (`401 VG-AuthenticationRequired`); đề xuất đổi apt sang HTTPS bằng `sed` | So sánh `curl` HTTP (302) và HTTPS (200), build lại thành công |
| 4 | Ghi CP1, CP2 vào `MISSION_ANSWERS.md` | AI chạy các lệnh test và đo image, rồi soạn câu trả lời | Đọc lại từng câu trả lời, đối chiếu số dòng code và output lệnh |
| 5 | Làm CP3 (Part 4: API key, JWT, rate limit, cost guard) | AI chạy test 401/403/200/429, phát hiện bug `budget_remaining_usd`, viết `cost_guard_redis.py` (Lua script atomic) + `test_cost_guard_redis.py` | Chạy lại vòng lặp curl thấy 429; chạy test Redis, kiểm tra kết quả 50 request đồng thời không vượt budget |
| 6 | Làm CP4 (Part 5: health check, graceful shutdown, stateless, load balancing) | AI sửa Dockerfile Part 5 (apt sang HTTPS), chạy stack 3 agent, test tắt instance / tắt Redis, test SIGTERM trong container Linux, chỉ ra điểm yếu tự chuyển sang RAM khi không có Redis | Đối chiếu `served_by` và history 10 tin nhắn; gọi `/ready` thẳng vào từng container thấy 503 |
| 7 | Hướng dẫn Part 6 (12 tiêu chí) | AI giải thích cách script chấm kiểm tra, đưa code mẫu từng file (config, auth, rate limiter Redis, cost guard, main, Dockerfile, compose, railway.toml) đã chạy thử trên bản nháp | Tự chạy `check_production_ready.py` trong WSL → `PASS 12/12`; sửa `.env.example` còn thiếu biến theo gợi ý |
| 9 | Làm CP7 (Part 7 Bước 1) | AI chạy toàn bộ lệnh trong WSL của mình (env `day14-lab`): load test 4 mức concurrency + 3 mức `MOCK_SLOW_RATE`, eval v1/v2, thêm metric `agent_question_length_chars`, thêm 2 tài liệu vào `KNOWLEDGE_BASE` (develop + production), tạo `.github/workflows/eval.yml`, điền mục 1–3 `BENCHMARK_REPORT.md` bằng số đọc trực tiếp từ file JSON | Đối chiếu từng số trong báo cáo với `develop/reports/*.json`; eval cuối 23/23, quality gate PASS, 0 regression; chạy lại các lệnh của job CI ở local → exit 0 |
| 8 | Deploy Railway (CP6) | AI hướng dẫn cấu hình Root Directory, config file, Redis, biến môi trường; chẩn đoán lỗi 500 do `AGENT_API_KEY` chứa chuỗi có dấu làm `hmac.compare_digest` ném `TypeError`; sửa `auth.py` so sánh bytes; viết `DEPLOYMENT.md` và mục Part 3 | Chạy 4 lệnh CP6 trên URL public (200/200/401/200), gửi key có dấu → 401, `--public-url` → ✅ |
