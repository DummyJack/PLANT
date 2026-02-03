from typing import Dict, List


# 調解代理，協助人類
class MediatorAgent:

    system_prompt = "你是需求調解專家，擅長提供決策建議。"

    def __init__(self, model):
        self.model = model

    # 產生衝突報告
    def generate_conflict_report(self, conflict_groups: List[Dict]) -> List[Dict]:
        if not conflict_groups:
            return []

        conflicts = []
        for idx, group in enumerate(conflict_groups, 1):
            conflict_id = f"CR-{idx:02d}"

            # 準備利害關係人發言內容
            stakeholder_texts = "\n\n".join(
                [
                    f"利害關係人 {name} ({sid}):\n{group['texts'][sid]}"
                    for sid, name in zip(
                        group["stakeholder_ids"], group["stakeholder_names"]
                    )
                ]
            )

            user_prompt = f"""以下是分析師識別出的需求衝突。

            涉及的利害關係人：{', '.join(group['stakeholder_names'])}

            發言內容：
            {stakeholder_texts}

            分析理由：
            {group.get('reason', '')}

            候選需求：
            {group.get('candidates', [])}

            請為這個衝突生成：
            2. description: 詳細的衝突描述
            3. conflict_type: 衝突類型(efficiency vs control)

            請以 JSON 格式回應：
            {{{{
            "description": "衝突描述",
            "conflict_type": "衝突類型"
            }}}}"""

            response = self.model.generate_json(user_prompt, self.system_prompt)

            conflicts.append(
                {
                    "id": conflict_id,
                    "stakeholder_names": group["stakeholder_names"],
                    "description": response.get("description"),
                    "conflict_type": response.get("conflict_type"),
                }
            )

        return conflicts

    # 產生決策選項
    def generate_decision_options(
        self, conflicts: List[Dict], feedback: List[Dict]
    ) -> List[Dict]:
        decision_options = []

        for conflict in conflicts:
            option = self._generate_single_decision(conflict, feedback)
            decision_options.append(option)

        return decision_options

    # 為單一衝突產生決策選項
    def _generate_single_decision(self, conflict: Dict, feedback: List[Dict]) -> Dict:
        # 準備專家建議
        feedback_text = "\n".join(
            [f"- {fb['id']}: {'; '.join(fb['text'])}" for fb in feedback]
        )

        user_prompt = f"""衝突 {conflict['id']}: {conflict['title']}
        
                涉及利害關係人: {', '.join(conflict['stakeholder_names'])}
                
                衝突類型: {conflict['conflict_type']}

                衝突描述:
                {conflict['description']}

                專家建議:
                {feedback_text}

                請為這個衝突整理出清晰的決策選項（至少提供 3 個選項）,並提供建議。

                請以 JSON 格式回應：
                {{{{
                "options": ["選項A: ...", "選項B: ...", "選項C: ..."],
                "recommendation": "建議選擇哪個選項及理由"
                }}}}"""

        response = self.model.generate_json(user_prompt, self.system_prompt)
        return {
            "conflict_id": conflict["id"],
            "conflict_title": conflict["title"],
            "options": response.get("options"),
            "recommendation": response.get("recommendation"),
        }
