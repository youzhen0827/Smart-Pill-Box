# Raspberry Pi：感測器、免費本機 STT、免費本機 TTS

本資料夾不使用 OpenAI Whisper API、Google Cloud TTS 或其他付費 API：

- **STT**：`faster-whisper` 在 Raspberry Pi／本機執行。
- **TTS**：優先使用自行安裝的 Piper 語音模型；未設定時使用 `espeak-ng`。
- **藥物 QA**：只把辨識後文字送到本專案 Django API；Django 從已匯入的 FDA／Kaggle 真實資料檢索。
- **感測器**：`gpiozero` 監看早／中／晚三格藥盒開關並 POST 真實事件。

## 1. 安裝

```bash
sudo apt update
sudo apt install -y python3-venv alsa-utils espeak-ng libopenblas0
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-rpi.txt
```

`faster-whisper` 第一次用模型名稱（例如 `small`）時會下載免費模型。也可先下載模型後，將 `WHISPER_MODEL` 指向本機資料夾，完全離線執行。

## 2. 設定

複製 `.env.rpi.example` 的值到 shell 或 systemd `EnvironmentFile`。`SMARTPILL_API_URL` 必須是 Raspberry Pi 可連到的 Django 位址，不可使用 Android 模擬器專用的 `10.0.2.2`。

## 3. 早／中／晚三格藥盒感測器

```bash
export SMARTPILL_API_URL=http://192.168.1.100:8000/api/v1/
export SMARTPILL_DEVICE_TOKEN=請與Django的DEVICE_API_TOKEN相同
python sensor_client.py
```

預設腳位格式：

```text
SLOT_PINS=1:5,2:6,3:13
```

左邊是時段（1=早、2=中、3=晚），右邊是 BCM GPIO。實際接線不同時必須修改。先用下列命令驗證 API，不會假裝成正式資料；事件原始 payload 會標記 `manual_test`：

```bash
python sensor_client.py --simulate-slot 1
```

## 4. 語音問藥

```bash
python voice_qa.py --drug acetaminophen --user-name 王阿公
```

流程：ALSA 錄音 → 本機 faster-whisper → Django `/api/v1/qa/ask/` → FDA/Kaggle RAG → 本機 TTS。

也可跳過錄音測試：

```bash
python voice_qa.py \
  --drug metformin \
  --question "為什麼要吃這顆藥？有什麼需要注意？"
```

## 5. 朗讀狀態 Agent 介入

Docker 的 `agent` 容器會建立「到時提醒／未開盒／漏服」介入事件。Raspberry Pi 輪詢並朗讀：

```bash
python intervention_speaker.py --device-id pillbox-01 --user-name 王阿公
```

朗讀完成後，程式會把介入狀態更新為 `delivered`，避免重複播放。

## 台語說明

本專案預設提供淺顯繁體中文朗讀，符合「台語或淺顯易懂語音」中的後者。若要真正的台語語音，可另外安裝合法授權的本機 Piper 台語模型，並把 `PIPER_MODEL` 指向 `.onnx` 模型；程式不依賴付費 TTS。
