# Human input helpers for project choices and topic decisions.
from typing import Dict, List


STAKEHOLDER_CATEGORY_LABELS = {
    "Primary Users": "核心使用者",
    "System Owners & Management": "系統所有者與管理者",
    "External Parties": "外部相關單位",
}


class Collect:
    @staticmethod
    def user_selection(
        proposed: List[Dict[str, str]], max_select: int = 5
    ) -> List[int]:
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
                selected_indices = []
                has_invalid_selection = False
                parts = [x.strip() for x in user_input.split(",")]

                for part in parts:
                    try:
                        idx = int(part) - 1
                        if 0 <= idx < len(proposed):
                            selected_indices.append(idx)
                        else:
                            print(f"\n⚠️ 編號 {part} 無效，請重新選擇")
                            has_invalid_selection = True
                            break
                    except ValueError:
                        if part:
                            proposed.append({"name": part, "reason": "使用者自訂"})
                            selected_indices.append(len(proposed) - 1)

                if has_invalid_selection:
                    continue

                if len(selected_indices) > max_select:
                    print(f"\n⚠️ 選擇超過 {max_select} 個，請重新選擇")
                    continue

                if len(selected_indices) == 0:
                    print("\n❌ 至少需要選擇 1 個利害關係人")
                    continue

                return selected_indices

            except Exception as e:
                print(f"\n❌ 錯誤：{e}")
                continue

    @staticmethod
    def human_decision_on_issue(issue: Dict, options) -> Dict:
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
            idx = opt.get("id", len(all_options) + 1)
            print(f"\n  方案 {idx}. {opt.get('title', '')}")
            print(f"     來源: {opt.get('source', '?')}")
            print(f"     內容: {opt.get('description', '')}")
            all_options.append(opt)

        if isinstance(compromise, dict) and compromise:
            idx = compromise.get("id", len(all_options) + 1)
            print(f"\n  方案 {idx}. [折衷] {compromise.get('title', '')}")
            print(f"     內容: {compromise.get('description', '')}")
            print(f"     理由: {compromise.get('rationale', '')}")
            all_options.append(compromise)

        print(f"\n{'─' * 40}")
        print("  0. 自行輸入裁決")

        user_input = input("\n請選擇方案編號（或 Enter 跳過）：").strip()
        if not user_input:
            return {
                "resolution": "unresolved",
                "summary": "人類選擇暫不裁決",
                "decision": "暫緩處理",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        try:
            choice = int(user_input)
        except ValueError:
            print("無效的輸入，暫緩處理")
            return {
                "resolution": "unresolved",
                "summary": "無效輸入",
                "decision": "暫緩處理",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        if choice == 0:
            custom = input("\n請輸入您的裁決：").strip()
            if not custom:
                return {
                    "resolution": "unresolved",
                    "summary": "人類未輸入裁決",
                    "decision": "暫緩處理",
                    "chosen_option_id": 0,
                    "chosen_option_title": "自行輸入裁決",
                }
            return {
                "resolution": "agreed",
                "summary": f"由人類裁決: {custom}",
                "decision": custom,
                "chosen_option_id": 0,
                "chosen_option_title": "自行輸入裁決",
            }

        chosen = None
        for opt in all_options:
            if opt.get("id") == choice:
                chosen = opt
                break
        if not chosen:
            print("無效的選項，暫緩處理")
            return {
                "resolution": "unresolved",
                "summary": "無效輸入",
                "decision": "暫緩處理",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }

        title = chosen.get("title", "")
        desc = chosen.get("description", "")
        source = chosen.get("source", "方案")
        return {
            "resolution": "agreed",
            "summary": f"人類採納方案 {choice}（{source}）: {title}",
            "decision": desc,
            "chosen_option_id": choice,
            "chosen_option_title": title,
        }
