"""
가짜 센서. 규격대로 5초마다 CSI 4링크 + mmWave 4구역 데이터를 보낸다.
나중에 이 자리에 진짜 센서가 들어온다.
"""
import time
import random
import requests

SERVER = "http://127.0.0.1:8000/ingest"

LINKS = ["link_1", "link_2", "link_3", "link_4"]
ZONES = ["zone_A", "zone_B", "zone_C", "zone_D"]

# 구역별 "실제" 혼잡 상태를 흉내내기 위한 값 (0.0~1.0)
occupancy = {z: random.uniform(0.1, 0.5) for z in ZONES}


def now_grid_ms() -> int:
    """현재 시각을 5초 grid로 내림. 규격: window 시작 시각."""
    return int(time.time() * 1000) // 5000 * 5000


def send(timestamp, source, identifier, features):
    payload = {
        "timestamp": timestamp,
        "source": source,
        "identifier": identifier,
        "features": features,
    }
    try:
        r = requests.post(SERVER, json=payload, timeout=3)
        if r.status_code != 200:
            print(f"  ⚠ {r.status_code} {r.text[:100]}")
        return r.status_code == 200
    except requests.RequestException as e:
        print("전송 실패:", e)
        return False


def step():
    ts = now_grid_ms()

    # 구역별 점유율이 서서히 변하도록 (랜덤워크)
    for z in ZONES:
        occupancy[z] = min(1.0, max(0.0, occupancy[z] + random.uniform(-0.08, 0.08)))

    # --- CSI (link_1~4) : 움직임이 많을수록 분산이 커진다 ---
    for i, link in enumerate(LINKS):
        zone = ZONES[i]              # link_1↔zone_A ... (검증 전 가정)
        base = occupancy[zone]
        packet_count = random.randint(470, 500)
        send(ts, "csi", link, {
            "csi_amp_var": round(base * 0.5 + random.uniform(0, 0.1), 3),
            "csi_amp_mean": round(10 + base * 5 + random.uniform(-1, 1), 2),
            "csi_packet_count": packet_count,
            "csi_missing_rate": round((500 - packet_count) / 500, 3),
        })

    # --- mmWave (zone_A~D) : 앉아 있으면 정적 에너지가 높다 ---
    for zone in ZONES:
        base = occupancy[zone]
        send(ts, "mmwave", zone, {
            "mm_presence": 1 if base > 0.2 else 0,
            "mm_static_energy": round(base + random.uniform(-0.05, 0.05), 3),
            "mm_moving_energy": round(base * 0.3 + random.uniform(0, 0.1), 3),
            "mm_frame_count": random.randint(95, 100),
        })

    # --- 키오스크 발권량 (5초 동안 발권된 수) ---
    # 전체가 붐빌수록 발권이 잦다
    avg_occ = sum(occupancy.values()) / len(ZONES)
    tickets = max(0, int(random.gauss(avg_occ * 4, 1)))
    send(ts, "external", None, {
        "ext_ticket_count": tickets,
    })

    print(f"{ts} 전송 완료  " + "  ".join(f"{z}:{occupancy[z]:.2f}" for z in ZONES))


if __name__ == "__main__":
    print("mock 센서 시작 (Ctrl+C로 중지)")
    while True:
        step()
        time.sleep(5)