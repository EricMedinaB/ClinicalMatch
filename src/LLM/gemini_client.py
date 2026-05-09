import os
from typing import Type, cast
from dotenv import load_dotenv
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel

from LLM.base import LLMClient


class GeminiClient(LLMClient):
    def __init__(self, model_name: str, api_key: str | None = None):
        self.model_name = model_name
        self.client = genai.Client(
            api_key=api_key or os.environ["GEMINI_API_KEY"]
        )

    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> str:
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        return response.text or ""

    def generate_json(
        self,
        *,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> BaseModel:
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        if response.parsed is None:
            raise ValueError(
                f"Gemini no devolvió JSON parseable para el schema {response_schema.__name__}"
            )

        return cast(BaseModel, response.parsed)
    
if __name__ == "__main__":
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    
    load_dotenv(dotenv_path=env_path)

    model = os.getenv("GEMINI_FLASH_LITE_MODEL")

    if model is None:
        raise ValueError("Falta GEMINI_FLASH_LITE_MODEL")

    client = GeminiClient(
        model_name=model
    )

    response = client.generate_text(
        prompt="¿Cuál es la capital de Francia?"
    )

    print(response)