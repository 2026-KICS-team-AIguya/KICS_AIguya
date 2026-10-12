#!/usr/bin/env python3
"""
Unit test for 1:4 CSI Multi-Receiver logic, feature extraction, and storage loop
without external network dependencies.
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path
from queue import Queue

# Add csi/logger to path
sys.path.insert(0, str(Path(__file__).parent.parent / "csi" / "logger"))

import tcp_receiver


def test_amplitude_calculation():
    # 8 subcarriers (16 values: [I, Q, I, Q, ...])
    # Subcarrier 1: (3, 4) -> mag = 5.0
    # Subcarrier 2: (6, 8) -> mag = 10.0
    # Average amplitude = (5.0 + 10.0) / 2 = 7.5
    subcarriers = [3, 4, 6, 8]
    data_str = json.dumps(subcarriers)
    mean_amp = tcp_receiver.calculate_packet_mean_amplitude(data_str)
    assert abs(mean_amp - 7.5) < 1e-6, f"Expected 7.5, got {mean_amp}"
    print("✅ test_amplitude_calculation passed")


def test_window_stats_and_feature_generation():
    temp_dir = Path(tempfile.mkdtemp(prefix="csi_unit_test_"))
    feature_path = temp_dir / "test_feature.csv"
    active_links = ("link_1", "link_2", "link_3", "link_4")
    expected_packet_count = 175  # 35 pps * 5s

    windows: dict[tuple[int, str], tcp_receiver.WindowStats] = {}
    last_packet_ids: dict[str, int] = {}
    window_start = 1700000000000

    # Simulate 4 links sending packets in window_start
    # link_1: 175 packets (100% reception), amp around 10.0
    # link_2: 140 packets (20% missing rate)
    # link_3: 175 packets with 1 reset
    # link_4: 175 packets with duplicate packets
    for i in range(175):
        key1 = (window_start, "link_1")
        st1 = windows.setdefault(key1, tcp_receiver.WindowStats())
        tcp_receiver.update_window_stats(st1, i, "link_1", last_packet_ids, mean_amplitude=10.0 + (i % 3))

    for i in range(0, 175, 5):  # only every 5th missing (140 received)
        for j in range(4):
            pid = i + j
            if pid < 175:
                key2 = (window_start, "link_2")
                st2 = windows.setdefault(key2, tcp_receiver.WindowStats())
                tcp_receiver.update_window_stats(st2, pid, "link_2", last_packet_ids, mean_amplitude=8.0)

    for i in range(175):
        key3 = (window_start, "link_3")
        st3 = windows.setdefault(key3, tcp_receiver.WindowStats())
        pid = i if i < 100 else i - 50  # causes reset
        tcp_receiver.update_window_stats(st3, pid, "link_3", last_packet_ids, mean_amplitude=12.0)

    for i in range(175):
        key4 = (window_start, "link_4")
        st4 = windows.setdefault(key4, tcp_receiver.WindowStats())
        tcp_receiver.update_window_stats(st4, i // 2, "link_4", last_packet_ids, mean_amplitude=5.0)

    with feature_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        tcp_receiver.write_feature_window(
            writer=writer,
            window_start=window_start,
            active_links=active_links,
            expected_packet_count=expected_packet_count,
            windows=windows,
        )

    with feature_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert len(rows) == 4, f"Expected 4 rows, got {len(rows)}"
    link_results = {row[1]: row for row in rows}

    # link_1: 175 packets, missing_rate 0.0, csi_amp_mean at column 5
    assert link_results["link_1"][2] == "175"
    assert float(link_results["link_1"][3]) == 0.0
    assert float(link_results["link_1"][5]) > 9.0  # csi_amp_mean

    # link_2: 140 packets, missing_rate = (175 - 140) / 175 = 0.2
    assert link_results["link_2"][2] == "140"
    assert abs(float(link_results["link_2"][3]) - 0.2) < 1e-4

    print("✅ test_window_stats_and_feature_generation passed")


def test_registry_1to4():
    expected = {"link_1", "link_2", "link_3", "link_4"}
    q = Queue()
    registry = tcp_receiver.ConnectionRegistry(expected, q)

    mock_sock1 = object()
    mock_sock2 = object()
    assert registry.claim("link_1", mock_sock1, ("127.0.0.1", 1001)) is True
    # Reconnecting link_1 with a new socket should gracefully overwrite and return True
    assert registry.claim("link_1", mock_sock2, ("127.0.0.1", 1005)) is True
    assert registry.collection_started is False

    assert registry.claim("link_2", mock_sock1, ("127.0.0.1", 1002)) is True
    assert registry.claim("link_3", mock_sock1, ("127.0.0.1", 1003)) is True
    assert registry.collection_started is False

    # When 4th link connects, collection starts!
    assert registry.claim("link_4", mock_sock1, ("127.0.0.1", 1004)) is True
    assert registry.collection_started is True
    assert not q.empty()
    item = q.get()
    assert isinstance(item, tcp_receiver.StartCollection)
    print("✅ test_registry_1to4 passed")


if __name__ == "__main__":
    test_amplitude_calculation()
    test_window_stats_and_feature_generation()
    test_registry_1to4()
    print("\n🎉 ALL 1:4 UNIT TESTS PASSED SUCCESSFULLY!")
