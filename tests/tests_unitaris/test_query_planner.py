# -*- coding: utf-8 -*-
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

sys.path.append(str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from query_planner import QueryPlanner

def main() -> None:
    project_root = PROJECT_ROOT

    output_path = (
        project_root
        / "data"
        / "query_plans"
        / "runner_query_plan.json"
    )

    input_patient = {
        "patient_id": "RUNNER-PAC-003",
        "raw_text": "Paciente con cáncer de pulmón metastásico, mutación EGFR positiva. Previamente tratado con quimioterapia.",
        "patient_profile": {
            "condition": "Lung Cancer",
            "condition_confidence": 0.95,
            "subtype": "Non-Small Cell",
            "stage": "IV",
            "metastatic": True,
            "biomarkers": [
                {"name": "EGFR", "status": "positive", "variant": "exon 19 deletion"}
            ],
            "prior_treatments": ["chemotherapy"],
            "location": {"country": "United States"}
        }
    }


    print("Inicializando QueryPlanner (y cargando normalización clínica)...")
    planner = QueryPlanner()
    print(f"Construyendo plan de búsqueda para el paciente: {input_patient['patient_id']}...")
    try:
        result = planner.build_plan(
            patient=input_patient,
            output_path=output_path
        )
    except Exception as e:
        print(f"\n Error durante la ejecución: {e}")
        return
    base_queries = result.get("base_queries", [])
    refined_queries = result.get("refined_queries", [])
    fallback_queries = result.get("fallback_queries", [])
    normalized = result.get("normalized_inputs", {})

    print("\n" + "="*50)
    print("Query Planner Completado")
    print("="*50)
    print(f"Archivo JSON generado en: {output_path}")
    print(f"Patient ID: {result.get('patient_id')}")
    print(f"Status del Plan: {result.get('status')}")
    
    warnings = result.get("warnings", [])
    if warnings:
        print(f"\n Advertencias ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")

    print("-" * 50)
    print(" RESUMEN DE QUERIES GENERADAS:")
    print(f"  Base Queries:    {len(base_queries)} (Búsqueda general por enfermedad)")
    print(f"  Refined Queries: {len(refined_queries)} (Combinaciones con edad, biomarcadores, etc.)")
    print(f"  Fallback Queries:{len(fallback_queries)} (Búsquedas de rescate si lo demás falla)")
    print(f"  TOTAL QUERIES:   {len(base_queries) + len(refined_queries) + len(fallback_queries)}")
    
    cond_norm = normalized.get("condition", {})
    if cond_norm:
        print(f"\n Normalización Oficial (MeSH):")
        print(f"  - Texto Original:  '{input_patient['patient_profile']['condition']}'")
        print(f"  - Término oficial: '{cond_norm.get('normalized', 'N/A')}'")

    print("="*50)

if __name__ == "__main__":
    main()
