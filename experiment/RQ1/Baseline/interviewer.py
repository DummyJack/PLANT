from typing import Dict, Any, List, Optional
from .env.prompts import model_call
from .env.utils import build_history_into_prompt


class Interviewer:

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model_name: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout


        self.model_config = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }

    def ask_question(self, conversation_history: List[Dict[str, str]], return_usage: bool = False) -> Any:
        history_str = build_history_into_prompt(conversation_history, with_note=False)

        system_prompt = """You are an interviewer trying to understand a user's requirements for a software system. Your goal is to ask clarifying questions to better understand their needs based on their initial requirements.

Ask one clear, focused question based on the conversation so far. You can:
- Clarify something mentioned
- Probe for more details about requirements
- Finish dialogue: When you believe you have gathered enough information about the user's requirements, you should finish the dialogue and generate a comprehensive set of user stories as the final output artifact. The user stories should be based on all the requirements you have elicited during the conversation.

When finishing, use the following format:
"I have gathered enough information. Based on our conversation, here is the set of user stories:

User Story 1: As a [user type], I want to [action/goal] so that [benefit/value].
User Story 2: As a [user type], I want to [action/goal] so that [benefit/value].
User Story 3: As a [user type], I want to [action/goal] so that [benefit/value].
..."

Important: When you finish, you must generate a complete set of user stories that comprehensively captures all the requirements discussed during the conversation. Each user story should follow the standard format: "As a [user type], I want to [action/goal] so that [benefit/value]."
"""

        user_prompt = f"""Conversation history:
{history_str if history_str else "User: [Initial requirements]"}

Ask your next question to better understand the user's requirements, or finish the dialogue and generate a comprehensive set of user stories based on all the requirements you have elicited."""


        if return_usage:
            response_text, usage_info = model_call(
                system_prompt,
                user_prompt,
                self.model_config,
                return_json=False,
                return_usage=True,
            )
            return (response_text if response_text else "", usage_info)
        else:
            response_text = model_call(
                system_prompt,
                user_prompt,
                self.model_config,
                return_json=False,
                return_usage=False,
            )
            return response_text if response_text else ""


    def __repr__(self) -> str:
        return f"Interviewer(model={self.model_name}, temperature={self.temperature})"
