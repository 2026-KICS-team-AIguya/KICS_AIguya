import logging
import os
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException

from server.models import CsiMeasurement, KioskSample
from server.predict import summarize

GRID_MS = 5_000
WINDOW_MS = 300_000
STALE_MS = 30_000
FLOORS = {"sangnok": [1, 2, 3], "dormitory": [0], "business": [-2], "test": [0]}


@dataclass(frozen=True)
class SensorScope:
    location_id: str = "sangnok"
    floor: int = 1
    link_id: str = "link_3"
    mode: str = "test"

    @classmethod
    def from_environment(cls):
        scope = cls(os.getenv("CSI_LOCATION_ID", "sangnok"), int(os.getenv("CSI_FLOOR", "1")),
                    os.getenv("CSI_LINK_ID", "link_3"), os.getenv("CSI_MODE", "test"))
        if scope.floor not in FLOORS.get(scope.location_id, []) or scope.mode not in ("test", "live"):
            raise ValueError("CSI_LOCATION_ID, CSI_FLOOR, CSI_MODE 설정을 확인하세요.")
        return scope

    def as_dict(self):
        return {"location_id": self.location_id, "floor": self.floor, "link_id": self.link_id, "mode": self.mode}


class CongestionService:
    def __init__(self, scope=None, predictor=None, clock=None):
        self.scope = scope or SensorScope.from_environment()
        self.predictor = predictor
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.lock = threading.RLock()
        self.session_id = str(uuid4())
        self.error = None
        self.input_kind = None

    def start(self):
        if self.predictor is not None:
            return
        try:
            from ai.main import CongestionPredictor
            # 모델 입력·등급 규격 검사는 CongestionPredictor가 직접 한다 (맞지 않으면 ValueError)
            self.predictor = CongestionPredictor()
        except Exception as error:
            self.error = "모델 파일 또는 AI 패키지를 확인하세요."
            logging.exception("AI initialization failed: %s", error)

    def ingest(self, db, reading):
        location = reading.location_id or self.scope.location_id
        floor = reading.floor if reading.floor is not None else self.scope.floor
        if (location, floor, reading.identifier) != (self.scope.location_id, self.scope.floor, self.scope.link_id):
            raise HTTPException(422, "CSI 한 쌍의 설치 위치와 link_id가 서버 설정과 다릅니다.")
        if self.predictor is None:
            raise HTTPException(503, self.error or "AI 초기화 전입니다.")
        if self.scope.mode == "live" and reading.input_kind != "sensor":
            raise HTTPException(422, "실측 모드에서는 실제 센서 입력만 사용할 수 있습니다.")
        row = {**reading.features, "timestamp": reading.timestamp, "link_id": reading.identifier}
        try:
            self.predictor.check_schema(row)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with self.lock:
            if self.input_kind is not None and self.input_kind != reading.input_kind:
                raise HTTPException(409, "입력 종류를 전환하려면 서버를 재시작해 기준값을 다시 수집하세요.")
            existing = db.query(CsiMeasurement).filter_by(location_id=location, floor=floor,
                        link_id=reading.identifier, timestamp=reading.timestamp).first()
            if existing:
                if existing.features != reading.features or existing.inference.get("input_kind", "sensor") != reading.input_kind:
                    raise HTTPException(409, "같은 시각의 CSI 데이터 내용이 다릅니다.")
                return {"ok": True, "id": existing.id, "duplicate": True, "inference": existing.inference}
            latest = db.query(CsiMeasurement).filter_by(location_id=location, floor=floor,
                     link_id=reading.identifier).order_by(CsiMeasurement.timestamp.desc()).first()
            if latest and reading.timestamp < latest.timestamp:
                raise HTTPException(409, "CSI 데이터는 시각 순서대로 전송하세요.")
            if reading.features.get("csi_packet_count") in (0, "0"):
                inference = {"timestamp": reading.timestamp, "link_id": reading.identifier,
                             "status": "skipped", "reason": "no_packets"}
            else:
                inference = self.predictor.update(row)
            inference = {**inference, "input_kind": reading.input_kind}
            measurement = CsiMeasurement(location_id=location, floor=floor, link_id=reading.identifier,
                          timestamp=reading.timestamp, received_at=self.clock(), session_id=self.session_id,
                          features=reading.features, inference=inference)
            db.add(measurement)
            try:
                db.commit()
            except Exception:
                db.rollback()
                self.predictor.reset_calibration()
                self.session_id = str(uuid4())
                self.input_kind = None
                raise
            self.input_kind = reading.input_kind
            return {"ok": True, "id": measurement.id, "duplicate": False, "inference": inference}

    def floor_snapshot(self, db, location, floor, now):
        result = {"floor": floor, "status": "unconnected", "level": None, "confidence": None,
                  "timestamp": None, "received_at": None, "mode": None, "history": []}
        if (location, floor) != (self.scope.location_id, self.scope.floor):
            return result
        result["mode"] = self.scope.mode
        result["input_kind"] = self.input_kind
        if self.predictor is None:
            return {**result, "status": "unavailable", "reason": self.error}
        rows = db.query(CsiMeasurement).filter_by(location_id=location, floor=floor, link_id=self.scope.link_id,
               session_id=self.session_id).filter(CsiMeasurement.timestamp >= now - 3_600_000).order_by(CsiMeasurement.timestamp).all()
        latest = db.query(CsiMeasurement).filter_by(location_id=location, floor=floor, link_id=self.scope.link_id,
                 session_id=self.session_id).order_by(CsiMeasurement.timestamp.desc()).first()
        result["history"] = summarize(rows)
        if latest is None:
            return {**result, "status": "waiting"}
        result.update(timestamp=latest.timestamp, received_at=latest.received_at)
        signal = next((item for item in reversed(rows) if item.features.get("csi_packet_count") not in (0, "0")), None)
        if latest.features.get("csi_packet_count") in (0, "0") and (signal is None or now - signal.timestamp - GRID_MS > STALE_MS):
            return {**result, "status": "stale"}
        if now - latest.received_at > STALE_MS or now - latest.timestamp - GRID_MS > STALE_MS:
            return {**result, "status": "stale"}
        return {**result, **latest.inference}

    def snapshot(self, db, location):
        now = self.clock()
        return {"version": 2, "location_id": location, "server_time": now, "sensor_scope": self.scope.as_dict(),
                "floors": [self.floor_snapshot(db, location, floor, now) for floor in FLOORS[location]],
                "kiosk": kiosk_summary(db, location, now)}


def ingest_kiosk(db, sample, now):
    existing = db.query(KioskSample).filter_by(location_id=sample.location_id, kiosk_id=sample.kiosk_id,
               timestamp=sample.timestamp).first()
    if existing:
        if existing.count != sample.count:
            raise HTTPException(409, "같은 발권 구간의 건수가 다릅니다.")
        return {"ok": True, "duplicate": True, "id": existing.id}
    row = KioskSample(**sample.model_dump(), received_at=now)
    db.add(row)
    db.commit()
    return {"ok": True, "duplicate": False, "id": row.id}


def kiosk_summary(db, location, now):
    end = now // GRID_MS * GRID_MS
    rows = db.query(KioskSample).filter_by(location_id=location).filter(
           KioskSample.timestamp >= end - 2 * WINDOW_MS, KioskSample.timestamp < end).all()
    # 누락 구간은 0건이 아니다. 등록된 키오스크마다 0건 구간도 전송해야 한다.
    devices = {device for (device,) in db.query(KioskSample.kiosk_id).filter_by(location_id=location).distinct().all()}
    received = {(row.kiosk_id, row.timestamp): row.count for row in rows}
    def window(start):
        keys = [(device, timestamp) for device in devices for timestamp in range(start, start + WINDOW_MS, GRID_MS)]
        return sum(received[key] for key in keys) if keys and all(key in received for key in keys) else None
    recent, previous = window(end - WINDOW_MS), window(end - 2 * WINDOW_MS)
    change = recent - previous if recent is not None and previous is not None else None
    last = db.query(KioskSample).filter_by(location_id=location).order_by(KioskSample.timestamp.desc()).first()
    status = "waiting" if last is None else "collecting" if recent is None else "ok"
    if last and (now - last.received_at > STALE_MS or now - last.timestamp - GRID_MS > STALE_MS):
        status, recent, previous, change = "stale", None, None, None
    return {"status": status, "scope": "식당 전체 · 등록된 키오스크", "as_of": end,
            "recent": recent, "previous": previous, "change": change,
            "percent": round(change / previous * 100) if change is not None and previous else None,
            "received_at": last.received_at if last else None}
