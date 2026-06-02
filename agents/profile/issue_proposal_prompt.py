# Shared issue proposal prompt builder.
import json
from typing import Any, Dict, List, Optional


def build_issue_proposal_prompt(
    *,
    agent_label: str,
    focus: str,
    common_problem_examples: List[str],
    value_gate: List[str],
    reject_rule: str,
    max_items: int,
    proposal_context: Optional[Dict[str, Any]] = None,
) -> str:
    examples = "\n".join(f"- {item}" for item in common_problem_examples)
    gates = "\n".join(f"- {item}" for item in value_gate)
    context_json = json.dumps(proposal_context or {}, ensure_ascii=False, indent=2)
    return f"""# 任務
提出本輪的{agent_label} issue proposal 候選，目標是讓 latest draft 更接近可生成 SRS。

# 提案規則
- proposal 只是候選訊號；Mediator 會合併、淘汰、排序與定題，所以可以比正式會議選題更寬鬆。
- latest_draft 是主要依據；proposal_context 只是摘要訊號，不可當成專案全文。
- 只提出能改善共同問題的候選：{focus}。
- 每筆 proposal 必須代表一組相關需求背後的共同問題，例如：
{examples}
- 不要為單一 REQ、單一 open question、單一 acceptance criteria、單一 source、單一模型或單一欄位補字建立 proposal；除非它明確代表更大的共同問題。
- 預設會議已處理整份衝突報告與全部 User Requirements 初步正式化；一般提案只處理預設會議後 latest draft 仍留下的具體缺口。
- 盡量提出有助於改善 SRS 品質的候選；不要提出沒有 source 的空泛議題。只有 latest draft 沒有明確共同缺口時才輸出空陣列。

# 優先順序
1. requirement_completeness：既有 REQ-* 缺 acceptance criteria、NFR category、metric、validation、外部限制影響、source coverage，或 title、description、rationale、risks、assumptions 雖存在但仍抽象、混雜、不可測、不可追溯或難以驗收。
2. boundary_responsibility：系統、人工、第三方或角色責任不清。
3. tradeoff：多方需求有方案取捨但尚未形成衝突。
4. model_alignment：模型揭露流程、狀態、actor、資料或責任不一致。
5. new_requirement：新增或延伸需求；若它能揭露既有需求不足，也可以提出。

# 判斷門檻
符合以下條件時應提出；接近門檻但可能影響 SRS 品質，也可以交由 Mediator triage：
{gates}
- 弱化欄位也算缺口，例如 title 混入不必要的 stakeholder；description 把多個能力串成一大段；NFR 缺 category；constraint 被寫成 non-functional；validation 只寫 `test`、`inspection`、`walkthrough`；metric 含「待確認、待協議、合理、快速、穩定、清楚」但沒有可觀察條件；acceptance criteria 只是重述 requirement；rationale、risks、assumptions 重複 description；source 籠統；system model 對應過廣或無法說明該 REQ。
- sources.evidence 必須指出 draft 中的具體缺口、弱欄位、矛盾、未決問題、角色衝突、限制、模型缺口或來源 id。
- expect_outcome 必須是會議後可落地的結果，例如補完整既有 REQ-* 的 acceptance criteria、NFR category、metric、validation、risks、assumptions、source coverage、模型一致性，或確認仍需 open question / human decision。
{reject_rule}

# 輸出欄位
- title：共同問題短標籤；不要只寫單一需求 id 或欄位缺口。
- category：clarify_requirement / define_boundary / tradeoff / align_model；只表示正式會議類型。
- issue_focus：requirement_completeness / boundary_responsibility / tradeoff / model_alignment / new_requirement；只表示排序焦點。
- expect_outcome：會議後應得到的明確結果。
- sources：array，每筆為 object：{{"artifact": "URL|REQ|conflict_report|conversation|system_models|open_questions|scope|feedback", "ids": ["draft 中看得到的具體 id"], "evidence": "draft 中的具體依據、缺口或 id"}}。
- importance：high / medium / low。
- reason：共同問題、為什麼需要正式會議、為什麼影響需求規格完整性。

# proposal_context 摘要
以下只供判斷 draft coverage 與缺口，不是專案資料全文：
```json
{context_json}
```

# 輸出 JSON
[]"""
