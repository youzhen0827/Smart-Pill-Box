#include <Arduino.h>

// 依硬體測試程式 smart_pill_box_test.ino 的既有接線：
// 左=早(1)、中=中(2)、右=晚(3)，不改線、不增加元件。
constexpr int8_t SENSOR_PINS[3] = {18, 19, 21};
constexpr int8_t LED_PINS[3] = {13, 14, 27};
constexpr int8_t PIR_PIN = 22;
constexpr int8_t BUZZER_PIN = 26;

// 照片中蓋子有磁鐵；一般簧片開關在蓋上時導通、開蓋時斷開。
// 若實測相反，只改成 false，不必改其他程式。
constexpr bool SENSOR_LOW_WHEN_LID_CLOSED = true;
constexpr bool LED_ACTIVE_HIGH = true;
constexpr bool BUZZER_ACTIVE_HIGH = true;

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t DEBOUNCE_MS = 120;
constexpr uint32_t PIR_DEBOUNCE_MS = 120;
constexpr uint32_t HEARTBEAT_MS = 30000;
constexpr uint32_t BUZZER_REPEAT_MS = 10000;
constexpr uint32_t BUZZER_PULSE_MS = 180;

bool lastSampleOpen[3] = {false, false, false};
bool stableOpen[3] = {false, false, false};
uint32_t changedAt[3] = {0, 0, 0};
bool reminderLed[3] = {false, false, false};
bool buzzerRequested = false;
bool buzzerPulsing = false;
uint32_t buzzerChangedAt = 0;
uint32_t lastHeartbeatAt = 0;
bool lastPirSample = false;
bool stablePresence = false;
uint32_t pirChangedAt = 0;
String serialLine;

bool pinConfigured(int8_t pin) {
  return pin >= 0;
}

void writeOutput(int8_t pin, bool on, bool activeHigh) {
  if (!pinConfigured(pin)) return;
  digitalWrite(pin, on == activeHigh ? HIGH : LOW);
}

bool readLidOpen(uint8_t index) {
  const int8_t pin = SENSOR_PINS[index];
  if (!pinConfigured(pin)) return false;
  const bool low = digitalRead(pin) == LOW;
  const bool lidClosed = SENSOR_LOW_WHEN_LID_CLOSED ? low : !low;
  return !lidClosed;
}

void emitEvent(uint8_t index, bool opened) {
  Serial.printf("EVENT|%u|%s\n", index + 1, opened ? "opened" : "closed");
}

void emitPresence(bool detected) {
  Serial.printf("PIR|%s\n", detected ? "detected" : "clear");
}

void applyReminderOutputs() {
  for (uint8_t i = 0; i < 3; ++i) {
    writeOutput(LED_PINS[i], reminderLed[i], LED_ACTIVE_HIGH);
  }
}

void setBuzzer(bool on) {
  writeOutput(BUZZER_PIN, on, BUZZER_ACTIVE_HIGH);
}

void handleStateCommand(const String &line) {
  int led1 = 0;
  int led2 = 0;
  int led3 = 0;
  int buzzer = 0;
  if (sscanf(line.c_str(), "STATE|%d|%d|%d|%d", &led1, &led2, &led3, &buzzer) != 4) {
    Serial.println("ERROR|bad_state_command");
    return;
  }
  reminderLed[0] = led1 != 0;
  reminderLed[1] = led2 != 0;
  reminderLed[2] = led3 != 0;
  buzzerRequested = buzzer != 0;
  applyReminderOutputs();
  if (!buzzerRequested) {
    buzzerPulsing = false;
    setBuzzer(false);
  }
  Serial.println("ACK|STATE");
}

void handleSerialLine(String line) {
  line.trim();
  if (line.startsWith("STATE|")) {
    handleStateCommand(line);
  } else if (line == "PING") {
    Serial.println("PONG");
  } else if (line == "STATUS") {
    Serial.printf(
      "STATUS|%d|%d|%d|%d\n",
      stableOpen[0] ? 1 : 0,
      stableOpen[1] ? 1 : 0,
      stableOpen[2] ? 1 : 0,
      buzzerRequested ? 1 : 0
    );
  } else if (line.length() > 0) {
    Serial.println("ERROR|unknown_command");
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\n') {
      handleSerialLine(serialLine);
      serialLine = "";
    } else if (value != '\r' && serialLine.length() < 120) {
      serialLine += value;
    }
  }
}

void updateSensors() {
  const uint32_t now = millis();
  for (uint8_t i = 0; i < 3; ++i) {
    if (!pinConfigured(SENSOR_PINS[i])) continue;
    const bool sampleOpen = readLidOpen(i);
    if (sampleOpen != lastSampleOpen[i]) {
      lastSampleOpen[i] = sampleOpen;
      changedAt[i] = now;
    }
    if (sampleOpen != stableOpen[i] && now - changedAt[i] >= DEBOUNCE_MS) {
      stableOpen[i] = sampleOpen;
      emitEvent(i, sampleOpen);
    }
  }
}

void updatePir() {
  if (!pinConfigured(PIR_PIN)) return;
  const uint32_t now = millis();
  const bool samplePresence = digitalRead(PIR_PIN) == HIGH;
  if (samplePresence != lastPirSample) {
    lastPirSample = samplePresence;
    pirChangedAt = now;
  }
  if (samplePresence != stablePresence && now - pirChangedAt >= PIR_DEBOUNCE_MS) {
    stablePresence = samplePresence;
    emitPresence(stablePresence);
  }
}

void updateBuzzer() {
  if (!pinConfigured(BUZZER_PIN) || !buzzerRequested) return;
  const uint32_t now = millis();
  if (buzzerPulsing && now - buzzerChangedAt >= BUZZER_PULSE_MS) {
    buzzerPulsing = false;
    buzzerChangedAt = now;
    setBuzzer(false);
  } else if (!buzzerPulsing && now - buzzerChangedAt >= BUZZER_REPEAT_MS) {
    buzzerPulsing = true;
    buzzerChangedAt = now;
    setBuzzer(true);
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  serialLine.reserve(128);

  for (uint8_t i = 0; i < 3; ++i) {
    if (pinConfigured(SENSOR_PINS[i])) {
      pinMode(SENSOR_PINS[i], INPUT_PULLUP);
      stableOpen[i] = readLidOpen(i);
      lastSampleOpen[i] = stableOpen[i];
      changedAt[i] = millis();
    }
    if (pinConfigured(LED_PINS[i])) {
      pinMode(LED_PINS[i], OUTPUT);
      writeOutput(LED_PINS[i], false, LED_ACTIVE_HIGH);
    }
  }
  if (pinConfigured(PIR_PIN)) {
    pinMode(PIR_PIN, INPUT);
    stablePresence = digitalRead(PIR_PIN) == HIGH;
    lastPirSample = stablePresence;
    pirChangedAt = millis();
  }
  if (pinConfigured(BUZZER_PIN)) {
    pinMode(BUZZER_PIN, OUTPUT);
    setBuzzer(false);
  }

  delay(300);
  Serial.println("HELLO|smartpill-esp32-usb|2");
  Serial.println("SLOTS|1:left:early|2:middle:noon|3:right:evening");
  Serial.println("PINS|reed:18,19,21|led:13,14,27|pir:22|buzzer:26");
  if (!pinConfigured(SENSOR_PINS[0]) || !pinConfigured(SENSOR_PINS[1]) || !pinConfigured(SENSOR_PINS[2])) {
    Serial.println("WARNING|sensor_gpio_not_configured");
  }
  Serial.println("HEARTBEAT");
  lastHeartbeatAt = millis();
}

void loop() {
  readSerialCommands();
  updateSensors();
  updatePir();
  updateBuzzer();

  const uint32_t now = millis();
  if (now - lastHeartbeatAt >= HEARTBEAT_MS) {
    Serial.println("HEARTBEAT");
    lastHeartbeatAt = now;
  }
  delay(5);
}
