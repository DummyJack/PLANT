# Provides RQ2 Plant experiment config helpers.
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from flow.setup import Flow
from storage.artifact import save_artifact as save_split_artifact
from storage.markdown import load_markdown as load_markdown_file
from storage.markdown import save_markdown as save_markdown_file
from utils import model_has_token_pricing

# ========
# Defines ExperimentLogger class for this experiment module.
# ========
class ExperimentLogger:

    # ========
    # Defines fmt function for this experiment module.
    # ========
    @staticmethod
    def fmt(args: tuple) -> str:
        if not args:
            return ""
        if len(args) == 1:
            return str(args[0])
        msg = str(args[0])
        try:
            return msg % args[1:]
        except Exception:
            return " ".join(str(x) for x in args)

    # ========
    # Defines info function for this experiment module.
    # ========
    def info(self, *args, **kwargs):
        print(self.fmt(args), flush=True)

    # ========
    # Defines debug function for this experiment module.
    # ========
    def debug(self, *args, **kwargs):
        return None

    # ========
    # Defines warning function for this experiment module.
    # ========
    def warning(self, *args, **kwargs):
        print(f"[Flow][WARN] {self.fmt(args)}", flush=True)

    # ========
    # Defines error function for this experiment module.
    # ========
    def error(self, *args, **kwargs):
        print(f"[Flow][ERROR] {self.fmt(args)}", flush=True)

    # ========
    # Defines stage started function for this experiment module.
    # ========
    def stage_started(self, stage_id: str, title: str, *, message: str | None = None):
        self.info(message or title)

    # ========
    # Defines stage completed function for this experiment module.
    # ========
    def stage_completed(self, stage_id: str, title: str, *, message: str | None = None):
        self.info(message or title)

    # ========
    # Defines step started function for this experiment module.
    # ========
    def step_started(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
    ):
        if agent:
            self.info("%s: %s", agent, message or title)
        else:
            self.info("%s", message or title)

    # ========
    # Defines step delta function for this experiment module.
    # ========
    def step_delta(
        self,
        stage_id: str,
        step_id: str,
        content,
        *,
        delta_type: str = "text",
        agent: str | None = None,
        title: str | None = None,
    ):
        return None

    # ========
    # Defines step completed function for this experiment module.
    # ========
    def step_completed(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
        output_path: str | None = None,
        summary: dict | None = None,
    ):
        text = message or title
        if output_path:
            text = f"{text} ({output_path})"
        if agent:
            self.info("%s: %s", agent, text)
        else:
            self.info("%s", text)

    # ========
    # Defines artifact created function for this experiment module.
    # ========
    def artifact_created(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        output_path: str,
        *,
        message: str | None = None,
    ):
        self.info("%s: %s (%s)", step_id, message or title, output_path)

    # ========
    # Defines heartbeat function for this experiment module.
    # ========
    def heartbeat(
        self,
        stage_id: str | None = None,
        step_id: str | None = None,
        *,
        message: str = "仍在處理中",
    ):
        self.info("%s", message)

# ========
# Defines ExperimentStore class for this experiment module.
# ========
class ExperimentStore:

    # ========
    # Defines initialize function for this experiment module.
    # ========
    def __init__(self) -> None:
        self.project_id = "rq2_experiment"

        self.output_dir = Path(tempfile.gettempdir()) / "plant_rq2_experiment_store"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir = self.output_dir
        self.project_dir = self.output_dir
        self.artifact_dir = self.project_dir / "artifact"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    # ========
    # Defines save artifact function for this experiment module.
    # ========
    def save_artifact(self, data: Dict[str, Any]):
        save_split_artifact(self.project_dir, self.artifact_dir, data)

    # ========
    # Defines save json function for this experiment module.
    # ========
    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        pass

    # ========
    # Defines save markdown function for this experiment module.
    # ========
    def save_markdown(self, content: str, filename: str):
        save_markdown_file(self.artifact_dir, self.output_dir, content, filename)

    # ========
    # Defines save plantuml files function for this experiment module.
    # ========
    def save_plantuml_files(self, model_data: Dict[str, Any]):
        pass

    # ========
    # Defines save draft function for this experiment module.
    # ========
    def save_draft(self, content: str, version: int):
        pass

    # ========
    # Defines get draft version function for this experiment module.
    # ========
    def get_draft_version(self) -> int:
        return -1

    # ========
    # Defines load draft function for this experiment module.
    # ========
    def load_draft(self, version: int):
        return None

    # ========
    # Defines load markdown function for this experiment module.
    # ========
    def load_markdown(self, filename: str) -> str:
        return load_markdown_file(self.artifact_dir, self.output_dir, filename)

# ========
# Defines build plant cost payload function for this experiment module.
# ========
def build_plant_cost_payload(flow: Flow) -> Dict[str, Any]:
    cost_by_agent: Dict[str, Any] = {}
    for agent_name, m in flow.agent_models.items():
        if not hasattr(m, "costTracker"):
            continue
        summary = m.costTracker.export_summary_dict()

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

# ========
# Defines assert agent models have token pricing function for this experiment module.
# ========
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

# ========
# Defines load rq2 config function for this experiment module.
# ========
def load_rq2_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("Plant/config.json 內容必須是 JSON 物件")
    return cfg

# ========
# Defines build flow function for this experiment module.
# ========
def build_flow(config: Optional[Dict[str, Any]] = None) -> Flow:
    if config is None:
        config = load_rq2_config()
    check_provider_model_mismatch(config)
    assert_agent_models_have_token_pricing(config)
    return Flow(config=config, store=ExperimentStore(), logger=ExperimentLogger())

# ========
# Defines check provider model mismatch function for this experiment module.
# ========
def check_provider_model_mismatch(config: Dict[str, Any]) -> None:

    # ========
    # Defines looks openai function for this experiment module.
    # ========
    def looks_openai(model: str) -> bool:
        m = (model or "").lower()
        return m.startswith("gpt-") or m.startswith("o")

    # ========
    # Defines looks gemini function for this experiment module.
    # ========
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
