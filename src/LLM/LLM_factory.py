import os
from enum import Enum
from dotenv import load_dotenv
from pathlib import Path

from LLM.base import LLMClient
from LLM.gemini_client import GeminiClient


class LLMSize(str, Enum):
    SMALL = "small"
    LARGE = "large"


def create_llm(size: LLMSize = LLMSize.SMALL) -> LLMClient:
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    
    load_dotenv(dotenv_path=env_path)
    
    if size == LLMSize.SMALL:
        model = os.getenv("GEMINI_FLASH_LITE_MODEL")

        if model is None:
            raise ValueError("Falta GEMINI_FLASH_LITE_MODEL en el .env")

        return GeminiClient(model_name=model)

    if size == LLMSize.LARGE:
        model = os.getenv("GEMINI_FLASH_MODEL")

        if model is None:
            raise ValueError("Falta GEMINI_FLASH_MODEL en el .env")

        return GeminiClient(model_name=model)

    raise ValueError(f"LLM size no válido: {size}")