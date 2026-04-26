from typing import Any, Dict

MAX_ITERATIONS: int = 1
TOOL_CALL_MAX_ROUNDS: int = 1
MAX_WEB_SEARCH_RESULTS: int = 5


def format_loaded_models_summary(config: dict) -> str:
    """僅依 config 內 agent_models 原樣列出；不顯示 default 槽位。"""
    am = config.get("agent_models") or {}
    parts: list[str] = []
    for name, slot in am.items():
        if name == "default":
            continue
        if not isinstance(slot, dict):
            continue
        raw = slot.get("model")
        model_name = raw if (raw is not None and str(raw).strip() != "") else "—"
        parts.append(f"{name}: {model_name}")
    if not parts:
        return "✓ 載入配置（agent_models 無有效項目）"
    return "✓ 載入配置 — " + "；".join(parts)


def read_max_iterations(
    config: Dict[str, Any],
    *,
    default: int = 3,
) -> int:
    """回傳固定的 MAX_ITERATIONS；保留簽名以相容既有呼叫點。"""
    _ = config, default
    return MAX_ITERATIONS


def human_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    """與人類互動／核准／挖掘流程相關設定。

    優先讀 config["human"][key]；若無則讀頂層同名鍵（舊版或實驗腳本直接寫入 flow.config 時相容）；再否則 default。
    """
    block = config.get("human")
    if isinstance(block, dict) and key in block:
        return block[key]
    return config.get(key, default)
