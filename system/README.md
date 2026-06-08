# REQ-Plant GUI

論文介面設計的單頁 Web 工作台：文件庫、會議討論區、需求規格書區、系統模型區。

## 啟動

```bash
# 終端 1：後端 API
cd /path/to/Plant
uvicorn server.app:app --reload --port 8000

# 終端 2：前端
cd system
npm install
npm run dev
```

瀏覽器開啟 http://localhost:3000

## 功能

- 多專案建立 / 切換 / 刪除
- 文件庫：外部上傳、產出物列表、編輯、附上文件
- 會議區：啟動 run、SSE 即時日誌轉對話、人類決策、停止
- 規格書：草稿 / SRS / 設計緣由，大綱導覽
- 模型：PlantUML + PNG 雙欄預覽

## 建置

```bash
npm run build
npm run preview
```

## 手動煙霧測試

啟動後端與前端，依序確認：

1. **建立專案** — 會議區工具列點「新建」，輸入 rough idea，專案出現在下拉選單
2. **上傳參考文件** — 左側參考文件區上傳 `.pdf` / `.md` 等檔案，列表顯示檔名
3. **啟動工作坊** — 中央輸入想法後按「開始」，Header 管線狀態與對話串有更新
4. **預覽產出物** — 右側產出物下拉可選 SRS、草稿或模型；模型同時有 PNG 與 PlantUML 時可切換圖表／原始碼
5. **設定面板** — Header「設定」可開啟 stage 開關，儲存後寫入 `config.json`（不會在每次 run 自動儲存）
6. **刪除專案** — 工具列垃圾桶（無執行中任務時）刪除後自動切換至其他專案
