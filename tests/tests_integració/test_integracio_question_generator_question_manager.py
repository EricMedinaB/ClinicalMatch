# -*- coding: utf-8 -*-
import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from LLM.LLM_factory import LLMSize, create_llm
from question_generator import MissingInfoQuestionGenerator 
from question_manager import QuestionManager

def run_integration_test():
    print(" Iniciando Test de Integración: Módulo 12 + Módulo 13...\n")

    print("Cargando la IA y el Gestor de Reportes usando la factoría...")

    client = create_llm(LLMSize.SMALL)
    generator = MissingInfoQuestionGenerator(llm_client=client)
    manager = QuestionManager()

    paciente_id = "PACIENTE_INTEGRACION_002"
    
    atributos_faltantes_mod10 = [
        {
            "attribute_id": "ECOG",
            "canonical_name": "ECOG Performance Status",
            "status": "not_found",
            "notes": "Paciente postrado en cama la mayor parte del día por debilidad.",
            "required_by": [{"trial_id": "NCT_A", "criterion_text": "ECOG <= 2"}],
            "impact": {"affected_trials": 3, "affected_criteria": 3, "is_ranking_critical": True} 
        },
        {
            "attribute_id": "EGFR_status",
            "canonical_name": "Mutación EGFR",
            "status": "not_found",
            "notes": "Biopsia de pulmón realizada hace 3 días, pendiente de laboratorio.",
            "required_by": [{"trial_id": "NCT_B", "criterion_text": "EGFR positivo"}],
            "impact": {"affected_trials": 1, "affected_criteria": 1, "is_ranking_critical": False} 
        }
    ]

    print("\n Módulo 12: Generando preguntas clínicas con Gemini...")
    preguntas_generadas = []
    
    for attr in atributos_faltantes_mod10:
        print(f"   -> Pensando pregunta para: {attr['canonical_name']}...")
        resultado_ia = generator.generate_question(attr)
        preguntas_generadas.append(resultado_ia)

    print("\n Módulo 13: Calculando Impact Score matemático y ordenando...")
    reporte_final_json = manager.unify_patient_questions(
        patient_id=paciente_id,
        generated_questions=preguntas_generadas,
        original_attributes=atributos_faltantes_mod10
    )

    ruta_base = Path("outputs/tests")
    ruta_base.mkdir(parents=True, exist_ok=True)
    
    ruta_json = ruta_base / "reporte_integracion.json"
    ruta_pdf = ruta_base / "reporte_integracion.pdf"

    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(reporte_final_json, f, indent=2, ensure_ascii=False)

    manager.export_to_pdf(reporte_final_json, str(ruta_pdf))

    print("\n" + "="*50)
    print(" REPORTE FINAL UNIFICADO (VISTA PREVIA)")
    print("="*50)
    
    for q in reporte_final_json["questions"]:
        print(f"[{q['priority']}] Score: {q['impact_score']} | Atributo: {q['attribute']}")
        print(f"    {q['question_text']}")
        if q.get('valid_answers'):
            print(f"    Opciones: {q['valid_answers']}")
        print("-" * 50)

    print(f"\n JSON completo guardado en: {ruta_json.absolute()}")
    print(f" PDF clínico guardado en: {ruta_pdf.absolute()}")

if __name__ == "__main__":
    run_integration_test()
