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
#include "esp_event.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#include "freertos/queue.h"
#include "freertos/task.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/socket.h>

#include "nvs_flash.h"

#include "esp_mac.h"
#include "rom/ets_sys.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_csi_gain_ctrl.h"
#include "esp_timer.h"
#include "esp_random.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"
#include <errno.h>

#define WIFI_SSID CONFIG_CSI_HOTSPOT_SSID
#define WIFI_PASS CONFIG_CSI_HOTSPOT_PASSWORD

#define TCP_SERVER_IP   CONFIG_CSI_TCP_SERVER_IP
#define TCP_SERVER_PORT CONFIG_CSI_TCP_SERVER_PORT

#define EXPECTED_WIFI_CHANNEL CONFIG_CSI_EXPECTED_CHANNEL
#if CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C61 || (CONFIG_IDF_TARGET_ESP32C6 && ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 4, 0))
#define CONFIG_WIFI_BAND_MODE               WIFI_BAND_MODE_2G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS           WIFI_BW_HT40
#define CONFIG_WIFI_5G_BANDWIDTHS           WIFI_BW_HT40
#define CONFIG_WIFI_2G_PROTOCOL             WIFI_PROTOCOL_11N
#define CONFIG_WIFI_5G_PROTOCOL             WIFI_PROTOCOL_11N
#else
#define CONFIG_WIFI_BANDWIDTH           WIFI_BW_HT20
#endif

#define CONFIG_ESP_NOW_PHYMODE           WIFI_PHY_MODE_HT20
#define CONFIG_ESP_NOW_RATE             WIFI_PHY_RATE_MCS0_LGI
#define CONFIG_FORCE_GAIN                   0

#if CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C61
#define CSI_FORCE_LLTF                      0
#endif

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C6 || CONFIG_IDF_TARGET_ESP32C61
#define CONFIG_GAIN_CONTROL                 1
#endif

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
#define ESP_IF_WIFI_STA ESP_MAC_WIFI_STA
#endif

static const uint8_t CONFIG_CSI_SEND_MAC[] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};
static const char *TAG = "csi_recv";

static EventGroupHandle_t s_wifi_event_group;

#define WIFI_CONNECTED_BIT BIT0
#define CSI_TCP_MAX_DATA_LEN 512

/*
 * [버그 수정 - 재연결 중 데이터 유실] 큐 슬롯 1개(csi_tcp_packet_t)는
 * 정확히 556바이트다(DWARF로 실측 확인). 재연결 한 번에 걸리는
 * 최악 시간이 약 5.5초(SO_SNDTIMEO 1.5초 x consecutive_errors 3회 +
 * TCP_RECONNECT_DELAY_MS 1초)인데, 기존 64개 큐는 36~50pps 기준
 * 약 1.3~1.8초치 밖에 못 담아서 재연결 구간의 나머지는 그냥
 * 유실됐다(drop-oldest 정책상 "최신 것 위주로 유지"는 되지만, 큐
 * 자체가 작으면 유지할 수 있는 절대량이 적다).
 *
 * 128개로 늘리면 약 71KB(556B x 128)로, ESP32 힙 여유 대비 부담이
 * 크지 않으면서 재연결 구간 동안 담아둘 수 있는 데이터가 2배로
 * 늘어난다.
 */
#define CSI_TCP_QUEUE_DEPTH 128
#define TCP_RECONNECT_DELAY_MS 1000

/*
 * [버그 수정] 기존 CSI_TCP_LINE_MAX=4096, 배칭 임계값=1200이었는데,
 * CSI 값 하나하나를 "-128," 같은 ASCII 십진수로 풀어 쓰다 보니
 * 패킷 1개의 라인 길이가 최악의 경우(CSI_TCP_MAX_DATA_LEN=512개)
 * 약 200(헤더) + 512*5(값) + 8(꼬리) ≈ 2768바이트에 달한다.
 * 즉 패킷 1개만 포맷해도 이미 1200바이트를 넘는 경우가 많아서,
 * "여러 패킷을 묶어 전송"하는 배칭 로직이 사실상 거의 항상
 * 패킷 1개당 TCP 전송 1번으로 동작하고 있었다(=배칭 무효화).
 * 매 전송마다 WiFi 프레임 전송/ACK/백오프 오버헤드가 그대로
 * 들어가므로, 이게 RX 자신의 업링크 트래픽이 채널을 점유하는
 * 시간을 늘려 TX의 CSI 트리거 브로드캐스트 수신 기회를
 * 깎아먹는 원인 중 하나로 보인다.
 *
 * 라인 버퍼를 2배로 늘리고, "한 줄의 최악 크기"를 기준으로
 * 배칭 여부를 판단하도록 바꿔서 실제로 여러 패킷이 한 번에
 * 묶여 나가도록 한다.
 */
#define CSI_TCP_LINE_MAX 8192

/*
 * [버그 수정 - 전송량 자체가 과다] 실측(2025-09-18) 결과, 특정 설치
 * 위치에서는 RSSI가 멀쩡한데도(-33~-66dBm) 링크가 서서히 무너지는
 * 현상이 나왔다. 시리얼 로그를 보면 재연결이 원인이 아니라 결과였다 -
 * "TCP sent(total)"이 "CSI capture"를 못 따라가서 큐 depth가 계속
 * 늘다가 최대치(128)에서 한참 버티고, 그러다 배치가 커질 대로 커진
 * 상태에서야 send가 정체되기 시작했다. 즉 근본 원인은 "그 위치에서
 * 버틸 수 있는 실제 처리량보다 우리가 보내려는 데이터양 자체가 많다"는
 * 것이었다.
 *
 * 기존 포맷은 서브캐리어 값 하나하나를 "-128," 같은 ASCII 십진수로
 * 풀어 써서 값 1개당 평균 4~5바이트를 썼다(부호+최대 3자리 숫자+콤마).
 * base64로 바꾸면 원본 바이트 1개가 약 4/3바이트로만 인코딩되어
 * (십진수 대비 약 1/3), 같은 서브캐리어 데이터를 하나도 안 버리면서
 * 전송량만 약 3배 줄일 수 있다. 값 손실 없는 순수 인코딩 변경이라
 * 데이터 품질에는 영향이 없다.
 */
#define CSI_TCP_B64_MAX_LEN (4 * ((CSI_TCP_MAX_DATA_LEN + 2) / 3))
#define CSI_TCP_LINE_ESTIMATED_MAX (200 + CSI_TCP_B64_MAX_LEN + 8)

/*
 * [개선] 통계 로그 출력 주기 (gain-control 로그 rate-limit에도 재사용)
 */
#define STATS_INTERVAL_US 5000000

/*
 * [버그 수정 - 전송 충돌] RX 4대 전송 슬롯 분리
 *
 * 기존에는 전송 직전 지터가 0~8ms "완전 랜덤"이었다. 이러면 매 전송마다
 * 4개 RX가 동일한 확률분포에서 지연값을 뽑기 때문에, 어쩌다 유리한
 * 지연값을 먼저 뽑은 노드가 802.11 지수 백오프 특성상 그 다음 라운드도
 * 계속 이기고(=먼저 나감), 진 쪽은 백오프가 계속 커지며 더 밀리는
 * "승자독식" 패턴으로 이어졌다.
 *
 * 실측 결과 이긴 노드는 link_id/RSSI와 무관하게 매 세션 랜덤하게
 * 바뀌었다(신호가 제일 약한 링크가 살아남은 적도 있음) - 즉 순전히
 * 지터 추첨의 우연으로 승자가 갈렸다는 뜻이다.
 *
 * link_id별로 고정된 슬롯을 우선 배정해서 4개 노드의 전송 시도가
 * 애초에 겹칠 확률을 구조적으로 줄이고, 슬롯 안에서만 작은 지터를
 * 둬서 슬롯끼리 주기적으로 정확히 맞물리는 것도 방지한다.
 * (CSI_LINK_ID_CUSTOM처럼 슬롯이 매핑되지 않는 경우는 슬롯 0으로
 * 폴백한다 - link_1과 슬롯이 겹치지만 최소한 동작은 한다.)
 */
#if CONFIG_CSI_LINK_ID_2
#define CSI_TX_SLOT_INDEX 1
#elif CONFIG_CSI_LINK_ID_3
#define CSI_TX_SLOT_INDEX 2
#elif CONFIG_CSI_LINK_ID_4
#define CSI_TX_SLOT_INDEX 3
#else
#define CSI_TX_SLOT_INDEX 0
#endif

#define CSI_TX_SLOT_SPACING_US 3000
#define CSI_TX_SLOT_JITTER_US 2000

typedef struct {
    uint32_t rx_id;
    uint8_t mac[6];

    wifi_pkt_rx_ctrl_t rx_ctrl;

    uint16_t len;
    uint8_t first_word_invalid;

    int8_t data[CSI_TCP_MAX_DATA_LEN];
} csi_tcp_packet_t;

static QueueHandle_t s_csi_tcp_queue = NULL;

static volatile uint32_t s_tcp_queue_drops = 0;

/*
 * [개선 1] "실제로 공중에서 CSI를 몇 개 캡처했는지"를 별도로 카운트.
 * 기존 코드는 "TCP로 보낸 개수"만 로그로 보여줘서, RF 수신 자체가
 * 안 되는 건지(=이 카운터가 안 늘어남) 아니면 큐/TCP 파이프라인이
 * 막힌 건지(=이 카운터는 늘어나는데 sent_count가 안 늘어남) 구분이
 * 불가능했다. 이 카운터를 추가해서 원인을 분리해서 볼 수 있게 한다.
 */
static volatile uint32_t s_csi_capture_count = 0;

static bool tcp_send_all(
    int sock,
    const char *data,
    size_t len,
    size_t *out_sent
)
{
    size_t total_sent = 0;

    while (total_sent < len) {
        int sent = send(
            sock,
            data + total_sent,
            len - total_sent,
            0
        );

        if (sent < 0) {
            if (errno == EINTR) {
                continue;
            }

            if (out_sent) {
                *out_sent = total_sent;
            }

            return false;
        }

        if (sent == 0) {
            if (out_sent) {
                *out_sent = total_sent;
            }

            return false;
        }

        total_sent += sent;
    }

    if (out_sent) {
        *out_sent = total_sent;
    }

    return true;
}

/*
 * [버그 수정 - 전송량 자체가 과다] CSI 서브캐리어 원본 바이트를
 * base64로 인코딩한다. 십진수 텍스트("-128,") 대비 값 손실 없이
 * 전송 바이트 수만 약 1/3로 줄이기 위한 목적. mbedtls 등 외부
 * 의존성을 끌어오지 않도록 표준 base64 인코딩을 직접 구현했다.
 *
 * out_size가 부족하면(=버퍼 초과) 0을 반환한다. 단, len==0(빈 배열)인
 * 정상 케이스도 결과가 0이므로, 호출부에서 반드시 "len>0인데 0이
 * 반환됨"과 "len==0이라 0이 반환됨"을 구분해서 처리해야 한다.
 */
static size_t base64_encode(
    const uint8_t *data,
    size_t len,
    char *out,
    size_t out_size
)
{
    static const char b64_chars[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789+/";

    size_t out_len = 4 * ((len + 2) / 3);

    if (out_size < out_len + 1) {
        return 0;
    }

    size_t oi = 0;

    for (size_t i = 0; i < len; i += 3) {
        uint32_t n = (uint32_t)data[i] << 16;

        if (i + 1 < len) {
            n |= (uint32_t)data[i + 1] << 8;
        }

        if (i + 2 < len) {
            n |= (uint32_t)data[i + 2];
        }

        out[oi++] = b64_chars[(n >> 18) & 0x3F];
        out[oi++] = b64_chars[(n >> 12) & 0x3F];
        out[oi++] = (i + 1 < len) ? b64_chars[(n >> 6) & 0x3F] : '=';
        out[oi++] = (i + 2 < len) ? b64_chars[n & 0x3F] : '=';
    }

    out[oi] = '\0';

    return oi;
}

static size_t format_csi_tcp_line(
    const csi_tcp_packet_t *packet,
    char *line,
    size_t line_size
)
{
    size_t used = 0;

    /*
     * [버그 수정 - 전송량 자체가 과다] 기존에는 여기서 끝을 "\"[" 로
     * 열고 값들을 십진수로 나열한 뒤 "]\"" 로 닫았다(CSV 콤마가 값
     * 안에도 있어서 따옴표로 감싸야 했음). base64 문자셋(A-Z a-z 0-9
     * + /)에는 콤마/따옴표가 없어서 따옴표로 감쌀 필요가 없고, 그냥
     * 콤마 하나로 필드를 열면 된다.
     */
    int written = snprintf(
        line,
        line_size,
        "CSI_DATA,%u," MACSTR
        ",%d,%d,%d,%d,%d"
        ",%d,%d,%d,%d,%d"
        ",%d,%d,%d,%d,%d"
        ",%u,%d,%d,%d,%u,%d,",
        (unsigned int)packet->rx_id,
        MAC2STR(packet->mac),

        packet->rx_ctrl.rssi,
        packet->rx_ctrl.rate,
        packet->rx_ctrl.sig_mode,
        packet->rx_ctrl.mcs,
        packet->rx_ctrl.cwb,
        packet->rx_ctrl.smoothing,
        packet->rx_ctrl.not_sounding,
        packet->rx_ctrl.aggregation,
        packet->rx_ctrl.stbc,
        packet->rx_ctrl.fec_coding,
        packet->rx_ctrl.sgi,

        packet->rx_ctrl.noise_floor,
        packet->rx_ctrl.ampdu_cnt,
        packet->rx_ctrl.channel,
        packet->rx_ctrl.secondary_channel,

        (unsigned int)packet->rx_ctrl.timestamp,
        packet->rx_ctrl.ant,
        packet->rx_ctrl.sig_len,

        packet->rx_ctrl.sig_mode,

        (unsigned int)packet->len,
        packet->first_word_invalid
    );

    if (written < 0 || (size_t)written >= line_size) {
        return 0;
    }

    used = (size_t)written;

    if (packet->len > 0) {
        size_t b64_len = base64_encode(
            (const uint8_t *)packet->data,
            packet->len,
            line + used,
            line_size - used
        );

        if (b64_len == 0) {
            // len>0인데 0이 반환됐다는 건 버퍼 초과(실패) - len==0 케이스는 이 분기에 안 들어옴
            return 0;
        }

        used += b64_len;
    }

    written = snprintf(
        line + used,
        line_size - used,
        "\n"
    );

    if (
        written < 0 ||
        (size_t)written >= (line_size - used)
    ) {
        return 0;
    }

    used += (size_t)written;

    return used;
}

static void queue_csi_for_tcp(
    const wifi_csi_info_t *info,
    uint32_t rx_id
)
{
    if (s_csi_tcp_queue == NULL) {
        return;
    }

    if (info->len > CSI_TCP_MAX_DATA_LEN) {
        s_tcp_queue_drops++;
        return;
    }

    csi_tcp_packet_t packet = {0};

    packet.rx_id = rx_id;

    memcpy(
        packet.mac,
        info->mac,
        sizeof(packet.mac)
    );

    packet.rx_ctrl = info->rx_ctrl;

    packet.len = (uint16_t)info->len;

    packet.first_word_invalid =
        info->first_word_invalid ? 1 : 0;

    memcpy(
        packet.data,
        info->buf,
        info->len
    );

    /*
     * 절대 기다리지 않는다.
     *
     * CSI callback은 즉시 return할 수 있어야 한다.
     */
    if (
        xQueueSend(
            s_csi_tcp_queue,
            &packet,
            0
        ) != pdTRUE
    ) {
        /*
         * [버그 수정 - 큐 정책] 기존 코드는 큐가 꽉 차면 방금 들어온
         * (가장 최신) 패킷을 버렸다. 한쪽 RX가 TCP 전송에서 밀리기
         * 시작하면 큐에는 계속 "옛날 데이터"만 쌓여 있다가, 나중에
         * 복구돼도 서버는 몇십 초 전의 낡은 CSI를 받게 됐다(서버의
         * 5초 윈도우 집계 시각축 자체가 어긋남).
         *
         * 큐가 꽉 찼을 때는 대신 가장 오래된 패킷 1개를 버리고 방금
         * 캡처한 최신 패킷을 그 자리에 넣는다. 큐 안의 데이터가 항상
         * "최근 것" 위주로 유지되어, 막혔다가 복구됐을 때 보내는
         * 데이터가 신선하게 유지된다.
         */
        csi_tcp_packet_t discarded;

        if (
            xQueueReceive(
                s_csi_tcp_queue,
                &discarded,
                0
            ) != pdTRUE ||
            xQueueSend(
                s_csi_tcp_queue,
                &packet,
                0
            ) != pdTRUE
        ) {
            s_tcp_queue_drops++;
        }
    }
}

static void tcp_sender_task(void *pvParameter)
{
    char *line = malloc(CSI_TCP_LINE_MAX);

    if (line == NULL) {
        ESP_LOGE(TAG, "Failed to allocate TCP line buffer");
        vTaskDelete(NULL);
        return;
    }

    while (1) {

        struct sockaddr_in dest_addr = {0};

        dest_addr.sin_family = AF_INET;
        dest_addr.sin_port = htons(TCP_SERVER_PORT);

        if (
            inet_pton(
                AF_INET,
                TCP_SERVER_IP,
                &dest_addr.sin_addr
            ) != 1
        ) {
            ESP_LOGE(
                TAG,
                "Invalid TCP server IP: %s",
                TCP_SERVER_IP
            );

            vTaskDelay(
                pdMS_TO_TICKS(TCP_RECONNECT_DELAY_MS)
            );

            continue;
        }

        int sock = socket(
            AF_INET,
            SOCK_STREAM,
            IPPROTO_IP
        );

        if (sock < 0) {
            ESP_LOGE(
                TAG,
                "TCP socket creation failed, errno=%d",
                errno
            );

            vTaskDelay(
                pdMS_TO_TICKS(TCP_RECONNECT_DELAY_MS)
            );

            continue;
        }

        /*
         * [버그 수정 - 장애 감지 지연] 기존 5초 타임아웃 x 실패 10회
         * 임계값(아래 consecutive_errors 참고) 조합은 막힌 링크를
         * 재연결시키기까지 최소 50초 이상 걸렸다. 그동안 해당 링크는
         * TCP로도, 로그로도 완전히 조용해져서(로그가 성공한 전송
         * 직후에만 찍힘) 겉보기엔 "그냥 죽은 것"처럼 보였다.
         *
         * [버그 수정 - 잦은 재연결] 처음엔 500ms까지 줄였는데, 이 정도로
         * 짧으면 정상적인 Wi-Fi 혼잡 상황(=곧 회복될 지연)에서도
         * 배치를 다 못 보내고 타임아웃이 걸리는 경우가 흔해졌다. 당시엔
         * "일부만 보낸 채" 타임아웃 나면 무조건 즉시 재연결하던
         * 시절이라(현재는 잔여분을 이어 보내는 방식으로 바뀜 -
         * pending_ptr/pending_len 처리 참고), 결과적으로 재연결이
         * 지나치게 잦아졌었다(정상적으로 몇 초 뒤 복구됐을 상황까지
         * 매번 재연결).
         *
         * 1.5초로 다시 늘려서 정상적인 지연은 재연결 없이 넘기되,
         * 기존 5초보다는 여전히 3배 이상 빠르게 반응하도록 한다.
         * (같이 늘린 CONFIG_LWIP_TCP_SND_BUF_DEFAULT와 함께 적용하면
         * "일부만 보내다 실패"하는 상황 자체도 줄어든다.)
         */
        struct timeval send_timeout = {
            .tv_sec = 1,
            .tv_usec = 500000,
        };


        if (
            setsockopt(
            sock,
            SOL_SOCKET,
            SO_SNDTIMEO,
            &send_timeout,
            sizeof(send_timeout)
        ) != 0
    ) {

        ESP_LOGW(
            TAG,
            "Failed to set send timeout errno=%d",
            errno
        );

    }

        int nodelay = 1;
        setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));

        ESP_LOGI(
            TAG,
            "TCP connecting to %s:%d...",
            TCP_SERVER_IP,
            TCP_SERVER_PORT
        );

        int err = connect(
            sock,
            (struct sockaddr *)&dest_addr,
            sizeof(dest_addr)
        );

        if (err != 0) {
            ESP_LOGW(
                TAG,
                "TCP connection failed, errno=%d",
                errno
            );

            close(sock);

            vTaskDelay(
                pdMS_TO_TICKS(TCP_RECONNECT_DELAY_MS)
            );

            continue;
        }

        ESP_LOGI(
            TAG,
            "TCP STREAM CONNECTED: link=%s",
            CONFIG_CSI_LINK_ID
        );

        /*
         * 연결된 RX가 누구인지 Mac이 알 수 있도록
         * 최초 1회 handshake 전송
         */
        char hello[64];

        int hello_len = snprintf(
            hello,
            sizeof(hello),
            "HELLO,%s\n",
            CONFIG_CSI_LINK_ID
        );

        if (
            hello_len <= 0 ||
            (size_t)hello_len >= sizeof(hello) ||
            !tcp_send_all(
                sock,
                hello,
                (size_t)hello_len,
                NULL
            )
        ) {
            ESP_LOGW(
                TAG,
                "TCP HELLO send failed"
            );

            shutdown(sock, SHUT_RDWR);
            close(sock);

            vTaskDelay(
                pdMS_TO_TICKS(TCP_RECONNECT_DELAY_MS)
            );

            continue;
        }

        csi_tcp_packet_t packet;
        uint32_t sent_count = 0;
        int consecutive_errors = 0;
        int64_t last_stats_time = esp_timer_get_time();
        uint32_t last_capture_count = s_csi_capture_count;

        /*
         * [버그 수정 - 과도한 재연결] 이전 버전은 배치를 "일부라도"
         * 보낸 상태에서 타임아웃이 나면 스트림 오염을 막기 위해
         * 무조건 즉시 재연결했다. 그런데 실측해보니 특정 위치의
         * RX(전파 환경이 남들보다 살짝 나쁜 노드)는 배치 전송 도중
         * 1.5초 정도 진행이 멈추는 상황 자체가 드물지 않게 발생했고,
         * 그때마다 매번 즉시 재연결되면서 사실상 재연결 루프에 갇혀
         * pps가 거의 0으로 떨어졌다(대시보드 틱마다 재연결 로그가
         * 찍히는 패턴으로 확인됨).
         *
         * 스트림을 오염시키지 않으면서도 이런 "느리지만 살아있는"
         * 링크를 봐줄 방법은, 실패해도 소켓을 버리지 않고 "이미 나간
         * 만큼은 건너뛰고 나머지부터" 같은 소켓으로 이어 보내는
         * 것이다(TCP는 바이트 스트림이므로 끊긴 지점부터 정확히 이어
         * 보내면 서버 입장에서는 그냥 좀 늦게 도착한 정상 데이터로
         * 보인다 - 새 배치를 얹는 게 아니라 미완성 라인 자체를 마저
         * 완성시키는 것이므로 오염이 생기지 않는다).
         *
         * pending_ptr/pending_len이 남아있는 동안은 새 배치를 만들지
         * 않고 그 잔여분부터 우선 재시도하며, 이게 3회 연속 실패할
         * 때만(최대 약 4.5초 이상 정체) 진짜로 끊긴 것으로 보고
         * 재연결한다.
         */
        const char *pending_ptr = NULL;
        size_t pending_len = 0;
        bool socket_ok = true;

        while (socket_ok) {
            if (pending_len == 0) {
                if (
                    xQueueReceive(
                        s_csi_tcp_queue,
                        &packet,
                        portMAX_DELAY
                    ) != pdTRUE
                ) {
                    break;
                }

                size_t total_batch_len = 0;
                char *batch_ptr = line;

                // 1번째 패킷 포맷팅
                size_t line_len = format_csi_tcp_line(&packet, batch_ptr, CSI_TCP_LINE_MAX - total_batch_len);
                if (line_len > 0) {
                    total_batch_len += line_len;
                    batch_ptr += line_len;
                } else {
                    // 패킷 1개가 라인 버퍼보다 큰 비정상 케이스 -> 유실 대신 드롭으로 기록
                    s_tcp_queue_drops++;
                }

                /*
                 * [버그 수정] 기존 코드는 xQueueReceive로 큐에서 미리
                 * 꺼내온 뒤 남은 버퍼에 안 들어가면(line_len==0) 그
                 * 패킷을 그냥 버렸다 - 카운트도 안 되고 큐에도 다시
                 * 안 들어가는 조용한 데이터 유실이었다.
                 *
                 * xQueuePeek으로 "꺼내기 전에" 남은 공간에 들어갈 만한지
                 * 먼저 가늠하고, 안 들어갈 것 같으면 큐에서 꺼내지 않고
                 * 다음 배치로 넘긴다. 이러면 유실 없이, 그리고 실제로
                 * 여러 패킷이 한 번에 배칭된다.
                 */
                csi_tcp_packet_t peek_packet;

                while (xQueuePeek(s_csi_tcp_queue, &peek_packet, 0) == pdTRUE) {
                    size_t remaining = CSI_TCP_LINE_MAX - total_batch_len;

                    if (remaining < CSI_TCP_LINE_ESTIMATED_MAX) {
                        break;
                    }

                    if (xQueueReceive(s_csi_tcp_queue, &packet, 0) != pdTRUE) {
                        break;
                    }

                    line_len = format_csi_tcp_line(&packet, batch_ptr, remaining);
                    if (line_len > 0) {
                        total_batch_len += line_len;
                        batch_ptr += line_len;
                    } else {
                        s_tcp_queue_drops++;
                    }
                }

                if (total_batch_len == 0) {
                    continue;
                }

                /*
                 * [개선] RX-RX 간 전송 타이밍 충돌 완화 (capture effect 대응)
                 *
                 * 4개 RX가 같은 TX 브로드캐스트를 거의 동시에 캡처하다 보니,
                 * 큐가 차는 타이밍도 서로 비슷해서 TCP 전송 시도가 겹치기
                 * 쉽다. link_id별 고정 슬롯(CSI_TX_SLOT_INDEX)으로 4개
                 * 노드의 전송 시작 시각을 구조적으로 분산시키고, 슬롯 내부
                 * 소지터로 슬롯끼리 주기적으로 정확히 맞물리는 것도
                 * 방지한다. 자세한 배경은 CSI_TX_SLOT_INDEX 정의부 주석 참고.
                 *
                 * 이 지터는 "새 배치를 처음 만들었을 때"만 적용한다 -
                 * 아래에서 실패한 잔여분을 재시도할 때는 이미 충분히
                 * 지연된 상태이므로 또 지터를 넣을 필요가 없다.
                 */
                uint32_t jitter_us =
                    (CSI_TX_SLOT_INDEX * CSI_TX_SLOT_SPACING_US) +
                    (esp_random() % CSI_TX_SLOT_JITTER_US);
                esp_rom_delay_us(jitter_us);

                pending_ptr = line;
                pending_len = total_batch_len;
            }

            size_t bytes_sent = 0;
            bool ok = tcp_send_all(
                sock,
                pending_ptr,
                pending_len,
                &bytes_sent
            );

            if (ok) {
                pending_ptr = NULL;
                pending_len = 0;
                consecutive_errors = 0;
                sent_count++;

                int64_t now = esp_timer_get_time();
                if (now - last_stats_time >= STATS_INTERVAL_US) {
                    /*
                     * [개선] CSI 캡처량(=RF 수신 성공 개수)을 구간(5초) delta로
                     * 계산해서 실제 PPS를 그대로 보여준다. 이 값이 낮으면
                     * TCP/큐 문제가 아니라 RF 레벨에서부터 패킷을 못 잡고
                     * 있다는 뜻이다.
                     */
                    uint32_t captured_now = s_csi_capture_count;
                    uint32_t captured_delta = captured_now - last_capture_count;
                    last_capture_count = captured_now;

                    double elapsed_sec = (double)(now - last_stats_time) / 1000000.0;

                    /*
                     * [진단용 - 2026-09-21] 공유기/핫스팟을 바꿔도, 데이터양을
                     * 줄여도 똑같이 반복되는 "약 60~90초 후 막힘 -> 재연결하면
                     * 잠깐 회복"이라는 패턴이 AP 문제가 아니라 보드 자체의
                     * 메모리 누수일 가능성을 확인하기 위해 힙 여유량을 같이
                     * 찍는다. free_heap이 막히기 직전까지 계속 줄어들고
                     * min_free_heap과 거의 같아지면(=역대 최저치를 계속
                     * 갱신 중이면) 진짜 누수다.
                     */
                    ESP_LOGI(
                        TAG,
                        "[%s] CSI capture: %lu (~%.1f pps) | TCP sent(total): %lu | Queue drops(total): %lu | Queue depth: %u | free_heap: %lu | min_free_heap: %lu",
                        CONFIG_CSI_LINK_ID,
                        (unsigned long)captured_delta,
                        (double)captured_delta / elapsed_sec,
                        (unsigned long)sent_count,
                        (unsigned long)s_tcp_queue_drops,
                        (unsigned)uxQueueMessagesWaiting(s_csi_tcp_queue),
                        (unsigned long)esp_get_free_heap_size(),
                        (unsigned long)esp_get_minimum_free_heap_size()
                    );
                    last_stats_time = now;
                }

                continue;
            }

            // 실패: 이미 나간 만큼은 건너뛰고, 다음 시도에 "나머지"부터 이어 보낸다
            pending_ptr += bytes_sent;
            pending_len -= bytes_sent;
            consecutive_errors++;

            if (consecutive_errors >= 3) {
                ESP_LOGW(
                    TAG,
                    "TCP send stalled %d times in a row (%u bytes of current batch still unsent), free_heap=%lu min_free_heap=%lu, reconnecting...",
                    consecutive_errors,
                    (unsigned)pending_len,
                    (unsigned long)esp_get_free_heap_size(),
                    (unsigned long)esp_get_minimum_free_heap_size()
                );
                socket_ok = false;
            }
            // 3회 미만이면 소켓을 유지한 채 같은 잔여분을 계속 재시도
        }

        shutdown(sock, SHUT_RDWR);
        close(sock);

        ESP_LOGW(
            TAG,
            "TCP disconnected. reconnecting..."
        );

        vTaskDelay(
            pdMS_TO_TICKS(TCP_RECONNECT_DELAY_MS)
        );
    }
}

/*
 * [개선 2] 세션 도중 공유기 채널이 튀는지(Channel drift) 30초마다 재확인.
 * 기존 코드는 IP_EVENT_STA_GOT_IP 시점(최초 연결 직후) 딱 한 번만
 * 채널을 확인했기 때문에, 세션 도중 공유기가 채널을 바꾸면
 * (자동채널/DFS 등) 감지할 방법이 없었다. 곁들여 RSSI도 주기적으로
 * 남겨서 신호 품질 저하도 같이 추적할 수 있게 한다.
 */
static void channel_monitor_task(void *pvParameter)
{
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(30000));

        uint8_t primary = 0;
        wifi_second_chan_t second = WIFI_SECOND_CHAN_NONE;

        if (
            esp_wifi_get_channel(&primary, &second) == ESP_OK &&
            primary != EXPECTED_WIFI_CHANNEL
        ) {
            ESP_LOGE(
                TAG,
                "Channel drift detected! current=%u expected=%u",
                primary,
                EXPECTED_WIFI_CHANNEL
            );
        }

        wifi_ap_record_t ap_info;

        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            ESP_LOGI(
                TAG,
                "[%s] link RSSI: %d dBm",
                CONFIG_CSI_LINK_ID,
                ap_info.rssi
            );
        }
    }
}

static void wifi_event_handler(void *arg,
    esp_event_base_t event_base,
    int32_t event_id,
    void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "Connecting to hotspot...");
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT &&
        event_id == WIFI_EVENT_STA_DISCONNECTED) {

        wifi_event_sta_disconnected_t *event =
            (wifi_event_sta_disconnected_t *)event_data;

        ESP_LOGW(TAG,
            "Disconnected from hotspot, reason=%d, retrying...",
            event->reason);

        esp_wifi_connect();
    } else if (event_base == IP_EVENT &&
        event_id == IP_EVENT_STA_GOT_IP) {

        ip_event_got_ip_t *event = (ip_event_got_ip_t *) event_data;

        ESP_LOGI(TAG, "========================================");
        ESP_LOGI(TAG, "HOTSPOT CONNECTED");
        ESP_LOGI(TAG, "RX IP: " IPSTR, IP2STR(&event->ip_info.ip));
        ESP_LOGI(TAG, "Gateway: " IPSTR, IP2STR(&event->ip_info.gw));

        uint8_t primary = 0;
        wifi_second_chan_t second = WIFI_SECOND_CHAN_NONE;

        ESP_ERROR_CHECK(
            esp_wifi_get_channel(
                &primary,
                &second
            )
        );

    /* 핫스팟 연결 후 RX가 실제로 따라간 채널 출력 */
    ESP_LOGI(
        TAG,
        "RX Wi-Fi channel: primary=%u, secondary=%d",
        primary,
        (int)second
    );

    /* TX는 채널 6 고정이므로 불일치 여부 확인 */
    if (
        primary
        != EXPECTED_WIFI_CHANNEL
    )   {
            ESP_LOGE(
                TAG,
                "Channel mismatch: hotspot=%u, TX=%u",
                primary,
                EXPECTED_WIFI_CHANNEL
            );
        }

        ESP_LOGI(TAG, "RX link ID: %s", CONFIG_CSI_LINK_ID);

        ESP_LOGI(
            TAG,
            "TCP server: %s:%d",
            CONFIG_CSI_TCP_SERVER_IP,
            CONFIG_CSI_TCP_SERVER_PORT
        );

        ESP_LOGI(
            TAG,
            "Expected Wi-Fi channel: %d",
            CONFIG_CSI_EXPECTED_CHANNEL
        );

        ESP_LOGI(
            TAG,
            "========================================"
        );

        /* IP와 채널 확인이 끝난 다음 연결 완료 처리 */
        xEventGroupSetBits(
            s_wifi_event_group,
            WIFI_CONNECTED_BIT
        );
    }
}

static void wifi_init()
{
ESP_ERROR_CHECK(esp_netif_init());
ESP_ERROR_CHECK(esp_event_loop_create_default());

esp_netif_create_default_wifi_sta();

s_wifi_event_group = xEventGroupCreate();

ESP_ERROR_CHECK(
    esp_event_handler_register(
        WIFI_EVENT,
        ESP_EVENT_ANY_ID,
        &wifi_event_handler,
        NULL
    )
);

ESP_ERROR_CHECK(
    esp_event_handler_register(
        IP_EVENT,
        IP_EVENT_STA_GOT_IP,
        &wifi_event_handler,
        NULL
    )
);

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    wifi_config_t wifi_config = {0};

strncpy(
    (char *)wifi_config.sta.ssid,
    WIFI_SSID,
    sizeof(wifi_config.sta.ssid) - 1
);

strncpy(
    (char *)wifi_config.sta.password,
    WIFI_PASS,
    sizeof(wifi_config.sta.password) - 1
);

// wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

ESP_ERROR_CHECK(
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config)
);

// ESP_ERROR_CHECK(
   // esp_wifi_set_bandwidth(
       // WIFI_IF_STA,
       // CONFIG_WIFI_BANDWIDTH
   // )
// );

ESP_ERROR_CHECK(esp_wifi_start());

ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
esp_wifi_set_max_tx_power(78); // Max 20dBm power

    ESP_LOGI(TAG, "Waiting for hotspot connection...");

xEventGroupWaitBits(
    s_wifi_event_group,
    WIFI_CONNECTED_BIT,
    pdFALSE,
    pdTRUE,
    portMAX_DELAY
);

}

static void wifi_esp_now_init(esp_now_peer_info_t peer)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));
    esp_now_rate_config_t rate_config = {
        .phymode = CONFIG_ESP_NOW_PHYMODE,
        .rate = CONFIG_ESP_NOW_RATE,//  WIFI_PHY_RATE_MCS0_LGI,
        .ersu = false,
        .dcm = false
    };
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer.peer_addr, &rate_config));

}

static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf) {
        ESP_LOGW(TAG, "<%s> wifi_csi_cb", esp_err_to_name(ESP_ERR_INVALID_ARG));
        return;
    }

    if (memcmp(info->mac, CONFIG_CSI_SEND_MAC, 6)) {
        return;
    }

    /* [개선] RF 레벨에서 실제 캡처된 CSI 개수를 카운트 (TCP 전송 성공 여부와 무관) */
    s_csi_capture_count++;

    const wifi_pkt_rx_ctrl_t *rx_ctrl = &info->rx_ctrl;
    static int s_count = 0;
    float compensate_gain = 1.0f;
    static uint8_t agc_gain = 0;
    static int8_t fft_gain = 0;
#if CONFIG_GAIN_CONTROL
    static uint8_t agc_gain_baseline = 0;
    static int8_t fft_gain_baseline = 0;
    static int64_t s_last_gain_log_time = 0;

    esp_csi_gain_ctrl_get_rx_gain(rx_ctrl, &agc_gain, &fft_gain);
    if (s_count < 100) {
        esp_csi_gain_ctrl_record_rx_gain(agc_gain, fft_gain);
    } else if (s_count == 100) {
        esp_csi_gain_ctrl_get_rx_gain_baseline(&agc_gain_baseline, &fft_gain_baseline);
#if CONFIG_FORCE_GAIN
        esp_csi_gain_ctrl_set_rx_force_gain(agc_gain_baseline, fft_gain_baseline);
        ESP_LOGD(TAG, "fft_force %d, agc_force %d", fft_gain_baseline, agc_gain_baseline);
#endif
    }
    esp_csi_gain_ctrl_get_gain_compensation(&compensate_gain, agc_gain, fft_gain);

    /*
     * [개선 핵심] 기존 코드는 이 ESP_LOGI가 매 패킷마다(=WiFi 드라이버
     * 콜백 컨텍스트에서 매번) 실행됐다. CSI 콜백 안에서 UART 로그처럼
     * 느린 동기 작업을 매번 하면 콜백이 밀리면서 드라이버가 다음
     * CSI 이벤트를 이 콜백으로 넘기지 못하고 놓칠 수 있다. 즉 로그
     * 자체가 PPS를 깎아먹는 원인이 될 수 있으므로, 5초에 한 번만
     * 출력하도록 rate-limit한다.
     */
    int64_t now_us = esp_timer_get_time();
    if (now_us - s_last_gain_log_time >= STATS_INTERVAL_US) {
        ESP_LOGI(TAG, "compensate_gain %f, agc_gain %d, fft_gain %d", compensate_gain, agc_gain, fft_gain);
        s_last_gain_log_time = now_us;
    }
#endif

    if (info->payload == NULL) {
    return;
}

uint32_t rx_id = 0;

memcpy(
    &rx_id,
    info->payload + 15,
    sizeof(rx_id)
);

queue_csi_for_tcp(info, rx_id);
    s_count++;
}

static void wifi_csi_init()
{
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));

    /**< default config */
#if CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C61
    wifi_csi_config_t csi_config = {
        .enable                   = true,
        .acquire_csi_legacy       = false,
        .acquire_csi_force_lltf   = CSI_FORCE_LLTF,
        .acquire_csi_ht20         = true,
        .acquire_csi_ht40         = true,
        .acquire_csi_vht          = false,
        .acquire_csi_su           = false,
        .acquire_csi_mu           = false,
        .acquire_csi_dcm          = false,
        .acquire_csi_beamformed   = false,
        .acquire_csi_he_stbc_mode = 2,
        .val_scale_cfg            = 0,
        .dump_ack_en              = false,
        .reserved                 = false
    };
#elif CONFIG_IDF_TARGET_ESP32C6
    wifi_csi_config_t csi_config = {
        .enable                 = true,
        .acquire_csi_legacy     = false,
        .acquire_csi_ht20       = true,
        .acquire_csi_ht40       = true,
        .acquire_csi_su         = true,
        .acquire_csi_mu         = true,
        .acquire_csi_dcm        = true,
        .acquire_csi_beamformed = true,
        .acquire_csi_he_stbc    = 2,
        .val_scale_cfg          = false,
        .dump_ack_en            = false,
        .reserved               = false
    };
#else
    wifi_csi_config_t csi_config = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = true,
        .manu_scale        = false,
        .shift             = false,
    };
#endif
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

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

    /*
    * CSI callback → TCP sender 사이의 Queue 생성
    */
s_csi_tcp_queue = xQueueCreate(
    CSI_TCP_QUEUE_DEPTH,
    sizeof(csi_tcp_packet_t)
);

if (s_csi_tcp_queue == NULL) {
    ESP_LOGE(
        TAG,
        "Failed to create CSI TCP queue"
    );

    abort();
}

/*
 * TCP sender는 CSI callback과 별도 FreeRTOS task에서 실행
 */
BaseType_t task_result = xTaskCreate(
    tcp_sender_task,
    "tcp_sender",
    8192,
    NULL,
    5,
    NULL
);

if (task_result != pdPASS) {
    ESP_LOGE(
        TAG,
        "Failed to create TCP sender task"
    );

    abort();
}

/*
 * [개선] 채널 드리프트 / RSSI 모니터링 task
 */
BaseType_t channel_monitor_result = xTaskCreate(
    channel_monitor_task,
    "channel_monitor",
    3072,
    NULL,
    3,
    NULL
);

if (channel_monitor_result != pdPASS) {
    ESP_LOGW(
        TAG,
        "Failed to create channel monitor task"
    );
}

    /**
     * @brief Initialize ESP-NOW
     *        ESP-NOW protocol see: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_now.html
     */

    esp_now_peer_info_t peer = {
        .channel = 0,
        .ifidx     = WIFI_IF_STA,
        .encrypt   = false,
        .peer_addr = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
    };

    wifi_esp_now_init(peer);

    wifi_csi_init();
}
