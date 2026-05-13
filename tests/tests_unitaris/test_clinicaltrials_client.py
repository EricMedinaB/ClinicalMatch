# -*- coding: utf-8 -*-
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

sys.path.append(str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from clinicaltrials_client import ClinicalTrialsClient

def main() -> None:
    project_root = PROJECT_ROOT

    output_path = (
        project_root
        / "data"
        / "api_responses"
        / "runner_clinicaltrials_response.json"
    )

    search_plan = {
        "patient_id": "RUNNER-PAC-002",
        "base_queries": [
            {
                "query.cond": "Lung Cancer", 
                "query.term": "Osimertinib",
                "filter.advanced": "AREA[OverallStatus]RECRUITING", 
                "pageSize": 3
            }
        ],
        "refined_queries": [
            {
                "query.cond": "Non-Small Cell Lung Cancer",
                "query.term": "EGFR",
                "filter.advanced": "AREA[OverallStatus]RECRUITING", 
                "pageSize": 2
            }
        ],
        "fallback_queries": []
    }

    client = ClinicalTrialsClient()
    print(" Conectando con la API de ClinicalTrials.gov...")
    print(f"Buscando ensayos para el paciente: {search_plan['patient_id']}\n")
    
    result = client.search_from_plan(
        plan=search_plan,
        output_path=output_path
    )

    print("="*50)
    print(" Búsqueda en ClinicalTrials Completada")
    print("="*50)
    print(f"Archivo de salida: {output_path}")
    print(f"Patient ID: {result.get('patient_id')}")
    print(f"Estado global: {result.get('status')}")
    print(f"Errores encontrados: {len(result.get('errors', []))}")
    print("-" * 50)

    resultados_consultas = result.get("results", [])
    total_estudios_descargados = 0

    if not resultados_consultas:
        print(" No se ejecutó ninguna consulta con éxito.")
    else:
        for res in resultados_consultas:
            q_id = res.get("query_id")
            q_status = res.get("status")
            found = res.get("total_found", 0)
            condicion = res.get("query", {}).get("query.cond", "N/A")
            
            total_estudios_descargados += found
            
            print(f"[{q_id}] Status: {q_status} | Encontrados: {found} | Condición buscada: '{condicion}'")
            
            estudios = res.get("studies", [])
            if estudios:
                ids = [estudio.get("nct_id") for estudio in estudios]
                print(f"   ↳ IDs: {', '.join(ids)}")

    print("-" * 50)
    print(f"Total de estudios únicos a procesar: {total_estudios_descargados}")


if __name__ == "__main__":
    main()
