# 早／中／晚三格修改確認

本版本已把可見 UI、API 驗證、資料模型、感測器程式與 Android 串接都統一為三格：

- slot=1：早
- slot=2：中
- slot=3：晚

## Django 已確認

- `core/slots.py` 是唯一三格標籤來源，`SLOT_COUNT = 3`。
- `core/models.py` 的 `MedicationSchedule`、`Reminder`、`SensorEvent` 都使用三格 choices。
- `core/forms.py` 的下拉選單只顯示「早／中／晚」，不再顯示多格版或 1–7 格。
- `core/views.py` 的 `_parse_slot()` 只接受 1、2、3。
- `dashboard.html` 右側監控中心以三格 `slot_payload()` 產生三張卡片，畫面標題為「早／中／晚三格藥盒感測狀態」。
- `/api/v1/health/` 回傳 `slot_count=3` 與 slots 清單，Android 可用來確認後端三格設定。
- `/api/v1/reminders/`、`/api/v1/schedules/` 回傳 `slot_label`，Android 顯示早／中／晚。
- Raspberry Pi `.env.rpi.example` 改為 `SLOT_PINS=1:5,2:6,3:13`。

## 注意

歷史 migration `0007` 仍會保留舊資料表建立歷程；真正套用後由 `0011_three_slot_pillbox.py` 正規化成三格，`0013_strict_three_slot_constraints.py` 再次清理舊資料並加入資料庫限制。請勿只看歷史 migration 判斷目前功能。
