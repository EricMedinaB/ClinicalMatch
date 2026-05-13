import json
import sys
from pathlib import Path
from question_manager import QuestionManager
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")



def run_tests():
    project_root = PROJECT_ROOT
    
    output_dir = project_root / "data" / "patient_questions"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_path = output_dir / "paciente_1_preguntas.json"
    pdf_path = output_dir / "paciente_1_formulario.pdf"

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
            "question": "Considerando que el paciente pasa más del 50% del día en cama, ¿podría confirmar si su estado funcional corresponds a un ECOG 3 o 4?",
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
    
    print("\n Unificando preguntas y calculando impacto de negocio...")
    patient_json = manager.unify_patient_questions(
        patient_id="TREC_TOPIC_1", 
        generated_questions=generated_questions, 
        original_attributes=original_attributes
    )

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(patient_json, f, indent=2, ensure_ascii=False)
    print(f"   JSON unificado guardado en: {json_path}")

    manager.export_to_pdf(patient_json, pdf_path)
    print(f"   PDF generado guardado en: {pdf_path}")

    print("\n" + "="*50)
    print(" RESULTADOS DE LA PRUEBA (MÓDULO 13)")
    print("="*50)
    print(f" Status del proceso: ÉXITO")
    print(f" Total preguntas gestionadas: {patient_json.get('total_questions', 0)}")
    print("-" * 50)
    print(f" Todo se ha centralizado correctamente en:\n  ↳ {output_dir}")
    print("="*50)

if __name__ == "__main__":
    run_tests()
