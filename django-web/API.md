# Smart Medicine Box API v1

Base URL：

```text
http://<django-host>:8000/api/v1/
```

除 `health/` 外，請帶：

```http
X-Device-Token: <DEVICE_API_TOKEN>
Content-Type: application/json
```

## 健康檢查

```http
GET /api/v1/health/
```

## 今日提醒

```http
GET /api/v1/reminders/?user_name=王阿公&date=2026-07-10
```

回應：

```json
{
  "results": [
    {
      "id": 12,
      "user_name": "王阿公",
      "medicine_name": "降血壓藥",
      "scheduled_datetime": "2026-07-10T08:00:00+08:00",
      "dose_count": "1",
      "slot": 1,
      "slot_label": "早",
      "device_id": "pillbox-01",
      "status": "已提醒",
      "agent_state": "waiting_sensor"
    }
  ]
}
```

## Android 新增單次提醒

```http
POST /api/v1/reminders/
```

```json
{
  "user_name": "王阿公",
  "user_age": "72",
  "medicine_name": "metformin",
  "scheduled_datetime": "2026-07-10T18:30:00+08:00",
  "scheduled_time": "06:30 PM",
  "dose_count": "1",
  "reminder_hint": "飯後服用",
  "slot": 2,
  "device_id": "pillbox-01"
}
```

## 確認已服藥

```http
POST /api/v1/reminders/12/taken/
```

## 刪除提醒

```http
POST /api/v1/reminders/12/delete/
```

## 感測器事件

```http
POST /api/v1/sensors/events/
```

```json
{
  "device_id": "pillbox-01",
  "user_name": "王阿公",
  "slot": 2,
  "event_type": "opened",
  "detected_at": "2026-07-10T18:31:12+08:00",
  "source": "raspberry_pi_gpio"
}
```

`event_type` 可為：

```text
opened
closed
heartbeat
```

`slot` 限制為 1=早、2=中、3=晚；`opened` 會配對時間最接近、裝置與格位相符的未完成任務。

## QA 醫療衛教

```http
POST /api/v1/qa/ask/
```

```json
{
  "user_name": "王阿公",
  "drug_name": "metformin",
  "question": "為什麼要吃這顆藥？有什麼需要注意？",
  "language": "zh-TW",
  "auto_sync": true
}
```

當本機知識庫沒有資料且 `auto_sync=true` 時，後端會嘗試從 openFDA 即時同步真實資料，再重新檢索；同步失敗時會明確回報，不會建立替代假資料。

回應包含：

```text
answer
translated
auto_synced
sync_message
evidence[]
```

每個 evidence 包含文件 ID、來源類型、source_id、藥名、NDC、檢索區段與 source_url。

## Agent 語音介入輪詢

```http
GET /api/v1/agent/interventions/?device_id=pillbox-01&user_name=王阿公&state=created
```

Raspberry Pi 朗讀後更新：

```http
POST /api/v1/agent/interventions/31/state/
```

```json
{
  "state": "delivered"
}
```

允許狀態：`created`、`delivered`、`acknowledged`、`closed`。

## 本機藥物文件搜尋

```http
GET /api/v1/drugs/?q=metformin
```
