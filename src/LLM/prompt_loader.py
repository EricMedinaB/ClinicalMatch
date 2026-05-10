from functools import lru_cache
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=32)
def load_prompt(filename: str) -> str:
    """
    Load a prompt file from src/LLM/prompts.

    Example:
        load_prompt("patient_extractor.md")
    """

    prompt_path = PROMPTS_DIR / filename

    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_path}"
        )

    if not prompt_path.is_file():
        raise ValueError(
            f"Prompt path is not a file: {prompt_path}"
        )

    return prompt_path.read_text(encoding="utf-8").strip()