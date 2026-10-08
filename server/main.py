import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from typing import Any, Dict, Optional

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, engine, get_db
import models
import predict
from menu_service import menu_service, WEB_ROOT

Base.metadata.create_all(bind=engine)


async def update_menu_cache():
    while True:
        try:
            await asyncio.to_thread(menu_service.refresh)
        except Exception:
            logging.exception("Menu cache update failed")
        # Check expiry each minute; official sites are fetched once per hour.
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app):
    updater = asyncio.create_task(update_menu_cache())
    try:
        yield
    finally:
        updater.cancel()
        with suppress(asyncio.CancelledError):
            await updater


app = FastAPI(title="KICS 혼잡도 서버", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReadingIn(BaseModel):
    """센서가 보내는 데이터 형식."""
    timestamp: int
    source: str
    identifier: Optional[str] = None
    features: Dict[str, Any]


def _to_dict(row):
    return {
        "ticket_count": row.ticket_count,
        "seat_occupancy": round(row.seat_occupancy or 0, 3),
        "seat_level": row.seat_level,
        "overall_density": round(row.overall_density or 0, 3),
        "overall_level": row.overall_level,
        "wait_minutes": row.wait_minutes,
    }


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/menus")
def get_menus(refresh: bool = False):
    """Official weekly menus. Manual refresh is limited to once per minute."""
    return JSONResponse(menu_service.refresh(force=refresh), headers={"Cache-Control": "no-store"})


app.mount("/dashboard", StaticFiles(directory=str(WEB_ROOT), html=True), name="dashboard")


@app.post("/ingest")
def ingest(reading: ReadingIn, db: Session = Depends(get_db)):
    """센서 데이터를 받아 DB에 저장한다."""
    row = models.Reading(
        timestamp=reading.timestamp,
        source=reading.source,
        identifier=reading.identifier,
        features=reading.features,
    )
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id}


@app.get("/readings")
def get_readings(limit: int = 20, db: Session = Depends(get_db)):
    """최근 수신 데이터 확인용."""
    rows = (
        db.query(models.Reading)
        .order_by(models.Reading.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": reading.timestamp,
            "source": reading.source,
            "identifier": reading.identifier,
            "features": reading.features,
        }
        for reading in rows
    ]


@app.post("/aggregate")
def run_aggregate(slot_ts: int = None, db: Session = Depends(get_db)):
    """5분 슬롯을 집계한다."""
    if slot_ts is None:
        slot_ts = predict.slot_start(int(time.time() * 1000))

    row = predict.aggregate_slot(db, slot_ts)
    if row is None:
        return {"slot": slot_ts, "result": None}
    return {"slot": slot_ts, "result": _to_dict(row)}


@app.get("/congestion")
def get_congestion(db: Session = Depends(get_db)):
    """최신 슬롯의 통합 혼잡도."""
    row = (
        db.query(models.Result)
        .order_by(models.Result.timestamp.desc())
        .first()
    )
    if not row:
        return {"slot": None, "result": None}
    return {"slot": row.timestamp, "result": _to_dict(row)}
