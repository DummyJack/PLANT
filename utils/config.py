# Config helpers for model summaries and human settings.
from typing import Any, Dict


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


def human_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    """與人類互動／核准／挖掘流程相關設定。

    優先讀 config["human"][key]；若無則讀頂層同名鍵；再否則 default。
    """
    block = config.get("human")
    if isinstance(block, dict) and key in block:
        return block[key]
    return config.get(key, default)


def meeting_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    """讀取會議開關設定。

    優先讀 config["enable_meeting"][key]；若無則 default。
    """
    block = config.get("enable_meeting")
    if isinstance(block, dict) and key in block:
        return block[key]
    return default
