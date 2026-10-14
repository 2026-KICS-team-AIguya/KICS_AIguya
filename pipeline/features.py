"""CSI 담당의 학습용 계산 함수를 재사용하는 5초 특징값 조립기."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "csi/logger", ROOT / "csi/processing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from ai.scripts.config import FEATURES
from candidate_features import FEATURE_FIELDS as CANDIDATE_FIELDS, packet_amplitudes, window_features
from offline_feature import FEATURE_FIELDS as BASE_FIELDS, feature_row
from tcp_receiver import WINDOW_MS, WindowStats, calculate_packet_mean_amplitude, next_grid_start_ms, update_window_stats


class FeatureAssembler:
    def __init__(self, link_id="link_3", expected_pps=36):
        self.link_id = link_id
        self.expected_packets = round(expected_pps * WINDOW_MS / 1000)
        self.windows = {}
        self.last_packet_ids = {}
        self.next_window = None

    def add(self, row):
        if row["link_id"] != self.link_id:
            return
        host_ms, packet_id, rssi = int(row["host_epoch_ms"]), int(row["packet_id"]), int(row["rssi"])
        if self.next_window is None:
            self.next_window = next_grid_start_ms(host_ms)
        if host_ms < self.next_window:
            return
        timestamp = host_ms // WINDOW_MS * WINDOW_MS
        window = self.windows.setdefault(timestamp, {"stats": WindowStats(), "ids": [], "amps": [], "rssis": [], "seen": set()})
        update_window_stats(window["stats"], packet_id, self.link_id, self.last_packet_ids,
                            rssi, calculate_packet_mean_amplitude(row["csi_data"]))
        amplitudes = packet_amplitudes(row["csi_data"])
        if amplitudes is not None and packet_id not in window["seen"]:
            window["seen"].add(packet_id)
            window["ids"].append(packet_id)
            window["amps"].append(amplitudes)
            window["rssis"].append(rssi)

    def complete(self, now_ms, grace_ms=2000):
        while self.next_window is not None and self.next_window + WINDOW_MS + grace_ms <= now_ms:
            timestamp = self.next_window
            window = self.windows.pop(timestamp, {"stats": WindowStats(), "ids": [], "amps": [], "rssis": []})
            base = dict(zip(BASE_FIELDS, feature_row(timestamp, self.link_id, window["stats"], self.expected_packets)))
            candidates = dict(zip(CANDIDATE_FIELDS[2:], window_features(window["ids"], window["amps"], window["rssis"])))
            # 학습용 CSV의 join 조건과 동일하게 패킷 집합이 다르면 후보 값을 사용하지 않는다.
            if base["csi_packet_count"] != candidates["csi_packet_count"]:
                candidates = {name: None for name in CANDIDATE_FIELDS[4:]}
            merged = {**base, **candidates}
            features = {name: None if merged.get(name) == "" else merged.get(name) for name in FEATURES}
            features.update({name: base[name] for name in ("csi_packet_count", "csi_missing_rate")})
            yield {"timestamp": timestamp, "link_id": self.link_id, "features": features}
            self.next_window += WINDOW_MS
