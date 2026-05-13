import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"

sys.path.append(str(SRC_PATH))

from src.trial_candidate_store import TrialCandidateStore


def main() -> None:
    project_root = PROJECT_ROOT

    input_path = (
        project_root
        / "data"
        / "refined_querys"
        / "refined_candidates.json"
    )

    output_path = (
        project_root
        / "data"
        / "trial_candidate_store"
        / "trial_candidates.json"
    )

    store = TrialCandidateStore()

    store_result = store.build_store_from_file(
        input_path=input_path,
        output_path=output_path,
    )

    metadata = store_result.get("candidate_store_metadata", {})

    print("Trial Candidate Store generado")
    print(f"Archivo de entrada: {input_path}")
    print(f"Archivo de salida: {output_path}")
    print(f"Patient ID: {store_result.get('patient_id')}")
    print(f"Status: {metadata.get('status')}")
    print(f"Candidatos de entrada: {metadata.get('total_input_candidates')}")
    print(f"Candidatos guardados: {metadata.get('total_stored_candidates')}")
    print(f"Errores: {metadata.get('total_errors')}")

    if metadata.get("total_errors", 0) > 0:
        print("Hay errores en candidate_store_errors dentro del JSON de salida.")


if __name__ == "__main__":
    main()
