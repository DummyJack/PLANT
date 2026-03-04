from typing import Dict

# Agent 註冊中心(用於 Round 2 議題討論時查找 Agent 實例)
class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, Dict] = {}

    def register(self, name: str, agent):
        self._agents[name] = agent

    def get(self, agent_name: str):
        return self._agents.get(agent_name)

    def get_names(self) -> list:
        return list(self._agents.keys())
