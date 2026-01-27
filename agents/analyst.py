from typing import Dict, List
import itertools

class AnalystAgent:
    """
    Analyst Agent: 分析師代理
        - 對利害關係人需求做衝突分析
        - 產出衝突報告(report.md)
    """
    
    system_prompt = "你是系統分析師，擅長識別需求衝突並提供解決方案。"
    
    def __init__(self, model):
        self.model = model
    
    def analyze_pairs(self, stakeholders: List[Dict]) -> List[Dict]:
        """
        對利害關係人需求進行衝突分析
        
        Args:
            stakeholders: 利害關係人列表
        
        Returns:
            List[Dict]: 配對分析結果，每個包含 id, text1, text2, label
        """
        pairs = []
        stakeholder_combinations = list(itertools.combinations(stakeholders, 2))
        
        for sh1, sh2 in stakeholder_combinations:
            pair_analysis = self._analyze_single_pair(sh1, sh2)
            pairs.append(pair_analysis)
        
        return pairs
    
    def _analyze_single_pair(self, sh1: Dict, sh2: Dict) -> Dict:
        """
        衝突分析
        
        Returns:
            Dict: {"id": [id1, id2], "text1": str, "text2": str, "label": "Conflict"/"Neutral"}
        """
        user_prompt = f"""利害關係人 A ({sh1['name']}):
                {sh1['text']}

                利害關係人 B ({sh2['name']}):
                {sh2['text']}

                請分析這兩位利害關係人的需求是否存在衝突。
                衝突定義：兩個需求無法同時滿足，或存在明顯的優先順序、資源分配、技術選擇等方面的矛盾。

                請以 JSON 格式回應：
                {{{{
                "label": "Conflict" or "Neutral",
                "reason": "判斷理由"
                }}}}"""
        
        response = self.model.generate_json(user_prompt, self.system_prompt)
        return {
            "id": [sh1['id'], sh2['id']],
            "text1": sh1['text'],
            "text2": sh2['text'],
            "label": response.get("label"),
            "reason": response.get("reason")
        }

    
    def generate_conflict_report(self, pairs: List[Dict], stakeholders: List[Dict]) -> List[Dict]:
        """
        結構化衝突報告
        
        Args:
            pairs: 配對分析結果
            stakeholders: 利害關係人列表
        
        Returns:
            List[Dict]: 衝突報告，每個包含 id, title, stakeholder_name, description, solutions
        """
        conflict_pairs = [p for p in pairs if p['label'] == 'Conflict']
        
        if not conflict_pairs:
            return []
        
        # 建立 stakeholder id 到 name 的映射
        sh_map = {sh['id']: sh['name'] for sh in stakeholders}
        
        # 為每個衝突生成報告
        conflicts = []
        for idx, pair in enumerate(conflict_pairs, 1):
            conflict_id = f"CR-{idx:02d}"
            
            # 取得利害關係人名稱
            stakeholder_names = [sh_map.get(sid, sid) for sid in pair['id']]
            
            # 生成衝突描述和解決方案
            conflict_detail = self._generate_conflict_detail(pair, stakeholder_names)
            
            conflicts.append({
                "id": conflict_id,
                "title": conflict_detail['title'],
                "stakeholder_name": stakeholder_names,
                "description": conflict_detail['description'],
                "solutions": conflict_detail['solutions']
            })
        
        return conflicts
    
    def _generate_conflict_detail(self, pair: Dict, stakeholder_names: List[str]) -> Dict:
        """
        生成衝突報告解決方案
        """
        user_prompt = f"""衝突配對：
                利害關係人：{stakeholder_names[0]} vs {stakeholder_names[1]}

                需求 A:
                {pair['text1']}

                需求 B:
                {pair['text2']}

                分析理由：
                {pair.get('reason', '')}

                請為這個衝突生成：
                1. 簡短標題（10 字內）
                2. 詳細的衝突描述
                3. 2-3 個可能的解決方案

                請以 JSON 格式回應：
                {{{{
                "title": "衝突標題",
                "description": "詳細描述",
                "solutions": ["方案1", "方案2", "方案3"]
                }}}}"""
        
        response = self.model.generate_json(user_prompt, self.system_prompt)
        return {
            "title": response.get("title"),
            "description": response.get("description", pair.get('reason', '')),
            "solutions": response.get("solutions", ["需人類決策"])
        }
    
    def generate_report_markdown(self, system_description: str, conflicts: List[Dict]) -> str:
        """
        產生 Markdown 格式的衝突報告
        
        Args:
            system_description: 系統概述
            conflicts: 衝突報告列表
        
        Returns:
            str: Markdown 格式的報告
        """
        md = "# 需求分析報告\n\n"
        md += f"## 系統概述\n\n{system_description}\n\n"
        
        if conflicts:
            md += f"## 識別出的衝突（共 {len(conflicts)} 個）\n\n"
            for conflict in conflicts:
                md += f"### {conflict['id']}: {conflict['title']}\n\n"
                md += f"**涉及利害關係人**: {', '.join(conflict['stakeholder_name'])}\n\n"
                md += f"**衝突描述**:\n{conflict['description']}\n\n"
                md += "**可能的解決方案**:\n"
                for idx, solution in enumerate(conflict['solutions'], 1):
                    md += f"{idx}. {solution}\n"
                md += "\n---\n\n"
        else:
            md += "## 衝突分析\n\n未識別出明顯衝突。\n\n"
        
        return md
