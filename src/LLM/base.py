from abc import ABC, abstractmethod
from typing import Any, Type

from pydantic import BaseModel

class LLMClient(ABC):
    @abstractmethod
    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> str:
        pass

    @abstractmethod
    def generate_json(
        self,
        *,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> BaseModel:
        pass