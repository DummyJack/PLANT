# Initializes the model package.
from .base import (
    AUTH_ERROR_MESSAGE,
    BaseLLM,
    create_model,
    is_authentication_error,
    normalize_authentication_error,
    validate_provider_api_keys,
)
from .claude import ClaudeModel, claude_split_messages
from .gemini import GeminiModel, gemini_split_messages
from .local import LocalModel
from .openai import OpenAIModel

__all__ = [
    "BaseLLM",
    "AUTH_ERROR_MESSAGE",
    "ClaudeModel",
    "GeminiModel",
    "LocalModel",
    "OpenAIModel",
    "claude_split_messages",
    "create_model",
    "gemini_split_messages",
    "is_authentication_error",
    "normalize_authentication_error",
    "validate_provider_api_keys",
]
