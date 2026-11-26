# Deployment Information

## Public URL

https://k5-l3b-day14-trinhgiahuy-2a202603924-deployment-production.up.railway.app

## Platform

**Railway** (gói dùng thử), deploy từ GitHub repo này, thư mục `06-lab-complete/` (agent Part 6, `check_production_ready.py` báo `PASS 12/12` ở local).

| Thành phần | Cấu hình |
|---|---|
| Project / environment | `zesty-upliftment` / `production` |
| Service agent | Source: GitHub repo, nhánh `main`, tự deploy lại mỗi lần push |
| Root Directory | `06-lab-complete` (gốc repo có Dockerfile ví dụ Go nên bắt buộc đặt) |
| Railway Config File | `/06-lab-complete/railway.toml` — `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, restart `ON_FAILURE` (tối đa 3 lần) |
| Build | `06-lab-complete/Dockerfile`: multi-stage, `python:3.11-slim`, user non-root, `HEALTHCHECK`, image ~192 MB |
| Start | `CMD` của Dockerfile: `exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2` → nghe theo `PORT` do Railway cấp |
| Service Redis | Railway Database → Redis, có volume `redis-volume`; agent kết nối qua private network |

```text
Client ──HTTPS──► Railway edge (*.up.railway.app)
                        │
                        ▼
            agent (Docker, uvicorn x2 workers, :$PORT)
              │  /health  liveness (không phụ thuộc Redis)
              │  /ready   readiness (ping Redis)
              │  /ask     X-API-Key → rate limit → cost guard → mock LLM
              ▼
            Redis (private network) — rate limit (sorted set), chi phí theo ngày
```

## Environment Variables Set

Đặt trong tab **Variables** của service agent. Không có giá trị nào được ghi trong code, `railway.toml` hay repo.

| Biến | Giá trị / nguồn |
|---|---|
| `AGENT_API_KEY` | secret, sinh bằng `openssl rand -hex 24` (48 ký tự hex) — chỉ đặt trên Railway |
| `REDIS_URL` | reference variable `${{Redis.REDIS_URL}}` — Railway tự điền URL của service Redis |
| `ENVIRONMENT` | `production` (app fail-fast nếu thiếu `AGENT_API_KEY`) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | **không đặt** — Railway tự cấp; app đọc qua `${PORT:-8000}` |

## Test Commands

```bash
BASE=https://k5-l3b-day14-trinhgiahuy-2a202603924-deployment-production.up.railway.app
read -s AGENT_API_KEY      # nhập key, không hiện ra màn hình / history
```

### Health Check

```bash
curl -i "$BASE/health"
# HTTP 200
# {"status":"ok","environment":"production"}
```

### Readiness (Redis)

```bash
curl -i "$BASE/ready"
# HTTP 200
# {"ready":true,"redis":"ok"}
```

### API Test (with authentication)

```bash
# Không có key → 401
curl -i -X POST "$BASE/ask" -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# HTTP 401
# {"detail":"Missing or invalid API key. Include header: X-API-Key: <key>"}

# Sai key → 401
curl -i -X POST "$BASE/ask" -H "X-API-Key: wrong-key-123" -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# HTTP 401

# Đúng key → 200
curl -i -X POST "$BASE/ask" -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# HTTP 200
# {"question":"Hello","answer":"..."}
```

### Bốn lệnh tự kiểm của CP6 (chỉ in mã HTTP, không lộ key)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả: `200`, `200`, `401`, `200`.

### Script chấm với public URL

```text
$ cd 06-lab-complete && python check_production_ready.py --public-url "$BASE"
✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ App lắng nghe theo biến PORT do platform cấp
     ✅ Public URL: GET https://k5-l3b-day14-trinhgiahuy-2a202603924-deployment-production.up.railway.app/health → 200
```

## Sự cố khi deploy và cách xử lý

| Sự cố | Nguyên nhân | Cách xử lý |
|---|---|---|
| Lần deploy đầu tiên build lỗi | Railway build từ gốc repo, nơi có `Dockerfile` ví dụ viết cho Go | Đặt **Root Directory** = `06-lab-complete` và **Railway Config File** = `/06-lab-complete/railway.toml` (Railway không tự tìm config theo Root Directory) |
| `/ask` có key trả 401 | Biến `$AGENT_API_KEY` trong terminal rỗng (`read -s` không nhận được giá trị) | Kiểm tra `echo ${#AGENT_API_KEY}` (phải là 48), nhập lại key |
| `/ask` có key (kể cả sai key) trả **500** thay vì 401 | Biến `AGENT_API_KEY` trên Railway bị điền nhầm chuỗi mẫu có dấu tiếng Việt; `hmac.compare_digest(str, str)` ném `TypeError: comparing strings with non-ASCII characters is not supported` → exception handler trả 500 | 1) Đặt lại key hex thật trên Railway rồi Deploy. 2) Sửa `app/auth.py` so sánh dạng bytes (`compare_digest(a.encode(), b.encode())`) để key có ký tự lạ luôn trả 401 — commit `b8b7cde`, Railway tự deploy lại khi push |

## Ghi chú

- `GET /docs` (Swagger UI) đang public. Có thể tắt khi `ENVIRONMENT=production` bằng `FastAPI(docs_url=None, redoc_url=None)` để không lộ cấu trúc API.
- Redeploy: `git push origin main` → Railway tự build và deploy; healthcheck `/health` phải đạt thì bản mới mới nhận traffic, nếu không Railway giữ bản cũ.

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png) — project Railway với service agent + Redis
- [Service running](screenshots/running.png) — deployment Active, Deploy Logs dạng JSON
- [Test results](screenshots/test.png) — 4 lệnh tự kiểm: 200 / 200 / 401 / 200
