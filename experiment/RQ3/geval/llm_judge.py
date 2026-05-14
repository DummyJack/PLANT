import argparse
import json
import os
import re
import time
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import tqdm
from dotenv import load_dotenv
from openai import OpenAI


SCRIPT_DIR = Path(__file__).resolve().parent
RQ3_DIR = SCRIPT_DIR.parent
BASE_DIR = RQ3_DIR.parent.parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "llm_config.json"
SRS_PROMPT_DIR = SCRIPT_DIR / "prompts"
EXAMPLE_DIR = SCRIPT_DIR / "example"
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = RQ3_DIR / "results"

DIMENSION_PROMPTS: list[tuple[str, Path]] = [
    ("completeness", SRS_PROMPT_DIR / "com_detailed.txt"),
    ("correctness", SRS_PROMPT_DIR / "cor_detailed.txt"),
    ("cohesiveness", SRS_PROMPT_DIR / "coh_detailed.txt"),
]

SUPPORTED_SOURCE_SUFFIXES = {".md", ".txt", ".pdf", ".docx", ".doc"}

def resolve_path(raw: str, base_dir: Path) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def resolve_source_path(value: str, base_dir: Path) -> Path | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("file://"):
        p = Path(raw[len("file://") :]).resolve()
        return p if p.exists() else None
    if raw.startswith("@"):
        p = Path(raw[1:]).resolve()
        return p if p.exists() else None
    maybe_path = resolve_path(raw, base_dir)
    return maybe_path if maybe_path.exists() else None


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_reference_example_path(config: dict) -> Path | None:
    raw = str(config.get("reference_example", "") or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.suffix:
        p = resolve_source_path(raw, EXAMPLE_DIR)
        if p is None:
            p = resolve_source_path(raw, SCRIPT_DIR)
        if p and p.is_file():
            return p.resolve()
        return None

    stem = candidate.name
    matches = []
    for ext in (".pdf", ".md", ".docx", ".doc", ".txt"):
        p = (EXAMPLE_DIR / f"{stem}{ext}").resolve()
        if p.is_file():
            matches.append(p)
    if len(matches) == 1:
        return matches[0]
    return None


def discover_candidate_srss() -> list[Path]:
    if not DATA_DIR.exists():
        raise RuntimeError(f"找不到待評分資料夾：{DATA_DIR}")
    candidates = sorted(
        p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
    )
    if not candidates:
        raise RuntimeError(
            f"找不到 Candidate SRS 檔案：{DATA_DIR}（支援 {sorted(SUPPORTED_SOURCE_SUFFIXES)}）"
        )
    return candidates


def upload_file_once(client: OpenAI, *, path: Path, cache: dict[Path, str]) -> str:
    path = path.resolve()
    if path in cache:
        return cache[path]
    with path.open("rb") as f:
        created = client.files.create(file=f, purpose="user_data")
    cache[path] = created.id
    return created.id


def parse_metric(output: str, metric_name: str) -> float | None:
    matched = re.search(rf"{metric_name}\s*:\s*([1-5](?:\.\d+)?)", output, flags=re.IGNORECASE)
    if not matched:
        return None
    try:
        return float(matched.group(1))
    except ValueError:
        return None


def build_summary(records: list[dict]) -> dict:
    metric_item_scores: dict[str, list[list[float]]] = {
        "completeness": [],
        "correctness": [],
        "cohesiveness": [],
    }
    for item in records:
        for metric in metric_item_scores:
            scores = [
                float(x)
                for x in ((item.get(metric) or {}).get("scores", []) or [])
                if x is not None
            ]
            metric_item_scores[metric].append(scores)

    def round_means(score_lists: list[list[float]]) -> list[float]:
        max_len = max((len(x) for x in score_lists), default=0)
        values = []
        for i in range(max_len):
            ith = [scores[i] for scores in score_lists if i < len(scores)]
            if ith:
                values.append(mean(ith))
        return values

    def metric_stats(values: list[float]) -> dict[str, Any]:
        return {
            "mean": mean(values) if values else 0.0,
            "std": pstdev(values) if len(values) > 1 else 0.0,
            "per_round_values": values,
        }

    comp_rounds = round_means(metric_item_scores["completeness"])
    corr_rounds = round_means(metric_item_scores["correctness"])
    cohe_rounds = round_means(metric_item_scores["cohesiveness"])
    run_candidates = [len(x) for x in [comp_rounds, corr_rounds, cohe_rounds] if x]

    return {
        "runs": min(run_candidates) if run_candidates else 0,
        "metrics": {
            "completeness": metric_stats(comp_rounds),
            "correctness": metric_stats(corr_rounds),
            "cohesiveness": metric_stats(cohe_rounds),
        },
    }


def output_paths_for_item(item_stem: str) -> tuple[Path, Path]:
    stem = str(item_stem or "").strip()
    if stem.lower().startswith("srs_"):
        stem = stem[4:]
    safe_stem = re.sub(r"[^\w.-]+", "_", stem) or "candidate"
    return (
        RESULTS_DIR / f"record_{safe_stem}.json",
        RESULTS_DIR / f"summary_{safe_stem}.json",
    )


def build_prompt_text(prompt_path: Path) -> str:
    tmpl = prompt_path.read_text(encoding="utf-8")
    return (
        tmpl.replace("{{ReferenceExample}}", "[Attached file: Reference SRS Example]")
        .replace("{{GroundTruthRequirements}}", "")
        .replace("{{CandidateSRS}}", "[Attached file: Evaluated SRS]")
    )


def response_texts(
    client: OpenAI,
    *,
    model: str,
    prompt_text: str,
    candidate_file_id: str,
    reference_file_id: str | None,
    n: int,
    max_output_tokens: int,
    enable_temperature: bool,
    temperature: float,
    enable_reasoning: bool,
    reasoning_effort: str,
    enable_web_search: bool,
) -> list[str]:
    contents: list[str] = []
    tools = [{"type": "web_search_preview"}] if enable_web_search else None
    input_items = [{"role": "user", "content": [{"type": "input_text", "text": prompt_text}]}]
    file_parts = []
    if reference_file_id:
        file_parts.append({"type": "input_file", "file_id": reference_file_id})
    file_parts.append({"type": "input_file", "file_id": candidate_file_id})
    input_items[0]["content"].extend(file_parts)

    for _ in range(max(1, int(n))):
        kwargs: dict[str, Any] = {
            "model": model,
            "input": input_items,
            "max_output_tokens": max_output_tokens,
        }
        if enable_temperature:
            kwargs["temperature"] = temperature
        if enable_reasoning and reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = client.responses.create(**kwargs)
        contents.append((response.output_text or "").strip())
        time.sleep(0.5)
    return contents


def confirm_without_reference() -> bool:
    try:
        answer = input("找不到 ReferenceExample，仍要繼續執行 judge 嗎？(yes/no): ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--model", type=str, default="")
    args = parser.parse_args()

    load_dotenv(dotenv_path=BASE_DIR / ".env")
    cfg = load_config(resolve_path(args.config, SCRIPT_DIR))

    model = args.model or str(cfg.get("model") or "gpt-5.2")
    max_output_tokens = int(cfg.get("max_output_tokens", cfg.get("max_tokens", 120)) or 120)
    n = int(cfg.get("n", 3) or 3)
    enable_temperature = bool(cfg.get("enable_temperature", False))
    temperature = float(cfg.get("temperature", 1.0) or 1.0)
    enable_reasoning = bool(cfg.get("enable_reasoning", False))
    reasoning_effort = str(cfg.get("reasoning_effort") or "").strip()
    enable_web_search_for_correctness = bool(cfg.get("enable_web_search_for_correctness", False))

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("未設定 OPENAI_API_KEY（請在專案根目錄 .env 設定）")
    client = OpenAI(api_key=api_key)

    candidate_paths = discover_candidate_srss()
    reference_path = resolve_reference_example_path(cfg)
    if reference_path is None:
        print("警告：未找到 ReferenceExample。")
        if not confirm_without_reference():
            print("已取消執行。")
            return 1

    file_cache: dict[Path, str] = {}
    reference_file_id = None
    if reference_path:
        reference_file_id = upload_file_once(client, path=reference_path, cache=file_cache)

    ignore = 0

    for candidate_path in tqdm.tqdm(candidate_paths):
        candidate_file_id = upload_file_once(client, path=candidate_path, cache=file_cache)
        record: dict[str, Any] = {"item_id": candidate_path.stem}

        for dim_key, prompt_path in DIMENSION_PROMPTS:
            prompt_text = build_prompt_text(prompt_path)
            use_web_search = dim_key == "correctness" and enable_web_search_for_correctness
            try:
                all_responses = response_texts(
                    client,
                    model=model,
                    prompt_text=prompt_text,
                    candidate_file_id=candidate_file_id,
                    reference_file_id=reference_file_id,
                    n=n,
                    max_output_tokens=max_output_tokens,
                    enable_temperature=enable_temperature,
                    temperature=temperature,
                    enable_reasoning=enable_reasoning,
                    reasoning_effort=reasoning_effort,
                    enable_web_search=use_web_search,
                )
                metric_label = dim_key.capitalize()
                scores = [parse_metric(x, metric_label) for x in all_responses]
                record[dim_key] = {
                    "scores": scores,
                    "responses": all_responses,
                }
            except Exception as e:
                ignore += 1
                print(e)
                print("ignored", ignore)
                record[dim_key] = {
                    "scores": [],
                    "responses": [],
                    "error": str(e),
                }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        record_fp, summary_fp = output_paths_for_item(candidate_path.stem)
        with record_fp.open("w", encoding="utf-8") as f:
            json.dump({"record": [record]}, f, indent=2, ensure_ascii=False)

        summary_payload = build_summary([record])
        with summary_fp.open("w", encoding="utf-8") as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        print(f"saved record: {record_fp}")
        print(f"saved summary: {summary_fp}")

    print("ignored total", ignore)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
