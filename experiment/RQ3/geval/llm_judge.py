import argparse
import json
import os
import re
import time
from pathlib import Path
from statistics import mean, pstdev

import tqdm
from dotenv import load_dotenv
from openai import OpenAI


SCRIPT_DIR = Path(__file__).resolve().parent
RQ3_DIR = SCRIPT_DIR.parent
BASE_DIR = RQ3_DIR.parent.parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "llm_config.json"
SRS_PROMPT_DIR = SCRIPT_DIR / "prompts"
# One prompt per metric, same spirit as upstream G-Eval SummEval prompts:
# https://github.com/nlpyang/geval
DIMENSION_PROMPTS: list[tuple[str, Path]] = [
    ("completeness", SRS_PROMPT_DIR / "com_detailed.txt"),
    ("correctness", SRS_PROMPT_DIR / "cor_detailed.txt"),
    ("cohesiveness", SRS_PROMPT_DIR / "coh_detailed.txt"),
]
EXAMPLE_DIR = SCRIPT_DIR / "example"
DATA_DIR = SCRIPT_DIR / "data"
DEFAULT_SAVE_FP = RQ3_DIR / "results" / "record_srs_Baseline.json"
DEFAULT_SUMMARY_FP = RQ3_DIR / "results" / "summary_srs_Baseline.json"


def resolve_path(raw: str, base_dir: Path) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def read_pdf_text(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader
    except ImportError as e:
        raise RuntimeError(
            f"讀取 PDF 需要 PyPDF2：{path}，請先安裝 `pip install PyPDF2`，"
            "或改用 .txt/.md 檔。"
        ) from e
    reader = PdfReader(str(path))
    pages = [p.extract_text() or "" for p in reader.pages]
    return "\n".join(pages).strip()


def read_text_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_text(path)
    return path.read_text(encoding="utf-8").strip()


def resolve_text(value: str, base_dir: Path) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("file://"):
        return read_text_path(Path(raw[len("file://") :]))
    if raw.startswith("@"):
        return read_text_path(Path(raw[1:]))

    maybe_path = resolve_path(raw, base_dir)
    if maybe_path.exists():
        return read_text_path(maybe_path)
    return raw


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_metric(output: str, metric_name: str) -> float:
    matched = re.search(rf"{metric_name}\s*:\s*([1-5](?:\.\d+)?)", output, flags=re.IGNORECASE)
    if not matched:
        return 0.0
    try:
        return float(matched.group(1))
    except ValueError:
        return 0.0


def build_summary(records: list[dict]) -> dict:
    metric_item_scores: dict[str, list[list[float]]] = {
        "completeness": [],
        "correctness": [],
        "cohesiveness": [],
    }
    for item in records:
        dims = item.get("dimensions") or {}
        comp_responses = (dims.get("completeness") or {}).get("all_responses", [])
        corr_responses = (dims.get("correctness") or {}).get("all_responses", [])
        cohe_responses = (dims.get("cohesiveness") or {}).get("all_responses", [])
        comp_scores = [parse_metric(x, "Completeness") for x in comp_responses]
        corr_scores = [parse_metric(x, "Correctness") for x in corr_responses]
        cohe_scores = [parse_metric(x, "Cohesiveness") for x in cohe_responses]
        metric_item_scores["completeness"].append(comp_scores)
        metric_item_scores["correctness"].append(corr_scores)
        metric_item_scores["cohesiveness"].append(cohe_scores)

    def round_means(score_lists: list[list[float]]) -> list[float]:
        max_len = max((len(x) for x in score_lists), default=0)
        values = []
        for i in range(max_len):
            ith = [scores[i] for scores in score_lists if i < len(scores)]
            if ith:
                values.append(mean(ith))
        return values

    comp_rounds = round_means(metric_item_scores["completeness"])
    corr_rounds = round_means(metric_item_scores["correctness"])
    cohe_rounds = round_means(metric_item_scores["cohesiveness"])

    run_candidates = [len(x) for x in [comp_rounds, corr_rounds, cohe_rounds] if x]
    runs = min(run_candidates) if run_candidates else 0

    def metric_stats(values: list[float]) -> dict:
        return {
            "mean": mean(values) if values else 0.0,
            "std": pstdev(values) if len(values) > 1 else 0.0,
            "per_round_values": values,
        }

    return {
        "runs": runs,
        "metrics": {
            "completeness": metric_stats(comp_rounds),
            "correctness": metric_stats(corr_rounds),
            "cohesiveness": metric_stats(cohe_rounds),
        },
    }


def build_instances() -> list[dict]:
    if not EXAMPLE_DIR.exists():
        raise RuntimeError(f"找不到參考範例資料夾：{EXAMPLE_DIR}")
    ref_candidates = sorted(
        [
            p
            for p in EXAMPLE_DIR.glob("*")
            if p.is_file() and p.suffix.lower() in {".txt", ".md", ".pdf"}
        ]
    )
    if not ref_candidates:
        raise RuntimeError(f"找不到參考範例：{EXAMPLE_DIR}")
    ref_path = ref_candidates[0]
    gt_path = ref_path

    if not DATA_DIR.exists():
        raise RuntimeError(f"找不到待評分資料夾：{DATA_DIR}")
    candidates = sorted([p for p in DATA_DIR.glob("*.md") if p.is_file()])
    if not candidates:
        raise RuntimeError(f"找不到待評分 SRS 檔案（*.md）：{DATA_DIR}")

    instances = []
    for fp in candidates:
        instances.append(
            {
                "item_id": fp.stem,
                "reference_example": str(ref_path),
                "ground_truth_requirements": str(gt_path),
                "candidate_srs": str(fp),
            }
        )
    return instances


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--model", type=str, default="")
    parser.add_argument("--temperature", type=float, default=-1.0)
    parser.add_argument("--max_tokens", type=int, default=-1)
    parser.add_argument("--n", type=int, default=-1)
    args = parser.parse_args()

    load_dotenv(dotenv_path=BASE_DIR / ".env")
    cfg = load_config(resolve_path(args.config, SCRIPT_DIR))
    model = args.model or cfg.get("model", "gpt-5.2")
    temperature = args.temperature if args.temperature >= 0 else float(cfg.get("temperature", 1.0))
    max_tokens = args.max_tokens if args.max_tokens > 0 else int(cfg.get("max_tokens", 80))
    n = args.n if args.n > 0 else int(cfg.get("n", 20))
    save_fp = DEFAULT_SAVE_FP

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("未設定 OPENAI_API_KEY（請在專案根目錄 .env 設定）")
    client = OpenAI(api_key=api_key)

    instances = build_instances()

    ignore = 0
    output_json = []
    for instance in tqdm.tqdm(instances):
        ref_example = resolve_text(instance.get("reference_example", ""), SCRIPT_DIR)
        ground_truth = resolve_text(instance.get("ground_truth_requirements", ""), SCRIPT_DIR)
        candidate = resolve_text(instance.get("candidate_srs", ""), SCRIPT_DIR)

        record = dict(instance)
        record["dimensions"] = {}

        for dim_key, prompt_path in DIMENSION_PROMPTS:
            if not prompt_path.is_file():
                raise RuntimeError(f"找不到 prompt：{prompt_path}")
            tmpl = prompt_path.read_text(encoding="utf-8")
            cur_prompt = (
                tmpl.replace("{{ReferenceExample}}", ref_example)
                .replace("{{GroundTruthRequirements}}", ground_truth)
                .replace("{{CandidateSRS}}", candidate)
            )

            while True:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": cur_prompt}],
                        temperature=temperature,
                        max_completion_tokens=max_tokens,
                        top_p=1,
                        frequency_penalty=0,
                        presence_penalty=0,
                        stop=None,
                        n=n,
                    )
                    time.sleep(0.5)
                    all_responses = [
                        (choice.message.content or "")
                        for choice in (response.choices or [])
                    ]
                    record["dimensions"][dim_key] = {
                        "prompt_file": prompt_path.name,
                        "prompt": cur_prompt,
                        "all_responses": all_responses,
                    }
                    break
                except Exception as e:
                    print(e)
                    if "limit" in str(e).lower():
                        time.sleep(2)
                    else:
                        ignore += 1
                        print("ignored", ignore)
                        record["dimensions"][dim_key] = {
                            "prompt_file": prompt_path.name,
                            "prompt": cur_prompt,
                            "all_responses": [],
                            "error": str(e),
                        }
                        break

        output_json.append(record)

    print("ignored total", ignore)
    save_fp.parent.mkdir(parents=True, exist_ok=True)
    record_payload = {"record": output_json}
    with save_fp.open("w", encoding="utf-8") as f:
        json.dump(record_payload, f, indent=4, ensure_ascii=False)

    summary_payload = build_summary(output_json)
    with DEFAULT_SUMMARY_FP.open("w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2, ensure_ascii=False)

    print(f"saved record: {save_fp}")
    print(f"saved summary: {DEFAULT_SUMMARY_FP}")
