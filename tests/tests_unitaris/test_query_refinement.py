# -*- coding: utf-8 -*-
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from query_refinement import QueryRefinementLoop

def main() -> None:
    project_root = PROJECT_ROOT

    input_path = (
        project_root
        / "data"
        / "api_responses"
        / "runner_clinicaltrials_response.json"
    )

    output_path = (
        project_root
        / "data"
        / "refined_querys"
        / "refined_candidates.json"
    )

    mock_api_result = {
        "patient_id": "RUNNER-PAC-006",
        "results": [
            {
                "query_id": "refined_queries_1",
                "query_type": "refined_queries",
                "studies": [
                    {"nct_id": "NCT-001", "raw": {"title": "Ensayo Específico 1"}},
                    {"nct_id": "NCT-002", "raw": {"title": "Ensayo Específico 2"}}
                ]
            },
            {
                "query_id": "base_queries_1",
                "query_type": "base_queries",
                "studies": [
                    {"nct_id": "NCT-002", "raw": {"title": "Ensayo Específico 2"}},
                    {"nct_id": "NCT-003", "raw": {"title": "Ensayo General 3"}}
                ]
            }
        ],
        "errors": []
    }

    print("Executing Query Refinement Loop...")
    
    if input_path.exists():
        print(f" Cargando ensayos reales de cáncer desde: {input_path}")
        with open(input_path, "r", encoding="utf-8") as f:
            api_result = json.load(f)
    else:
        print(" No se detectó 'runner_clinicaltrials_response.json'. Usando datos Mock.")
        api_result = mock_api_result

    refiner = QueryRefinementLoop(
        min_candidates=2, 
        target_candidates=50, 
        max_candidates=150
    )

    try:
        refined_data = refiner.refine_from_api_result(
            api_result=api_result,
            output_path=output_path
        )
    except Exception as e:
        print(f"\n Error durante la ejecución: {e}")
        return

    print("\n" + "="*50)
    print(" Query Refinement Completado")
    print("="*50)
    print(f"Archivo JSON generado en:\n  ↳ {output_path}")
    print(f"\nPatient ID: {refined_data.get('patient_id')}")
    print(f"Status: {refined_data.get('status')}")
    
    raw_count = refined_data.get('total_raw_candidates', 0)
    unique_count = refined_data.get('total_unique_candidates', 0)
    
    print("-" * 50)
    print("  RESULTADOS DEL FILTRADO:")
    print(f"  Ensayos brutos leídos:     {raw_count}")
    print(f"  Ensayos tras deduplicar:   {unique_count} (Se eliminaron {raw_count - unique_count} duplicados)")
    print(f"  Queries utilizadas:        {', '.join(refined_data.get('used_query_types', []))}")
    
    if refined_data.get('was_truncated'):
        print("  La lista fue truncada porque superaba el límite máximo.")
        
    print("="*50)

if __name__ == "__main__":
    main()