"""Deterministic, database-free cafeteria simulation. Never sensor observations."""
from datetime import datetime, timedelta, timezone
import math
import random

SEOUL = timezone(timedelta(hours=9))
OPEN, CLOSE = 9 * 60, 19 * 60
CORNERS = {
    "korean": {"name": "한식", "menu": "따뜻한 백반", "service_rate": 5, "daily_limit": 500},
    "special": {"name": "일품", "menu": "치즈돈까스", "service_rate": 2, "daily_limit": 250},
    "noodle": {"name": "분식", "menu": "라면 · 우동", "service_rate": 3, "daily_limit": 300},
}
# Minute-by-minute demand anchors, interpolated continuously. Illustrative only.
PROFILES = {
    "korean": [(540, .12), (660, .6), (690, 1.8), (710, 2.8), (715, 3.5), (720, 6.3), (725, 6), (740, 1.2), (780, .3), (900, .12), (1080, 1.5), (1140, 0)],
    "special": [(540, .6), (660, 1.1), (690, 1.6), (710, 2.6), (715, 3.2), (720, 5.1), (725, 4.8), (740, 1), (780, .2), (900, .1), (1080, 1), (1140, 0)],
    "noodle": [(540, .1), (660, .4), (690, 1), (710, 1.5), (715, 2), (720, 3.5), (725, 3.2), (740, .6), (780, .2), (900, .1), (1080, 1), (1140, 0)],
}


def demand(key, minute):
    if not OPEN <= minute < CLOSE:
        return 0
    points = PROFILES[key]
    for (a, x), (b, y) in zip(points, points[1:]):
        if a <= minute < b:
            return x + (y - x) * (minute - a) / (b - a)
    return 0


def survival(age):
    """Assumed seated duration: everyone stays 10m, then leaves by 40m."""
    return max(0., min(1., (40 - age) / 30))


def timeline(day, key):
    cfg = CORNERS[key]
    tickets, served, queues, stocks = [], [], [], []
    remaining, queue = cfg["daily_limit"], 0
    for minute in range(1440):
        rng = random.Random(f"kiosk-v1:{day}:{key}:{minute}")
        expected = demand(key, minute) * rng.uniform(.85, 1.15)
        count = min(remaining, math.floor(expected + rng.random()))
        remaining -= count
        queue += count
        meals = min(queue, cfg["service_rate"])
        queue -= meals
        tickets.append(count)
        served.append(meals)
        queues.append(queue)
        stocks.append(remaining)
    return tickets, served, queues, stocks


def analyze_kiosk(test_hour=None, test_minute=None, now=None):
    if test_hour is not None and (type(test_hour) is not int or not 0 <= test_hour <= 23):
        raise ValueError("test_hour는 0~23 정수여야 합니다.")
    if test_minute is not None and (test_hour is None or type(test_minute) is not int or not 0 <= test_minute <= 59):
        raise ValueError("test_minute는 test_hour와 함께 0~59 정수로 지정하세요.")
    now = now or datetime.now(SEOUL)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SEOUL)
    effective = now.astimezone(SEOUL).replace(second=0, microsecond=0)
    if test_hour is not None:
        effective = effective.replace(hour=test_hour, minute=test_minute or 0)
    minute = effective.hour * 60 + effective.minute
    # Fixed demo day gives repeatable presentation scenarios on every calendar day.
    day = "demo" if test_hour is not None else effective.date().isoformat()
    series = {key: timeline(day, key) for key in CORNERS}
    histories, corners = {}, {}
    staying = leaving = 0.
    operating = OPEN <= minute < CLOSE
    for key, cfg in CORNERS.items():
        tickets, served, queues, stocks = series[key]
        histories[key] = [sum(tickets[max(0, minute - (i + 1) * 5):max(0, minute - i * 5)]) for i in range(6)]
        remaining = stocks[minute - 1] if minute else cfg["daily_limit"]
        backlog = queues[minute - 1] if minute else 0
        wait = round(backlog / cfg["service_rate"], 1)
        burn = sum(tickets[max(0, minute - 15):minute]) / 15
        mins = max(1, math.ceil(remaining / burn)) if burn and remaining else None
        if mins is not None and (not operating or minute + mins >= CLOSE):
            mins = None
        for t in range(max(0, minute - 40), minute):
            age = minute - t
            staying += served[t] * survival(age)
            leaving += served[t] * (survival(age) - survival(age + 10))
        corners[key] = {
            **cfg, "recent_5m_tickets": histories[key][0], "history_5m": histories[key],
            "accumulated": cfg["daily_limit"] - remaining, "backlog": backlog,
            "wait_time_min": wait, "status": "CONGESTED" if wait >= 7 else "NORMAL" if wait >= 3 else "SMOOTH",
            "remaining_stock": remaining, "sold_out": remaining == 0,
            "burn_rate_per_min": round(burn, 2), "mins_to_sold_out": mins,
            "expected_sold_out_time": (effective + timedelta(minutes=mins)).strftime("%H:%M") if mins is not None else None,
        }
    totals = [sum(h[i] for h in histories.values()) for i in range(6)]
    recent, previous = totals[:2]
    surge = round((recent - previous) / previous * 100, 1) if previous else (0. if not recent else None)
    current = recent + previous
    usual = 85 if effective.hour == 12 else 50 if effective.hour in (11, 13, 18) else 20
    diff = round((current - usual) / usual * 100, 1) if operating else None
    available = [c for c in corners.values() if not c["sold_out"]]
    best = min(available, key=lambda c: c["wait_time_min"], default=None)
    # Forecast only within the mock scenario, using the same queue evolution.
    candidates = []
    if operating:
        for future in range(minute + 10, min(minute + 46, CLOSE)):
            waits = [series[k][2][future - 1] / cfg["service_rate"] for k, cfg in CORNERS.items() if series[k][3][future - 1] > 0]
            if waits:
                candidates.append((sum(waits) / len(waits), future))
    current_wait = sum(c["wait_time_min"] for c in available) / len(available) if available else 0
    better = min(candidates, default=None)
    recommended = None
    if better and current_wait >= 2 and better[0] <= current_wait * .7:
        start = better[1]
        recommended = f"{start // 60:02}:{start % 60:02} ~ {min(start + 10, CLOSE) // 60:02}:{min(start + 10, CLOSE) % 60:02}"
    if not operating:
        briefing = "지금은 시연 설정의 운영시간 밖이에요. 점심 피크를 선택해 발권 흐름과 코너별 대기를 살펴보세요."
    elif not best:
        briefing = "오늘 준비한 가상 메뉴가 모두 소진되었어요. 다른 시연 시간을 선택해 주세요."
    else:
        intro = f"최근 발권이 {surge:g}% 늘었어요. " if surge is not None and surge >= 25 else "발권 흐름과 코너별 대기를 함께 살펴보세요. "
        briefing = intro + f"지금은 {best['name']} 코너의 예상 대기가 {best['wait_time_min']:g}분으로 가장 짧아요."
        urgent = [c for c in available if c["mins_to_sold_out"] is not None and c["mins_to_sold_out"] <= 20]
        if urgent:
            c = min(urgent, key=lambda c: c["mins_to_sold_out"])
            briefing += f" {c['name']}은 {c['remaining_stock']}개 남아 약 {c['mins_to_sold_out']}분 뒤 소진될 수 있어요."
    return {
        "version": 1, "data_source": "mock", "location_id": "sangnok", "floor": 2,
        "mode": "demo" if test_hour is not None else "clock", "as_of": effective.isoformat(),
        "simulated_hour": effective.hour, "operating": operating, "operating_hours": "09:00 ~ 19:00",
        "summary_briefing": briefing,
        "staying_estimation": {"current_eating": round(staying), "leaving_in_10m": min(round(staying), round(leaving)), "total_5m_trend": totals[::-1]},
        "surge_momentum": {"recent_5m": recent, "prev_5m": previous, "surge_rate_percent": surge, "is_surging": surge is not None and surge >= 25},
        "corners": corners,
        "golden_time_stats": {"diff_vs_usual_percent": diff, "usual_10m_avg": usual if operating else None,
            "recommended_time": recommended, "tip": "판매 중인 코너 기준 · 인기 메뉴는 먼저 품절될 수 있어요." if recommended else "운영시간 밖이에요." if not operating else "재고가 있는 코너를 지금 비교해 보세요."},
    }
