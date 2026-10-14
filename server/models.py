from sqlalchemy import Column, Integer, String, Float, JSON, Index, UniqueConstraint
from server.database import Base


class Reading(Base):
    """센서에서 들어오는 5초 단위 특징값."""
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, index=True)

    # 규격: epoch milliseconds 정수, 5초 grid (window 시작 시각)
    timestamp = Column(Integer, nullable=False, index=True)

    # 기존 수신 테이블은 보존한다. 새 수신은 CsiMeasurement/KioskSample 사용.
    source = Column(String, nullable=False)

    # 기존 센서 식별자
    identifier = Column(String, nullable=True)

    # 특징값 전체를 딕셔너리로 저장
    # 예: {"csi_amp_var": 0.31, "csi_packet_count": 493}
    features = Column(JSON, nullable=False)


class Result(Base):
    """기존 임시 계산 이력. 새 API에서는 조회하거나 갱신하지 않는다."""
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Integer, nullable=False, index=True)  # 5분 슬롯 시작

    ticket_count = Column(Integer, nullable=True)      # 최근 5분 발권량
    seat_occupancy = Column(Float, nullable=True)      # 정적 좌석 점유율 0~1
    seat_level = Column(String, nullable=True)         # 여유|보통|혼잡
    overall_density = Column(Float, nullable=True)     # 전체 밀도 0~1
    overall_level = Column(String, nullable=True)      # 여유|보통|혼잡
    wait_minutes = Column(Integer, nullable=True)


Index("ix_readings_ts_source", Reading.timestamp, Reading.source)


class CsiMeasurement(Base):
    __tablename__ = "csi_measurements"
    __table_args__ = (UniqueConstraint("location_id", "floor", "link_id", "timestamp"),)

    id = Column(Integer, primary_key=True)
    location_id = Column(String, nullable=False, index=True)
    floor = Column(Integer, nullable=False)
    link_id = Column(String, nullable=False)
    timestamp = Column(Integer, nullable=False, index=True)
    received_at = Column(Integer, nullable=False)
    session_id = Column(String, nullable=False)
    features = Column(JSON, nullable=False)
    inference = Column(JSON, nullable=False)


class KioskSample(Base):
    """한 키오스크가 5초 구간에 새로 발권한 건수. 0건 구간도 전송한다."""
    __tablename__ = "kiosk_samples"
    __table_args__ = (UniqueConstraint("location_id", "kiosk_id", "timestamp"),)

    id = Column(Integer, primary_key=True)
    location_id = Column(String, nullable=False, index=True)
    kiosk_id = Column(String, nullable=False)
    timestamp = Column(Integer, nullable=False, index=True)
    received_at = Column(Integer, nullable=False)
    count = Column(Integer, nullable=False)
