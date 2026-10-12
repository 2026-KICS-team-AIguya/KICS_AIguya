# CSI 펌웨어 (ESP32)

ESP32 Wi-Fi CSI 송신기(TX)·수신기(RX) 펌웨어. ESP-IDF v5.5 기준.
원래 별도 레포(`KICS_AIguya-esp32`)에서 관리하던 코드를 옮겨왔다.

```text
        [ ESP32 TX (csi_send) ]
   (채널 11 / 36 PPS ESP-NOW 브로드캐스트)
                  │
                  ▼
        [ ESP32 RX (csi_recv) ]  link_1 ~ link_4 중 선택
                  │  TCP (port 5001)
                  ▼
   [ 수집 PC: csi/logger/tcp_receiver.py ]
                  │
         raw CSV / 5초 feature CSV
```

> 현재 수집은 RX 1대(`link_3`)만 사용한다. 펌웨어는 RX 4대(link_1~4)까지 지원한다.

---

## 폴더 구조

```text
csi/firmware/
├── csi_send/                          # TX 펌웨어
│   ├── main/app_main.c                # ESP-NOW 브로드캐스트 송신 (36 PPS, 채널 11)
│   └── build_flash_tx.sh
└── csi_recv/                          # RX 펌웨어
    ├── main/
    │   ├── app_main.c                 # CSI 콜백 → FreeRTOS Queue → TCP 전송
    │   └── Kconfig.projbuild          # link ID·Wi-Fi·서버 설정 항목
    ├── sdkconfig.defaults             # 공통 설정 (비밀번호는 {placeholder})
    ├── sdkconfig.defaults.rx1~rx4     # RX별 link ID 프리셋
    ├── sdkconfig.defaults.local.example
    └── build_flash_rx.sh
```

---

## 최초 설정: Wi-Fi 비밀번호·서버 IP

비밀번호와 수집 PC IP는 git에 올리지 않는다. 로컬 파일을 만들어 실제 값을 넣는다.

```bash
cd csi/firmware/csi_recv
cp sdkconfig.defaults.local.example sdkconfig.defaults.local
# sdkconfig.defaults.local 의 {WIFI_SSID} {WIFI_PASSWORD} {TCP_SERVER_IP} 를 실제 값으로 수정
```

`sdkconfig.defaults.local`은 `.gitignore` 대상이다. `build_flash_rx.sh`는 이 파일이 없거나
`{...}` 값이 남아 있으면 빌드를 멈춘다.

---

## RX 빌드 & 플래시

```bash
cd csi/firmware/csi_recv
./build_flash_rx.sh 3 /dev/cu.usbserial-110                 # link_3
./build_flash_rx.sh 3 /dev/cu.usbserial-110 192.168.0.5     # 서버 IP를 이번만 바꿀 때
```

`idf.py`를 직접 쓸 때는 local 파일까지 함께 지정한다.

```bash
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.rx3;sdkconfig.defaults.local" build flash -p <포트>
```

## TX 빌드 & 플래시

```bash
cd csi/firmware/csi_send
./build_flash_tx.sh /dev/cu.usbserial-110
```

- 채널 11에서 36 PPS로 브로드캐스트한다 (`CONFIG_SEND_FREQUENCY`, `CONFIG_LESS_INTERFERENCE_CHANNEL`).
- 패킷 ID는 송신마다 1씩 증가하고, RX는 이 ID로 손실을 계산한다.

---

## 수집 서버 실행

```bash
python3 csi/logger/tcp_receiver.py --links link_3 --expected-pps 36
```

- `--expected-pps`는 TX의 `CONFIG_SEND_FREQUENCY`와 같아야 결측률이 맞게 계산된다.

## 통신 프로토콜

RX가 접속하면 최초 1회 `HELLO,<link_id>\n`을 보낸 뒤 CSI 줄을 스트리밍한다.

```text
CSI_DATA,<packet_id>,<mac>,<rssi>,<rate>,...,<device_time_us>,...,"[<I/Q 값 256개>]"\n
```
