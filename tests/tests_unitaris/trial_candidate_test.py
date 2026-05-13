# -*- coding: utf-8 -*-
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
if str(SRC_PATH) not in sys.path:
    sys.path.append(str(SRC_PATH))

from trial_candidate_store import TrialCandidateStore

def main() -> None:
    project_root = PROJECT_ROOT

    input_path = PROJECT_ROOT / "data" / "refined_querys" / "refined_candidates.json"

    output_path = (
        project_root
        / "data"
        / "trial_candidate_store"
        / "trial_candidates.json"
    )

    print(" Ejecutando Trial Candidate Store con datos reales...")
    store = TrialCandidateStore()

    try:
        store_result = store.build_store_from_file(
            input_path=input_path,
            output_path=output_path,
        )
    except Exception as e:
        print(f" ERROR CRÍTICO en el almacén de candidatos: {e}")
        return

    metadata = store_result.get("candidate_store_metadata", {})

    print("\n" + "="*50)
    print(" Trial Candidate Store generado con Éxito")
    print("="*50)
    print(f" Archivo de entrada: {input_path}")
    print(f" Archivo de salida:  {output_path}")
    print(f"\n Patient ID:           {store_result.get('patient_id')}")
    print(f" Status:               {metadata.get('status')}")
    print(f" Candidatos entrada:   {metadata.get('total_input_candidates')}")
    print(f" Candidatos guardados:  {metadata.get('total_stored_candidates')}")
    print(f" Total Errores:         {metadata.get('total_errors')}")
    print("="*50)

    if metadata.get("total_errors", 0) > 0:
        print("\n[AVISO] Hay errores detallados en 'candidate_store_errors' dentro del JSON.")

if __name__ == "__main__":
    main()
