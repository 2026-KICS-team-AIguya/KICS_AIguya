from __future__ import annotations

import argparse
import csv
import json
import math
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

from raw_logger import (
    CSI_FIELDS,
    CSIParseError,
    parse_csi_line,
)

import sys
import urllib.request
import urllib.error
import numpy as np

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5001
DEFAULT_INGEST_URL = "http://127.0.0.1:8000/ingest"

WINDOW_MS = 5_000
FLUSH_INTERVAL_SECONDS = 1.0
FEATURE_FLUSH_GRACE_MS = 2_000

MAX_TCP_LINE_BYTES = 8_192
RECV_BUFFER_BYTES = 4_096

VALID_LINK_IDS = {
    "link_1",
    "link_2",
    "link_3",
    "link_4",
}
DEFAULT_1TO4_LINKS = {"link_1", "link_2", "link_3", "link_4"}

FEATURE_FIELDS = [
    "timestamp",
    "link_id",
    "csi_packet_count",
    "csi_missing_rate",
    "csi_rssi_mean",
    "csi_amp_mean",
    "csi_amp_std",
    "csi_amp_var",
    "csi_distortion_cv_pct",
    "csi_expected_packet_count",
    "csi_id_gap_count",
    "csi_received_row_count",
    "csi_duplicate_count",
    "csi_reset_count",
    "csi_over_expected_count",
    # Candidate Features 6개
    "csi_sc_corr_mean",
    "csi_temporal_var_mean",
    "csi_temporal_diff_mean",
    "csi_temporal_diff_std",
    "csi_amp_range",
    "csi_rssi_std",
]

STOP_RECORD = object()


@dataclass(frozen=True)
class PacketRecord:
    host_epoch_ms: int
    link_id: str
    row: list[str]
    packet_id: int
    rssi: int = -50
    noise_floor: int = -90
    mean_amplitude: float = 0.0
    cand_amp: np.ndarray | None = None


@dataclass(frozen=True)
class StartCollection:
    host_epoch_ms: int


@dataclass
class WindowStats:
    received_rows: int = 0
    packet_ids: set[int] = field(default_factory=set)

    id_gap_count: int = 0
    duplicate_count: int = 0
    reset_count: int = 0

    # RSSI Statistics
    rssi_sum: float = 0.0
    rssi_count: int = 0

    # CSI Amplitude & Distortion Statistics for 5s Window
    amp_sum: float = 0.0
    amp_sq_sum: float = 0.0
    amp_count: int = 0

    # Candidate Features (6개) 계산용 데이터 (중복 packet_id 제외)
    cand_seen_ids: set[int] = field(default_factory=set)
    cand_packet_ids: list[int] = field(default_factory=list)
    cand_amps: list[np.ndarray] = field(default_factory=list)
    cand_rssis: list[int] = field(default_factory=list)


@dataclass
class LinkLiveStats:
    connected: bool = False
    addr: tuple | None = None
    valid_packets: int = 0
    malformed_lines: int = 0
    last_packet_id: int | None = None
    id_gaps: int = 0
    recent_packets: int = 0
    recent_rssi_sum: float = 0.0
    recent_amp_sum: float = 0.0
    recent_amp_sq_sum: float = 0.0
    last_report_time: float = field(default_factory=time.monotonic)
    current_pps: float = 0.0
    current_rssi: float = 0.0
    current_amp_mean: float = 0.0
    current_distortion_cv: float = 0.0


class ConnectionRegistry:
    def __init__(
        self,
        expected_links: set[str],
        record_queue: Queue,
    ):
        self.expected_links = expected_links
        self.record_queue = record_queue
        self.lock = threading.Lock()

        self.connections: dict[
            str,
            tuple[socket.socket, tuple]
        ] = {}

        self.link_stats: dict[str, LinkLiveStats] = {
            link: LinkLiveStats() for link in expected_links
        }

        self.collection_started = False

    def claim(
        self,
        link_id: str,
        conn: socket.socket,
        addr: tuple,
    ) -> bool:
        """
        link_id를 현재 TCP 연결에 등록한다.
        이전 유령 세션(stale connection)이 남아있다면 기존 소켓을 안전하게 닫고
        새로운 연결로 즉시 덮어쓴다(Overwrite).
        """
        with self.lock:
            old_conn_tuple = self.connections.get(link_id)
            if old_conn_tuple is not None:
                old_sock, old_addr = old_conn_tuple
                if old_sock is not conn:
                    print(
                        f"[RECONNECT OVERWRITE] {link_id} reconnected from {addr} "
                        f"(closed stale session from {old_addr})"
                    )
                    try:
                        if hasattr(old_sock, "shutdown"):
                            old_sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        if hasattr(old_sock, "close"):
                            old_sock.close()
                    except OSError:
                        pass

            self.connections[link_id] = (conn, addr)

            if link_id not in self.link_stats:
                self.link_stats[link_id] = LinkLiveStats()

            self.link_stats[link_id].connected = True
            self.link_stats[link_id].addr = addr

            connected_links = set(self.connections)
            print(
                f"[REGISTRY] Active Links: {sorted(connected_links)} "
                f"({len(connected_links)}/{len(self.expected_links)})"
            )

            if (
                not self.collection_started
                and connected_links >= self.expected_links
            ):
                self.collection_started = True

                # 모든 RX 연결 직후의 불안정 구간을 제외한다 (2초 유예).
                start_epoch_ms = (
                    time.time_ns() // 1_000_000 + 2_000
                )

                self.record_queue.put(
                    StartCollection(host_epoch_ms=start_epoch_ms)
                )
                print(
                    "\n" + "=" * 65 + "\n"
                    f"🎉 All {len(self.expected_links)} RX links connected! 3-Hour Sensing starting...\n"
                    + "=" * 65 + "\n"
                )

            return True

    def release(
        self,
        link_id: str | None,
        conn: socket.socket,
    ) -> None:
        if link_id is None:
            return

        with self.lock:
            current = self.connections.get(link_id)
            if current is not None and current[0] is conn:
                del self.connections[link_id]
                if link_id in self.link_stats:
                    self.link_stats[link_id].connected = False

    def close_all(self) -> None:
        with self.lock:
            connections = [
                value[0] for value in self.connections.values()
            ]

        for conn in connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass


def parse_link_ids(value: str) -> set[str]:
    links = {
        item.strip()
        for item in value.split(",")
        if item.strip()
    }

    if not links:
        raise argparse.ArgumentTypeError(
            "at least one link is required"
        )

    invalid = links - VALID_LINK_IDS
    if invalid:
        raise argparse.ArgumentTypeError(
            "invalid link ID: " + ", ".join(sorted(invalid))
        )

    return links


def calculate_packet_mean_amplitude(csi_data_str: str) -> float:
    """
    CSI JSON 문자열에서 서브캐리어 진폭 평균을 계산한다.
    ESP32 CSI는 I/Q 쌍으로 구성될 수 있으므로
    2바이트씩 묶어 sqrt(I^2 + Q^2)의 평균을 계산한다.
    """
    try:
        raw_values = json.loads(csi_data_str)
        if not isinstance(raw_values, list) or len(raw_values) == 0:
            return 0.0

        n = len(raw_values)
        if n >= 2 and n % 2 == 0:
            # I/Q Pairs
            amp_sum = 0.0
            subcarrier_count = n // 2
            for i in range(0, n, 2):
                real = float(raw_values[i])
                imag = float(raw_values[i + 1])
                amp_sum += math.sqrt(real * real + imag * imag)
            return amp_sum / subcarrier_count if subcarrier_count > 0 else 0.0
        else:
            # Single value per subcarrier
            amp_sum = sum(abs(float(v)) for v in raw_values)
            return amp_sum / n
    except Exception:
        return 0.0


def grid_start_ms(epoch_ms: int) -> int:
    """epoch milliseconds를 5초 grid의 시작 시각으로 내린다."""
    return (epoch_ms // WINDOW_MS) * WINDOW_MS


def next_grid_start_ms(epoch_ms: int) -> int:
    """epoch milliseconds 이후의 첫 완전한 5초 grid를 반환한다."""
    return ((epoch_ms + WINDOW_MS - 1) // WINDOW_MS) * WINDOW_MS


_packet_amplitudes_fn = None
_window_features_fn = None


def _load_candidate_fns():
    global _packet_amplitudes_fn, _window_features_fn
    if _packet_amplitudes_fn is None or _window_features_fn is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "processing"))
        from candidate_features import packet_amplitudes, window_features
        _packet_amplitudes_fn = packet_amplitudes
        _window_features_fn = window_features
    return _packet_amplitudes_fn, _window_features_fn


def update_window_stats(
    stats: WindowStats,
    packet_id: int,
    link_id: str,
    last_packet_ids: dict[str, int],
    rssi: int = -50,
    mean_amplitude: float = 0.0,
    cand_amp: np.ndarray | None = None,
) -> None:
    stats.received_rows += 1

    if packet_id in stats.packet_ids:
        stats.duplicate_count += 1

    stats.packet_ids.add(packet_id)

    # RSSI 통계 누적
    stats.rssi_sum += rssi
    stats.rssi_count += 1

    # Amplitude 통계 누적
    if mean_amplitude > 0.0:
        stats.amp_sum += mean_amplitude
        stats.amp_sq_sum += mean_amplitude * mean_amplitude
        stats.amp_count += 1

    # Candidate Features 6개용 데이터 누적 (중복 packet_id 제외)
    if cand_amp is not None and packet_id not in stats.cand_seen_ids:
        stats.cand_seen_ids.add(packet_id)
        stats.cand_packet_ids.append(packet_id)
        stats.cand_amps.append(cand_amp)
        stats.cand_rssis.append(rssi)

    previous_id = last_packet_ids.get(link_id)
    if previous_id is None:
        last_packet_ids[link_id] = packet_id
        return

    # uint32 packet ID wrap-around 처리
    delta = (packet_id - previous_id) & 0xFFFFFFFF

    if delta == 0:
        stats.duplicate_count += 1
    elif delta < 0x80000000:
        gap = delta - 1
        if gap > 0:
            stats.id_gap_count += gap
        last_packet_ids[link_id] = packet_id
    else:
        # TX 재부팅 또는 역순 데이터
        stats.reset_count += 1
        last_packet_ids[link_id] = packet_id


def ingest_worker(
    ingest_queue: Queue,
    ingest_url: str,
    stop_event: threading.Event,
) -> None:
    """5초마다 완성된 feature JSON을 백엔드 /ingest로 HTTP POST 전송하는 비동기 워커."""
    last_warn_time = 0.0
    while not stop_event.is_set():
        try:
            item = ingest_queue.get(timeout=0.5)
        except Empty:
            continue

        if item is STOP_RECORD:
            break

        try:
            body = json.dumps(item).encode("utf-8")
            req = urllib.request.Request(
                ingest_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.5):
                pass
        except Exception as exc:
            now = time.monotonic()
            if now - last_warn_time >= 5.0:
                print(
                    f"[INGEST WARN] Failed to send window to {ingest_url}: {exc}",
                    file=sys.stderr,
                )
                last_warn_time = now


def write_feature_window(
    writer: csv.writer,
    window_start: int,
    active_links: tuple[str, ...],
    expected_packet_count: int,
    windows: dict[tuple[int, str], WindowStats],
    ingest_queue: Queue | None = None,
) -> None:
    for link_id in active_links:
        stats = windows.pop((window_start, link_id), WindowStats())

        # 동일 ID 중복은 패킷 수에 한 번만 반영
        packet_count = len(stats.packet_ids)

        missing_count = max(expected_packet_count - packet_count, 0)
        missing_rate = (
            missing_count / expected_packet_count
            if expected_packet_count > 0
            else 0.0
        )

        over_expected_count = max(packet_count - expected_packet_count, 0)

        # RSSI 평균
        csi_rssi_mean = (
            stats.rssi_sum / stats.rssi_count
            if stats.rssi_count > 0
            else 0.0
        )

        # 5초 Window 진폭 및 왜곡도 통계
        if stats.amp_count > 0:
            csi_amp_mean = stats.amp_sum / stats.amp_count
            csi_amp_var = max(
                0.0,
                (stats.amp_sq_sum / stats.amp_count) - (csi_amp_mean * csi_amp_mean)
            )
            csi_amp_std = math.sqrt(csi_amp_var)
            # 변동 계수 (Coefficient of Variation = 왜곡도 지표)
            csi_distortion_cv = (
                (csi_amp_std / csi_amp_mean) * 100.0
                if csi_amp_mean > 0
                else 0.0
            )
        else:
            csi_amp_mean = 0.0
            csi_amp_var = 0.0
            csi_amp_std = 0.0
            csi_distortion_cv = 0.0

        # Candidate 6개 feature 계산 (candidate_features.py 호출)
        _, window_features_fn = _load_candidate_fns()
        cand_results = window_features_fn(
            stats.cand_packet_ids,
            stats.cand_amps,
            stats.cand_rssis,
        )
        # cand_results = [n, pair_count, sc_corr_mean, temporal_var_mean, temporal_diff_mean, temporal_diff_std, amp_range, rssi_std]
        cand_sc_corr_mean = cand_results[2]
        cand_temporal_var_mean = cand_results[3]
        cand_temporal_diff_mean = cand_results[4]
        cand_temporal_diff_std = cand_results[5]
        cand_amp_range = cand_results[6]
        cand_rssi_std = cand_results[7]

        writer.writerow(
            [
                window_start,
                link_id,
                packet_count,
                round(missing_rate, 6),
                round(csi_rssi_mean, 2),
                round(csi_amp_mean, 4),
                round(csi_amp_std, 4),
                round(csi_amp_var, 4),
                round(csi_distortion_cv, 2),
                expected_packet_count,
                stats.id_gap_count,
                stats.received_rows,
                stats.duplicate_count,
                stats.reset_count,
                over_expected_count,
                cand_sc_corr_mean,
                cand_temporal_var_mean,
                cand_temporal_diff_mean,
                cand_temporal_diff_std,
                cand_amp_range,
                cand_rssi_std,
            ]
        )

        if ingest_queue is not None:
            def _to_float_or_none(v):
                if v == "" or v is None:
                    return None
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return None

            payload = {
                "timestamp": window_start,
                "source": "csi",
                "identifier": link_id,
                "features": {
                    "csi_packet_count": packet_count,
                    "csi_missing_rate": round(missing_rate, 6),
                    "csi_rssi_mean": _to_float_or_none(round(csi_rssi_mean, 2)) if stats.rssi_count > 0 else None,
                    "csi_amp_mean": _to_float_or_none(round(csi_amp_mean, 4)) if stats.amp_count > 0 else None,
                    "csi_amp_std": _to_float_or_none(round(csi_amp_std, 4)) if stats.amp_count > 0 else None,
                    "csi_amp_var": _to_float_or_none(round(csi_amp_var, 4)) if stats.amp_count > 0 else None,
                    "csi_distortion_cv_pct": _to_float_or_none(round(csi_distortion_cv, 2)) if stats.amp_count > 0 else None,
                    "csi_sc_corr_mean": _to_float_or_none(cand_sc_corr_mean),
                    "csi_temporal_var_mean": _to_float_or_none(cand_temporal_var_mean),
                    "csi_temporal_diff_mean": _to_float_or_none(cand_temporal_diff_mean),
                    "csi_temporal_diff_std": _to_float_or_none(cand_temporal_diff_std),
                    "csi_amp_range": _to_float_or_none(cand_amp_range),
                    "csi_rssi_std": _to_float_or_none(cand_rssi_std),
                },
            }
            try:
                ingest_queue.put_nowait(payload)
            except Exception:
                pass


def storage_loop(
    record_queue: Queue,
    raw_path: Path,
    feature_path: Path,
    active_links: tuple[str, ...],
    expected_pps: float,
    ingest_queue: Queue | None = None,
) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.parent.mkdir(parents=True, exist_ok=True)

    if raw_path.exists():
        raise FileExistsError(f"Raw output already exists: {raw_path}")

    if feature_path.exists():
        raise FileExistsError(f"Feature output already exists: {feature_path}")

    expected_packet_count = round(expected_pps * (WINDOW_MS / 1_000))

    windows: dict[tuple[int, str], WindowStats] = {}
    last_packet_ids: dict[str, int] = {}

    collection_started = False
    first_feature_window: int | None = None
    next_window_to_write: int | None = None

    last_flush = time.monotonic()

    with (
        raw_path.open(
            "x",
            newline="",
            encoding="utf-8",
            buffering=1024 * 1024,
        ) as raw_file,
        feature_path.open(
            "x",
            newline="",
            encoding="utf-8",
            buffering=1024 * 1024,
        ) as feature_file,
    ):
        raw_writer = csv.writer(raw_file)
        feature_writer = csv.writer(feature_file)

        raw_writer.writerow(
            [
                "host_epoch_ms",
                "link_id",
                *CSI_FIELDS,
            ]
        )

        feature_writer.writerow(FEATURE_FIELDS)

        while True:
            try:
                record = record_queue.get(timeout=0.5)
            except Empty:
                record = None

            if record is STOP_RECORD:
                break

            if isinstance(record, StartCollection):
                collection_started = True
                first_feature_window = next_grid_start_ms(record.host_epoch_ms)
                next_window_to_write = first_feature_window

                windows.clear()
                last_packet_ids.clear()

                print(
                    f"[COLLECTION START] First complete 5s grid = {first_feature_window}"
                )

            elif isinstance(record, PacketRecord):
                # Raw 데이터는 Feature 시작 전 데이터도 모두 기록
                raw_writer.writerow(
                    [
                        record.host_epoch_ms,
                        record.link_id,
                        *record.row,
                    ]
                )

                if (
                    collection_started
                    and first_feature_window is not None
                    and record.host_epoch_ms >= first_feature_window
                ):
                    window_start = grid_start_ms(record.host_epoch_ms)
                    key = (window_start, record.link_id)
                    stats = windows.setdefault(key, WindowStats())

                    update_window_stats(
                        stats=stats,
                        packet_id=record.packet_id,
                        link_id=record.link_id,
                        last_packet_ids=last_packet_ids,
                        rssi=record.rssi,
                        mean_amplitude=record.mean_amplitude,
                        cand_amp=record.cand_amp,
                    )

            now_monotonic = time.monotonic()
            if now_monotonic - last_flush >= FLUSH_INTERVAL_SECONDS:
                raw_file.flush()
                feature_file.flush()
                last_flush = now_monotonic

            if collection_started and next_window_to_write is not None:
                now_epoch_ms = time.time_ns() // 1_000_000
                flush_limit = now_epoch_ms - FEATURE_FLUSH_GRACE_MS

                while next_window_to_write + WINDOW_MS <= flush_limit:
                    write_feature_window(
                        writer=feature_writer,
                        window_start=next_window_to_write,
                        active_links=active_links,
                        expected_packet_count=expected_packet_count,
                        windows=windows,
                        ingest_queue=ingest_queue,
                    )
                    next_window_to_write += WINDOW_MS

        raw_file.flush()
        feature_file.flush()


def storage_worker(
    record_queue: Queue,
    raw_path: Path,
    feature_path: Path,
    active_links: tuple[str, ...],
    expected_pps: float,
    stop_event: threading.Event,
    error_queue: Queue,
    ingest_queue: Queue | None = None,
) -> None:
    try:
        storage_loop(
            record_queue=record_queue,
            raw_path=raw_path,
            feature_path=feature_path,
            active_links=active_links,
            expected_pps=expected_pps,
            ingest_queue=ingest_queue,
        )
    except Exception as exc:
        error_queue.put(exc)
        stop_event.set()


def enqueue_record(
    record_queue: Queue,
    record: PacketRecord,
    stop_event: threading.Event,
) -> bool:
    while not stop_event.is_set():
        try:
            record_queue.put(record, timeout=0.5)
            return True
        except Exception:
            continue
    return False


def handle_client(
    conn: socket.socket,
    addr: tuple,
    registry: ConnectionRegistry,
    record_queue: Queue,
    stop_event: threading.Event,
) -> None:
    print(f"[CONNECTED] TCP client from {addr}")

    conn.settimeout(1.0)
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass

    buffer = bytearray()
    link_id: str | None = None

    valid_packets = 0
    malformed_lines = 0

    try:
        while not stop_event.is_set():
            try:
                data = conn.recv(RECV_BUFFER_BYTES)
            except socket.timeout:
                continue

            if not data:
                break

            buffer.extend(data)

            while True:
                newline_index = buffer.find(b"\n")
                if newline_index < 0:
                    break

                raw_line = bytes(buffer[:newline_index]).rstrip(b"\r")
                del buffer[:newline_index + 1]

                if not raw_line:
                    continue

                if len(raw_line) > MAX_TCP_LINE_BYTES:
                    malformed_lines += 1
                    continue

                if raw_line.startswith(b"HELLO,"):
                    if link_id is not None:
                        raise ValueError("duplicate HELLO")

                    try:
                        hello = raw_line.decode("ascii", errors="strict")
                    except UnicodeDecodeError as exc:
                        raise ValueError("invalid HELLO encoding") from exc

                    parts = hello.split(",")
                    if (
                        len(parts) != 2
                        or parts[1] not in registry.expected_links
                    ):
                        raise ValueError(f"invalid HELLO: {hello!r}")

                    candidate_link_id = parts[1]
                    registry.claim(
                        link_id=candidate_link_id,
                        conn=conn,
                        addr=addr,
                    )
                    link_id = candidate_link_id
                    print(f"[HELLO] Registered {link_id} from {addr}")
                    continue

                if raw_line.startswith(b"CSI_DATA,"):
                    if link_id is None:
                        malformed_lines += 1
                        print("[WARN] CSI received before HELLO")
                        continue

                    host_epoch_ms = time.time_ns() // 1_000_000

                    try:
                        parsed = parse_csi_line(raw_line + b"\n")
                    except CSIParseError as exc:
                        malformed_lines += 1
                        print(f"[MALFORMED] {link_id}: {exc}")
                        continue

                    if parsed is None:
                        continue

                    row, packet_id = parsed

                    # RSSI & Noise Floor
                    try:
                        rssi = int(row[3])  # RSSI field
                    except Exception:
                        rssi = -50

                    try:
                        noise = int(row[14]) if len(row) > 14 else -90
                    except Exception:
                        noise = -90

                    # Amplitude feature calculation
                    csi_str = row[24] if len(row) > 24 else ""
                    mean_amp = calculate_packet_mean_amplitude(csi_str)
                    packet_amplitudes_fn, _ = _load_candidate_fns()
                    cand_amp = packet_amplitudes_fn(csi_str)

                    record = PacketRecord(
                        host_epoch_ms=host_epoch_ms,
                        link_id=link_id,
                        row=row,
                        packet_id=packet_id,
                        rssi=rssi,
                        noise_floor=noise,
                        mean_amplitude=mean_amp,
                        cand_amp=cand_amp,
                    )

                    if not enqueue_record(
                        record_queue=record_queue,
                        record=record,
                        stop_event=stop_event,
                    ):
                        break

                    valid_packets += 1

                    # Update live stats for dashboard
                    with registry.lock:
                        st = registry.link_stats.get(link_id)
                        if st:
                            st.valid_packets += 1
                            st.recent_packets += 1
                            st.recent_rssi_sum += rssi
                            st.recent_amp_sum += mean_amp
                            st.recent_amp_sq_sum += mean_amp * mean_amp
                            st.malformed_lines = malformed_lines
                            if st.last_packet_id is not None:
                                gap = (packet_id - st.last_packet_id - 1) & 0xFFFFFFFF
                                if 0 < gap < 0x80000000:
                                    st.id_gaps += gap
                            st.last_packet_id = packet_id

            if len(buffer) > MAX_TCP_LINE_BYTES:
                raise ValueError("TCP line exceeded maximum length")

    except (ConnectionError, OSError, ValueError) as exc:
        if not stop_event.is_set():
            if not (isinstance(exc, OSError) and getattr(exc, "errno", None) == 9):
                print(f"[ERROR] {link_id or addr}: {exc}")

    finally:
        with registry.lock:
            current = registry.connections.get(link_id)
            was_active = (current is not None and current[0] is conn)

        registry.release(link_id=link_id, conn=conn)
        try:
            conn.close()
        except OSError:
            pass

        if was_active:
            print(f"[DISCONNECTED] {link_id or addr}")


def print_dashboard_loop(
    registry: ConnectionRegistry,
    stop_event: threading.Event,
    interval: float = 2.0,
) -> None:
    """
    모든 연결된 1:4 RX 링크의 실시간 패킷 수신 상태 및 신호 왜곡도(CV)를 콘솔에 출력한다.
    """
    last_tick = time.monotonic()
    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            break

        now = time.monotonic()
        elapsed = max(now - last_tick, 0.001)
        last_tick = now

        statuses = []
        with registry.lock:
            for link_id in sorted(registry.expected_links):
                st = registry.link_stats.get(link_id)
                if not st or not st.connected:
                    statuses.append(f"[{link_id}: 🔴 OFF]")
                else:
                    n = st.recent_packets
                    pps = n / elapsed
                    avg_rssi = st.recent_rssi_sum / n if n > 0 else -50.0
                    avg_amp = st.recent_amp_sum / n if n > 0 else 0.0
                    var_amp = max(0.0, (st.recent_amp_sq_sum / n) - (avg_amp * avg_amp)) if n > 0 else 0.0
                    std_amp = math.sqrt(var_amp)
                    cv = (std_amp / avg_amp * 100.0) if avg_amp > 0 else 0.0

                    # Reset recent counters
                    st.recent_packets = 0
                    st.recent_rssi_sum = 0.0
                    st.recent_amp_sum = 0.0
                    st.recent_amp_sq_sum = 0.0

                    # State indicator: CV > 20% indicates motion / fading distortion
                    state_tag = "⚡️동적변동" if cv > 20.0 else "정적안정"

                    statuses.append(
                        f"[{link_id}: 🟢 {pps:4.1f}pps | {avg_rssi:.0f}dBm | 진폭:{avg_amp:.1f} | 왜곡:{cv:4.1f}% ({state_tag})]"
                    )

        # [진단용 - 2026-09-18] RX 쪽 TCP 전송이 막히는 원인이 보드/공유기
        # 쪽이 아니라, 맥 쪽 저장 스레드가 밀려서 record_queue가 쌓이고
        # (그래서 handle_client가 소켓을 못 읽어가고) 있을 가능성을
        # 확인하기 위해 큐 depth를 같이 출력한다. 링크 여러 개가 동시에
        # 막힐 때 이 값이 같이 치솟으면 저장 스레드 쪽 병목이 맞다는 뜻.
        queue_depth = registry.record_queue.qsize()

        time_str = datetime.now().strftime("%H:%M:%S")
        print(
            f"[{time_str}] (record_queue: {queue_depth}) "
            + "\n           ".join(statuses)
        )


def build_paths(output_root: Path) -> tuple[Path, Path]:
    today_str = datetime.now().strftime("%Y%m%d")
    raw_dir = output_root / "raw"
    feature_dir = output_root / "feature"
    raw_dir.mkdir(parents=True, exist_ok=True)
    feature_dir.mkdir(parents=True, exist_ok=True)

    # 오늘 날짜로 이미 저장된 csi_YYYYMMDD_*.csv 파일들의 번호 중 최댓값 찾기
    max_num = 0
    for p in raw_dir.glob(f"csi_{today_str}_*.csv"):
        suffix = p.stem.replace(f"csi_{today_str}_", "")
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))

    next_num = max_num + 1
    filename = f"csi_{today_str}_{next_num}.csv"

    raw_path = raw_dir / filename
    feature_path = feature_dir / filename
    return raw_path, feature_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESP32 CSI 1:4 Multi-Receiver TCP Server"
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="TCP bind address (default: 0.0.0.0)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="TCP bind port (default: 5001)",
    )

    parser.add_argument(
        "--links",
        type=parse_link_ids,
        default=DEFAULT_1TO4_LINKS,
        help=(
            "수집 대상 link ID (기본값: link_1,link_2,link_3,link_4). "
            "단일 테스트 시 --links link_1 지정 가능"
        ),
    )

    parser.add_argument(
        "--expected-pps",
        type=float,
        required=True,
        help="TX 펌웨어에 설정한 PPS (예: 35)",
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/csi"),
        help="데이터 저장 기본 디렉토리 (기본값: data/csi)",
    )

    parser.add_argument(
        "--ingest-url",
        default=DEFAULT_INGEST_URL,
        help=f"AI 서버 ingest 엔드포인트 URL (기본값: {DEFAULT_INGEST_URL})",
    )

    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="서버 HTTP POST 전송 비활성화 (CSV 저장만 수행)",
    )

    args = parser.parse_args()

    if args.expected_pps <= 0:
        parser.error("--expected-pps must be positive")

    active_links = tuple(sorted(args.links))
    raw_path, feature_path = build_paths(args.output_root)

    print("=" * 70)
    print(" 🚀 ESP32 CSI Multi-Receiver TCP Server & Real-time Sensing")
    print("=" * 70)
    print(f" Expected Links ({len(active_links)}): " + ", ".join(active_links))
    print(f" Expected TX PPS: {args.expected_pps}")
    print(f" Raw Output:     {raw_path}")
    print(f" Feature Output: {feature_path}")
    print(f" TCP Server:     {args.host}:{args.port}")
    if not args.no_ingest:
        print(f" Ingest URL:     {args.ingest_url}")
    print("=" * 70)

    stop_event = threading.Event()
    record_queue: Queue = Queue(maxsize=16384)
    error_queue: Queue = Queue(maxsize=1)

    ingest_queue: Queue | None = None
    ingest_thread: threading.Thread | None = None
    if not args.no_ingest:
        ingest_queue = Queue(maxsize=1024)
        ingest_thread = threading.Thread(
            target=ingest_worker,
            args=(ingest_queue, args.ingest_url, stop_event),
            name="csi-ingest",
            daemon=True,
        )
        ingest_thread.start()

    registry = ConnectionRegistry(
        expected_links=set(active_links),
        record_queue=record_queue,
    )

    writer_thread = threading.Thread(
        target=storage_worker,
        args=(
            record_queue,
            raw_path,
            feature_path,
            active_links,
            args.expected_pps,
            stop_event,
            error_queue,
            ingest_queue,
        ),
        name="csi-storage",
    )
    writer_thread.start()

    dashboard_thread = threading.Thread(
        target=print_dashboard_loop,
        args=(registry, stop_event, 3.0),
        name="csi-dashboard",
    )
    dashboard_thread.start()

    client_threads: list[threading.Thread] = []
    accepted_connections: list[socket.socket] = []

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(max(10, len(active_links) * 2))
    server.settimeout(1.0)

    print(f"\n[SERVER READY] Listening on {args.host}:{args.port}...")
    print(f"Waiting for {len(active_links)} RX board(s) to connect...\n")

    try:
        while not stop_event.is_set():
            if not error_queue.empty():
                raise RuntimeError("storage worker failed")

            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue

            accepted_connections.append(conn)

            thread = threading.Thread(
                target=handle_client,
                args=(
                    conn,
                    addr,
                    registry,
                    record_queue,
                    stop_event,
                ),
                name=f"csi-client-{addr}",
            )
            thread.start()
            client_threads.append(thread)

    except KeyboardInterrupt:
        print("\nStopping receiver gracefully...")

    finally:
        stop_event.set()

        try:
            server.close()
        except OSError:
            pass

        registry.close_all()

        for conn in accepted_connections:
            try:
                conn.close()
            except OSError:
                pass

        for thread in client_threads:
            thread.join(timeout=3.0)

        record_queue.put(STOP_RECORD)
        writer_thread.join()
        dashboard_thread.join(timeout=2.0)

        if ingest_queue is not None:
            ingest_queue.put(STOP_RECORD)
        if ingest_thread is not None:
            ingest_thread.join(timeout=2.0)

    if not error_queue.empty():
        raise error_queue.get()

    print("Receiver stopped cleanly.")


if __name__ == "__main__":
    main()