from typing import Literal, Any, List, Optional
from pydantic import BaseModel, Field

from LLM.LLM_factory import LLMSize, create_llm
from LLM.prompt_loader import load_prompt

class MissingQuestion(BaseModel):
    attribute: str = Field(description="El nombre del atributo clínico que falta.")
    question: str = Field(description="Pregunta médica directa y precisa en español para obtener el dato faltante.")
    expected_answer_type: Literal["integer", "float", "boolean", "string", "date"] = Field(description="El tipo de dato esperado.")
    valid_answers: Optional[List[Any]] = Field(default=None, description="Opciones válidas si es cerrada.")
    resolves_criteria: List[str] = Field(default_factory=list, description="IDs de los criterios que resuelve.")
    status: Literal["generated", "requires_clinician_review", "not_generatable"] = Field(description="Estado.")

class MissingInfoQuestionGenerator:
    def __init__(self, llm_client=None):
        self.client = llm_client or create_llm(LLMSize.SMALL)
        self.temperature = 0.0 
        self.system_instruction = load_prompt("question_generator.md")

    def generate_question(self, missing_attribute_data: dict) -> dict:
        attribute_name = missing_attribute_data.get("attribute_id", "unknown")
        canonical_name = missing_attribute_data.get("canonical_name", attribute_name)
        notes = missing_attribute_data.get("notes", "Ninguna nota clínica.")
        
        required_by = missing_attribute_data.get("required_by", [])
        criteria_texts = [f"- Ensayo {req.get('trial_id')}: {req.get('criterion_text', req.get('criterion_id'))}" for req in required_by]
        criteria_block = "\n".join(criteria_texts) if criteria_texts else "Criterio desconocido"

        user_prompt = f"""
        Atributo faltante: {canonical_name} ({attribute_name})
        
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
                temperature=self.temperature
            )
            return generated_data.model_dump()

        except Exception as e:
            fallback = MissingQuestion(
                attribute=attribute_name,
                question=f"¿Cuál es el valor clínico para: {canonical_name}?",
                expected_answer_type="string",
                resolves_criteria=[req.get("criterion_id", "unknown") for req in required_by],
                status="not_generatable"
            )
            result = fallback.model_dump()
            result["error"] = str(e)
            return result