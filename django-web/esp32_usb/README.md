# 照片版 ESP32 三格藥盒：只用 USB 線連線

本資料夾只對應照片中已經存在的硬體：

- ESP32 開發板
- 左、中、右三格既有的磁鐵／感測線路
- 三格既有指示燈
- 既有 PIR 人體感測器
- 板上既有發聲元件
- 照片中的 USB-A 轉 USB-C 線

不需要 Raspberry Pi、外接 Wi-Fi 模組或其他新硬體。ESP32 內建 Wi-Fi 雖然存在，但本版本不使用；USB 線同時負責供電、燒錄及資料傳輸。

## 固定格位

| 實體位置 | API slot | 顯示 |
|---|---:|---|
| 左 | 1 | 早 |
| 中 | 2 | 中 |
| 右 | 3 | 晚 |

## 已確認的 GPIO

依提供的 `smart_pill_box_test.ino`，韌體已填入既有接線：

```text
早格幹簧管 GPIO 18    早格 LED GPIO 13
中格幹簧管 GPIO 19    中格 LED GPIO 14
晚格幹簧管 GPIO 21    晚格 LED GPIO 27
PIR 人體感測 GPIO 22
蜂鳴器 GPIO 26
```

不需改線或增加零件；所有硬體腳位都已依提供的程式與確認資訊填入。

## 1. 安裝軟體

可安裝以下軟體；這些不是新增硬體：

1. Arduino IDE 2.x。
2. Arduino IDE 的「esp32 by Espressif Systems」開發板套件。
3. Python 套件：

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` 已包含 `pyserial`。

## 2. 燒錄 ESP32

1. 用照片中的 USB 線接上電腦與 ESP32。
2. Arduino IDE 開啟 `SmartPillBoxUsb/SmartPillBoxUsb.ino`。
3. 開發板選 `ESP32 Dev Module`，連接埠選偵測到的 `COM` 埠。
4. 上傳，序列監控器設為 `115200`。

正常開機會看到：

```text
HELLO|smartpill-esp32-usb|2
SLOTS|1:left:early|2:middle:noon|3:right:evening
PINS|reed:18,19,21|led:13,14,27|pir:22|buzzer:26
HEARTBEAT
```

## 3. 啟動 Django

```powershell
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

## 4. 啟動 USB 橋接器

先查 ESP32 的連接埠：

```powershell
python esp32_usb/serial_bridge.py --list-ports
```

再啟動橋接；姓名、裝置 ID 與 Android 排程必須完全相同：

```powershell
python esp32_usb/serial_bridge.py --port COM5 --device-id pillbox-01 --user-name 王阿公
```

若 Django 的 `DEVICE_API_TOKEN` 已更換：

```powershell
$env:SMARTPILL_DEVICE_TOKEN='你的 token'
python esp32_usb/serial_bridge.py --port COM5 --device-id pillbox-01 --user-name 王阿公
```

## 5. Android 設定

- 模擬器 API URL：`http://10.0.2.2:8000/api/v1/`
- 實體手機 API URL：`http://電腦區網IP:8000/api/v1/`
- 裝置 ID：`pillbox-01`
- 長輩姓名：必須與橋接器 `--user-name` 相同
- Token：必須與 Django 的 `DEVICE_API_TOKEN` 相同

資料流為：

```text
左／中／右藥格
    ↕ 既有焊線
ESP32
    ↕ 照片中的 USB 線
serial_bridge.py（電腦）
    ↕
Django API
    ↕
Android App
```

開蓋事件會由 Django 自動配對同一 `device_id`、同一格位、時間最近的未完成提醒，並標記為已服藥。PIR 的有人／無人狀態也會經 USB 上傳，但不會誤判成服藥。
