import json
from pathlib import Path
from question_manager import QuestionManager

def run_tests():
    print("Iniciando pruebas del Módulo 13 (Gestor de Preguntas y PDF)...")

    original_attributes = [
        {
            "attribute_id": "ECOG Performance Status",
            "impact": {"affected_trials": 2, "affected_criteria": 2, "is_ranking_critical": True} 
        },
        {
            "attribute_id": "EGFR_status",
            "impact": {"affected_trials": 1, "affected_criteria": 1, "is_ranking_critical": False} 
        }
    ]

    generated_questions = [
        {
            "attribute": "ECOG Performance Status",
            "question": "Considerando que el paciente pasa más del 50% del día en cama, ¿podría confirmar si su estado funcional corresponde a un ECOG 3 o 4?",
            "expected_answer_type": "integer",
            "valid_answers": [0, 1, 2, 3, 4],
            "resolves_criteria": ["C1"]
        },
        {
            "attribute": "EGFR_status",
            "question": "¿Cuál es el resultado del análisis molecular respecto a la mutación EGFR?",
            "expected_answer_type": "string",
            "valid_answers": ["Positivo", "Negativo", "Pendiente"],
            "resolves_criteria": ["C2"]
        }
    ]

    manager = QuestionManager()
    
    print("\nUnificando preguntas y calculando impacto...")
    patient_json = manager.unify_patient_questions(
        patient_id="TREC_TOPIC_1", 
        generated_questions=generated_questions, 
        original_attributes=original_attributes
    )

    json_path = "outputs/tests/paciente_1_preguntas.json"
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(patient_json, f, indent=2, ensure_ascii=False)
    print(f"JSON unificado guardado en: {json_path}")

    pdf_path = "outputs/tests/paciente_1_formulario.pdf"
    manager.export_to_pdf(patient_json, pdf_path)
    print(f"PDF generado guardado en: {pdf_path}")

if __name__ == "__main__":
    run_tests()
