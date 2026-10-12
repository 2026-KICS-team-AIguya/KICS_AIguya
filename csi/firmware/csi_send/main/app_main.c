/*
 * SPDX-FileCopyrightText: 2025-2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* Get Start Example

   This example code is in the Public Domain (or CC0 licensed, at your option.)

   Unless required by applicable law or agreed to in writing, this
   software is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
   CONDITIONS OF ANY KIND, either express or implied.
*/
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nvs_flash.h"

#include "esp_mac.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_timer.h"

/*
 * [채널 변경 - 2026-09-21] 무선 스캔 결과 채널 6에 DGU-WIFI/eduroam
 * (-55dBm, 대학 캠퍼스망 추정)이 같이 떠 있는 게 확인됐다. 데이터 압축,
 * 속도 하향(15pps)으로도 안 고쳐졌던 걸 보면 우리 부하 문제가 아니라
 * 이 이웃 네트워크와의 채널 경쟁일 가능성이 높아, 스캔에서 완전히
 * 비어있던 채널 11로 옮긴다. 공유기 2.4GHz 채널 및 csi_recv의
 * CONFIG_CSI_EXPECTED_CHANNEL도 반드시 11로 같이 맞출 것.
 */
#define CONFIG_LESS_INTERFERENCE_CHANNEL   11

#if CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C61 || (CONFIG_IDF_TARGET_ESP32C6 && ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 4, 0))
#define CONFIG_WIFI_BAND_MODE   WIFI_BAND_MODE_2G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS           WIFI_BW_HT40
#define CONFIG_WIFI_5G_BANDWIDTHS           WIFI_BW_HT40
#define CONFIG_WIFI_2G_PROTOCOL             WIFI_PROTOCOL_11N
#define CONFIG_WIFI_5G_PROTOCOL             WIFI_PROTOCOL_11N
#else
#define CONFIG_WIFI_BANDWIDTH           WIFI_BW_HT20
#endif

#define CONFIG_ESP_NOW_PHYMODE           WIFI_PHY_MODE_HT20
#define CONFIG_ESP_NOW_RATE             WIFI_PHY_RATE_MCS0_LGI

/*
 * [버그 수정 - 핫스팟 채널 자동 추적 - 2026-09-21] 아이폰 등 일부
 * 핫스팟은 "빈 채널"을 스스로 찾아 채널을 옮겨 다닌다. TX는 공유기에
 * 접속하는 게 아니라 고정 채널에 방송만 하는 구조라, 핫스팟이 채널을
 * 옮기면 TX는 그걸 전혀 알 방법이 없어서 RX(새 채널로 자동 재연결됨)와
 * 완전히 다른 채널에서 서로 떠드는 상태가 된다 - 이게 예전에 핫스팟을
 * 쓰다가 공유기로 바꾼 이유였다.
 *
 * CSI_TX_FOLLOW_HOTSPOT_CHANNEL을 1로 켜면 TX가 주기적으로 핫스팟
 * SSID를 지정 스캔해서 실제 채널을 확인하고, 우리가 쓰던 채널과
 * 다르면 esp_wifi_set_channel()로 따라간다. 채널이 고정된 일반
 * 공유기로 돌아가면(=이 문제가 원래 없던 환경) 0으로 꺼서 불필요한
 * 주기적 스캔(그동안 CSI 트리거 방송이 잠깐씩 끊김)을 없앨 것.
 */
#define CSI_TX_FOLLOW_HOTSPOT_CHANNEL       0
#define CSI_TX_HOTSPOT_SSID                 "iPhone"
#define CSI_TX_CHANNEL_FOLLOW_INTERVAL_MS   20000

/*
 * [진단용 임시 조정 - 2026-09-18] RX 쪽에서 RSSI는 멀쩡한데 TCP 전송이
 * 주기적으로 완전히 막히는 원인이 "보내려는 데이터양 자체가 이
 * 환경(공유기/채널)이 버틸 수 있는 양보다 많아서"인지 확인하기 위해
 * 36 -> 15로 임시로 낮춰서 테스트한다.
 *
 * - 15로 낮췄을 때 안정적으로 계속 돈다면: 용량 문제가 맞다는 뜻
 *   (이 환경에서 버틸 수 있는 현실적인 속도를 찾은 것)
 * - 15로 낮춰도 똑같이 막힌다면: 부하량과 무관한 외부 간섭/공유기
 *   문제라는 뜻
 *
 * 진단 끝나면 36으로 되돌리거나, 확인된 안정 속도로 정식 반영할 것.
 */
#define CONFIG_SEND_FREQUENCY               36

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
#define ESP_IF_WIFI_STA ESP_MAC_WIFI_STA
#endif

static const uint8_t CONFIG_CSI_SEND_MAC[] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};
static const char *TAG = "csi_send";

static void wifi_init()
{
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_ERROR_CHECK(esp_netif_init());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

#if CONFIG_IDF_TARGET_ESP32C5
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
    wifi_protocols_t protocols = {
        .ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
        .ghz_5g = CONFIG_WIFI_5G_PROTOCOL
    };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
    wifi_bandwidths_t bandwidth = {
        .ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
        .ghz_5g = CONFIG_WIFI_5G_BANDWIDTHS
    };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));
#elif (CONFIG_IDF_TARGET_ESP32C6 && ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 4, 0)) || CONFIG_IDF_TARGET_ESP32C61
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
    wifi_protocols_t protocols = {
        .ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
    };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
    wifi_bandwidths_t bandwidth = {
        .ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
    };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));
#else
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(ESP_IF_WIFI_STA, CONFIG_WIFI_BANDWIDTH));
    ESP_ERROR_CHECK(esp_wifi_start());

#endif

    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
#if CONFIG_IDF_TARGET_ESP32C5
    if ((CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_2G_ONLY && CONFIG_WIFI_2G_BANDWIDTHS == WIFI_BW_HT20)
            || (CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_5G_ONLY && CONFIG_WIFI_5G_BANDWIDTHS == WIFI_BW_HT20)) {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_NONE));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_BELOW));
    }
#elif (CONFIG_IDF_TARGET_ESP32C6 && ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 4, 0)) || CONFIG_IDF_TARGET_ESP32C61
    if (CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_2G_ONLY && CONFIG_WIFI_2G_BANDWIDTHS == WIFI_BW_HT20) {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_NONE));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_BELOW));
    }
#else
    if (CONFIG_WIFI_BANDWIDTH == WIFI_BW_HT20) {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_NONE));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_BELOW));
    }
#endif
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, CONFIG_CSI_SEND_MAC));
    esp_wifi_set_max_tx_power(78); // Max 20dBm power
}

static void wifi_esp_now_init(esp_now_peer_info_t peer)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    esp_now_rate_config_t rate_config = {
        .phymode = CONFIG_ESP_NOW_PHYMODE,
        .rate = CONFIG_ESP_NOW_RATE,
        .ersu = false,
        .dcm = false
    };
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer.peer_addr, &rate_config));
}

#if CSI_TX_FOLLOW_HOTSPOT_CHANNEL
static uint8_t s_tx_channel = CONFIG_LESS_INTERFERENCE_CHANNEL;

/*
 * 핫스팟 SSID를 지정 스캔해서 실제 채널을 확인하고, 우리가 쓰던
 * 채널과 다르면 따라간다. esp_now_peer_info_t.channel을 0으로 둬서
 * ESP-NOW가 "현재 Wi-Fi 채널"을 그대로 따라가게 만들었으므로(아래
 * app_main 참고), 여기서 esp_wifi_set_channel()만 호출하면 충분하다
 * - ESP-NOW 쪽에 별도로 채널을 다시 알려줄 필요가 없다.
 */
static void channel_follow_check_once(void)
{
    wifi_scan_config_t scan_config = {
        .ssid = (uint8_t *)CSI_TX_HOTSPOT_SSID,
        .bssid = NULL,
        .channel = 0,
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time.active.min = 100,
        .scan_time.active.max = 300,
    };

    if (esp_wifi_scan_start(&scan_config, true) != ESP_OK) {
        return;
    }

    uint16_t ap_count = 0;
    esp_wifi_scan_get_ap_num(&ap_count);

    if (ap_count == 0) {
        ESP_LOGW(TAG, "Hotspot '%s' not found in scan", CSI_TX_HOTSPOT_SSID);
        return;
    }

    wifi_ap_record_t ap_info = {0};
    uint16_t number = 1;

    if (
        esp_wifi_scan_get_ap_records(&number, &ap_info) != ESP_OK ||
        number == 0
    ) {
        return;
    }

    if (ap_info.primary != s_tx_channel) {
        ESP_LOGW(
            TAG,
            "Hotspot channel changed: %u -> %u, following...",
            s_tx_channel,
            ap_info.primary
        );

        esp_err_t err = esp_wifi_set_channel(
            ap_info.primary,
            WIFI_SECOND_CHAN_NONE
        );

        if (err == ESP_OK) {
            s_tx_channel = ap_info.primary;
        } else {
            ESP_LOGE(
                TAG,
                "Failed to follow channel: %s",
                esp_err_to_name(err)
            );
        }
    }
}

static void channel_follow_task(void *pvParameter)
{
    /*
     * [버그 수정 - 초기 채널 불일치] while 루프 진입 전에 먼저 한 번
     * 즉시 확인한다. 안 그러면 부팅 직후 최대
     * CSI_TX_CHANNEL_FOLLOW_INTERVAL_MS(20초)만큼 TX가 예전(고정)
     * 채널에 그대로 머물러서, 그 사이엔 RX(핫스팟의 실제 채널로 바로
     * 붙음)와 채널이 안 맞아 CSI가 하나도 안 잡힌다.
     */
    channel_follow_check_once();

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(CSI_TX_CHANNEL_FOLLOW_INTERVAL_MS));
        channel_follow_check_once();
    }
}
#endif

void app_main()
{
    /**
     * @brief Initialize NVS
     */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /**
     * @brief Initialize Wi-Fi
     */
    wifi_init();

    /**
     * @brief Initialize ESP-NOW
     *        ESP-NOW protocol see: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_now.html
     */
#if CSI_TX_FOLLOW_HOTSPOT_CHANNEL
    /*
     * [버그 수정 - 핫스팟 채널 자동 추적] peer.channel을 고정값이 아니라
     * 0으로 두면 ESP-NOW가 "지금 esp_wifi가 설정된 채널"을 그대로
     * 따라간다. 고정값을 넣으면 channel_follow_task가
     * esp_wifi_set_channel()로 라디오 채널을 바꿔도 ESP-NOW 자체는
     * 계속 예전 채널로 보내려고 해서 무용지물이 된다.
     */
    uint8_t peer_channel = 0;
#else
    uint8_t peer_channel = CONFIG_LESS_INTERFERENCE_CHANNEL;
#endif

    esp_now_peer_info_t peer = {
        .channel   = peer_channel,
        .ifidx     = WIFI_IF_STA,
        .encrypt   = false,
        .peer_addr = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
    };
    wifi_esp_now_init(peer);

#if CSI_TX_FOLLOW_HOTSPOT_CHANNEL
    BaseType_t channel_follow_result = xTaskCreate(
        channel_follow_task,
        "channel_follow",
        3072,
        NULL,
        3,
        NULL
    );

    if (channel_follow_result != pdPASS) {
        ESP_LOGW(TAG, "Failed to create channel follow task");
    }
#endif

    ESP_LOGI(TAG, "================ CSI SEND ================");
    ESP_LOGI(TAG, "wifi_channel: %d, send_frequency: %d, mac: " MACSTR,
             CONFIG_LESS_INTERFERENCE_CHANNEL, CONFIG_SEND_FREQUENCY, MAC2STR(CONFIG_CSI_SEND_MAC));

    /*
     * [개선 1] 정밀한 주기 전송 (drift 보정)
     *
     * 기존 코드는 "esp_now_send() 실행 -> usleep(고정시간)" 순서였는데,
     * esp_now_send() 자체가 걸리는 시간만큼 실제 주기가 목표(27.7ms)보다
     * 계속 밀리면서 누적 drift가 생겨, 실제 송신 PPS가 목표(36)보다
     * 낮아질 수 있다.
     *
     * next_send_time을 기준으로 "다음 목표 시각까지" 절대시간으로
     * 스케줄링하면 개별 호출의 처리 지연이 다음 주기로 누적되지 않는다.
     */
    const int64_t period_us = 1000000 / CONFIG_SEND_FREQUENCY;
    int64_t next_send_time = esp_timer_get_time();

    /*
     * [개선 2] 실제 송신 PPS를 눈으로 확인할 수 있도록 통계 로그 추가.
     * 기존 코드는 esp_now_send 실패시에만 로그를 찍어서, "성공은 하는데
     * 목표 PPS에 못 미치는" 상황은 확인할 방법이 없었다.
     */
    uint32_t sent_ok = 0;
    uint32_t sent_fail = 0;
    int64_t last_stats_time = esp_timer_get_time();

    for (uint32_t count = 0; ; ++count) {
        esp_err_t send_ret = esp_now_send(peer.peer_addr, (const uint8_t *)&count, sizeof(count));

        if (send_ret != ESP_OK) {
            sent_fail++;
            ESP_LOGW(TAG, "free_heap: %ld <%s> ESP-NOW send error", esp_get_free_heap_size(), esp_err_to_name(send_ret));
        } else {
            sent_ok++;
        }

        int64_t now = esp_timer_get_time();

        if (now - last_stats_time >= 5000000) {
            double elapsed_sec = (double)(now - last_stats_time) / 1000000.0;

            ESP_LOGI(
                TAG,
                "[TX] target_pps=%d, actual_pps=%.1f, ok=%lu, fail=%lu",
                CONFIG_SEND_FREQUENCY,
                (double)sent_ok / elapsed_sec,
                (unsigned long)sent_ok,
                (unsigned long)sent_fail
            );

            sent_ok = 0;
            sent_fail = 0;
            last_stats_time = now;
        }

        next_send_time += period_us;

        int64_t sleep_us = next_send_time - esp_timer_get_time();

        if (sleep_us > 0) {
            usleep((useconds_t)sleep_us);
        } else {
            /*
             * 이미 다음 목표 시각을 지나버린 경우(처리 지연이 한 주기를
             * 넘어선 경우) 기준 시각을 현재로 재설정해서 drift가
             * 무한정 누적되는 것을 방지한다.
             */
            next_send_time = esp_timer_get_time();
        }
    }
}
