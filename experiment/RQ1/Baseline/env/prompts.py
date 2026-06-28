import os
import time
from openai import OpenAI
from typing import Dict, Any, List
from .utils import (
    build_history_into_prompt,
    parse_output_as_json,
    relevant_requirement_ids_from_judgement,
)
from .utils import JUDGE_PROMPT_SYSTEM, JUDGE_PROMPT_USER
from .utils import PASSIVE_RESPONSE_SYSTEM, PASSIVE_RESPONSE_USER


GEMINI_OPENAI_HOST = "generativelanguage.googleapis.com"


def model_is_gemini_3_or_newer(model_name: str) -> bool:
    name = str(model_name or "").strip().lower()
    if not name.startswith("gemini-"):
        return False
    version = name.removeprefix("gemini-").split("-", 1)[0]
    try:
        return float(version) >= 3.0
    except ValueError:
        return False


def openai_endpoint_is_gemini_compat(model_config: Dict[str, Any]) -> bool:
    u = (model_config.get("base_url") or "").lower()
    return GEMINI_OPENAI_HOST in u


def use_max_completion_tokens(model_config: Dict[str, Any]) -> bool:
    if "use_max_completion_tokens" in model_config:
        return bool(model_config["use_max_completion_tokens"])
    val = os.environ.get("OPENAI_USE_MAX_COMPLETION_TOKENS", "1").strip().lower()
    if val in ("0", "false", "no"):
        return False
    return True


def apply_token_limit_to_create_kw(
    create_kw: Dict[str, Any], model_config: Dict[str, Any], max_val: int
) -> None:
    if openai_endpoint_is_gemini_compat(model_config):
        create_kw["max_tokens"] = max_val
        return
    if use_max_completion_tokens(model_config):
        create_kw["max_completion_tokens"] = max_val
    else:
        create_kw["max_tokens"] = max_val


def apply_gemini_thinking_config(
    create_kw: Dict[str, Any], model_config: Dict[str, Any]
) -> None:
    if not model_is_gemini_3_or_newer(model_config.get("model_name", "")):
        return
    level = str(model_config.get("thinking_level") or "").strip().lower()
    if not level:
        return
    create_kw["reasoning_effort"] = level


def chat_message_text(message: Any) -> str:
    c = getattr(message, "content", None) if message is not None else None
    return (c or "").strip() if isinstance(c, str) else ""


def model_call(
    system_prompt: str,
    user_prompt: str,
    model_config: Dict[str, Any],
    return_json: bool = True,
    return_usage: bool = False
) -> Any:

    if "base_url" in model_config and model_config["base_url"]:
        client = OpenAI(api_key=model_config["api_key"], base_url=model_config["base_url"])
    else:
        client = OpenAI(api_key=model_config["api_key"])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try_time = 0
    while try_time < 3:
        try:
            max_val = model_config.get("max_completion_tokens", model_config.get("max_tokens", 1024))
            create_kw = dict(
                model=model_config["model_name"],
                messages=messages,
                temperature=model_config["temperature"],
                timeout=model_config["timeout"],
            )
            apply_token_limit_to_create_kw(create_kw, model_config, max_val)
            apply_gemini_thinking_config(create_kw, model_config)
            response = client.chat.completions.create(**create_kw)
            response_text = chat_message_text(response.choices[0].message)


            usage_info = None
            if hasattr(response, 'usage') and response.usage:
                usage_info = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            else:
                usage_info = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }

            if return_json:
                response_json = parse_output_as_json(response_text)
                if return_usage:
                    return response_json, usage_info
                else:
                    return response_json
            else:
                if return_usage:
                    return response_text, usage_info
                else:
                    return response_text
        except Exception as e:
            print(f"[ReqElicitGym - Model Call] Error calling model: {e}")
            try_time += 1
            if try_time >= 3:
                if return_usage:
                    return ({}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) if return_json else ("", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                else:
                    return {} if return_json else ""
            time.sleep(2)
    if return_usage:
        return ({}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) if return_json else ("", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return {} if return_json else ""


def model_call_with_thinking(
    system_prompt: str,
    user_prompt: str,
    model_config: Dict[str, Any],
    return_json: bool = True,
    return_usage: bool = False
) -> Any:

    if "base_url" in model_config and model_config["base_url"]:
        client = OpenAI(api_key=model_config["api_key"], base_url=model_config["base_url"])
    else:
        client = OpenAI(api_key=model_config["api_key"])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try_time = 0
    while try_time < 3:
        try:
            max_val = model_config.get("max_completion_tokens", model_config.get("max_tokens", 1024))
            create_kw = dict(
                model=model_config["model_name"],
                messages=messages,
                temperature=model_config["temperature"],
                timeout=model_config["timeout"],
            )
            if not model_is_gemini_3_or_newer(model_config.get("model_name", "")):
                create_kw["extra_body"] = {"enable_thinking": True}
            apply_token_limit_to_create_kw(create_kw, model_config, max_val)
            apply_gemini_thinking_config(create_kw, model_config)
            response = client.chat.completions.create(**create_kw)
            response_text = chat_message_text(response.choices[0].message)


            usage_info = None
            if hasattr(response, 'usage') and response.usage:
                usage_info = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            else:
                usage_info = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }

            if return_json:
                response_json = parse_output_as_json(response_text)
                if return_usage:
                    return response_json, usage_info
                else:
                    return response_json
            else:
                if return_usage:
                    return response_text, usage_info
                else:
                    return response_text
        except Exception as e:
            print(f"[ReqElicitGym - Model Call] Error calling model: {e}")
            try_time += 1
            if try_time >= 3:
                if return_usage:
                    return ({}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) if return_json else ("", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                else:
                    return {} if return_json else ""
            time.sleep(2)
    if return_usage:
        return ({}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) if return_json else ("", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return {} if return_json else ""


def judge_interviewer_action(
    action: str,
    task: Dict[str, Any],
    model_config: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    remaining_requirements: List[Dict[str, Any]],
    return_usage: bool = False,
) -> Any:
    conversation_history_str = build_history_into_prompt(conversation_history, with_note=True)
    initial_requirements_str = task.get("initial_requirements", "")


    remaining_requirements_str = ""
    for requirement in remaining_requirements:
        req_id = requirement.get("id", "")
        aspect = requirement.get("aspect", "")
        req_text = requirement.get("requirement", "")
        remaining_requirements_str += f"Requirement ID: {req_id}\tAspect: {aspect}\tRequirement: {req_text}\n\n"
    remaining_requirements_str = remaining_requirements_str.strip()

    system_prompt = JUDGE_PROMPT_SYSTEM
    user_prompt = JUDGE_PROMPT_USER.format(
        initial_requirements=initial_requirements_str,
        conversation_history=conversation_history_str,
        remaining_requirements=remaining_requirements_str if remaining_requirements_str else "No remaining requirements.",
        latest_utterance=action
    )
    if return_usage:
        response_json, usage_info = model_call(
            system_prompt, user_prompt, model_config, return_usage=True
        )
        return response_json, usage_info
    response_json = model_call(system_prompt, user_prompt, model_config)
    return response_json

def generate_user_response(
    action: str,
    action_judgement: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    simulator_model_config: Dict[str, Any],
    remaining_requirements: List[Dict[str, Any]],
    return_usage: bool = False,
) -> Any:
    action_type = action_judgement.get("action_type", "probe")
    is_relevant = action_judgement.get("is_relevant_to_implied_requirements", False)
    relevant_req_ids = relevant_requirement_ids_from_judgement(action_judgement)

    implied_requirements: List[str] = []
    if is_relevant and relevant_req_ids:
        relevant_req_id_set = set(relevant_req_ids)
        for req in remaining_requirements:
            if req.get("id") in relevant_req_id_set:
                req_text = str(req.get("requirement") or "").strip()
                if req_text:
                    implied_requirements.append(req_text)

    conversation_history_str = build_history_into_prompt(conversation_history, with_note=False)

    system_prompt = PASSIVE_RESPONSE_SYSTEM
    user_prompt = PASSIVE_RESPONSE_USER.format(
        conversation_history=conversation_history_str,
        latest_utterance=action,
        action_type=action_type,
        is_relevant=is_relevant,
        relevant_requirement=(
            "\n".join(f"- {text}" for text in implied_requirements)
            if implied_requirements
            else "null"
        )
    )
    if return_usage:
        response_json, usage_info = model_call(
            system_prompt,
            user_prompt,
            simulator_model_config,
            return_usage=True,
        )
        return response_json.get("response", ""), usage_info
    response_json = model_call(system_prompt, user_prompt, simulator_model_config)
    return response_json.get("response", "")


def evaluate_action(
    action: str,
    task: Dict[str, Any],
    judge_model_config: Dict[str, Any],
    user_simulator_config: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    remaining_requirements: List[Dict[str, Any]],
    user_quality_level: str,
    return_usage: bool = False,
) -> Any:


    judge_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    user_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if return_usage:
        judgement, judge_usage = judge_interviewer_action(
            action=action,
            task=task,
            model_config=judge_model_config,
            conversation_history=conversation_history,
            remaining_requirements=remaining_requirements,
            return_usage=True,
        )
    else:
        judgement = judge_interviewer_action(
            action=action,
            task=task,
            model_config=judge_model_config,
            conversation_history=conversation_history,
            remaining_requirements=remaining_requirements,
        )

    if judgement.get("action_type") == "finish":
        if return_usage:
            return "", [], 0.0, judgement, {"judge": judge_usage, "user": user_usage}
        return "", [], 0.0, judgement

    if return_usage:
        simulated_user_response, user_usage = generate_user_response(
            action=action,
            action_judgement=judgement,
            conversation_history=conversation_history,
            simulator_model_config=user_simulator_config,
            remaining_requirements=remaining_requirements,
            return_usage=True,
        )
    else:
        simulated_user_response = generate_user_response(
            action=action,
            action_judgement=judgement,
            conversation_history=conversation_history,
            simulator_model_config=user_simulator_config,
            remaining_requirements=remaining_requirements,
        )


    is_relevant = judgement.get("is_relevant_to_implied_requirements")
    relevant_req_ids = relevant_requirement_ids_from_judgement(judgement)
    elicited_requirements = []
    if is_relevant and relevant_req_ids:
        relevant_req_id_set = set(relevant_req_ids)

        for req in remaining_requirements:
            req_id = req.get("id")
            if req_id in relevant_req_id_set:
                elicited_requirements.append(req_id)

    reward = 0.0

    if return_usage:
        return simulated_user_response, elicited_requirements, reward, judgement, {
            "judge": judge_usage,
            "user": user_usage,
        }
    return simulated_user_response, elicited_requirements, reward, judgement
