from sqlalchemy import Column, Integer, String, Float, JSON, Index
from database import Base


class Reading(Base):
    """센서에서 들어오는 5초 단위 특징값."""
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, index=True)

    # 규격: epoch milliseconds 정수, 5초 grid (window 시작 시각)
    timestamp = Column(Integer, nullable=False, index=True)

    # "csi" | "mmwave" | "external"
    source = Column(String, nullable=False)

    # CSI는 link_1~4, mmWave는 zone_A~D, external은 없음
    identifier = Column(String, nullable=True)

    # 특징값 전체를 딕셔너리로 저장
    # 예: {"csi_amp_var": 0.31, "csi_packet_count": 493}
    features = Column(JSON, nullable=False)


class Result(Base):
    """5분 슬롯마다 계산한 통합 결과."""
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