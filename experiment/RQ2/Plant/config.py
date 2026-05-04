import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from flow.setup import Flow
from utils import model_has_token_pricing

class ExperimentLogger:
    """實驗用無輸出 logger（不寫 log 檔）。"""

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

class ExperimentStore:
    """實驗用無 I/O store（不產生 project id 與 artifacts）。"""

    def __init__(self) -> None:
        self.project_id = "rq2_experiment"
        # AgendaRunner 會讀取 output_dir；不指向 repo 根目錄，避免誤讀既有 design_rationale.md
        self.output_dir = Path(tempfile.gettempdir()) / "plant_rq2_experiment_store"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = self.output_dir

    def save_artifact(self, data: Dict[str, Any]):
        pass

    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        pass

    def save_markdown(self, content: str, filename: str):
        pass

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        pass

    def save_draft(self, content: str, version: int):
        pass

    def get_draft_version(self) -> int:
        return -1

    def load_draft(self, version: int):
        return None

def build_plant_cost_payload(flow: Flow) -> Dict[str, Any]:
    """彙總 Flow 內各 LLM 的 CostTracker（與 flow.finalize 的 cost_summary 結構相近）。"""
    cost_by_agent: Dict[str, Any] = {}
    for agent_name, m in flow.agent_models.items():
        if not hasattr(m, "costTracker"):
            continue
        summary = m.costTracker.export_summary_dict()
        # 僅保留本次實驗中實際有 LLM token 使用的 agent。
        if int(summary.get("total_tokens", 0) or 0) <= 0:
            continue
        cost_by_agent[agent_name] = summary
    if not cost_by_agent:
        return {
            "agents": {},
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "run_time(s)": 0.0,
                "estimated_cost(USD)": 0.0,
            },
        }
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in cost_by_agent.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in cost_by_agent.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in cost_by_agent.values()),
        "run_time(s)": round(
            sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in cost_by_agent.values()),
            3,
        ),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in cost_by_agent.values()),
            8,
        ),
    }
    return {
        "agents": cost_by_agent,
        "totals": totals,
    }


RQ2_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

def assert_agent_models_have_token_pricing(config: Dict[str, Any]) -> None:
    for agent, info in (config.get("agent_models") or {}).items():
        if agent == "default" or not isinstance(info, dict):
            continue
        mn = info.get("model")
        if not mn:
            continue
        if not model_has_token_pricing(str(mn)):
            print(
                f"警告：沒有找到 token 的定價：agent_models.{agent} 模型「{mn}」。"
                "請在專案 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上該模型，"
                "或改用已定價的模型名稱。"
            )
            sys.exit(1)

def load_rq2_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("Plant/config.json 內容必須是 JSON 物件")
    return cfg

def build_flow(config: Optional[Dict[str, Any]] = None) -> Flow:
    if config is None:
        config = load_rq2_config()
    check_provider_model_mismatch(config)
    assert_agent_models_have_token_pricing(config)
    return Flow(config=config, store=ExperimentStore(), logger=ExperimentLogger())

def check_provider_model_mismatch(config: Dict[str, Any]) -> None:
    """檢查 provider/model 是否明顯不匹配；任一不匹配即拋 ValueError 中止。"""

    def looks_openai(model: str) -> bool:
        m = (model or "").lower()
        return m.startswith("gpt-") or m.startswith("o")

    def looks_gemini(model: str) -> bool:
        return (model or "").lower().startswith("gemini")

    mismatches: list[str] = []
    model_cfg = (config.get("agent_models") or {})
    for agent, info in model_cfg.items():
        if not isinstance(info, dict):
            continue
        provider = (info.get("provider") or "").lower()
        model = info.get("model") or ""
        if not provider or not model:
            continue
        bad = (
            (provider == "openai" and looks_gemini(model))
            or (provider == "gemini" and looks_openai(model))
        )
        if bad:
            mismatches.append(
                f"agent_models.{agent}: provider={provider!r}, model={model!r}"
            )

    if not mismatches:
        return
    detail = "\n".join(f"  - {line}" for line in mismatches)
    msg = f"provider/model 明顯不匹配（請修正 config 的 agent_models）：\n{detail}"
    raise ValueError(msg)
