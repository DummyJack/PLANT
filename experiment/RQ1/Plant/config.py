# Provides RQ1 Plant experiment config helpers.
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from flow.setup import Flow
from utils import model_has_token_pricing

from .oracle_user import OracleConfigs

GEMINI_OPENAI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

# ========
# Defines ExperimentLogger class for this experiment module.
# ========
class ExperimentLogger:

    # ========
    # Defines initialize function for this experiment module.
    # ========
    def __init__(self, verbose: bool = True):
        self.verbose = bool(verbose)

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
        fmt_args = args[1:]
        try:
            return msg % fmt_args
        except Exception:
            return " ".join(str(x) for x in args)

    # ========
    # Defines info function for this experiment module.
    # ========
    def info(self, *args, **kwargs):
        if self.verbose:
            print(self.fmt(args))

    # ========
    # Defines debug function for this experiment module.
    # ========
    def debug(self, *args, **kwargs):
        return None

    # ========
    # Defines warning function for this experiment module.
    # ========
    def warning(self, *args, **kwargs):
        print(f"[Flow][WARN] {self.fmt(args)}")

    # ========
    # Defines error function for this experiment module.
    # ========
    def error(self, *args, **kwargs):
        print(f"[Flow][ERROR] {self.fmt(args)}")

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
    def __init__(self, results_dir: Path) -> None:
        self.project_id = "rq1_plant_elicitation"
        self.output_dir = results_dir
        self.project_dir = results_dir
        self.artifact_dir = self.project_dir / "artifact"

    # ========
    # Defines save artifact function for this experiment module.
    # ========
    def save_artifact(self, data: Dict[str, Any]):
        pass

    # ========
    # Defines save json function for this experiment module.
    # ========
    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        pass

    # ========
    # Defines save markdown function for this experiment module.
    # ========
    def save_markdown(self, content: str, filename: str):
        pass

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
# Defines load json function for this experiment module.
# ========
def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"設定檔必須是 JSON object: {path}")
    return data

# ========
# Defines apply rq1 flow overrides function for this experiment module.
# ========
def apply_rq1_flow_overrides(flow_cfg: Dict[str, Any], exp_cfg: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(flow_cfg)
    if isinstance(exp_cfg.get("enable_agents"), dict):
        updated["enable_agents"] = exp_cfg["enable_agents"]
    if isinstance(exp_cfg.get("agent_models"), dict):
        updated["agent_models"] = exp_cfg["agent_models"]
    updated["rounds"] = 0
    if exp_cfg.get("elicitation_max_turns") is not None:
        updated["elicitation_max_turns"] = int(exp_cfg["elicitation_max_turns"])
    return updated

# ========
# Defines assert models have pricing function for this experiment module.
# ========
def assert_models_have_pricing(flow_cfg: Dict[str, Any], exp_cfg: Dict[str, Any]) -> None:
    for agent, info in (flow_cfg.get("agent_models") or {}).items():
        if agent == "default" or not isinstance(info, dict):
            continue
        model_name = str(info.get("model") or "").strip()
        if model_name and (not model_has_token_pricing(model_name)):
            print(
                f"警告：沒有找到 token 的定價：agent_models.{agent} 模型「{model_name}」。"
                "請在 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上定價。"
            )
            sys.exit(1)
    gym_model = str(exp_cfg.get("gym_model") or "").strip()
    if gym_model and (not model_has_token_pricing(gym_model)):
        print(
            f"警告：沒有找到 token 的定價：gym_model 模型「{gym_model}」。"
            "請在 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上定價。"
        )
        sys.exit(1)

# ========
# Defines build flow function for this experiment module.
# ========
def build_flow(flow_cfg: Dict[str, Any], *, verbose: bool, results_dir: Path) -> Flow:
    flow = Flow(
        config=flow_cfg,
        store=ExperimentStore(results_dir),
        logger=ExperimentLogger(verbose=verbose),
    )
    disable_rq1_candidate_extraction(flow)
    return flow

# ========
# Defines disable rq1 candidate extraction function for this experiment module.
# ========
def disable_rq1_candidate_extraction(flow: Flow) -> None:

    # ========
    # Defines skip extract elicited reqts function for this experiment module.
    # ========
    def skip_extract_elicited_reqts(*args, **kwargs):
        return []

    flow.analyst_agent.extract_elicited_reqts = skip_extract_elicited_reqts

# ========
# Defines build oracle configs function for this experiment module.
# ========
def model_provider(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if normalized.startswith("gemini-"):
        return "gemini"
    return "openai"


def endpoint_for_model(model_name: str) -> tuple[str, str]:
    provider = model_provider(model_name)
    if provider == "gemini":
        return (
            os.environ.get("GEMINI_API_KEY", ""),
            os.environ.get("GEMINI_BASE_URL") or GEMINI_OPENAI_COMPAT_BASE,
        )
    return (
        os.environ.get("OPENAI_API_KEY", ""),
        os.environ.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL,
    )


def build_oracle_configs(exp_cfg: Dict[str, Any]) -> OracleConfigs:
    gym_model = str(exp_cfg.get("gym_model") or "").strip()
    if not gym_model:
        raise ValueError("Plant/config.json 必須設定 gym_model")
    api_key, base_url = endpoint_for_model(gym_model)
    if not api_key:
        required_key = "GEMINI_API_KEY" if model_provider(gym_model) == "gemini" else "OPENAI_API_KEY"
        raise ValueError(f"gym_model={gym_model} 需要在 .env 設定 {required_key}")
    judge_api_key = os.getenv("JUDGE_API_KEY", api_key)
    user_api_key = os.getenv("USER_API_KEY", api_key)
    judge_base_url = os.getenv("JUDGE_BASE_URL", base_url)
    user_base_url = os.getenv("USER_BASE_URL", base_url)
    oracle_user = {
        "api_key": user_api_key,
        "base_url": user_base_url,
        "model_name": gym_model,
        "temperature": float(exp_cfg.get("user_temperature", 0.7)),
        "timeout": float(exp_cfg.get("user_timeout", 30.0)),
    }
    oracle_judge = {
        "api_key": judge_api_key,
        "base_url": judge_base_url,
        "model_name": gym_model,
        "temperature": float(exp_cfg.get("judge_temperature", 0.0)),
        "max_tokens": int(exp_cfg.get("judge_max_tokens", 1024)),
        "timeout": float(exp_cfg.get("judge_timeout", 30.0)),
    }
    return OracleConfigs(
        judge_model_config=oracle_judge,
        user_model_config=oracle_user,
    )
