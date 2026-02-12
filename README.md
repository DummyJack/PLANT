# Plant

## 專案架構

```
Plant/
├── main.py                 # 程式入口點
├── flow.py                 # 流程控制器（Phase 0 + Round 1 探索 + Round 2+ 議題式討論）
├── model.py                # LLM 整合層（OpenAI, Anthropic, Gemini, Ollama）
├── store.py                # I/O 層：JSON / Markdown 讀寫
├── utils.py                # Logger、MoMManager、Collect、AgentSelector
│
├── agents/                 # Agent 基礎設施
│   ├── __init__.py         # 匯出 BaseAgent, Memory, AgentRegistry
│   ├── base.py             # BaseAgent：ReAct 迴圈、工具調度、反思、Agent 溝通、議題回應
│   ├── memory.py           # Memory：短期對話記憶 + 長期跨輪次摘要
│   ├── registry.py         # AgentRegistry：Agent 註冊中心，跨 Agent 諮詢
│   └── tools/              # 外部工具
│       ├── base.py         # BaseTool 抽象介面
│       ├── web_search.py   # WebSearchTool（Tavily API）
│       └── plantuml.py     # PlantUMLValidatorTool（語法驗證）
│
├── team/                   # Agent 角色實作
│   ├── __init__.py
│   ├── user.py             # UserAgent：模擬利害關係人（自然口語發言）
│   ├── analyst.py          # AnalystAgent：需求衝突分析
│   ├── expert.py           # ExpertAgent：拘束性 + 非拘束性專業建議
│   ├── mediator.py         # MediatorAgent：會議主持人（議題管理、討論模式、草稿生成）
│   ├── modeler.py          # ModelerAgent：系統建模（PlantUML + AST）
│   └── documentor.py       # DocumentorAgent：SRS / Design Rationale 生成
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
    │   ├── artifact.json   # 核心中間產物（含 project_goal）
    │   ├── draft_N.json    # 需求草稿（含 UML 模型，N = 輪次）
    │   ├── srs.json        # 正式 SRS
    │   └── mom.json        # 會議記錄（Round 1: stages / Round 2+: meetings）
    ├── output/
    │   ├── report.md       # 衝突報告
    │   ├── draft_N.md      # 需求草稿 Markdown
    │   ├── dr.md           # Design Rationale
    │   ├── srs.md          # 正式 SRS Markdown
    │   ├── mom.md          # 會議記錄 Markdown
    │   └── *.plantuml      # PlantUML 圖表檔案
    └── log/
        └── system.log
```

## Agent 能力

每個 Agent 繼承自 `BaseAgent`，可選啟用以下核心能力：

| 能力                    | 說明                               | 使用的 Agent                                                 |
| ----------------------- | ---------------------------------- | ------------------------------------------------------------ |
| **Tool Use**            | 呼叫外部工具取得資訊或驗證結果     | ExpertAgent（web_search）、ModelerAgent（plantuml_validate） |
| **Memory**              | 短期對話記憶 + 長期跨輪次摘要      | 全部 Agent                                                   |
| **ReAct**               | Think → Act → Observe 多步推理迴圈 | ExpertAgent、ModelerAgent                                    |
| **Reflection**          | 自我評估輸出品質，不合格則重試     | AnalystAgent、ExpertAgent、ModelerAgent、DocumentorAgent     |
| **Agent Communication** | 透過 Registry 諮詢其他 Agent       | MediatorAgent → Analyst/Expert、DocumentorAgent → Analyst    |
| **Topic Discussion**    | `respond_to_topic()` 議題回應介面  | 全部 Agent（Round 2+ 由 Mediator 調度）                      |

## 執行流程

### 總覽

```
人類輸入 rough_idea
    │
    ▼
Phase 0: Mediator 建立專案目標 → 人類確認
    │
    ▼
Round 1: 探索階段（Stage 1-8，現有線性流程）
    │
    ▼
draft_1.json（含 UML）
    │
    ▼
Round 2+: 議題式討論
    ├─ Mediator 分析 Spec → 生成議題清單
    ├─ For each 議題:
    │   ├─ Mediator 決定模式（逐一發言 / 同時發言）
    │   ├─ Agent 們討論
    │   ├─ Mediator 綜合結果
    │   ├─ 未解決 → Expert 拘束性裁決
    │   └─ 仍未解決 → 人類介入
    ├─ Mediator 更新 Draft
    └─ Modeler 更新 UML
    │
    ▼
最終: DocumentorAgent → SRS / Design Rationale
```

### Phase 0: 專案目標建立

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 0: MediatorAgent                                      │
│ ├─ 分析 rough_idea，用一句話描述系統核心目標                │
│ └─ 人類確認（可修改）後存入 artifact["project_goal"]        │
└─────────────────────────────────────────────────────────────┘
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
│ Stage 3: AnalystAgent                  [Reflection]         │
│ ├─ 兩兩配對分析利害關係人需求                               │
│ ├─ 全體分析並萃取候選需求                                   │
│ └─ 識別需求衝突（Conflict / Neutral）                       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 4: MediatorAgent           [Agent Communication]      │
│ ├─ 諮詢 AnalystAgent 取得補充觀點                           │
│ └─ 產生衝突報告 → report.md                                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 5: ExpertAgent     [ReAct + Tool Use + Reflection]    │
│ ├─ 載入外部文件（doc/ 資料夾 RAG）                          │
│ ├─ 使用 web_search 搜尋法規、標準、最佳實務                 │
│ └─ 提供專家建議（含 binding 拘束性 + advisory 非拘束性）    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 6: MediatorAgent           [Agent Communication]      │
│ ├─ 諮詢 ExpertAgent 取得專業建議                            │
│ ├─ 根據衝突報告和專家建議產生決策選項                       │
│ └─ 人類裁決每個衝突的解決方案                               │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 7: MediatorAgent                                      │
│ └─ 整合所有中間產物，產生需求草稿 → draft_N.json            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 8: ModelerAgent    [ReAct + Tool Use + Reflection]    │
│ ├─ 根據草稿產生 Use Case / Class / Sequence Diagram         │
│ ├─ 使用 plantuml_validate 驗證語法                          │
│ └─ 將模型整合至 draft_N.json（含 .plantuml 輸出）           │
└─────────────────────────────────────────────────────────────┘
```

### Round 2+: 議題式討論

第 2 輪起，Mediator 轉為會議主持人，以議題為單位進行討論：

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: MediatorAgent 分析 Spec → 生成議題清單              │
│ ├─ 議題類型: conflict / requirement_gap / refinement /      │
│ │            new_concern                                    │
│ └─ 為每個議題決定討論模式 + 參與者 + 發言順序               │
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
│ Step 2c: 升級路徑                                           │
│ ├─ ExpertAgent 提供拘束性裁決（基於法規/標準/技術限制）     │
│ └─ 仍無法解決 → 人類介入裁決                                │
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
Mediator 綜合 → agreed? ──Yes──→ 記錄決策，下個議題
                  │
                  No
                  ▼
          Expert 拘束性裁決 → resolved? ──Yes──→ 記錄決策
                  │
                  No
                  ▼
           人類介入裁決 → 記錄決策
```

### 會議記錄結構

- **Round 1**：使用 `stages` 結構（每個 Stage 一筆記錄）
- **Round 2+**：使用 `meetings` 結構（每個議題一筆會議記錄），包含參與者、發言記錄、決議結果

## Agent Prompt 設計

### MediatorAgent（會議主持人）

**System Prompt 核心指令：**
- 中立、客觀地主持需求討論會議
- 建立並維護專案目標，確保討論圍繞目標
- 分析需求規格識別議題，決定討論模式
- 綜合各方意見，促成共識

**主要方法與 Prompt：**

| 方法 | 觸發時機 | Prompt 重點 |
| --- | --- | --- |
| `establish_project_goal()` | Phase 0 | 從 rough_idea 提取一句話核心目標（project_goal 字串） |
| `generate_draft()` | Round 1 Stage 7 / Round 2+ Step 3 | 根據 artifact 中間產物和 spec 模板產生需求草稿 |
| `generate_topics()` | Round 2+ 開頭 | 分析 Spec 識別衝突/缺口/精煉/新關注點，決定 discussion_mode 和 participants |
| `moderate_sequential()` | 議題討論 | 按 speaking_order 依序呼叫 Agent 的 `respond_to_topic()`，傳遞 previous_responses |
| `moderate_simultaneous()` | 議題討論 | 同時呼叫所有 Agent 的 `respond_to_topic()`，不傳遞 previous_responses |
| `synthesize_and_resolve()` | 討論結束 | 綜合各方意見，判斷 agreed/partial/unresolved |
| `generate_conflict_report()` | Round 1 Stage 4 | 保留原有的衝突報告生成邏輯 |
| `generate_decision_options()` | Round 1 Stage 6 | 保留原有的決策選項生成邏輯 |

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

**輸出格式：** `{"id": "SH-01", "name": "...", "text": "..."}` — 自然口語文字，不使用結構化格式

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
  "text": ["具體建議"],
  "ref": ["來源 URL"],
  "reason": "為何是 advisory 或 binding"
}
```

**binding 判斷標準：**

| binding | 適用情境 | 範例 |
| --- | --- | --- |
| `true` | 法規強制、安全標準、技術硬性限制 | GDPR 合規、資料加密標準 |
| `false` | 一般建議、最佳實務、風險提醒 | 建議使用快取、考慮效能 |

**新增方法：`provide_binding_ruling(topic, contributions)`**
- 議題無法達成共識時，由 Expert 基於客觀證據做出拘束性裁決
- 若無客觀依據，`resolved` 設為 `false`，升級至人類

### AnalystAgent（分析師）

**System Prompt 核心指令：**
- 進行需求分析與衝突辨識（不負責草稿生成，草稿由 MediatorAgent 負責）

**Reflection 標準：**
- 衝突判斷必須有明確理由
- 不得遺漏明顯的需求矛盾
- Neutral 需確認確實不存在衝突

### ModelerAgent（系統建模）

**System Prompt 核心指令：**
- 根據需求草稿轉換系統模型

**Reflection 標準：**
- UML 必須涵蓋所有主要角色和使用案例
- PlantUML 語法必須正確（透過 plantuml_validate 工具驗證）

### DocumentorAgent（文件撰寫）

**System Prompt 核心指令：**
- 撰寫符合 IEEE 29148 標準的 SRS 文件

**Reflection 標準：**
- SRS 必須涵蓋所有需求草稿中的需求項目
- 格式必須符合 IEEE 29148 標準結構

### BaseAgent（議題回應介面）

所有 Agent 繼承的 `respond_to_topic()` 方法：

**輸出格式：**

```json
{
  "position": "對議題的立場或看法",
  "arguments": ["支持論點1", "支持論點2"],
  "suggestions": ["具體建議1", "具體建議2"]
}
```

子類別可覆寫此方法，提供角色特化的回應邏輯。

## 配置說明

`config/config.json` 主要設定：

| 設定                                                                         | 說明                  | 預設值                               |
| ---------------------------------------------------------------------------- | --------------------- | ------------------------------------ |
| `provider`                                                                   | LLM 供應商            | `"openai"`                           |
| `model`                                                                      | 模型名稱              | `"gpt-4o-mini"`                      |
| `rounds`                                                                     | 討論輪數              | `1`                                  |
| `enable_user` / `analyst` / `expert` / `mediator` / `modeler` / `documentor` | 各 Agent 開關         | `true`                               |
| `enable_web_search`                                                          | 是否啟用網路搜尋      | `true`                               |
| `enable_reflection`                                                          | 是否啟用反思機制      | `true`                               |
| `enable_agent_communication`                                                 | 是否啟用跨 Agent 溝通 | `true`                               |
| `agent_max_steps`                                                            | ReAct 迴圈最大步數    | `5`                                  |
| `plantuml_server`                                                            | PlantUML 驗證伺服器   | `"http://www.plantuml.com/plantuml"` |

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
