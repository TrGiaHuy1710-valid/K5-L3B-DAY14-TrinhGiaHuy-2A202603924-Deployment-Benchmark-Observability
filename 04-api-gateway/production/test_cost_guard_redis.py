"""
Test cost_guard_redis.py với Redis thật.

    docker run -d --rm --name p4-redis -p 6380:6379 redis:7-alpine
    REDIS_URL=redis://localhost:6380/0 python test_cost_guard_redis.py
    docker stop p4-redis
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import cost_guard_redis as cg


def reset(*users):
    for u in users:
        cg.r.delete(cg.month_key(u))


def main():
    cg.r.ping()
    print(f"Budget: ${cg.MONTHLY_BUDGET_USD}/tháng, key: {cg.month_key('alice')}")

    # 1. Tiêu dần tới khi vượt budget
    reset("alice")
    print("\n[1] alice tiêu dần:")
    for cost in [3.0, 3.0, 3.0, 3.0, 1.0, 0.01]:
        before = cg.get_spent("alice")
        ok = cg.check_budget("alice", cost)
        print(f"  spent=${before:5.2f} + ${cost:4.2f} → {'OK  ' if ok else 'DENY (→ 402)'}"
              f"  spent sau=${cg.get_spent('alice'):.2f}")

    # 2. User khác có budget riêng
    reset("bob")
    print(f"\n[2] bob (budget riêng): check $5 → {cg.check_budget('bob', 5.0)}, spent=${cg.get_spent('bob')}")

    # 3. TTL để tự xoá key tháng cũ
    print(f"\n[3] TTL key alice: {cg.r.ttl(cg.month_key('alice'))} giây (~{cg.r.ttl(cg.month_key('alice')) / 86400:.0f} ngày)")

    # 4. Reset đầu tháng: tháng sau dùng key khác
    next_month = datetime(2026, 12, 1, tzinfo=timezone.utc)
    print(f"\n[4] Key tháng sau: {cg.month_key('alice', next_month)} "
          f"(chưa tồn tại → spent=0: {cg.r.get(cg.month_key('alice', next_month)) is None})")

    # 5. Atomic: 50 request đồng thời, mỗi request $0.5, budget $10 → đúng 20 request qua
    reset("carol")
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(lambda _: cg.check_budget("carol", 0.5), range(50)))
    print(f"\n[5] 50 request đồng thời x $0.5: OK={sum(results)}, DENY={results.count(False)}, "
          f"spent=${cg.get_spent('carol'):.2f} (không vượt ${cg.MONTHLY_BUDGET_USD})")

    reset("alice", "bob", "carol")


if __name__ == "__main__":
    main()
