import argparse
import json
from pathlib import Path

from llm_judge import build_summary


SCRIPT_DIR = Path(__file__).resolve().parent
RQ3_DIR = SCRIPT_DIR.parent
DEFAULT_AGG_OUT = RQ3_DIR / "results" / "summary_srs_Baseline.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_fp", type=str, required=True)
    parser.add_argument("--save_fp", type=str, default=str(DEFAULT_AGG_OUT))
    args = parser.parse_args()

    in_path = Path(args.input_fp)
    with in_path.open(encoding="utf-8") as f:
        loaded = json.load(f)
    rows = loaded["record"] if isinstance(loaded, dict) and "record" in loaded else loaded

    payload = build_summary(rows)
    out_path = Path(args.save_fp)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(json.dumps(payload, indent=2, ensure_ascii=False))
