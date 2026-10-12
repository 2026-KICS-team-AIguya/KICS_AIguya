from __future__ import annotations

import argparse
import base64
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


# ESP-CSI 공식 get-started/csi_recv 출력 순서
#
# 공식 출력명 중 일부는 프로젝트에서 의미가 더 명확하도록 이름만 변경한다.
# local_timestamp -> device_time_us
# len             -> csi_len
# data            -> csi_data
CSI_FIELDS = [
    "type",
    "packet_id",
    "mac",
    "rssi",
    "rate",
    "sig_mode",
    "mcs",
    "bandwidth",
    "smoothing",
    "not_sounding",
    "aggregation",
    "stbc",
    "fec_coding",
    "sgi",
    "noise_floor",
    "ampdu_cnt",
    "channel",
    "secondary_channel",
    "device_time_us",
    "ant",
    "sig_len",
    "rx_format",
    "csi_len",
    "first_word",
    "csi_data",
]

EXPECTED_FIELD_COUNT = len(CSI_FIELDS)


class LineSource(Protocol):
    """
    데이터 입력 인터페이스.

    현재는 SerialLineSource를 사용한다.
    나중에 RX -> Mac 전송을 Wi-Fi로 변경하더라도
    readline() / close() 인터페이스만 동일하게 구현하면
    Logger의 파싱 및 저장 로직을 재사용할 수 있다.
    """

    def readline(self) -> bytes:
        ...

    def close(self) -> None:
        ...


class SerialLineSource:
    """
    ESP32 RX의 USB Serial 출력을 읽는다.
    """

    def __init__(self, port: str, baudrate: int):
        import serial

        self.serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=1.0,
        )

        # Logger 실행 이전에 Serial 버퍼에 남아 있던 데이터를 제거한다.
        self.serial.reset_input_buffer()

    def readline(self) -> bytes:
        return self.serial.readline()

    def close(self) -> None:
        self.serial.close()


class CSIParseError(ValueError):
    """
    CSI_DATA 행이 존재하지만 정상적으로 파싱할 수 없는 경우 발생.
    """

    pass


@dataclass
class CaptureStats:
    # 정상적으로 파싱된 CSI_DATA 행 수
    valid_packets: int = 0

    # 동일 packet_id가 연속으로 다시 관측된 횟수
    duplicate_packets: int = 0

    # Mac Logger에서 관측된 packet_id gap 개수.
    #
    # 이 값만으로는
    # TX -> RX RF 구간의 손실인지,
    # RX 내부 / UART / Mac Logger 과정의 손실인지
    # 구분할 수 없다.
    missing_packets: int = 0

    # CSI_DATA로 시작했지만
    # CSV 구조 / 숫자 / CSI 배열 등이 깨진 행
    malformed_csi_lines: int = 0

    # ESP-IDF 로그 또는 식별 불가능한 Serial 데이터
    ignored_lines: int = 0

    # packet_id가 이전 ID보다 작아진 횟수
    # TX 재부팅 / reset 등의 가능성을 나타낸다.
    backward_or_reset: int = 0

    # Serial 포트에서 읽은 전체 byte 수
    serial_bytes: int = 0

    # 정상 CSI_DATA 행에 해당하는 byte 수
    csi_bytes: int = 0

    first_packet_id: int | None = None
    last_packet_id: int | None = None

    def observe_packet(self, packet_id: int) -> None:
        """
        정상적으로 파싱된 CSI_DATA의 packet_id를 이용하여
        중복, ID gap, reset/역순 여부를 계산한다.
        """

        if self.first_packet_id is None:
            self.first_packet_id = packet_id
            self.last_packet_id = packet_id
            self.valid_packets += 1
            return

        assert self.last_packet_id is not None

        if packet_id == self.last_packet_id:
            self.duplicate_packets += 1

        elif packet_id > self.last_packet_id:
            gap = packet_id - self.last_packet_id - 1

            if gap > 0:
                self.missing_packets += gap

        else:
            # TX가 재부팅되어 ID가 다시 0부터 시작했거나,
            # 비정상적인 역순 데이터가 들어온 경우.
            #
            # reset 전 ID와 reset 후 ID 사이를
            # missing packet으로 계산하지 않는다.
            self.backward_or_reset += 1

        self.last_packet_id = packet_id
        self.valid_packets += 1

    def missing_rate(self) -> float:
        """
        Mac Logger에서 관측된 packet ID gap 비율.

        expected =
            실제 고유 수신 packet 수
            + 관측된 packet ID gap 수

        주의:
        TX -> RX RF 손실률만을 의미하지 않는다.
        """

        unique_valid = (
            self.valid_packets
            - self.duplicate_packets
        )

        expected = (
            unique_valid
            + self.missing_packets
        )

        if expected <= 0:
            return 0.0

        return (
            self.missing_packets
            / expected
        )


def parse_csi_line(
    raw: bytes,
) -> tuple[list[str], int] | None:
    """
    ESP32 RX에서 받은 한 줄을 파싱한다.

    반환:
        CSI_DATA 행이면 (row, packet_id)
        CSI_DATA가 아닌 행이면 None

    예외:
        CSI_DATA 행이지만 정상 파싱할 수 없으면 CSIParseError
    """

    try:
        line = raw.decode(
            "utf-8",
            errors="strict",
        ).strip()

    except UnicodeDecodeError as exc:
        raise CSIParseError(
            "UTF-8 decode error"
        ) from exc

    if not line:
        return None

    # ESP-IDF 부팅 로그 등
    # CSI_DATA가 아닌 행은 무시한다.
    if not line.startswith("CSI_DATA,"):
        return None

    try:
        # CSI 배열 내부에도 comma가 존재하므로
        # 단순 split(",") 대신 csv.reader를 사용한다.
        row = next(
            csv.reader(
                [line],
                strict=True,
            )
        )

    except csv.Error as exc:
        raise CSIParseError(
            "CSV parsing error"
        ) from exc

    if len(row) != EXPECTED_FIELD_COUNT:
        raise CSIParseError(
            f"invalid field count: "
            f"{len(row)} "
            f"(expected {EXPECTED_FIELD_COUNT})"
        )

    if row[0] != "CSI_DATA":
        raise CSIParseError(
            "invalid row type"
        )

    try:
        packet_id = int(row[1])

        # 필수 숫자 필드 검증
        int(row[18])  # device_time_us

        csi_len = int(row[22])

        # [버그 수정 - 전송량 자체가 과다] 기존엔 서브캐리어 값을
        # "[1,2,3,...]" 형태의 십진수 텍스트로 받아 json.loads()로
        # 바로 파싱했다. 보드(csi_recv)에서 같은 데이터를 손실 없이
        # base64로 압축해서 보내도록 바꿨으므로(전송 바이트 수 약 1/3
        # 절감), 여기서 base64를 디코딩해 부호 있는 정수(int8) 리스트로
        # 복원한다.
        #
        # 이후 raw CSV 저장 / mean amplitude 계산 등 다운스트림 코드는
        # row[24]가 "[1,2,3,...]" 형태의 JSON 배열 문자열이라고 가정하고
        # 있으므로, 여기서 디코딩한 값을 다시 같은 형태의 문자열로
        # 만들어 row[24]에 되돌려 넣는다 - 이러면 이 함수 밖의 어떤
        # 코드도 건드릴 필요가 없다.
        raw_bytes = base64.b64decode(
            row[24],
            validate=True,
        )

        csi_values = [
            (b - 256) if b >= 128 else b
            for b in raw_bytes
        ]

    except (
        ValueError,
        TypeError,
    ) as exc:
        raise CSIParseError(
            "invalid numeric or CSI base64 value"
        ) from exc

    if len(csi_values) != csi_len:
        raise CSIParseError(
            f"CSI length mismatch: "
            f"actual={len(csi_values)}, "
            f"declared={csi_len}"
        )

    row = list(row)
    row[24] = json.dumps(
        csi_values,
        separators=(",", ":"),
    )

    return row, packet_id


def build_default_output(
    baudrate: int,
) -> Path:
    """
    output 경로를 지정하지 않았을 때
    사용할 기본 파일명을 생성한다.
    """

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    return Path(
        f"csi_raw_"
        f"{timestamp}_"
        f"b{baudrate}.csv"
    )


def print_live_stats(
    stats: CaptureStats,
    elapsed: float,
) -> None:
    """
    현재 수집 상태를 터미널 한 줄에
    실시간으로 표시한다.
    """

    observed_pps = (
        stats.valid_packets / elapsed
        if elapsed > 0
        else 0.0
    )

    print(
        "\r"
        f"elapsed={elapsed:7.1f}s | "
        f"valid={stats.valid_packets:6d} | "
        f"id_gap={stats.missing_packets:5d} | "
        f"id_gap_rate={stats.missing_rate():.4%} | "
        f"duplicate={stats.duplicate_packets:4d} | "
        f"malformed={stats.malformed_csi_lines:4d} | "
        f"ignored={stats.ignored_lines:4d} | "
        f"observed_pps={observed_pps:6.2f}",
        end="",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "ESP-CSI USB Serial Raw Logger"
        )
    )

    parser.add_argument(
        "--port",
        required=True,
        help=(
            "ESP32 RX Serial port. "
            "예: /dev/cu.usbserial-110"
        ),
    )

    parser.add_argument(
        "--baud",
        required=True,
        type=int,
        choices=[
            115200,
            230400,
            460800,
            921600,
        ],
        help=(
            "ESP32 RX UART baud rate"
        ),
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=300.0,
        help=(
            "측정 시간(초). "
            "기본값 300초. "
            "0 이하이면 Ctrl+C까지 계속 측정"
        ),
    )

    parser.add_argument(
        "--link-id",
        default="link_1",
        help=(
            "CSI 링크 식별자. "
            "현재 1:1 실험은 link_1 사용"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "CSV 저장 경로. "
            "지정하지 않으면 "
            "baud가 포함된 파일명을 자동 생성"
        ),
    )

    args = parser.parse_args()

    output_path = (
        args.output
        or build_default_output(
            args.baud
        )
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_path = (
        output_path.with_suffix(
            ".summary.json"
        )
    )

    # 기존 실험 파일 덮어쓰기 방지
    if output_path.exists():
        raise FileExistsError(
            f"Output file already exists: {output_path}"
        )

    if summary_path.exists():
        raise FileExistsError(
            f"Summary file already exists: {summary_path}"
        )

    stats = CaptureStats()

    source: LineSource = (
        SerialLineSource(
            args.port,
            args.baud,
        )
    )

    started_monotonic = (
        time.monotonic()
    )

    last_report = (
        started_monotonic
    )

    aborted_reason = None

    try:
        with output_path.open(
            "x",
            newline="",
            encoding="utf-8",
            buffering=1024 * 1024,
        ) as output_file:

            writer = csv.writer(
                output_file
            )

            writer.writerow(
                [
                    "host_epoch_ms",
                    "link_id",
                    *CSI_FIELDS,
                ]
            )

            try:
                while True:
                    now = (
                        time.monotonic()
                    )

                    elapsed = (
                        now
                        - started_monotonic
                    )

                    if (
                        args.duration > 0
                        and elapsed
                        >= args.duration
                    ):
                        break

                    raw = (
                        source.readline()
                    )

                    if raw:
                        stats.serial_bytes += (
                            len(raw)
                        )

                        # Mac이 해당 Serial 행을
                        # 읽은 시점의 Epoch timestamp(ms)
                        host_epoch_ms = (
                            time.time_ns()
                            // 1_000_000
                        )

                        try:
                            parsed = (
                                parse_csi_line(
                                    raw
                                )
                            )

                        except CSIParseError:
                            # CSI_DATA로 시작했다면
                            # 깨진 CSI 행
                            if (
                                raw
                                .lstrip()
                                .startswith(
                                    b"CSI_DATA,"
                                )
                            ):
                                (
                                    stats
                                    .malformed_csi_lines
                                ) += 1

                            else:
                                # 깨진 부팅 로그 또는
                                # 식별 불가능한 Serial 데이터
                                (
                                    stats
                                    .ignored_lines
                                ) += 1

                        else:
                            if parsed is None:
                                # 정상적인 ESP-IDF
                                # 부팅 로그 등
                                (
                                    stats
                                    .ignored_lines
                                ) += 1

                            else:
                                (
                                    row,
                                    packet_id,
                                ) = parsed

                                stats.csi_bytes += (
                                    len(raw)
                                )

                                stats.observe_packet(
                                    packet_id
                                )

                                writer.writerow(
                                    [
                                        host_epoch_ms,
                                        args.link_id,
                                        *row,
                                    ]
                                )

                    # 정상 CSI가 하나도 들어오지 않아도
                    # 1초마다 상태를 출력한다.
                    now = (
                        time.monotonic()
                    )

                    if (
                        now
                        - last_report
                        >= 1.0
                    ):
                        elapsed = (
                            now
                            - started_monotonic
                        )

                        print_live_stats(
                            stats,
                            elapsed,
                        )

                        last_report = now

            except KeyboardInterrupt:
                pass

            except Exception as exc:
                # 시리얼 끊김 등 예상치 못한 예외로 루프가 죽더라도
                # summary.json은 항상 남겨서 원인 파악에 쓴다.
                aborted_reason = (
                    f"{type(exc).__name__}: {exc}"
                )

    finally:
        source.close()

    elapsed = (
        time.monotonic()
        - started_monotonic
    )

    observed_pps = (
        stats.valid_packets
        / elapsed
        if elapsed > 0
        else 0.0
    )

    serial_kib_per_sec = (
        stats.serial_bytes
        / elapsed
        / 1024
        if elapsed > 0
        else 0.0
    )

    csi_kib_per_sec = (
        stats.csi_bytes
        / elapsed
        / 1024
        if elapsed > 0
        else 0.0
    )

    summary = {
        "metric_scope": (
            "End-to-end packet ID gap observed "
            "at Mac Logger; cannot isolate RF loss "
            "from RX/UART/logger loss"
        ),

        "port": args.port,
        "baudrate": args.baud,
        "link_id": args.link_id,

        "duration_seconds": round(
            elapsed,
            3,
        ),

        "valid_packets": (
            stats.valid_packets
        ),

        "first_packet_id": (
            stats.first_packet_id
        ),

        "last_packet_id": (
            stats.last_packet_id
        ),

        "end_to_end_missing_packets_by_id_gap": (
            stats.missing_packets
        ),

        "end_to_end_id_gap_rate": (
            stats.missing_rate()
        ),

        "duplicate_packets": (
            stats.duplicate_packets
        ),

        "malformed_csi_lines": (
            stats.malformed_csi_lines
        ),

        "ignored_non_csi_lines": (
            stats.ignored_lines
        ),

        "backward_or_reset_count": (
            stats.backward_or_reset
        ),

        "observed_pps": (
            observed_pps
        ),

        "serial_bytes": (
            stats.serial_bytes
        ),

        "csi_bytes": (
            stats.csi_bytes
        ),

        "serial_kib_per_second": (
            serial_kib_per_sec
        ),

        "csi_kib_per_second": (
            csi_kib_per_sec
        ),

        "csv_file": str(
            output_path
        ),

        "aborted_reason": (
            aborted_reason
        ),
    }

    with summary_path.open(
        "x",
        encoding="utf-8",
    ) as summary_file:

        json.dump(
            summary,
            summary_file,
            ensure_ascii=False,
            indent=2,
        )

    print()

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

    print(
        f"\nCSV 저장: "
        f"{output_path}"
    )

    print(
        f"요약 저장: "
        f"{summary_path}"
    )

    if aborted_reason:
        print(
            f"\n⚠️  비정상 종료로 중단됨: "
            f"{aborted_reason}"
        )


if __name__ == "__main__":
    main()