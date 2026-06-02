# Human input helpers for project choices and topic decisions.
import re
from typing import Dict, List


STAKEHOLDER_CATEGORY_LABELS = {
    "Primary Users": "核心使用者",
    "System Owners & Management": "系統所有者與管理者",
    "External Parties": "外部相關單位",
}
STAKEHOLDER_CATEGORY_VALUES = set(STAKEHOLDER_CATEGORY_LABELS.keys())


class Collect:
    @staticmethod
    def custom_stakeholder_type(name: str) -> str:
        categories = [
            ("Primary Users", "核心使用者"),
            ("System Owners & Management", "系統所有者與管理者"),
            ("External Parties", "外部相關單位"),
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

    @staticmethod
    def human_decision_on_issue(issue: Dict, options) -> Dict:
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
            option.setdefault("source", "compromise")
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
