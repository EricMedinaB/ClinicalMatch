from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
def generate_question(self, missing_attribute_data: dict) -> dict:
    attribute_data = missing_attribute_data.get("attribute", {})

    attribute_name = (
        missing_attribute_data.get("attribute_id")
        or attribute_data.get("attribute_id")
        or "unknown"
    )

    canonical_name = (
        missing_attribute_data.get("canonical_name")
        or attribute_data.get("canonical_name")
        or attribute_name
    )

    notes = (
        missing_attribute_data.get("notes")
        or missing_attribute_data.get("error")
        or "Ninguna nota clínica."
    )

    expected_type = (
        attribute_data.get("type")
        or missing_attribute_data.get("type")
        or "string"
    )

    allowed_values = (
        attribute_data.get("allowed_values")
        or missing_attribute_data.get("allowed_values")
    )

    required_by = missing_attribute_data.get("required_by", [])

    criteria_texts = [
        f"- Ensayo {req.get('trial_id', 'unknown')}: "
        f"{req.get('criterion_text') or req.get('criterion_id', 'unknown')}"
        for req in required_by
    ]

    criteria_block = "\n".join(criteria_texts) if criteria_texts else "Criterio desconocido"

    user_prompt = f"""
    Atributo faltante: {canonical_name} ({attribute_name})

    Tipo de dato esperado, si está disponible: {expected_type}

    Valores válidos, si existen:
    {allowed_values}

    Criterios que dependen de este atributo:
    {criteria_block}

    Notas previas:
    {notes}
    """

    try:
        generated_data: MissingQuestion = self.client.generate_json(
            prompt=user_prompt.strip(),
            system_instruction=self.system_instruction,
            response_schema=MissingQuestion,
            temperature=self.temperature,
        )
        return generated_data.model_dump()

    except Exception as e:
        fallback = MissingQuestion(
            attribute=attribute_name,
            question=f"¿Cuál es el valor clínico para: {canonical_name}?",
            expected_answer_type=self._safe_expected_answer_type(expected_type),
            valid_answers=allowed_values if isinstance(allowed_values, list) else None,
            resolves_criteria=[
                req.get("criterion_id", "unknown")
                for req in required_by
            ],
            status="not_generatable",
        )
        result = fallback.model_dump()
        result["error"] = str(e)
        return result


def _safe_expected_answer_type(self, value: Any) -> Literal["integer", "float", "boolean", "string", "date"]:
    valid_types = {"integer", "float", "boolean", "string", "date"}

    if value in valid_types:
        return value

    mapping = {
        "int": "integer",
        "number": "float",
        "numeric": "float",
        "bool": "boolean",
        "str": "string",
        "text": "string",
        "enum": "string",
        "categorical": "string",
    }

    return mapping.get(str(value).lower(), "string")
