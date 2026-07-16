# Handles human logic for shared utility behavior for the Plant runtime.
import json
import re
from pathlib import Path
from typing import Dict, List, Optional


STAKEHOLDER_CATEGORY_LABELS = {
    "primary_user": "核心使用者",
    "system_owner": "系統所有者與管理者",
    "external_party": "外部相關單位",
}
STAKEHOLDER_CATEGORY_VALUES = set(STAKEHOLDER_CATEGORY_LABELS.keys())
TARGET_MENTION_RE = re.compile(
    r"(?<!\S)@((?:URL|REQ|SM|CR|ST)-[A-Za-z0-9_.:-]+|R\d+-M\d+)",
    re.IGNORECASE,
)


def cli_skip_all_interventions() -> bool:
    config_path = Path.cwd() / "config.json"
    if not config_path.exists():
        config_path = Path(__file__).resolve().parent.parent / "config.json"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return False
    return bool(config.get("human_skip_judge", False))


def reference_type(name: str) -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    return suffix or "file"


def suggestion_target_ids(text: str) -> List[str]:
    ids = [
        match.group(1).strip().upper()
        for match in TARGET_MENTION_RE.finditer(str(text or ""))
    ]
    return list(dict.fromkeys(value for value in ids if value))


def strip_suggestion_targets(text: str) -> str:
    stripped = TARGET_MENTION_RE.sub(" ", str(text or ""))
    return re.sub(r"\s{2,}", " ", stripped).strip()


def cli_suggestion_response(raw: str, references: Optional[List[Dict]] = None) -> Dict:
    text = str(raw or "").strip()
    if not text and not references:
        return {"action": "approve"}
    return {
        "action": "submit_suggestions",
        "suggestions": [
            {
                "text": strip_suggestion_targets(text) or text,
                "target_ids": suggestion_target_ids(text),
                "references": references or [],
            }
        ],
    }


def referenced_files_from_cli_text(raw: str, references: List[Dict]) -> tuple[str, List[Dict]]:
    text = str(raw or "")
    rows: List[Dict] = []
    seen = set()
    by_index = {}
    by_name = {}
    for index, reference in enumerate(references or [], 1):
        if not isinstance(reference, dict):
            continue
        name = str(reference.get("name") or "").strip()
        if not name:
            continue
        by_index[str(index)] = name
        by_name[name.lower()] = name

    def add_name(name: str) -> None:
        clean = str(name or "").strip()
        if not clean or clean in seen:
            return
        seen.add(clean)
        rows.append({
            "name": clean,
            "path": clean,
            "type": reference_type(clean),
        })

    for token in re.findall(r"@(\d+)(?=\s|$|[,，;；])", text):
        if token in by_index:
            add_name(by_index[token])
            text = re.sub(rf"@{re.escape(token)}(?=\s|$|[,，;；])", " ", text)

    for token in re.findall(r"(?<!\S)(\d+)(?=\s|$|[,，;；])", text):
        if token in by_index:
            add_name(by_index[token])
            text = re.sub(rf"(?<!\S){re.escape(token)}(?=\s|$|[,，;；])", " ", text, count=1)

    for lower_name, name in sorted(by_name.items(), key=lambda item: len(item[1]), reverse=True):
        marker = f"@{name}"
        if marker.lower() in text.lower():
            add_name(name)
            text = re.sub(re.escape(marker), " ", text, flags=re.IGNORECASE)
        elif lower_name in text.lower():
            for match in re.finditer(re.escape(name), text, flags=re.IGNORECASE):
                before = text[match.start() - 1] if match.start() > 0 else " "
                if before in {"@", " ", "\n", "\t", ",", "，", ";", "；"}:
                    add_name(name)
                    text = text[:match.start()] + " " + text[match.end():]
                    break

    text = re.sub(r"[ \t]{2,}", " ", text).strip(" ,，;；\n\t")
    return text, rows


# ========
# Defines Collect class for this module workflow.
# ========
def domain_research_review_response(raw: str, references: List[Dict]) -> Dict:
    text = str(raw or "").strip()
    if not text or text == "0":
        return {"action": "approve"}
    feedback, referenced_files = referenced_files_from_cli_text(text, references)
    return cli_suggestion_response(feedback, referenced_files)


class Collect:
    # ========
    # Defines custom stakeholder type function for this module workflow.
    # ========
    @staticmethod
    def custom_stakeholder_type(name: str) -> str:
        categories = [
            ("primary_user", "核心使用者"),
            ("system_owner", "系統所有者與管理者"),
            ("external_party", "外部相關單位"),
        ]
        while True:
            print(f"\n請選擇「{name}」的類型：")
            for i, (_, label) in enumerate(categories, 1):
                print(f"{i}. {label}")
            raw = input("請輸入類型編號：").strip()
            try:
                idx = int(raw) - 1
            except ValueError:
                print("❌ 類型編號必須是數字")
                continue
            if 0 <= idx < len(categories):
                return categories[idx][0]
            print("❌ 類型編號無效")

    # ========
    # Defines user selection function for this module workflow.
    # ========
    @staticmethod
    def user_selection(
        proposed: List[Dict[str, str]], max_select: int = 5
    ) -> List[Dict[str, str]]:
        while True:
            print("\n建議選擇的利害關係人：")
            for i, sh in enumerate(proposed, 1):
                stakeholder_type = str(sh.get("type") or "").strip()
                display_type = STAKEHOLDER_CATEGORY_LABELS.get(stakeholder_type, stakeholder_type)
                type_label = f"({display_type})" if display_type else ""
                print(f"{i}. {sh['name']}{type_label}，理由: {sh['reason']}")

            print(
                "\n提示: 可以輸入編號或直接輸入新的利害關係人名稱(例如: 1,3,系統管理員)"
            )
            user_input = input(f"\n請選擇利害關係人(最多 {max_select} 位)：").strip()

            if not user_input:
                print("\n❌ 請至少選擇 1 個利害關係人")
                continue

            try:
                selected_records: List[Dict[str, str]] = []
                seen_names = set()
                has_invalid_selection = False
                parts = [x.strip() for x in user_input.split(",")]

                for part in parts:
                    if not part:
                        continue
                    try:
                        idx = int(part) - 1
                        if 0 <= idx < len(proposed):
                            row = proposed[idx]
                            name = str(row.get("name") or "").strip()
                            stakeholder_type = str(row.get("type") or "").strip()
                            if stakeholder_type not in STAKEHOLDER_CATEGORY_VALUES:
                                print(f"\n⚠️ 建議項目「{name or part}」缺少合法類型，請重新選擇或改用自訂名稱")
                                has_invalid_selection = True
                                break
                            if name and name not in seen_names:
                                selected_records.append(row)
                                seen_names.add(name)
                        else:
                            print(f"\n⚠️ 編號 {part} 無效，請重新選擇")
                            has_invalid_selection = True
                            break
                    except ValueError:
                        name = part.strip()
                        if name and name not in seen_names:
                            stakeholder_type = Collect.custom_stakeholder_type(name)
                            selected_records.append({
                                "name": name,
                                "type": stakeholder_type,
                                "reason": "使用者自訂",
                            })
                            seen_names.add(name)

                if has_invalid_selection:
                    continue

                invalid_records = [
                    row for row in selected_records
                    if not str(row.get("name") or "").strip()
                    or str(row.get("type") or "").strip() not in STAKEHOLDER_CATEGORY_VALUES
                ]
                if invalid_records:
                    print("\n⚠️ 選擇結果包含格式不合法的利害關係人，請重新選擇")
                    continue

                if len(selected_records) > max_select:
                    print(f"\n⚠️ 選擇超過 {max_select} 個，請重新選擇")
                    continue

                if len(selected_records) == 0:
                    print("\n❌ 至少需要選擇 1 個利害關係人")
                    continue

                return selected_records

            except Exception as e:
                print(f"\n❌ 錯誤：{e}")
                continue

    # ========
    # Defines human decision on issue function for this module workflow.
    # ========
    @staticmethod
    def human_decision_on_issue(issue: Dict, options) -> Dict:
        if cli_skip_all_interventions():
            return {
                "summary": "CLI 設定已跳過本次裁決",
                "decision": "",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        def clean_option_title(value) -> str:
            title = str(value or "").strip()
            return re.sub(r"^[A-Z]\s*[:：]\s*", "", title)

        print(f"\n{'=' * 60}")
        print(f"需要人類裁決: {issue.get('title', '')}")
        print(f"議題描述: {issue.get('description', '')}")
        print(f"{'=' * 60}")

        if isinstance(options, dict):
            best_options = options.get("best_options", []) or []
            compromise = options.get("compromise", {}) or {}
        elif isinstance(options, list):
            best_options = options
            compromise = {}
        else:
            best_options = []
            compromise = {}

        print("\nMediator 推薦方案：")
        all_options = []
        for opt in best_options:
            if not isinstance(opt, dict):
                continue
            idx = len(all_options) + 1
            option = dict(opt)
            title = clean_option_title(opt.get("title", ""))
            description = str(opt.get("description") or "").strip()
            option["id"] = idx
            option["title"] = title
            print(f"\n  {idx}. {title}")
            if description and description != title:
                print(f"     內容: {description}")
            all_options.append(option)

        if isinstance(compromise, dict) and compromise:
            idx = len(all_options) + 1
            option = dict(compromise)
            option["id"] = idx
            title = clean_option_title(compromise.get("title", ""))
            description = str(compromise.get("description") or "").strip()
            print(f"\n  {idx}. {title}")
            if description and description != title:
                print(f"     內容: {description}")
            print(f"     理由: {compromise.get('rationale', '')}")
            all_options.append(option)

        print(f"\n{'─' * 40}")
        print("  0. 自行輸入裁決")

        user_input = input("\n請選擇方案編號，可多選(或 Enter 跳過)：").strip()
        if not user_input:
            return {
                "summary": "人類選擇暫不裁決",
                "decision": "",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        parts = [part.strip() for part in re.split(r"[,，\s]+", user_input) if part.strip()]
        try:
            choices = [int(part) for part in parts]
        except ValueError:
            print("無效的輸入，暫緩處理")
            return {
                "summary": "無效輸入",
                "decision": "",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        choices = list(dict.fromkeys(choices))
        if 0 in choices and len(choices) > 1:
            print("自行輸入裁決不能和其他方案一起選，暫緩處理")
            return {
                "summary": "無效輸入",
                "decision": "",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        if choices == [0]:
            custom = input("\n請輸入您的裁決：").strip()
            if not custom:
                return {
                    "summary": "人類未輸入裁決",
                    "decision": "",
                    "chosen_option_id": 0,
                    "chosen_option_title": "自行輸入裁決",
                }
            return {
                "status": "human_decision",
                "summary": f"由人類裁決: {custom}",
                "decision": custom,
                "chosen_option_id": 0,
                "chosen_option_title": "自行輸入裁決",
            }

        chosen_options = [
            opt for choice in choices for opt in all_options if opt.get("id") == choice
        ]
        if len(chosen_options) != len(choices):
            print("無效的選項，暫緩處理")
            return {
                "summary": "無效輸入",
                "decision": "",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        decision_items = []
        selected_options = []
        for opt in chosen_options:
            title = clean_option_title(opt.get("title", ""))
            desc = str(opt.get("description") or "").strip()
            rationale = str(opt.get("rationale") or "").strip()
            option_text = title
            if desc and desc != title:
                option_text = f"{title}，{desc}" if title else desc
            if rationale:
                option_text = f"{option_text}。理由：{rationale}" if option_text else f"理由：{rationale}"
            if option_text:
                decision_items.append(option_text)
            selected_options.append({
                "id": opt.get("id"),
                "title": title,
                "description": desc,
                "rationale": rationale,
            })
        decision_text = "\n".join(
            f"{index}. {text}" for index, text in enumerate(decision_items, 1)
        )
        choice_label = ",".join(str(choice) for choice in choices)
        title_label = "；".join(
            clean_option_title(opt.get("title", "")) for opt in chosen_options
        )
        return {
            "status": "human_decision",
            "summary": f"人類採納方案 {choice_label}: {title_label}",
            "decision": decision_text,
            "chosen_option_id": choice_label,
            "chosen_option_title": title_label,
            "chosen_options": selected_options,
        }

    @staticmethod
    def stakeholder_statement_review(stakeholders: List[Dict]) -> Dict:
        if cli_skip_all_interventions():
            return {"action": "approve", "skipped": True, "auto_skipped": True}

        print("\n利害關係人發言已產生：")
        for index, stakeholder in enumerate(stakeholders or [], 1):
            name = str(stakeholder.get("name") or f"利害關係人 {index}").strip()
            print(f"\n{index}. {name}")
            for item in stakeholder.get("text") or []:
                text = str(item.get("text") if isinstance(item, dict) else item or "").strip()
                if text:
                    print(f"   - {text}")
        raw = input("\n按 Enter 確認，或輸入修正意見：").strip()
        if not raw:
            return {"action": "approve"}
        return cli_suggestion_response(raw)

    @staticmethod
    def requirements_review(requirements: List[Dict]) -> Dict:
        if cli_skip_all_interventions():
            return {"action": "approve", "skipped": True, "auto_skipped": True}

        print("\n初始需求分析已產生：")
        for index, requirement in enumerate(requirements or [], 1):
            if not isinstance(requirement, dict):
                continue
            req_id = str(requirement.get("id") or f"URL-{index}").strip()
            text = str(requirement.get("text") or requirement.get("description") or "").strip()
            if text:
                print(f"  {req_id}. {text}")
        raw = input("\n按 Enter 確認，或輸入整體/局部建議：").strip()
        if not raw:
            return {"action": "approve"}
        return cli_suggestion_response(raw)

    @staticmethod
    def scope_review(scope: Dict) -> Dict:
        if cli_skip_all_interventions():
            return {"action": "approve", "skipped": True, "auto_skipped": True}

        print("\n需求範圍已產生：")
        source = scope if isinstance(scope, dict) else {}
        for key, title in (("in_scope", "範圍內"), ("out_of_scope", "範圍外")):
            print(f"\n{title}:")
            values = source.get(key) or []
            if not values:
                print("  - 無")
                continue
            for item in values:
                text = str(item or "").strip()
                if text:
                    print(f"  - {text}")
        raw = input("\n按 Enter 確認，或輸入需求範圍修正建議：").strip()
        if not raw:
            return {"action": "approve"}
        return cli_suggestion_response(raw)

    @staticmethod
    def domain_research_review(references: List[Dict]) -> Dict:
        if cli_skip_all_interventions():
            return {"action": "approve", "skipped": True, "auto_skipped": True}

        if references:
            print("\n可引用文件：")
            for index, reference in enumerate(references, 1):
                if not isinstance(reference, dict):
                    continue
                name = str(reference.get("name") or "").strip()
                if name:
                    print(f"  {index}. {name}")
        raw = input("\n輸入領域研究建議；引用文件請直接輸入編號(按 Enter 或輸入 0 確認)：")
        return domain_research_review_response(raw, references)

    @staticmethod
    def meeting_issue_proposal_review(
        proposals: List[Dict],
        round_num: int,
        max_issues: int = 5,
    ) -> Dict:
        if cli_skip_all_interventions():
            return {"action": "approve", "custom_issues": [], "skipped": True, "auto_skipped": True}

        print(f"\n第 {round_num} 輪候選議題已產生：")
        for row in proposals or []:
            if not isinstance(row, dict):
                continue
            issue_id = str(row.get("issue_id") or "").strip()
            title = str(row.get("title") or "").strip()
            proposed_by = str(row.get("proposed_by") or "").strip()
            if title:
                print(f"- {issue_id} {title} ({proposed_by})")
        raw = input("\n可輸入自訂議題 title，多筆請用換行或分號分隔；Enter 跳過：").strip()
        if not raw:
            return {"action": "approve", "custom_issues": []}
        titles = [
            item.strip()
            for item in re.split(r"[\n;；]+", raw)
            if item.strip()
        ]
        return {
            "action": "human_issues",
            "custom_issues": [{"title": title} for title in titles[:max_issues]],
        }
