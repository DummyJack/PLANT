# Plant

## 專案架構

```
Plant/
├── main.py                 # 程式入口點
├── flow.py                 # 流程控制器（Round 1 探索 + Round 2+ 議題式討論）
├── model.py                # LLM 整合層（OpenAI, Ollama）
├── store.py                # I/O 層：JSON / Markdown 讀寫
├── utils.py                # Logger、MoMManager、Collect、AgentSelector
│
├── agents/                 # Agent 基礎設施
│   ├── __init__.py         # 匯出 BaseAgent, AgentRegistry
│   ├── base.py             # BaseAgent：工具、議題回應
│   ├── registry.py         # AgentRegistry：Agent 註冊中心，跨 Agent 諮詢
│   ├── profile/            # Agent 角色實作
│   │   ├── __init__.py
│   │   ├── user.py         # UserAgent：模擬利害關係人（自然口語發言）
│   │   ├── analyst.py      # AnalystAgent：需求衝突分析
│   │   ├── expert.py       # ExpertAgent：拘束性 + 非拘束性專業建議
│   │   ├── mediator.py     # MediatorAgent：會議主持人（議題管理、討論模式、草稿生成）
│   │   ├── modeler.py      # ModelerAgent：系統建模（PlantUML + AST）
│   │   └── documentor.py   # DocumentorAgent：SRS / Design Rationale 生成
│   └── tools/              # 外部工具
│       ├── base.py         # BaseTool 抽象介面
│       └── web_search.py   # WebSearchTool（Tavily API）
│
├── config/
│   ├── config.json         # 系統配置（模型、Agent 開關、能力開關）
│   ├── .env                # API Keys（OPENAI_API_KEY, TAVILY_API_KEY）
│   └── spec.json           # Draft 和 IEEE 29148 模板
│
├── doc/                    # 外部參考文件（RAG 知識來源）
│
└── projects/<id>/          # 專案資料（每個專案獨立目錄）
    ├── artifact/
    │   ├── artifact.json   # 核心中間產物（rough_idea, stakeholders, analyse, reports, feedback）
    │   └── srs.json        # 正式 SRS（JSON）
    ├── output/
    │   ├── report.md       # 衝突報告
    │   ├── spec_N.md       # 需求草稿 Markdown（N = 輪次，含 UML 附錄）
    │   ├── dr.md           # Design Rationale
    │   ├── srs.md          # 正式 SRS Markdown
    │   ├── R*-Spec.md      # Round 1 會議記錄（stages）
    │   ├── *.md            # Round 2+ 各議題會議記錄
    │   └── *.plantuml      # PlantUML 圖表檔案
    └── log/
        └── system.log
```

## Agent 能力

每個 Agent 繼承自 `BaseAgent`，可選啟用以下核心能力：

| 能力                    | 說明                               | 使用的 Agent                                                 |
| ----------------------- | ---------------------------------- | ------------------------------------------------------------ |
| **Tool Use**            | 呼叫外部工具取得資訊或驗證結果     | ExpertAgent（web_search）                                   |
| **Agent Communication** | 透過 Registry 諮詢其他 Agent       | MediatorAgent → Analyst/Expert、DocumentorAgent → Analyst    |
| **Topic Discussion**    | `respond_to_topic()` 議題回應介面  | 全部 Agent（Round 2+ 由 Mediator 調度）                      |

## 執行流程

### 總覽

```
人類輸入 rough_idea
    │
    ▼
Round 1: 探索階段（Stage 1～7）
    ├─ User 建議利害關係人 → 人類選擇 → User 產生需求
    ├─ Analyst 衝突分析 → Mediator 衝突報告 → Expert 建議
    ├─ Mediator 產生需求草稿（spec_1.md）
    └─ Modeler 產生 UML，寫入 spec 附錄
    │
    ▼
Round 2+: 議題式討論
    ├─ Mediator 分析 Spec → 生成議題清單
    ├─ For each 議題: 討論（sequential/simultaneous）→ Mediator 綜合
    ├─ 未解決 → Mediator 篩選方案 → 人類裁決
    ├─ Mediator 更新 Spec
    └─ Modeler 更新 UML
    │
    ▼
最終: DocumentorAgent → dr.md、srs.json、srs.md
```

### Round 1: 探索階段

```
┌─────────────────────────────────────────────────────────────┐
│ Stage 1: UserAgent                                          │
│ ├─ 根據想法建議 5-8 位利害關係人                            │
│ └─ 人類選擇要納入的利害關係人                               │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 2: UserAgent                                          │
│ └─ 模擬各利害關係人，以第一人稱口語方式自然發言             │
│    （涵蓋日常情境、痛點、期望、擔心的事、對其他角色的看法） │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 3: AnalystAgent                                       │
│ ├─ 兩兩配對 + 全體分析利害關係人需求                         │
│ └─ 識別需求衝突（Conflict / Neutral）、萃取候選需求          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 4: MediatorAgent                                       │
│ └─ 產生衝突報告 → report.md                                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 5: ExpertAgent     [Tool Use]                         │
│ ├─ 載入外部文件（doc/）                                     │
│ ├─ 可選 web_search 搜尋法規、標準、最佳實務                  │
│ └─ 提供專家建議（binding 拘束性 + 非拘束性）                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 6: MediatorAgent                                       │
│ └─ 整合中間產物，產生需求草稿 → spec_N.md                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 7: ModelerAgent                                       │
│ ├─ 根據草稿產生 Use Case / Class / Sequence Diagram         │
│ ├─ PlantUML 模型寫入 spec 附錄、輸出 .plantuml 檔            │
│ └─ 更新 artifact["uml"]                                     │
└─────────────────────────────────────────────────────────────┘
```

### Round 2+: 議題式討論

第 2 輪起，Mediator 轉為會議主持人，以議題為單位進行討論：

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: MediatorAgent 分析 Spec → 生成議題清單              │
│ ├─ 議題類型: conflict / requirement_gap / refinement       │
│ └─ 為每個議題決定 discussion_mode、participants、speaking_order │
└─────────────────────────────────────────────────────────────┘
    │
    ▼  For each 議題
┌─────────────────────────────────────────────────────────────┐
│ Step 2a: 討論                                               │
│ ├─ sequential（逐一發言）: 各 Agent 依序發言，              │
│ │   後面的 Agent 能看到前面的內容                            │
│ └─ simultaneous（同時發言）: 各 Agent 獨立作答              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2b: MediatorAgent 綜合結果                             │
│ └─ 判斷: agreed / partial / unresolved                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼  若 unresolved
┌─────────────────────────────────────────────────────────────┐
│ Step 2c: 未達成共識時                                       │
│ ├─ MediatorAgent.prepare_human_options() 篩選方案與折衷     │
│ └─ Collect.human_decision_on_topic() 人類裁決               │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: MediatorAgent 根據討論結果更新 Draft                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: ModelerAgent 根據新 Draft 更新 UML                   │
└─────────────────────────────────────────────────────────────┘
```

### 討論模式

| 模式         | 適用情境                     | 特徵                                     |
| ------------ | ---------------------------- | ---------------------------------------- |
| **sequential** | 爭議性高、需要互相回應的議題 | 按順序發言，後者可看到前者的發言         |
| **simultaneous** | 資訊補充、簡單議題         | 所有人同時獨立發言，看不到彼此           |

### 升級路徑

```
Mediator 綜合 → agreed/partial? ──Yes──→ 記錄決策，下個議題
                  │
                  No (unresolved)
                  ▼
     Mediator 篩選 best_options + compromise → 人類選擇 → 記錄決策
```

### 會議記錄結構

- **Round 1**：MoM 使用 `stages`，輸出合併為 `R{round_num}-Spec.md`
- **Round 2+**：每個議題一筆會議記錄（`meetings`），即時存為獨立 MD；含參與者、發言、決議

## Agent Prompt 設計

### MediatorAgent（會議主持人）

**System Prompt 核心指令：**
- 中立、客觀地主持需求討論會議
- 建立並維護專案目標，確保討論圍繞目標
- 分析需求規格識別議題，決定討論模式
- 綜合各方意見，促成共識

**主要方法：**

| 方法 | 觸發時機 | 說明 |
| --- | --- | --- |
| `generate_draft(artifact)` | Round 1 Stage 6 / Round 2+ Step 3 | 依 artifact 中間產物產生需求草稿 Markdown |
| `generate_topics(spec_md, rough_idea, registry)` | Round 2+ Step 1 | 分析 Spec 產生議題清單（type、discussion_mode、participants） |
| `moderate_sequential(topic, registry)` | 議題討論 | 依 speaking_order 依序呼叫各 Agent 的 `respond_to_topic()` |
| `moderate_simultaneous(topic, registry)` | 議題討論 | 同時呼叫各 Agent 的 `respond_to_topic()` |
| `synthesize_and_resolve(topic, contributions)` | 討論結束 | 綜合發言，判斷 agreed / partial / unresolved |
| `generate_conflict_report(conflict_groups)` | Round 1 Stage 4 | 將衝突分析結果結構化為報告 |
| `prepare_human_options(topic, contributions)` | 議題 unresolved 時 | 篩選 3 個最佳方案 + 1 個折衷方案，供人類裁決 |

### UserAgent（利害關係人模擬）

**System Prompt 核心指令：**
- 模擬不同利害關係人，以第一人稱口語方式自然發言

**Prompt 引導面向（鼓勵豐富發言）：**
1. 日常使用情境：典型的操作流程
2. 痛點與困擾：效率低下、不便之處
3. 期望功能：最重要的功能需求
4. 擔心的事：對系統的顧慮
5. 對其他角色的看法：可能的衝突點
6. 額外想法：補充內容

**輸出格式：** 建議名單 `{"proposed_stakeholders": [{name, reason}]}`；需求 `{"stakeholders": [{id, name, text: []}]}`

### ExpertAgent（領域專家）

**System Prompt 核心指令：**
- 提供兩種建議：**binding（拘束性）** 和 **advisory（非拘束性）**
- Evidence-first：所有建議必須有可查證的來源
- 禁止虛構 URL，無來源必須標註「資訊不足」

**Feedback 輸出格式：**

```json
{
  "id": "FB-01",
  "binding": false,
  "text": ["具體建議1", "建議2"],
  "ref": "來源 URL 或文件名或「資訊不足」"
}
```

**binding 判斷標準：** `true` 僅限法規/安全/技術硬性限制；其餘為 `false`。無外部文件時 ref 填「無外部文件」或「領域常識」，一律 binding=false。

### AnalystAgent（分析師）

**System Prompt 核心指令：**
- 辨識利害關係人需求間的衝突（術語、範圍、數值、行為不一致為 Conflict；一致或無關為 Neutral）
- 兩兩配對 + 全體分析，輸出 label、reason；全體時可萃取 candidates

### ModelerAgent（系統建模）

**System Prompt 核心指令：**
- 根據需求草稿轉換系統模型

### DocumentorAgent（文件撰寫）

**System Prompt 核心指令：**
- 依會議記錄產生 Design Rationale（dr.md）
- 依 spec 與模板產生 SRS（srs.json、srs.md），結構符合 spec 範本

### BaseAgent（議題回應介面）

所有 Agent 繼承的 `respond_to_topic()` 方法：

**輸出格式：** `position`、`arguments`、`suggestions`、`questions_to_others`。子類別可覆寫以提供角色特化回應。

## 配置說明

`config/config.json` 主要設定：

| 設定                                                                         | 說明                  | 預設值                               |
| ---------------------------------------------------------------------------- | --------------------- | ------------------------------------ |
| `provider`                                                                   | LLM 供應商            | `"openai"`（支援 openai, ollama）    |
| `model`                                                                      | 模型名稱              | `"gpt-4o-mini"`                      |
| `temperature`                                                                | 生成溫度              | `0`                                  |
| `rounds`                                                                     | 討論輪數              | `1`                                  |
| `start_round`                                                                | 起始輪次（繼續專案用）| `1`                                  |
| `enable_user` / `analyst` / `expert` / `mediator` / `modeler` / `documentor` | 各 Agent 開關         | `true`                               |
| `enable_web_search`                                                          | Expert 是否啟用網路搜尋 | `true`                             |
| `enable_agent_communication`                                                 | 是否啟用 Registry（跨 Agent 調度） | `true`                      |

## 快速開始

```bash
# 安裝依賴
pip install -r requirements.txt

# 設定 API Keys
cp config/.env.example config/.env
# 編輯 config/.env 填入 OPENAI_API_KEY（必須）和 TAVILY_API_KEY（可選）

# 執行
python main.py
```
