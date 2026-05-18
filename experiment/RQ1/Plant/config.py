import json
import sys
from pathlib import Path
from typing import Any, Dict

from flow.setup import Flow
from utils import model_has_token_pricing

from .oracle_user import OracleConfigs


class ExperimentLogger:
    def __init__(self, verbose: bool = True):
        self.verbose = bool(verbose)

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

    def info(self, *args, **kwargs):
        if self.verbose:
            print(self.fmt(args))

    def warning(self, *args, **kwargs):
        print(f"[Flow][WARN] {self.fmt(args)}")

    def error(self, *args, **kwargs):
        print(f"[Flow][ERROR] {self.fmt(args)}")


class ExperimentStore:
    """RQ1 experiment store: only keep primary experiment output files."""

    def __init__(self, results_dir: Path) -> None:
        self.project_id = "rq1_plant_elicitation"
        self.output_dir = results_dir
        self.project_dir = results_dir
        self.artifact_dir = self.project_dir / "artifact"

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


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"設定檔必須是 JSON object: {path}")
    return data


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
    for k in ("oracle_user", "oracle_judge"):
        model_name = str((exp_cfg.get(k) or {}).get("model") or "").strip()
        if model_name and (not model_has_token_pricing(model_name)):
            print(
                f"警告：沒有找到 token 的定價：{k} 模型「{model_name}」。"
                "請在 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上定價。"
            )
            sys.exit(1)


def build_flow(flow_cfg: Dict[str, Any], *, verbose: bool, results_dir: Path) -> Flow:
    flow = Flow(
        config=flow_cfg,
        store=ExperimentStore(results_dir),
        logger=ExperimentLogger(verbose=verbose),
    )
    disable_rq1_candidate_extraction(flow)
    return flow


def disable_rq1_candidate_extraction(flow: Flow) -> None:
    """RQ1 metric 只依 oracle_trace.revealed_ids 計分，不需要每輪 LLM candidate extraction。"""

    def skip_extract_elicited_reqts(*args, **kwargs):
        return []

    flow.analyst_agent.extract_elicited_reqts = skip_extract_elicited_reqts


def build_oracle_configs(exp_cfg: Dict[str, Any], api_key: str, base_url: str) -> OracleConfigs:
    user_cfg = exp_cfg.get("oracle_user") or {}
    judge_cfg = exp_cfg.get("oracle_judge") or {}
    oracle_user = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": str(user_cfg.get("model") or ""),
        "temperature": float(user_cfg.get("temperature", 0.7)),
        "max_tokens": int(user_cfg.get("max_tokens", 1024)),
        "timeout": float(user_cfg.get("timeout", 30.0)),
    }
    oracle_judge = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": str(judge_cfg.get("model") or ""),
        "temperature": float(judge_cfg.get("temperature", 0.0)),
        "max_tokens": int(judge_cfg.get("max_tokens", 1024)),
        "timeout": float(judge_cfg.get("timeout", 30.0)),
    }
    return OracleConfigs(
        judge_model_config=oracle_judge,
        user_model_config=oracle_user,
    )
