#!/usr/bin/env bash
set -e

# ==============================================================================
# 1:4 CSI Multi-Receiver Build & Flash Helper Script
# Usage:
#   ./build_flash_rx.sh <1|2|3|4> [PORT] [SERVER_IP]
# Example:
#   ./build_flash_rx.sh 1 /dev/cu.usbserial-110
#   ./build_flash_rx.sh 1 /dev/cu.usbserial-110 192.168.0.5
# ==============================================================================

LINK_NUM="$1"
PORT="$2"
SERVER_IP="$3"

# Auto-source ESP-IDF environment if not active
if ! command -v idf.py &> /dev/null; then
    if [ -f "$HOME/.espressif/v5.5.5/esp-idf/export.sh" ]; then
        . "$HOME/.espressif/v5.5.5/esp-idf/export.sh"
    fi
fi

if [ -z "$LINK_NUM" ]; then
    echo "Usage: $0 <1|2|3|4> [PORT] [SERVER_IP]"
    echo "Example: $0 1 /dev/cu.usbserial-110"
    echo "Example with Server IP: $0 1 /dev/cu.usbserial-110 192.168.0.5"
    exit 1
fi

case "$LINK_NUM" in
    1|link_1)
        TARGET_DEF="sdkconfig.defaults.rx1"
        LINK_ID="link_1"
        ;;
    2|link_2)
        TARGET_DEF="sdkconfig.defaults.rx2"
        LINK_ID="link_2"
        ;;
    3|link_3)
        TARGET_DEF="sdkconfig.defaults.rx3"
        LINK_ID="link_3"
        ;;
    4|link_4)
        TARGET_DEF="sdkconfig.defaults.rx4"
        LINK_ID="link_4"
        ;;
    *)
        echo "Error: Link number must be 1, 2, 3, or 4 (e.g. link_1, link_2, ...)"
        exit 1
        ;;
esac

echo "=========================================="
echo " Building and Flashing CSI Receiver: ${LINK_ID}"
echo " Config: sdkconfig.defaults + ${TARGET_DEF}"
if [ -n "$PORT" ]; then
    echo " Target Port: ${PORT}"
fi
if [ -n "$SERVER_IP" ]; then
    echo " Mac TCP Server IP: ${SERVER_IP}"
fi
echo "=========================================="

# Wi-Fi 비밀번호·서버 IP는 레포에 없는 로컬 파일에서 읽는다
LOCAL_CONFIG="sdkconfig.defaults.local"
if [ ! -f "$LOCAL_CONFIG" ]; then
    echo "Error: ${LOCAL_CONFIG} not found."
    echo "  cp sdkconfig.defaults.local.example ${LOCAL_CONFIG} 후 실제 값을 채우세요."
    exit 1
fi
if grep -q '{' "$LOCAL_CONFIG"; then
    echo "Error: ${LOCAL_CONFIG}에 아직 {placeholder} 값이 남아 있습니다."
    exit 1
fi

# Remove existing sdkconfig to force clean configuration
rm -f sdkconfig

EXTRA_CONFIG=";${LOCAL_CONFIG}"
if [ -n "$SERVER_IP" ]; then
    echo "CONFIG_CSI_TCP_SERVER_IP=\"${SERVER_IP}\"" > sdkconfig.defaults.custom_ip
    EXTRA_CONFIG="${EXTRA_CONFIG};sdkconfig.defaults.custom_ip"
fi

if [ -n "$PORT" ]; then
    idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;${TARGET_DEF}${EXTRA_CONFIG}" build flash -p "$PORT"
else
    idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;${TARGET_DEF}${EXTRA_CONFIG}" build flash
fi

rm -f sdkconfig.defaults.custom_ip

echo "=========================================="
echo " ✅ ${LINK_ID} successfully built and flashed!"
echo "=========================================="
