# 早／中／晚三格與 Django 連線檢查

## 已改成三格

Android 端所有藥盒格位選單與今日狀態只保留：

- 1 = 早
- 2 = 中
- 3 = 晚

App 送給 Django 的 JSON 仍使用 `slot` 數字，Django 回傳時另外提供 `slot_label`，App 會優先顯示 `slot_label`。

## 與 Django 第二個 App 連線

模擬器連本機 Django：

```text
http://10.0.2.2:8000/api/v1/
```

實體手機連電腦 Django：

```text
http://電腦區網IP:8000/api/v1/
```

Django 端請用：

```bash
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

App 的「連線設定」請確認：

- API Base URL 指向 `/api/v1/`
- API Token 與 Django `.env` 的 `DEVICE_API_TOKEN` 一致
- 預設長輩姓名要和 Django 使用者姓名綁定一致，例如：王阿公
- 裝置 ID 預設為 `pillbox-01`

## 改格子後需要一起檢查

- 新增單次提醒：`slot` 只能是 1、2、3
- 固定排程：`slot` 只能是 1、2、3
- 感測器測試：spinner 只會送出早／中／晚
- 今日三格狀態：只顯示早、中、晚三格
- 排程與提醒列表：顯示早／中／晚，不再顯示第 4～7 格
