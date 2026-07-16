# Defines module workflow behavior.
import json
from typing import Any


def _web_evidence_example(source_ref: str) -> dict[str, Any]:
    return {
        "text": "",
        "related_requirement_ids": [],
        "source": source_ref,
        "source_ids": ["SRC-..."],
        "trace_reason": "",
        "evidence_type": "web",
    }


def _document_evidence_example(source_ref: str) -> dict[str, Any]:
    return {
        "text": "",
        "related_requirement_ids": [],
        "source": source_ref,
        "source_paths": ["104431333156/參考文件.pdf"],
        "trace_reason": "",
        "evidence_type": "project_document",
    }


def domain_research_output_schema(*, wrapper: str, source_ref: str) -> str:
    web = _web_evidence_example(source_ref)
    document = _document_evidence_example(source_ref)
    schema = {
        wrapper: {
            "findings": [web, document],
            "sources": [
                {
                    "id": "SRC-...",
                    "title": "發布機關：文件主題",
                    "url": "https://...",
                    "type": "web",
                },
                {
                    "title": "參考文件.pdf",
                    "url": "104431333156/參考文件.pdf",
                    "type": "file",
                },
            ],
            "constraints": [web],
            "risks": [document],
            "recommendations": [document],
        }
    }
    return "輸出 JSON：\n" + json.dumps(schema, ensure_ascii=False, indent=2)


def repair_plan_output(*, raw: Any, error: str, context: Any = None) -> str:
    raw_text = raw if isinstance(raw, str) else json.dumps(
        raw, ensure_ascii=False, separators=(",", ":")
    )
    return f"""修正 Expert research_domain plan 輸出格式。

目前合法 target context：
{json.dumps(context or {}, ensure_ascii=False)}

修正規則：
- steps 必須至少包含一個 research_issue，不能只輸出 done 或空 steps。
- research_issue 必須提供 target_type 與非空 target_ids，且只能使用 target context 中的合法 ID。
- referenced_files 非空時，第一個研究動作必須是 read_reference_docs。
- update_feedback 必須是最後一個 step。

錯誤：
{error}

規則：
- 只修正 research_plan、action 名稱、params 結構與 steps 格式。
- 最外層必須只有 research_plan。
- 可用 action 只有 read_reference_docs、research_issue、update_feedback、done。
- read_reference_docs / research_issue 必須有 params.query。
- research_issue 必須有 params.value_reason，說明為什麼此問題是 high-value research issue。
- high-value 指會影響需求是否成立、系統邊界、驗收標準、多個 URL/REQ，或目前 artifact 沒有清楚答案。
- research_issue 最多 4 個；若超過，合併相近題目。
- 不同法規、主管機關要求、產業標準或外部證據主題必須拆成不同 research_issue，不得合併成一個過大的 query。
- 若 steps 有 research_issue，最後必須包含 update_feedback。
- update_feedback 只允許放在 steps 最後一次。
- 若 user_guidance、referenced_files、coverage、gaps 或 issue 明確標記需要外部查證，且目前沒有 existing feedback / research_results，必須輸出 research_issue + update_feedback。
- 沒有高價值且可取得可靠來源的研究問題時，可以輸出 done，不要硬塞低品質 research_issue。
- 不新增新的研究結論；這裡只決定下一步要跑什麼。

輸出 JSON：
{{
  "research_plan": {{
    "action": "done",
    "params": {{}},
    "reasoning": "使用目前輸出語系的一句說明",
    "goal": "本輪 research_domain 目標",
    "steps": [
        {{"action": "read_reference_docs", "params": {{"query": "具體文件查詢問題"}}}},
        {{
          "action": "research_issue",
          "params": {{
            "target_type": "URL",
            "target_ids": ["URL-1"],
            "query": "具體高價值研究問題",
            "value_reason": "為什麼此問題會影響需求品質"
          }}
        }},
        {{"action": "update_feedback", "params": {{}}}}
    ]
  }}
}}

原始輸出：
{raw_text}
"""


def repair_action_output(
    *,
    action: str,
    raw: Any,
    error: str,
    source_ref: str,
) -> str:
    raw_text = raw if isinstance(raw, str) else json.dumps(
        raw, ensure_ascii=False, separators=(",", ":")
    )
    if action == "read_reference_docs":
        return f"""修正 Expert read_reference_docs action 的輸出格式。

錯誤：
{error}

規則：
- 只修正格式與欄位，不新增原始內容沒有支持的文件證據。
- document_evidence 每筆必須包含 source、summary、related_requirement_ids。
- source 要能追蹤到文件名稱、路徑或片段位置。
- related_requirement_ids 只能是輸入資料中已存在的 URL-* / REQ-*；無法對應時用空陣列。
- coverage 每筆必須包含 target_id、status、reason；status 只能是 document_supported、not_found_in_documents、document_conflict、needs_external_validation。
- 若沒有相關文件證據，document_evidence 輸出空陣列，並在 gaps 說明缺口。

輸出 JSON：
{{
  "document_evidence": [
    {{
      "source": "doc/...",
      "section": "章節或片段位置",
      "summary": "文件證據摘要",
      "related_requirement_ids": ["URL-1"]
    }}
  ],
  "coverage": [
    {{
      "target_id": "URL-1",
      "status": "document_supported",
      "reason": "文件支持、缺口、衝突或仍需外部驗證的簡短原因"
    }}
  ],
  "gaps": []
}}

原始輸出：
{raw_text}
"""
    wrapper = "research_evidence" if action == "research_issue" else "feedback"
    output_schema = domain_research_output_schema(wrapper=wrapper, source_ref=source_ref)
    return f"""修正 Expert domain research action 的輸出格式。

action：
{action}

錯誤：
{error}

規則：
- 只修正格式與欄位，不新增原始內容沒有支持的結論。
- findings、constraints、risks、recommendations 的每筆 item 只包含 text、related_requirement_ids、source、source_ids、source_paths、trace_reason、evidence_type；不要在 item 內放 sources。
- evidence_type 使用 web、project_document、user_statement、artifact_context 或 model_context；使用外部 URL 證據時必須是 web，使用專案引用文件時必須是 project_document。
- 每個 evidence_type=web 的 item 必須包含非空 source_ids，且只能引用原始輸出 sources 中已存在、具有完整 URL 的 SRC-* id。
- 每個 evidence_type=project_document 的 item 必須包含非空 source_paths，且只能引用原始輸出 sources 中已存在、type=file 的完整專案文件路徑。
- 修復時必須把原始 sources 的 web id 原樣保留；不得新造來源 ID、URL 或來源內容。
- 若原始輸出沒有可引用的有效 web source id，移除對應外部結論；只有原始文件證據確實支持該結論時，才能改為 project_document。
- related_requirement_ids 只能是輸入資料中已存在的 URL-* / REQ-*；無法對應時用空陣列。
- sources 集中放在最外層；web 來源使用 {{"id": "原始 SRC-*", "title": "web_search 或官方頁面提供的來源標題", "url": "完整 URL", "type": "web"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
- sources.title 必須是人可讀的頁面標題、法規/文件名稱或「發布機關/組織：文件主題」；不得填 URL、網址路徑或純網域。若原始輸出 title 是 URL，請依來源發布者與頁面主題補成簡短標題；無法補標題時移除該來源與對應外部結論。
- sources 只接受可追溯來源；來源可信度依 URL、頁面標題、發布者與 context 中保留的來源資訊判斷。
- 不引用部落格、社群媒體、論壇、新聞稿、行銷文章、一般心得文或內容農場。
- 若結論來自網路研究，evidence_type 必須是 web，且必須有完整 URL sources；找不到 URL 時移除該外部結論。
- 若結論來自 document_evidence 的專案引用文件，sources 必須列出對應文件路徑並標記 type=file，且不得新增 document_evidence 沒有支持的外部結論。
- constraints / recommendations 使用候選或建議語氣，不寫成已定案需求。
- 本次新增 item.source 使用：{source_ref}
- research_issue 必須輸出 research_evidence wrapper。
- update_feedback 必須輸出 feedback wrapper。

{output_schema}

原始輸出：
{raw_text}
"""
