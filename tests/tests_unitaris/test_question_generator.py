import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from LLM.LLM_factory import LLMSize, create_llm
from question_generator import MissingInfoQuestionGenerator 

def run_tests():
    print("Iniciando pruebas del Módulo 12 (Missing Info Question Generator)...\n")

    print("Cargando modelo LLM (SMALL recomendado para generación de texto directa)...")
    client = create_llm(LLMSize.SMALL)
    question_generator = MissingInfoQuestionGenerator(llm_client=client)

    mock_ecog = {
        "attribute_id": "ECOG",
        "canonical_name": "ECOG Performance Status",
        "status": "not_found",
        "notes": "El paciente pasa más del 50% del día en la cama debido a debilidad severa, pero no hay puntuación oficial.",
        "required_by": [{"trial_id": "NCT_001", "criterion_id": "C1", "criterion_text": "ECOG 0-2"}]
    }

    mock_egfr = {
        "attribute_id": "EGFR_status",
        "canonical_name": "Estado de Mutación EGFR",
        "status": "not_found",
        "notes": "Se le hizo biopsia hace 2 semanas pero los resultados moleculares aún no están en el historial.",
        "required_by": [{"trial_id": "NCT_002", "criterion_id": "C2", "criterion_text": "EGFR Exon 19 deletion positive"}]
    }
    
    mock_date = {
        "attribute_id": "last_chemo_date",
        "canonical_name": "Fecha de última quimioterapia",
        "status": "not_found",
        "notes": "El texto dice que recibió platino recientemente, pero no especifica qué día terminó el ciclo.",
        "required_by": [{"trial_id": "NCT_003", "criterion_id": "C3", "criterion_text": "At least 3 weeks since last chemotherapy"}]
    }

    atributos_a_probar = [mock_ecog, mock_egfr, mock_date]
    resultados = []

    print("\nGenerando preguntas clínicas...")
    for attr in atributos_a_probar:
        print(f" -> Procesando: {attr['canonical_name']}...")
        try:
            resultado = question_generator.generate_question(attr)
            resultados.append(resultado)
        except Exception as e:
            print(f" ERROR al generar para {attr['attribute_id']}: {e}")

    ruta_salida = Path("outputs/tests/resultado_test_mod12.json")
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)

    print("\n" + "="*40)
    print(" RESULTADOS DE LA PRUEBA (MÓDULO 12)")
    print("="*40)

    for res in resultados:
        attr_name = res.get("attribute", "unknown")
        status = res.get("status", "unknown")
        pregunta = res.get("question", "No generada")
        tipo_esperado = res.get("expected_answer_type", "")
        opciones = res.get("valid_answers")

        if status == "generated":
            print(f" ÉXITO: {attr_name}")
            print(f"    Pregunta: {pregunta}")
            print(f"   Tipo: {tipo_esperado} | Opciones: {opciones}\n")
        else:
            print(f" FALLO: {attr_name} | Estado devuelto: {status}")
            print(f"   Detalle del error: {res.get('error', 'Ninguno')}\n")

    print(f" El JSON completo se ha guardado en: {ruta_salida.absolute()}")

if __name__ == "__main__":
    run_tests()
