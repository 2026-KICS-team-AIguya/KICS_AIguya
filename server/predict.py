"""AI 출력을 5분 단위 등급 확률 요약으로 묶는다. 점유율은 계산하지 않는다."""
from collections import defaultdict

SLOT_MS = 300_000
LEVELS = ("여유", "보통", "혼잡")


def slot_start(timestamp_ms):
    return timestamp_ms // SLOT_MS * SLOT_MS


def summarize(measurements):
    slots = defaultdict(list)
    for measurement in measurements:
        if measurement.inference["status"] == "ok":
            slots[slot_start(measurement.timestamp)].append(measurement.inference)
    result = []
    for timestamp, predictions in sorted(slots.items()):
        proba = {level: sum(item["proba"].get(level, 0) for item in predictions) / len(predictions) for level in LEVELS}
        level = max(proba, key=proba.get)
        result.append({"timestamp": timestamp, "level": level, "confidence": proba[level], "samples": len(predictions)})
    return result
