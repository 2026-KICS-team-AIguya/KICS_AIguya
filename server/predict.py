"""5분 단위 특징값을 집계하는 임시 규칙 기반 모델."""
from sqlalchemy.orm import Session
import models

SLOT_MS = 5 * 60 * 1000  # 5분


def slot_start(timestamp_ms: int) -> int:
    return timestamp_ms // SLOT_MS * SLOT_MS


def to_level(value: float) -> str:
    """규격: 여유 ≤30% / 보통 30~70% / 혼잡 ≥70%"""
    if value >= 0.7:
        return "혼잡"
    if value > 0.3:
        return "보통"
    return "여유"


def estimate_wait(ticket_count: int, seat_occupancy: float) -> int:
    """실측 라벨을 확보하기 전의 대기시간 추정값(분)."""
    ticket_pressure = ticket_count * 0.4
    seat_pressure = seat_occupancy * 8
    return int(ticket_pressure + seat_pressure)


def aggregate_slot(db: Session, slot_ts: int):
    """한 5분 슬롯을 집계해 통합 결과를 저장한다."""
    rows = (
        db.query(models.Reading)
        .filter(models.Reading.timestamp >= slot_ts)
        .filter(models.Reading.timestamp < slot_ts + SLOT_MS)
        .all()
    )
    if not rows:
        return None

    static_values = []   # mmWave 정적 에너지 (좌석 점유)
    motion_values = []   # CSI 진폭 분산 (움직임)
    ticket_total = 0

    for reading in rows:
        features = reading.features
        if reading.source == "mmwave" and "mm_static_energy" in features:
            static_values.append(features["mm_static_energy"])
        elif reading.source == "csi" and "csi_amp_var" in features:
            motion_values.append(features["csi_amp_var"])
        elif reading.source == "external":
            ticket_total += features.get("ext_ticket_count", 0)

    # 정적 좌석 점유율 = 구역별 정적 에너지 평균
    seat_occupancy = sum(static_values) / len(static_values) if static_values else 0.0

    # 움직임 수준 = CSI 분산 평균 (0~0.6 정도로 나오므로 정규화)
    motion = sum(motion_values) / len(motion_values) if motion_values else 0.0
    motion_norm = min(1.0, motion / 0.6)

    # 혼합 가중치는 실측 데이터로 검증하기 전의 임시값이다.
    overall_density = min(1.0, seat_occupancy * 0.7 + motion_norm * 0.3)

    seat_level = to_level(seat_occupancy)
    overall_level = to_level(overall_density)
    wait = estimate_wait(ticket_total, seat_occupancy)

    existing = (
        db.query(models.Result)
        .filter(models.Result.timestamp == slot_ts)
        .first()
    )
    if existing:
        row = existing
    else:
        row = models.Result(timestamp=slot_ts)
        db.add(row)

    row.ticket_count = ticket_total
    row.seat_occupancy = seat_occupancy
    row.seat_level = seat_level
    row.overall_density = overall_density
    row.overall_level = overall_level
    row.wait_minutes = wait

    db.commit()
    return row
