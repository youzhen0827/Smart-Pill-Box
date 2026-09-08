# 早／中／晚三格與 Android 連線檢查

## 已改成三格

Django 後端統一使用：

- `slot=1`：早
- `slot=2`：中
- `slot=3`：晚

API 回傳會同時包含：

```json
{
  "slot": 1,
  "slot_label": "早"
}
```

Android 端顯示會優先用 `slot_label`，所以兩邊會同步顯示早／中／晚。

## 與 Android App 連線

Android 模擬器連 Django 本機請填：

```text
http://10.0.2.2:8000/api/v1/
```

Django 建議這樣啟動，模擬器與手機都比較容易連到：

```bash
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

若用實體手機，Android App 的 API Base URL 要改成電腦區網 IP：

```text
http://電腦區網IP:8000/api/v1/
```

## 改格子後已同步檢查

- `MedicationSchedule.slot`：只允許 1～3
- `Reminder.slot`：只允許 1～3
- `SensorEvent.slot`：只允許 1～3
- API `/api/v1/reminders/`：建立與查詢都回傳 `slot_label`
- API `/api/v1/schedules/`：建立與查詢都回傳 `slot_label`
- API `/api/v1/sensors/events/`：只接受 1～3，回傳事件的 `slot_label`
- Web 表單選單：早／中／晚
- Dashboard 感測狀態：早／中／晚三格
- Raspberry Pi `.env.rpi.example`：只剩 `1:5,2:6,3:13`
