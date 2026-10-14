import asyncio
import json
import logging
import math
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal

# 저장소 루트 실행과 --app-dir server 실행을 함께 지원한다.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from server.database import Base, engine
from server.congestion_service import CongestionService, GRID_MS, ingest_kiosk
from server.models import CsiMeasurement
from server.menu_service import menu_service, WEB_ROOT


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: int = Field(strict=True, ge=0)
    source: Literal["csi"] = "csi"
    input_kind: Literal["sensor", "replay", "synthetic"] = "sensor"
    identifier: str = Field(min_length=1, max_length=64, validation_alias=AliasChoices("identifier", "link_id"))
    location_id: str | None = None
    floor: int | None = Field(default=None, strict=True)
    features: dict[str, Any]

    @field_validator("timestamp")
    @classmethod
    def five_second_grid(cls, value):
        if value % GRID_MS:
            raise ValueError("timestamp는 5초 구간 시작 시각(epoch ms)이어야 합니다.")
        return value

    @field_validator("features")
    @classmethod
    def finite_features(cls, values):
        try:
            json.dumps(values, allow_nan=False)
        except (ValueError, TypeError) as error:
            raise ValueError("NaN/Infinity 대신 None 또는 빈칸을 사용하세요.") from error
        for key, value in values.items():
            if not key.startswith("csi_"):
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if isinstance(value, (bool, dict, list)):
                raise ValueError(f"숫자가 아닌 특징값: {key}")
            if value is not None:
                try:
                    if not math.isfinite(float(value)):
                        raise ValueError()
                except ValueError as error:
                    raise ValueError(f"유한한 숫자가 아닌 특징값: {key}") from error
            if key == "csi_packet_count" and (float(value) < 0 or not float(value).is_integer()):
                raise ValueError("csi_packet_count는 0 이상의 정수입니다.")
        return values


class KioskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_id: Literal["sangnok", "dormitory", "business", "test"]
    kiosk_id: str = Field(default="main", min_length=1, max_length=64)
    timestamp: int = Field(strict=True, ge=0)
    count: int = Field(strict=True, ge=0)

    @field_validator("timestamp")
    @classmethod
    def five_second_grid(cls, value):
        return ReadingIn.five_second_grid(value)


def create_app(db_engine=None, service=None, menu_updates=True):
    db_engine = db_engine or engine
    service = service or CongestionService()
    sessions = sessionmaker(bind=db_engine)

    async def update_menus():
        while True:
            try:
                await asyncio.to_thread(menu_service.refresh)
            except Exception:
                logging.exception("Menu cache update failed")
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(bind=db_engine)
        service.start()
        updater = asyncio.create_task(update_menus()) if menu_updates else None
        try:
            yield
        finally:
            if updater:
                updater.cancel()
                with suppress(asyncio.CancelledError):
                    await updater

    app = FastAPI(title="KICS CSI 혼잡도 서버", lifespan=lifespan)
    app.state.congestion = service
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # NaN이 포함된 잘못된 원본 입력을 JSON 응답에 다시 넣지 않는다.
        errors = [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    def get_db():
        with sessions() as db:
            yield db

    def validate_time(timestamp):
        if timestamp + GRID_MS > service.clock() + 10_000:
            raise HTTPException(422, "미래 구간은 아직 수집할 수 없습니다.")

    @app.get("/")
    def root():
        return {"status": "ok", "ai_ready": service.predictor is not None, "sensor_scope": service.scope.as_dict()}

    @app.post("/ingest")
    def ingest(reading: ReadingIn, db: Session = Depends(get_db)):
        validate_time(reading.timestamp)
        return service.ingest(db, reading)

    @app.post("/kiosk/ingest")
    def kiosk_ingest(sample: KioskIn, db: Session = Depends(get_db)):
        validate_time(sample.timestamp)
        if sample.timestamp + GRID_MS > service.clock():
            raise HTTPException(422, "완료된 5초 구간의 발권량을 전송하세요.")
        with service.lock:
            return ingest_kiosk(db, sample, service.clock())

    @app.get("/readings")
    def readings(limit: int = Query(20, ge=1, le=1000), db: Session = Depends(get_db)):
        rows = db.query(CsiMeasurement).order_by(CsiMeasurement.id.desc()).limit(limit).all()
        return [{"timestamp": row.timestamp, "identifier": row.link_id, "location_id": row.location_id,
                 "floor": row.floor, "features": row.features, "inference": row.inference} for row in rows]

    @app.get("/congestion")
    def congestion(location_id: Literal["sangnok", "dormitory", "business", "test"] = "sangnok", db: Session = Depends(get_db)):
        return JSONResponse(service.snapshot(db, location_id), headers={"Cache-Control": "no-store"})

    @app.post("/aggregate")
    def aggregate(location_id: Literal["sangnok", "dormitory", "business", "test"] = "sangnok", db: Session = Depends(get_db)):
        return {"floors": service.snapshot(db, location_id)["floors"]}

    @app.get("/menus")
    def menus(refresh: bool = False):
        return JSONResponse(menu_service.refresh(force=refresh), headers={"Cache-Control": "no-store"})

    app.mount("/dashboard", StaticFiles(directory=str(WEB_ROOT), html=True), name="dashboard")
    return app


app = create_app()
