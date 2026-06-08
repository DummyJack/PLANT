from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class ReqElicitGymConfig:


    data_path: str = "data/test.json"


    judge_api_key: Optional[str] = None
    judge_base_url: Optional[str] = None
    judge_model_name: str = "gpt-5.1"
    judge_temperature: float = 0
    judge_max_tokens: int = 1024
    judge_timeout: float = 30.0


    user_api_key: Optional[str] = None
    user_base_url: Optional[str] = None
    user_model_name: str = "gpt-5.1"
    user_temperature: float = 0.7
    user_max_tokens: int = 1024
    user_timeout: float = 30.0


    user_answer_quality: str = "high"


    max_turns: int = 20


    track_conversation_history: bool = True
    track_elicit_state: bool = True


    verbose: bool = False
    seed: Optional[int] = None


    evaluation_result_path: Optional[str] = None
    conversation_result_path: Optional[str] = None

    def __post_init__(self):
        if self.judge_api_key is None:
            raise ValueError("judge_api_key must be provided")
        if self.user_api_key is None:
            raise ValueError("user_api_key must be provided")
        if self.user_answer_quality not in ["high", "medium", "low"]:
            raise ValueError(f"user_answer_quality must be one of ['high', 'medium', 'low'], got {self.user_answer_quality}")
        if not self.data_path:
            raise ValueError("data_path must be provided")

    def validate(self):
        if self.max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if self.judge_temperature < 0:
            raise ValueError("judge_temperature must be non-negative")
        if self.user_temperature < 0:
            raise ValueError("user_temperature must be non-negative")
        if self.judge_max_tokens <= 0:
            raise ValueError("judge_max_tokens must be positive")
        if self.user_max_tokens <= 0:
            raise ValueError("user_max_tokens must be positive")
        if self.judge_timeout <= 0:
            raise ValueError("judge_timeout must be positive")
        if self.user_timeout <= 0:
            raise ValueError("user_timeout must be positive")


        if not os.path.exists(self.data_path):
            raise FileNotFoundError(f"Data file not found: {self.data_path}")

def get_default_config() -> ReqElicitGymConfig:
    return ReqElicitGymConfig()
