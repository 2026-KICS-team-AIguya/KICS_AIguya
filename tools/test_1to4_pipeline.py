#!/usr/bin/env python3
"""
Test script to verify 1:4 multi-receiver CSI pipeline:
- Starts Mac TCP Receiver in a thread
- Connects 4 mock RX clients (link_1, link_2, link_3, link_4)
- Streams synthetic CSI packets at 35 pps for several seconds
- Verifies Raw CSV and Feature CSV generation and accuracy
"""

import csv
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

# Add csi/logger to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "csi" / "logger"))

import tcp_receiver


def make_mock_csi_line(packet_id: int, mac: str = "1a:00:00:00:00:00") -> str:
    # 64 subcarriers: 128 bytes of [I, Q, I, Q, ...]
    subcarriers = [10, -5, 12, -4, 8, 3, -10, 2] * 16  # 128 items
    subcarrier_json = json.dumps(subcarriers)
    return (
        f"CSI_DATA,{packet_id},{mac},-45,1,1,0,0,0,0,0,0,0,0,-90,1,6,0,1234567,0,100,1,128,0,\"{subcarrier_json}\"\n"
    )


def mock_rx_client(port: int, link_id: str, count: int, pps: float, stop_event: threading.Event):
    time.sleep(0.5)  # Wait for server to start
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("127.0.0.1", port))
        # Send HELLO handshake
        sock.sendall(f"HELLO,{link_id}\n".encode("ascii"))
        interval = 1.0 / pps

        for i in range(count):
            if stop_event.is_set():
                break
            line = make_mock_csi_line(i)
            sock.sendall(line.encode("ascii"))
            time.sleep(interval)
    except Exception as e:
        print(f"Mock client {link_id} error: {e}")
    finally:
        try:
            sock.close()
        except OSError:
            pass


def main():
    print("Testing 1:4 CSI Multi-Receiver Pipeline...")
    temp_dir = Path(tempfile.mkdtemp(prefix="csi_1to4_test_"))
    port = 5599
    expected_links = {"link_1", "link_2", "link_3", "link_4"}
    pps = 35.0
    packets_per_link = 120  # ~3.4 seconds

    raw_path, feature_path = tcp_receiver.build_paths(temp_dir)

    stop_event = threading.Event()
    record_queue = tcp_receiver.Queue(maxsize=16384)
    error_queue = tcp_receiver.Queue(maxsize=1)

    registry = tcp_receiver.ConnectionRegistry(
        expected_links=expected_links,
        record_queue=record_queue,
    )

    writer_thread = threading.Thread(
        target=tcp_receiver.storage_worker,
        args=(
            record_queue,
            raw_path,
            feature_path,
            tuple(sorted(expected_links)),
            pps,
            stop_event,
            error_queue,
        ),
    )
    writer_thread.start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(10)
    server.settimeout(1.0)

    client_threads = []
    accepted_conns = []

    def server_accept_loop():
        while not stop_event.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            accepted_conns.append(conn)
            th = threading.Thread(
                target=tcp_receiver.handle_client,
                args=(conn, addr, registry, record_queue, stop_event),
            )
            th.start()
            client_threads.append(th)

    server_thread = threading.Thread(target=server_accept_loop)
    server_thread.start()

    # Launch 4 mock RX clients
    mock_stop = threading.Event()
    mock_threads = []
    for link_id in sorted(expected_links):
        t = threading.Thread(
            target=mock_rx_client,
            args=(port, link_id, packets_per_link, pps, mock_stop),
        )
        mock_threads.append(t)
        t.start()

    # Wait for all mock clients to finish
    for t in mock_threads:
        t.join()

    time.sleep(1.0)
    print("Stopping test server...")
    stop_event.set()

    try:
        server.close()
    except OSError:
        pass
    registry.close_all()

    for conn in accepted_conns:
        try:
            conn.close()
        except OSError:
            pass

    for th in client_threads:
        th.join(timeout=2.0)

    server_thread.join(timeout=2.0)
    record_queue.put(tcp_receiver.STOP_RECORD)
    writer_thread.join(timeout=3.0)

    # Verify outputs
    print(f"\nVerifying outputs in {temp_dir}...")
    assert raw_path.exists(), f"Raw file {raw_path} not found!"
    assert feature_path.exists(), f"Feature file {feature_path} not found!"

    with raw_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header[0] == "host_epoch_ms"
        assert header[1] == "link_id"
        raw_rows = list(reader)

    print(f"✅ Raw CSV created with {len(raw_rows)} rows across 4 links.")
    links_in_raw = set(row[1] for row in raw_rows)
    print(f"✅ Distinct links in Raw CSV: {sorted(links_in_raw)}")
    assert links_in_raw == expected_links, f"Expected {expected_links}, got {links_in_raw}"

    with feature_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        feature_header = next(reader)
        print(f"✅ Feature CSV Header: {feature_header}")
        assert "csi_amp_mean" in feature_header
        assert "csi_amp_var" in feature_header
        feature_rows = list(reader)

    print(f"✅ Feature CSV created with {len(feature_rows)} window records.")
    print("\n🎉 1:4 CSI Multi-Receiver Pipeline test passed successfully!")


if __name__ == "__main__":
    main()
