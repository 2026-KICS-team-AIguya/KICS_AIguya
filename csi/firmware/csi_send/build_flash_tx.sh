#!/usr/bin/env bash
set -e

# ==============================================================================
# 1:4 CSI Transmitter (TX) Build & Flash Helper Script
# Usage:
#   ./build_flash_tx.sh [PORT]
# Example:
#   ./build_flash_tx.sh /dev/cu.usbserial-110
# ==============================================================================

PORT="$1"

# Auto-source ESP-IDF environment if not active
if ! command -v idf.py &> /dev/null; then
    if [ -f "$HOME/.espressif/v5.5.5/esp-idf/export.sh" ]; then
        . "$HOME/.espressif/v5.5.5/esp-idf/export.sh"
    fi
fi

echo "=========================================="
echo " Building and Flashing CSI Transmitter (TX)"
echo " Frequency: 36 PPS | Wi-Fi Channel: 6 | Max 20dBm Power"
if [ -n "$PORT" ]; then
    echo " Target Port: ${PORT}"
fi
echo "=========================================="

# Remove existing sdkconfig to force clean configuration
rm -f sdkconfig

if [ -n "$PORT" ]; then
    idf.py build flash -p "$PORT"
else
    idf.py build flash
fi

echo "=========================================="
echo " ✅ TX (송신기) successfully built and flashed!"
echo "=========================================="
