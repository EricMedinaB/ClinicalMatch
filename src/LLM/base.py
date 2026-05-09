from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


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
        response_schema: type[SchemaT],
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> SchemaT:
        pass