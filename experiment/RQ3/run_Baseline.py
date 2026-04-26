import os
import sys
from pathlib import Path
from typing import Any

RQ3_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ3_DIR.parent.parent
for p in (BASE_DIR, RQ3_DIR):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from dotenv import load_dotenv
from openai import OpenAI

from utils import CostTracker, json_dump_no_scientific, model_has_token_pricing

RESULTS_DIR = RQ3_DIR / "results"
RESULT_PREFIX = "Baseline"
SCENARIO_PATH = RQ3_DIR / "scenario.txt"

# 實驗參數設置（"openai" 或 "gemini"，與 RQ2 Baseline 一致）
BASELINE_PROVIDER = "openai"
MODEL_NAME = "gpt-4.1"
TEMPERATURE = 0.0

def build_srs_prompt(scenario: str) -> list[dict[str, str]]:
    user = f"""請依據設置的情境：{scenario.strip()}，產生一份軟體需求規格書，以 Markdown 格式撰寫，請不要產生和規格書無關的內容。""".strip()

    return [{"role": "user", "content": user}]


def load_scenario_text() -> str:
    if SCENARIO_PATH.is_file():
        return SCENARIO_PATH.read_text(encoding="utf-8").strip()
    return ""


def prompt_scenario_interactive() -> str:
    """當找不到情境檔或內容為空時，改由使用者於終端機輸入。"""
    print(f"找不到情境檔或內容為空：{SCENARIO_PATH}")
    return input("請輸入情境說明：").strip()


def messages_user_text(messages: list[dict[str, str]]) -> str:
    parts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    return "\n\n".join(parts).strip()


def gemini_response_text(response: Any) -> str:
    try:
        t = getattr(response, "text", None)
        if t:
            return t
    except Exception:
        pass
    if getattr(response, "candidates", None):
        parts: list[str] = []
        for c in response.candidates:
            for p in getattr(c.content, "parts", []) or []:
                if getattr(p, "text", None):
                    parts.append(p.text)
        return "".join(parts)
    return ""


def call_openai_srs(
    client: OpenAI,
    model_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    tracker: CostTracker,
) -> tuple[str, dict[str, Any]]:
    tracker.start()
    resp = None
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
        )
    finally:
        run_s = tracker.end_segment()

    if resp is None:
        raise RuntimeError("OpenAI 回傳為空")

    usage = getattr(resp, "usage", None)
    if usage:
        tracker.addUsage(
            {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            },
            run_time_s=run_s,
        )

    if not getattr(resp, "choices", None):
        raise RuntimeError("OpenAI 未返回 choices")
    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("OpenAI 回傳內容為空")

    raw_resp: dict[str, Any] = {
        "id": getattr(resp, "id", None),
        "model": getattr(resp, "model", model_name),
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
        },
    }
    return content, raw_resp


def call_gemini_srs(
    genai_client: Any,
    genai_types: Any,
    model_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    tracker: CostTracker,
) -> tuple[str, dict[str, Any]]:
    user_prompt = messages_user_text(messages)
    if not user_prompt:
        raise RuntimeError("Gemini：messages 中無 user 內容")

    cfg = genai_types.GenerateContentConfig(temperature=temperature)
    tracker.start()
    response = None
    try:
        response = genai_client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=cfg,
        )
    finally:
        run_s = tracker.end_segment()

    um = getattr(response, "usage_metadata", None) if response is not None else None
    if um:
        prompt = getattr(um, "prompt_token_count", 0) or 0
        cand = getattr(um, "candidates_token_count", 0) or 0
        total = getattr(um, "total_token_count", None)
        if total is None:
            total = prompt + cand
        tracker.addUsage(
            {
                "prompt_tokens": prompt,
                "completion_tokens": cand,
                "total_tokens": int(total),
            },
            run_time_s=run_s,
        )

    content = gemini_response_text(response).strip()
    if not content:
        raise RuntimeError("Gemini 無回應內容（可能被安全過濾或無候選）")

    return content, {}


def main() -> None:
    load_dotenv(dotenv_path=BASE_DIR / ".env")
    provider = (BASELINE_PROVIDER or "openai").strip().lower()
    if provider not in ("openai", "gemini"):
        print(f"錯誤：不支援的 BASELINE_PROVIDER「{BASELINE_PROVIDER}」（請用 openai 或 gemini）")
        sys.exit(1)

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("錯誤：未找到 OPENAI_API_KEY")
            sys.exit(1)
    else:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("錯誤：未找到 GEMINI_API_KEY")
            sys.exit(1)

    scenario = load_scenario_text()
    if not scenario:
        scenario = prompt_scenario_interactive()
    if not scenario:
        print("錯誤：未提供情境內容")
        sys.exit(1)

    model_name = str(MODEL_NAME).strip()
    temperature = float(TEMPERATURE)

    if not model_name:
        print("錯誤：model 不可為空")
        sys.exit(1)
    if not model_has_token_pricing(model_name):
        print(
            f"錯誤：模型 {model_name} 沒有 token 定價，"
            "請先在 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 加入定價。"
        )
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    srs_path = RESULTS_DIR / f"srs_{RESULT_PREFIX}.md"
    cost_path = RESULTS_DIR / f"cost_{RESULT_PREFIX}.json"

    print(f"RQ3 Baseline provider={provider} model={model_name}")
    print("輸出語言：繁體中文")
    print(f"輸出 SRS：{srs_path}")

    tracker = CostTracker(model_name=model_name)
    messages = build_srs_prompt(scenario)

    if provider == "openai":
        client = OpenAI(api_key=api_key)
        srs_markdown, _ = call_openai_srs(
            client=client,
            model_name=model_name,
            messages=messages,
            temperature=temperature,
            tracker=tracker,
        )
    else:
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError:
            print("錯誤：使用 Gemini 請先安裝 google-genai（見 requirements.txt）")
            raise SystemExit(1)
        genai_client = genai.Client(api_key=api_key)
        srs_markdown, _ = call_gemini_srs(
            genai_client=genai_client,
            genai_types=genai_types,
            model_name=model_name,
            messages=messages,
            temperature=temperature,
            tracker=tracker,
        )

    srs_path.write_text(srs_markdown, encoding="utf-8")

    cost_payload = tracker.export_summary_dict()
    with cost_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)

    print(f"已完成：{srs_path}")
    print(f"已儲存 cost：{cost_path}")


if __name__ == "__main__":
    main()
