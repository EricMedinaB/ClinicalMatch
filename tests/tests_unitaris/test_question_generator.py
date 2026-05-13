# -*- coding: utf-8 -*-
import sys
import json
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.append(str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from LLM.LLM_factory import LLMSize, create_llm

class MissingQuestion(BaseModel):
    attribute: str
    question: str
    expected_answer_type: Literal["integer", "float", "boolean", "string", "date"]
    valid_answers: Optional[list[Any]] = None
    resolves_criteria: list[str] = Field(default_factory=list)
    status: str = "generated"

import question_generator
question_generator.MissingQuestion = MissingQuestion 

class MockGenerator:
    def __init__(self, llm_client):
        self.client = llm_client
        self.temperature = 0.0
        self.system_instruction = "Eres un oncólogo experto. Genera preguntas claras."
        
    def generate_question(self, data):
        return question_generator.generate_question(self, data)

    def _safe_expected_answer_type(self, value):
        return question_generator._safe_expected_answer_type(self, value)

def run_tests():
    project_root = PROJECT_ROOT
    ruta_salida = project_root / "data" / "generated_questions" / "resultado_test_mod12.json"

    print("Iniciando pruebas del Módulo 12 (Funciones Sueltas)...\n")
    print(" Cargando modelo LLM...")
    client = create_llm(LLMSize.SMALL)
    generator = MockGenerator(llm_client=client)

    mock_attributes = [
        {
            "attribute_id": "ECOG",
            "canonical_name": "ECOG Performance Status",
            "notes": "Paciente débil, pasa mucho tiempo en cama.",
            "required_by": [{"trial_id": "NCT_001", "criterion_text": "ECOG 0-2"}]
        },
        {
            "attribute_id": "EGFR_status",
            "canonical_name": "Mutación EGFR",
            "notes": "Pendiente de biopsia.",
            "required_by": [{"trial_id": "NCT_002", "criterion_text": "EGFR+"}]
        }
    ]

    resultados = []
    print("\n Generando preguntas...")
    for attr in mock_attributes:
        print(f"   Procesando: {attr['canonical_name']}...")
        try:
            res = generator.generate_question(attr)
            resultados.append(res)
        except Exception as e:
            print(f"  ERROR: {e}")


    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)

    print(f"\n Proceso completado. Resultados en: {ruta_salida}")

if __name__ == "__main__":
    run_tests()
