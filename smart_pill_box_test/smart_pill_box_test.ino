// ================================================================
//  智慧藥盒 — 完整整合程式 v2.2（待機全滅 + Django 排程精準控制）
// ================================================================

#include <WiFi.h>
#include <PubSubClient.h>

// ── WiFi、MQTT 與裝置設定 ────────────────────────────────────────
const char* WIFI_SSID   = "";   // wifi名稱
const char* WIFI_PASS   = "";   // wifi密碼
const char* BROKER_IP   = "";   // 電腦ip
const int   BROKER_PORT = 1883;

const char* DEVICE_ID   = "pillbox-01";
const char* USER_NAME   = "王阿公";

// ── 接腳定義 ─────────────────────────────────────────────────────
#define REED_AM    18   // 幹簧管 早格
#define REED_NOON  19   // 幹簧管 中格
#define REED_PM    21   // 幹簧管 晚格
#define PIR_PIN    22   // PIR 人體感測
#define LED_AM     13   // LED 早格（外串 470Ω）
#define LED_NOON   14   // LED 中格（外串 470Ω）
#define LED_PM     27   // LED 晚格（外串 470Ω）
#define BUZZER     26   // 有源蜂鳴器

// ── 時間參數（毫秒） ─────────────────────────────────────────────
#define BUZZ_ON_MS      150   // 每次蜂鳴長度
#define BUZZ_OFF_MS    1200   // 蜂鳴間隔
#define PIR_COOL_MS   12000   // PIR 冷卻時間
#define OPEN_MIN_MS    1000   // 開蓋至少 1 秒才算取藥
#define HEARTBEAT_MS  60000   // 每 60 秒回報裝置在線心跳

// ── MQTT Topic ───────────────────────────────────────────────────
#define TOPIC_EVENT     "pillbox/pillbox-01/event"
#define TOPIC_PIR       "pillbox/pillbox-01/pir"
#define TOPIC_CARE      "pillbox/pillbox-01/care"
#define TOPIC_HEARTBEAT "pillbox/pillbox-01/heartbeat"
#define TOPIC_CMD       "pillbox/pillbox-01/cmd"

// ── 格子資料結構 ─────────────────────────────────────────────────
struct Slot {
  const int   slotNum;      // 1=早, 2=中, 3=晚
  const int   reedPin;
  const int   ledPin;
  const char* name;
  const char* mqttName;
  bool   isAlerting;        // 是否正在提醒（由 Django remind 指令觸發）
  bool   isOpen;            // 目前蓋子狀態
  unsigned long openTime;   // 本次開蓋時間
};

// 預設全部待機（isAlerting = false），只有收到 Django 指令才亮燈蜂鳴
Slot slots[3] = {
  {1, REED_AM,   LED_AM,   "早", "morning", false, false, 0},
  {2, REED_NOON, LED_NOON, "中", "noon",    false, false, 0},
  {3, REED_PM,   LED_PM,   "晚", "evening", false, false, 0},
};

bool          lastPIR         = false;
unsigned long lastPIRTime     = 0;
unsigned long lastHeartbeatMs = 0;
bool          buzzActive      = false;
unsigned long lastBuzzTime    = 0;

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// ================================================================
//  解析 JSON 中的 "slot" 數值（1 ~ 3）
// ================================================================
int extractSlotFromJson(const String& msg) {
  int idx = msg.indexOf("\"slot\"");
  if (idx < 0) return 0;
  int colon = msg.indexOf(':', idx);
  if (colon < 0) return 0;
  String sub = msg.substring(colon + 1);
  sub.trim();
  return sub.toInt();
}

// ================================================================
//  MQTT 收到 Django 後端控制指令
// ================================================================
void onMqttMessage(char* topic, byte* payload, unsigned int len) {
  String msg;
  msg.reserve(len + 1);
  for (unsigned int i = 0; i < len; i++) {
    msg += (char)payload[i];
  }
  Serial.printf("[MQTT收到] %s → %s\n", topic, msg.c_str());

  int slotNum = extractSlotFromJson(msg);
  if (slotNum < 1 || slotNum > 3) {
    Serial.println("[警告] 指令未包含有效的 slot (1~3)");
    return;
  }

  Slot& s = slots[slotNum - 1];

  if (msg.indexOf("\"remind\"") >= 0) {
    s.isAlerting = true;
    digitalWrite(s.ledPin, HIGH);
    Serial.printf(">>> [Django提醒] 啟動「%s格」(slot=%d) 亮燈與蜂鳴\n", s.name, slotNum);
  } else if (msg.indexOf("\"ack\"") >= 0) {
    s.isAlerting = false;
    digitalWrite(s.ledPin, LOW);
    Serial.printf(">>> [Django確認] 關閉「%s格」(slot=%d) 亮燈與蜂鳴\n", s.name, slotNum);
  }
}

// ================================================================
//  發布 MQTT 訊息
// ================================================================
void mqttPublish(const char* topic, const String& json) {
  if (mqtt.connected()) {
    bool ok = mqtt.publish(topic, json.c_str());
    Serial.printf("[MQTT發布] %s → %s (%s)\n", topic, json.c_str(), ok ? "OK" : "FAIL");
  } else {
    Serial.println("[MQTT] 未連線，訊息未發出");
  }
}

void publishHeartbeat() {
  String json = String("{\"device_id\":\"") + DEVICE_ID
                + "\",\"event_type\":\"heartbeat\"}";
  mqttPublish(TOPIC_HEARTBEAT, json);
}

// ================================================================
//  WiFi 與 MQTT 連線
// ================================================================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("[WiFi] 連線中");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 20) {
    delay(500);
    Serial.print(".");
    retry++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] 連線成功，IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WiFi] 連線失敗，繼續離線運作");
  }
}

void connectMQTT() {
  if (mqtt.connected()) return;
  Serial.print("[MQTT] 連線中...");
  String clientId = String("pillbox_esp32_") + DEVICE_ID;
  if (mqtt.connect(clientId.c_str())) {
    mqtt.subscribe(TOPIC_CMD, 1);
    Serial.printf("成功！已訂閱 %s\n", TOPIC_CMD);
    publishHeartbeat();
  } else {
    Serial.printf("失敗（rc=%d），稍後重試\n", mqtt.state());
  }
}

// ================================================================
//  開機自我測試（測試完畢後全部熄燈待機）
// ================================================================
void selfTest() {
  Serial.println("\n==============================");
  Serial.println("  開機自我測試");
  Serial.println("==============================");

  for (int i = 0; i < 3; i++) {
    digitalWrite(slots[i].ledPin, HIGH);
    delay(300);
    digitalWrite(slots[i].ledPin, LOW);
    delay(150);
  }

  for (int i = 0; i < 2; i++) {
    digitalWrite(BUZZER, HIGH); delay(120);
    digitalWrite(BUZZER, LOW);  delay(150);
  }

  for (int i = 0; i < 3; i++) {
    Serial.printf("  %s格幹簧管 → %s\n",
      slots[i].name,
      digitalRead(slots[i].reedPin) == LOW ? "關閉（磁鐵靠近中）" : "開啟（磁鐵未靠近）");
    digitalWrite(slots[i].ledPin, LOW); // 確保待機全滅
  }
  Serial.println("  自我測試完成，三格待機熄燈中\n");
}

// ================================================================
//  蜂鳴器非阻塞間歇蜂鳴
// ================================================================
void updateBuzzer(bool shouldBuzz) {
  unsigned long now = millis();
  if (!shouldBuzz) {
    if (buzzActive) {
      digitalWrite(BUZZER, LOW);
      buzzActive = false;
    }
    return;
  }
  if (!buzzActive && now - lastBuzzTime >= BUZZ_OFF_MS) {
    digitalWrite(BUZZER, HIGH);
    buzzActive   = true;
    lastBuzzTime = now;
  } else if (buzzActive && now - lastBuzzTime >= BUZZ_ON_MS) {
    digitalWrite(BUZZER, LOW);
    buzzActive   = false;
    lastBuzzTime = now;
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  for (int i = 0; i < 3; i++) {
    pinMode(slots[i].reedPin, INPUT_PULLUP);
    pinMode(slots[i].ledPin,  OUTPUT);
    digitalWrite(slots[i].ledPin, LOW);
  }
  pinMode(PIR_PIN, INPUT);
  pinMode(BUZZER,  OUTPUT);
  digitalWrite(BUZZER, LOW);

  selfTest();

  connectWiFi();
  mqtt.setServer(BROKER_IP, BROKER_PORT);
  mqtt.setBufferSize(512);
  mqtt.setCallback(onMqttMessage);
  connectMQTT();
}

void loop() {
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqtt.connected()) connectMQTT();
    mqtt.loop();
  }

  bool anyAlert = false;

  for (int i = 0; i < 3; i++) {
    Slot& s   = slots[i];
    bool open = (digitalRead(s.reedPin) == HIGH);

    // ▸ 剛開蓋
    if (open && !s.isOpen) {
      s.isOpen   = true;
      s.openTime = now;
      Serial.printf("[%s格] 蓋子開啟\n", s.name);
    }

    // ▸ 剛蓋回去
    if (!open && s.isOpen) {
      s.isOpen = false;

      if (now - s.openTime >= OPEN_MIN_MS) {
        s.isAlerting = false;
        digitalWrite(s.ledPin, LOW);
        Serial.printf("[%s格] ✓ 開蓋取藥完成，LED 熄滅\n", s.name);

        String json = String("{\"device_id\":\"") + DEVICE_ID
                      + "\",\"user_name\":\"" + USER_NAME
                      + "\",\"event_type\":\"opened\""
                      + ",\"slot\":" + String(s.slotNum)
                      + ",\"compartment\":\"" + s.mqttName
                      + "\",\"status\":\"taken\"}";
        mqttPublish(TOPIC_EVENT, json);

        digitalWrite(BUZZER, HIGH); delay(80); digitalWrite(BUZZER, LOW);
      } else {
        Serial.printf("[%s格] 蓋回（未達 1 秒，不計入取藥）\n", s.name);
      }
    }

    // ▸ 依 Django 提醒狀態控制該格 LED 與蜂鳴
    if (s.isAlerting) {
      digitalWrite(s.ledPin, HIGH);
      anyAlert = true;
    } else {
      digitalWrite(s.ledPin, LOW);
    }
  }

  updateBuzzer(anyAlert);

// ── PIR 人體感測 ────────────────────────────────────────────
  bool pirNow = (digitalRead(PIR_PIN) == HIGH);

  if (pirNow && !lastPIR && (now - lastPIRTime >= PIR_COOL_MS)) {
    lastPIRTime = now;
    Serial.println("[PIR] 偵測到有人靠近");

    String untakenList = "";
    for (int i = 0; i < 3; i++) {
      if (slots[i].isAlerting) untakenList += String(slots[i].name) + "格 ";
    }

    String msg = untakenList.length() > 0
                 ? String("有人在附近，") + untakenList + "尚未服藥"
                 : "有人在附近，目前無待服藥提醒";

    String json = String("{\"device_id\":\"") + DEVICE_ID
                  + "\",\"user_name\":\"" + USER_NAME
                  + "\",\"event\":\"pir\",\"status\":\"" + msg + "\"}";
    mqttPublish(TOPIC_PIR, json);

    if (untakenList.length() > 0) {
      Serial.printf("[Agent主動問候] 「您好！%s尚未服藥，請記得吃藥喔～」\n", untakenList.c_str());
    } else {
      Serial.println("[Agent主動問候] 「您好，目前沒有待服用的藥物，辛苦了！」");
    }
  }
  lastPIR = pirNow;

  // ── 定期發送心跳 ────────────────────────────────────────────
  if (now - lastHeartbeatMs >= HEARTBEAT_MS) {
    lastHeartbeatMs = now;
    publishHeartbeat();
  }

  delay(80);
}