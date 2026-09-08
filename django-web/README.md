# smart_medicine_box_Django_re_1

智慧藥盒 Django 雲端端，已整合：

- Android REST API
- 週期服藥排程與狀態追蹤 Agent
- Raspberry Pi 早／中／晚三格藥盒開關感測事件
- 真實 FDA NDC Directory／Drug Label 資料同步
- 使用者自行從 Kaggle 下載之真實 CSV 匯入與來源追溯
- 以真實資料文件為證據的 RAG 醫療衛教 QA
- 免費／本機語音流程：faster-whisper + Piper 或 eSpeak NG
- Week12 形式的 Docker Compose 多容器架構：MySQL、migrate、Django web、Agent

> 系統不內建或自動生成假藥物資料。新資料庫一開始是空的，必須由網站連線 openFDA，或由使用者上傳實際從 Kaggle 下載的 CSV。

## 1. 本機啟動（Conda）

```bat
conda activate venv_312
cd smart_medicine_box_Django_re_1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

另開一個已啟用相同 Conda 環境的終端機，啟動狀態 Agent：

```bat
conda activate venv_312
cd smart_medicine_box_Django_re_1
python manage.py run_medication_agent
```

網站：`http://127.0.0.1:8000/`

Android 模擬器預設 API：`http://10.0.2.2:8000/api/v1/`

實體 Android 手機與 Raspberry Pi 必須改用電腦區域網路 IP，例如：`http://192.168.1.100:8000/api/v1/`。

## 2. Docker Compose（依 Week12 多容器模式）

Windows CMD：

```bat
copy .env.example .env
```

編輯 `.env`，至少更換：

```text
DJANGO_SECRET_KEY
DB_PASSWORD
DB_ROOT_PASSWORD
DEVICE_API_TOKEN
```

啟動：

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f web agent
```

建立管理帳號：

```bash
docker compose exec web python manage.py createsuperuser
```

直接從 FDA 官方 API 匯入一小批真實資料（選用 profile，不會建立 seed 假資料）：

```bash
docker compose --profile dataset run --rm dataset-sync
```

此服務會即時查詢 `acetaminophen`、`metformin`、`amoxicillin`。也可改用網站表單或 `sync_openfda` 指令指定其他藥物。

停止但保留 MySQL 資料：

```bash
docker compose down
```

連 MySQL volume 一起刪除：

```bash
docker compose down -v
```

Compose 啟動順序：

```text
MySQL healthcheck 通過
        ↓
migrate 一次性容器完成資料表 migration
        ↓
Django web 啟動時 collectstatic + Gunicorn
        ＋
medication agent 常駐執行
```

## 3. 選用免費自架英翻中

QA 不依賴付費翻譯 API。未啟用翻譯時，FDA 英文證據會保留原文；啟用 LibreTranslate overlay 後，在本機容器翻譯：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.translation.yml \
  up --build -d
```

第一次啟動翻譯容器需要下載語言模型，時間與記憶體用量會較高。

## 4. 真實資料集如何進入網站

登入後開啟「FDA 資料集」。

### A. openFDA 即時同步

輸入英文學名、品牌名或 Product NDC，例如：

```text
acetaminophen
metformin
50580-506
```

系統同時查詢：

- FDA NDC Directory：產品、品牌、學名、製造商、劑型、給藥途徑、Product NDC
- FDA Drug Label：用途、適應症、副作用、警告、藥物交互作用

也可使用命令：

```bash
python manage.py sync_openfda --drug acetaminophen --drug metformin --limit 10
```

openFDA API key 為選填；本專案不要求付費 key。

### B. Kaggle 真實 CSV

1. 由 Kaggle 實際資料集頁面下載 CSV。
2. 在網站填入該資料集頁面網址。
3. 上傳 CSV。
4. 系統驗證來源網域為 `kaggle.com`，保存原始列、檔名、列號與來源網址。

網站已列出三個可採用的真實資料集頁面：

```text
https://www.kaggle.com/datasets/shudhanshusingh/250k-medicines-usage-side-effects-and-substitutes
https://www.kaggle.com/datasets/jithinanievarghese/drugs-side-effects-and-medical-condition
https://www.kaggle.com/datasets/mghobashy/drug-drug-interactions
```

支援常見欄名，例如：

```text
drug_name / Drug Name / generic_name
brand_name / Brand Names
side_effects / Side Effects / adverse_reactions
drug_interactions / Drug Interactions
medical_condition / Medical Condition / indications
warnings / contraindications
sideEffect0 ... sideEffectN
use0 ... useN
Drug 1 / Drug 2 / Interaction
```

對於 250k Medicines 類型的 numbered columns，系統會彙整多個 `sideEffectN` 與 `useN` 欄位；對 DDI 資料則會把 `Drug 1 + Drug 2` 建成可檢索藥物對。CSV 至少要有藥名（或 Drug 1），以及副作用、交互作用、適應症或警告其中一欄；否則拒絕匯入。

## 5. 資料集在系統中的實際用途

```text
真實 openFDA / Kaggle 文件
          ↓
DrugKnowledgeDocument（保留 source_id、source_url、raw_json）
          ↓
RAG 依藥名 + 問題類型檢索相關區段
          ↓
只整理檢索證據；不補寫未出現在資料中的藥效或副作用
          ↓
網站 / Android / Raspberry Pi 顯示或朗讀
```

網站每筆文件均可開啟詳細頁，核對原始來源、同步時間、NDC、製造商、RAG 欄位及原始 JSON／CSV 列。

## 6. 狀態追蹤 Agent

每一筆週期排程包含：

- 長輩
- 藥物
- 早／中／晚三格藥盒格位
- 星期與服藥時間
- 感測器等待分鐘
- 漏服判定分鐘
- 裝置 ID

狀態機：

```text
pending
  └─ 到服藥時間 → 建立 initial_reminder
                    ↓
              waiting_sensor
                    ├─ 收到相同裝置／格位 opened → taken
                    └─ 超過 grace_minutes → sensor_missing → intervened
                                                  └─ 超過 missed_after_minutes → missed
```

Docker 的 `agent` 服務持續執行；本機開發也可手動執行一次：

```bash
python manage.py run_medication_agent --once
```

## 7. Raspberry Pi

完整程式與安裝說明在：

```text
raspberry_pi/
├── sensor_client.py
├── intervention_speaker.py
├── voice_qa.py
├── common.py
└── README.md
```

語音流程完全不使用付費 API：

```text
麥克風 → 本機 faster-whisper STT
      → Django QA API
      → 真實 FDA/Kaggle RAG
      → 本機 Piper 或 eSpeak NG TTS
```

## 8. API 驗證

除 health 以外，裝置 API 預設要求：

```http
X-Device-Token: smartpill-dev-token
```

此值必須與 Django `DEVICE_API_TOKEN` 相同。正式部署不得保留預設 token。

API 詳細格式請見 [`API.md`](API.md)。

## 9. 測試

```bash
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

## 10. 醫療安全界線

QA 只做研究與衛教展示，不提供診斷、處方、劑量調整或停藥決策。FDA/openFDA 與 Kaggle 資料仍可能有缺漏、版本差異或不適用於特定病人；個別用藥必須由醫師或藥師判斷。
