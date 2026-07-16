# PLANT System

## 事前準備

### 1. 確認執行環境

請先安裝：

- Python 3.10 以上版本
- Node.js
- npm

確認環境是否已安裝：

```bash
python --version
node --version
npm --version
```

### 2. 建立 Python 虛擬環境（可選用）

建立虛擬環境：

```bash
python -m venv venv
```

Windows：

```powershell
# PowerShell
.\venv\Scripts\Activate.ps1

# CMD
venv\Scripts\activate.bat

# Git Bash
source venv/Scripts/activate
```

macOS 或 Linux：

```bash
source venv/bin/activate
```

停用虛擬環境：
```
deactivate
```

### 3. 安裝套件

```bash
pip install -r requirements.txt
```

### 4. 建立環境變數檔案

複製專案提供的環境變數範例：

```bash
cp .env.example .env
```

- 只需要設定實際使用的模型 API Key

- `activation_code` 用於開啟網站的編輯與執行權限。沒有設定，網站就只會是唯讀模式

- 已有公開網域，可將 `frontend_host` 改為實際網域名稱，不需要加入 `http://` 或 `https://`，範例：frontend_host=`plant.example.com`

- Tavily API Key 未設定，請在 `config.json` 關閉："enable_tools": {"web_search": false}

> `.env` 為敏感資訊，請勿提交至 Git 或公開分享

### 5. 安裝前端套件

```bash
cd system
npm install
```

## 使用方式

### 方式一：網站

啟動後端：

```bash
# 執行位置：根目錄(PLANT/)
python -m server.run

uvicorn server.app:app --reload
```

- 修改 Python 程式碼後會自動重新啟動

```bash
uvicorn server.app:app
```

- 修改程式碼後不會自動重新啟動，適合正式環境

開啟另一個終端機並啟動前端：

```bash
cd system
npm run dev
```

啟動完成後，使用瀏覽器開啟 `http://127.0.0.1:3000`

### 方式二：CLI

CLI 不需要啟動前端或後端服務，可直接執行：

```bash
python main.py
```

## 系統設定(config.json)

### 基本設定

|                         | 說明                     |
| ----------------------- | ------------------------ |
| `rounds`                | 正式會議的討論回合數     |
| `max_issues`            | 最多處理的需求議題數量   |
| `max_stakeholders`      | 最多分析的利害關係人數量 |
| `elicitation_max_turns` | 需求訪談的最大對話輪數   |
| `human_skip_judge`      | 是否要跳過人工判斷       |

### 功能設定

|                  | 說明                                 |
| ---------------- | ------------------------------------ |
| `stage`          | 控制需要執行的流程階段               |
| `export`         | 控制紀錄、HTML、成本及說明文件等輸出 |
| `enable_tools`   | 控制網路搜尋、檔案讀取等工具         |
| `enable_meeting` | 控制可執行的會議類型                 |
| `enable_agents`  | 控制各 Agent 角色是否啟用            |
| `agent_models`   | 設定各 Agent 使用的模型              |

`true` 表示啟用 | `false` 表示停用

### 模型設定

每個 Agent 可以分別設定模型供應商、模型名稱及溫度：

```json
{
  "analyst": {
    "provider": "openai",
    "model": "gpt-4.1",
    "temperature": 0
  }
}
```

| Provider | 環境變數                                      |
| -------- | --------------------------------------------- |
| `openai` | `OPENAI_API_KEY`                              |
| `gemini` | `GEMINI_API_KEY`                              |
| `claude` | `ANTHROPIC_API_KEY`                           |
| `local`  | `LOCAL_MODEL_BASE_URL`、`LOCAL_MODEL_API_KEY` |

### API 測試狀態

設定主要用於網站上，顯示各模型供應商 API Key 的測試狀態。使用者在網頁中手動測試 API Key 後，系統會更新對應的狀態

`api_state` 記錄各模型 API Key 上一次的測試結果：

```json
{
  "api_state": {
    "openai": "untested",
    "gemini": "untested",
    "claude": "untested"
  }
}
```

- `valid`：上一次測試成功
- `invalid`：上一次測試失敗
- `untested`：尚未測試

## API 文件

文件位置：`server/swagger.yml` 和 `server/swagger.html`

### 安裝套件

```bash
cd system
npm install
```

### 產生或更新 HTML

```bash
# 執行位置：PLANT/system
npm run build:swagger
```
