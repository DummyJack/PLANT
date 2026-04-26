import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

RQ3_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ3_DIR.parent.parent
for p in (BASE_DIR, RQ3_DIR):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from flow.main import Flow
from flow.project_flow import (
    _run_one_round,
    _sync_project_output_language,
    _write_pre_meeting_conflict_report,
)
from storage import Store
from utils import Logger, json_dump_no_scientific


RESULTS_DIR = RQ3_DIR / "results"
RESULT_PREFIX = "Plant"
BASE_CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_PATH = RQ3_DIR / "config_RQ3.json"
SCENARIO_PATH = RQ3_DIR / "scenario.txt"
PROJECT_ID = "rq3_plant"


def load_scenario_text() -> str:
    if SCENARIO_PATH.is_file():
        return SCENARIO_PATH.read_text(encoding="utf-8").strip()
    return ""


def is_likely_english(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    cjk = re.findall(r"[\u4e00-\u9fff]", s)
    if not letters:
        return False
    if not cjk:
        return True
    return len(letters) >= (len(cjk) * 2)


def sync_output_language(rough_idea: str) -> str:
    lang = "en" if is_likely_english(rough_idea) else "zh-Hant"
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    return lang


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(base_value, value)
        else:
            merged[key] = value
    return merged


def load_flow_config() -> Dict[str, Any]:
    with BASE_CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)
    if CONFIG_PATH.is_file():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            rq3_override = json.load(f)
        if not isinstance(rq3_override, dict):
            raise ValueError("config_RQ3.json 內容必須是 JSON 物件")
        config = _deep_merge_dict(config, rq3_override)
    config["rounds"] = int(config.get("rounds", 1) or 1)
    return config


def load_rq3_stakeholders(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = config.get("stakeholder") or []
    if not isinstance(payload, list):
        raise ValueError("config_RQ3.json 的 stakeholder 內容必須是陣列")
    normalized: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        texts = item.get("text") or []
        if not name or not isinstance(texts, list):
            continue
        cleaned = [str(x).strip() for x in texts if str(x).strip()]
        if not cleaned:
            continue
        normalized.append({"name": name, "text": cleaned})
    return normalized


def build_seeded_artifact(scenario: str, stakeholders: List[Dict[str, Any]], rounds: int) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "rough_idea": scenario,
        "stakeholders": stakeholders,
        "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
        "requirements": [],
        "conflicts": [],
        "feedback": {},
        "system_models": {},
        "discussions": [],
        "decisions": [],
        "open_questions": [],
        "meta": {
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
            "updated_by": "rq3.plant.seeded_artifact",
            "last_round": 0,
            "session_end_round": int(rounds),
            "rq3_seeded_stakeholders": bool(stakeholders),
        },
    }


def run_rq3_flow(flow: Flow, scenario: str, stakeholders: List[Dict[str, Any]]) -> Dict[str, Any]:
    rounds = int(flow.config.get("rounds", 1) or 1)
    artifact = build_seeded_artifact(scenario, stakeholders, rounds)
    artifact = flow._ensure_artifact_contract(artifact)
    _sync_project_output_language(artifact)
    flow._touch_artifact_meta(
        artifact,
        updated_by="rq3.plant.init",
        round_num=0,
    )
    flow.store.save_artifact(artifact)

    flow.logger.info("=== Phase 0: 初始草稿建立（RQ3 seeded stakeholders） ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)
    _write_pre_meeting_conflict_report(flow, artifact, round_num=0)

    for round_num in range(1, rounds + 1):
        artifact = _run_one_round(flow, artifact, round_num)

    flow.logger.info("=== 規格化 ===")
    flow.finalize(artifact)
    flow.logger.info("流程完成！")
    return artifact


def main() -> None:
    load_dotenv(dotenv_path=BASE_DIR / ".env")

    scenario = load_scenario_text()
    if not scenario:
        print(f"找不到情境檔案：{SCENARIO_PATH}")
        sys.exit(1)

    out_lang = sync_output_language(scenario)
    config = load_flow_config()
    seeded_stakeholders = load_rq3_stakeholders(config)

    store = Store(BASE_DIR, PROJECT_ID)
    logger = Logger(store.log_dir)
    flow = Flow(config=config, store=store, logger=logger)

    run_rq3_flow(flow, scenario, seeded_stakeholders)

    srs_src = store.output_dir / "srs.md"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    srs_dst = RESULTS_DIR / f"srs_{RESULT_PREFIX}.md"
    cost_dst = RESULTS_DIR / f"cost_{RESULT_PREFIX}.json"

    if not srs_src.is_file():
        raise RuntimeError(f"Plant 未產出正式 SRS：{srs_src}")

    shutil.copyfile(srs_src, srs_dst)

    cost_payload = flow._build_cost_summary() or {
        "project_id": store.project_id,
        "agents": {},
        "totals": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "run_time(s)": 0.0,
            "estimated_cost(USD)": 0.0,
        },
    }
    with cost_dst.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)

    print(f"RQ3 Plant output language={out_lang}")
    print(f"輸出 SRS：{srs_dst}")
    print(f"輸出 cost：{cost_dst}")


if __name__ == "__main__":
    main()
