# HLK-LD6004 60GHz mmWave Radar Technical & Protocol Notes

## 1. Hardware Pinout (J1 Connector)

Looking at the module front face (components visible, antenna top, `HLHN` label vertical):

```text
[ Sensor J1 Header ]
Pin 1 (Bottom): 3.3V (VCC)    ──► USB Board 3.3V (Red wire)
Pin 2         : GND           ──► USB Board GND (Black wire)
Pin 3         : RX (UART RX)  ──► USB Board TXD (Yellow wire)
Pin 4         : TX (UART TX)  ──► USB Board RXT (Green wire)
Pin 5 (Top)   : OUT (GPIO)    ──► DO NOT CONNECT / Leave floating (Blue wire)
```

> **⚠️ Warning:** Never connect 5V to VCC. Operating voltage is 3.1V ~ 3.5V. Never connect Pin 5 (OUT) to GND.

---

## 2. Serial Communication Specs

* **Baud Rate:** 115200 bps
* **Data Bits:** 8
* **Stop Bits:** 1
* **Parity:** None
* **Measured Output Frequency:** 20.0 Hz (50.0 ms / frame)

---

## 3. TinyFrame Protocol Structure

```text
+------+---------+---------+---------+-------------+------------------+-------------+
| SOF  | ID (BE) | LEN(BE) | TYPE(BE)| HEAD_CKSUM  | DATA PAYLOAD(LE) | DATA_CKSUM  |
| 1B   | 2B      | 2B      | 2B      | 1B          | LEN Bytes        | 1B          |
+------+---------+---------+---------+-------------+------------------+-------------+
```

### Checksum Algorithm
```python
def checksum(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return (~r) & 0xFF
```
* `HEAD_CKSUM` = `checksum(header[0:7])`
* `DATA_CKSUM` = `checksum(data_payload)` if `LEN > 0` else `0xFF`

---

## 4. Supported Message Types

### 1) Presence State (`0x0A0A`)
* **Payload Length:** 16 bytes (4 x `uint32_t` little-endian)
* **Description:** Occupancy state for Zone 0, Zone 1, Zone 2, Zone 3 (1 = occupied, 0 = vacant).

### 2) Target Location (`0x0A04`)
* **Payload Structure:**
  * Byte 0-3: `uint32_t` Target Count ($N \le 3$)
  * Repeated $N$ times (20 bytes per target):
    * Byte 0-3: `float` X (Lateral position in meters, left<0, right>0)
    * Byte 4-7: `float` Y (Depth/forward distance in meters)
    * Byte 8-11: `float` Z (Vertical position in meters)
    * Byte 12-15: `int32_t` Doppler index (+ approaching, - receding)
    * Byte 16-19: `int32_t` Tracking Cluster ID
