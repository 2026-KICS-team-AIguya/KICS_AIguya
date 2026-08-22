/**
 * ESP32 Bluetooth Bridge for HLK-LD6004 mmWave Sensor
 * 
 * Functions:
 * 1. Reads 20Hz TinyFrame packets from LD6004 on Serial2 (RX2=GPIO16, TX2=GPIO17)
 * 2. Transmits stream wirelessly to PC via Bluetooth Serial (SPP)
 * 3. Bluetooth Device Name: "LD6004_mmWave"
 * 
 * Pinout Wiring:
 * - LD6004 Red wire   (3.3V) --> ESP32 3V3 pin
 * - LD6004 Black wire (GND)  --> ESP32 GND pin
 * - LD6004 Green wire (TX)   --> ESP32 D16 pin (RX2)
 * - LD6004 Yellow wire(RX)   --> ESP32 D17 pin (TX2)
 * - LD6004 Blue wire  (OUT)  --> DO NOT CONNECT (leave floating)
 */

#include "BluetoothSerial.h"

// Check if Bluetooth is properly enabled in ESP32 core
#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to enable it
#endif

BluetoothSerial SerialBT;

// Hardware Serial2 pins connected to LD6004
#define RADAR_RX_PIN 16 // Connects to LD6004 TX (Green wire)
#define RADAR_TX_PIN 17 // Connects to LD6004 RX (Yellow wire)
#define RADAR_BAUD   115200

#define BT_DEVICE_NAME "LD6004_mmWave"

void setup() {
  // Debug Serial over USB-C
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n========================================");
  Serial.println(" ESP32 HLK-LD6004 Bluetooth Bridge");
  Serial.println("========================================");

  // Initialize Bluetooth Serial
  if (!SerialBT.begin(BT_DEVICE_NAME)) {
    Serial.println("[!] An error occurred initializing Bluetooth");
  } else {
    Serial.printf("[+] Bluetooth Serial Started! Device Name: %s\n", BT_DEVICE_NAME);
    Serial.println("[+] Pair your PC with 'LD6004_mmWave' to receive data.");
  }

  // Initialize Hardware Serial2 for mmWave Radar
  Serial2.begin(RADAR_BAUD, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);
  Serial.printf("[+] Serial2 listening on RX: GPIO%d, TX: GPIO%d at %d baud.\n", 
                RADAR_RX_PIN, RADAR_TX_PIN, RADAR_BAUD);
}

void loop() {
  // Forward data from Radar (Serial2) to Bluetooth & USB Serial
  if (Serial2.available()) {
    uint8_t buffer[256];
    int bytesRead = Serial2.readBytes(buffer, min(Serial2.available(), 256));
    
    // Send to Bluetooth (PC wireless pipeline)
    if (SerialBT.hasClient()) {
      SerialBT.write(buffer, bytesRead);
    }
    
    // Echo to USB Serial monitor for debugging
    Serial.write(buffer, bytesRead);
  }

  // Forward any configuration commands from Bluetooth back to Radar
  if (SerialBT.available()) {
    Serial2.write(SerialBT.read());
  }

  // Forward commands from USB Serial to Radar
  if (Serial.available()) {
    Serial2.write(Serial.read());
  }
}
