# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from ranking_engine import RankingEngine


def read_json(path: Path) -> dict:
    assert path.exists(), f"No existe el archivo: {path}"
    assert path.is_file(), f"La ruta no es un archivo: {path}"

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    assert isinstance(data, dict), f"El JSON raíz debe ser un objeto: {path}"
    return data


def write_debug_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def inspect_input_structure(candidate_json: dict) -> dict:
    """
    Inspecciona la estructura de entrada para detectar por qué no se rankea nada.
    """
    report = {
        "root_keys": list(candidate_json.keys()),
        "has_patient_id": "patient_id" in candidate_json,
        "has_unique_studies": "unique_studies" in candidate_json,
        "unique_studies_type": type(candidate_json.get("unique_studies")).__name__,
        "unique_studies_count": 0,
        "studies_with_criterion_evaluation": 0,
        "studies_without_criterion_evaluation": 0,
        "studies_with_valid_criterion_evaluation_dict": 0,
        "first_study_keys": None,
        "first_study_nct_id": None,
        "first_study_has_criteria": None,
        "first_study_has_criterion_evaluation": None,
        "first_criterion_evaluation_keys": None,
        "first_criterion_evaluation_status": None,
        "first_criterion_evaluation_all_count": None,
        "first_criterion_evaluation_inclusion_count": None,
        "first_criterion_evaluation_exclusion_count": None,
        "examples": [],
    }

    unique_studies = candidate_json.get("unique_studies")

    if not isinstance(unique_studies, list):
        report["error"] = "unique_studies no existe o no es una lista"
        return report

    report["unique_studies_count"] = len(unique_studies)

    if not unique_studies:
        report["warning"] = "unique_studies está vacío"
        return report

    first_study = unique_studies[0]

    if isinstance(first_study, dict):
        report["first_study_keys"] = list(first_study.keys())
        report["first_study_nct_id"] = (
            first_study.get("nct_id")
            or first_study.get("trial_id")
            or first_study.get("trial", {}).get("nct_id")
            if isinstance(first_study.get("trial"), dict)
            else None
        )
        report["first_study_has_criteria"] = "criteria" in first_study
        report["first_study_has_criterion_evaluation"] = "criterion_evaluation" in first_study

    for index, study in enumerate(unique_studies):
        if not isinstance(study, dict):
            report["examples"].append({
                "index": index,
                "issue": "study_no_es_dict",
                "type": type(study).__name__,
            })
            continue

        criterion_evaluation = study.get("criterion_evaluation")

        if criterion_evaluation is None:
            report["studies_without_criterion_evaluation"] += 1

            if len(report["examples"]) < 5:
                report["examples"].append({
                    "index": index,
                    "nct_id": study.get("nct_id") or study.get("trial_id"),
                    "issue": "missing_criterion_evaluation",
                    "study_keys": list(study.keys()),
                    "has_criteria": "criteria" in study,
                })

            continue

        report["studies_with_criterion_evaluation"] += 1

        if isinstance(criterion_evaluation, dict):
            report["studies_with_valid_criterion_evaluation_dict"] += 1

            if report["first_criterion_evaluation_keys"] is None:
                report["first_criterion_evaluation_keys"] = list(criterion_evaluation.keys())
                report["first_criterion_evaluation_status"] = criterion_evaluation.get("evaluation_status")

                all_items = criterion_evaluation.get("all")
                inclusion_items = criterion_evaluation.get("inclusion")
                exclusion_items = criterion_evaluation.get("exclusion")

                report["first_criterion_evaluation_all_count"] = (
                    len(all_items) if isinstance(all_items, list) else None
                )
                report["first_criterion_evaluation_inclusion_count"] = (
                    len(inclusion_items) if isinstance(inclusion_items, list) else None
                )
                report["first_criterion_evaluation_exclusion_count"] = (
                    len(exclusion_items) if isinstance(exclusion_items, list) else None
                )

            if len(report["examples"]) < 5:
                report["examples"].append({
                    "index": index,
                    "nct_id": study.get("nct_id") or study.get("trial_id"),
                    "issue": "valid_criterion_evaluation",
                    "evaluation_status": criterion_evaluation.get("evaluation_status"),
                    "summary": criterion_evaluation.get("summary"),
                    "all_count": (
                        len(criterion_evaluation.get("all"))
                        if isinstance(criterion_evaluation.get("all"), list)
                        else None
                    ),
                    "inclusion_count": (
                        len(criterion_evaluation.get("inclusion"))
                        if isinstance(criterion_evaluation.get("inclusion"), list)
                        else None
                    ),
                    "exclusion_count": (
                        len(criterion_evaluation.get("exclusion"))
                        if isinstance(criterion_evaluation.get("exclusion"), list)
                        else None
                    ),
                })
        else:
            if len(report["examples"]) < 5:
                report["examples"].append({
                    "index": index,
                    "nct_id": study.get("nct_id") or study.get("trial_id"),
                    "issue": "criterion_evaluation_no_es_dict",
                    "type": type(criterion_evaluation).__name__,
                })

    return report


def test_ranking_engine_debug_with_mod11_output():
    """
    Test diagnóstico del RankingEngine.

    Input:
        data/resultado_evaluacion_mod11.json

    Outputs:
        data/ranking/resultado_ranking_mod14_debug.json
        data/ranking/ranking_debug_report.json
    """

    input_path = PROJECT_ROOT / "data" / "resultado_evaluacion_mod11.json"
    output_path = PROJECT_ROOT / "data" / "ranking" / "resultado_ranking_mod14_debug.json"
    debug_path = PROJECT_ROOT / "data" / "ranking" / "ranking_debug_report.json"

    print("\n========== RANKING ENGINE DEBUG ==========")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"SRC_DIR: {SRC_DIR}")
    print(f"INPUT PATH: {input_path}")
    print(f"OUTPUT PATH: {output_path}")
    print(f"DEBUG PATH: {debug_path}")
    print(f"Input exists: {input_path.exists()}")
    print(f"Output parent exists before: {output_path.parent.exists()}")

    candidate_json = read_json(input_path)

    input_report = inspect_input_structure(candidate_json)

    debug_report = {
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "src_dir": str(SRC_DIR),
            "input_path": str(input_path),
            "output_path": str(output_path),
            "debug_path": str(debug_path),
            "input_exists": input_path.exists(),
            "output_parent_exists_before": output_path.parent.exists(),
        },
        "input_report": input_report,
        "ranking_result_report": None,
        "exception": None,
    }

    write_debug_json(debug_path, debug_report)

    print("\n--- INPUT REPORT ---")
    print(json.dumps(input_report, ensure_ascii=False, indent=2))

    engine = RankingEngine()

    try:
        result = engine.rank_patient_candidate_file(
            candidate_json=candidate_json,
            output_path=output_path,
        )

        ranking_result_report = {
            "result_type": type(result).__name__,
            "result_keys": list(result.keys()) if isinstance(result, dict) else None,
            "ranking_status": result.get("ranking_status") if isinstance(result, dict) else None,
            "ranked_trials_count": (
                len(result.get("ranked_trials", []))
                if isinstance(result, dict) and isinstance(result.get("ranked_trials"), list)
                else None
            ),
            "summary": result.get("summary") if isinstance(result, dict) else None,
            "flags": result.get("flags") if isinstance(result, dict) else None,
            "output_exists_after_call": output_path.exists(),
            "output_parent_exists_after_call": output_path.parent.exists(),
        }

        debug_report["ranking_result_report"] = ranking_result_report
        write_debug_json(debug_path, debug_report)

        print("\n--- RANKING RESULT REPORT ---")
        print(json.dumps(ranking_result_report, ensure_ascii=False, indent=2))

    except Exception as error:
        debug_report["exception"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        write_debug_json(debug_path, debug_report)
        raise

    assert isinstance(result, dict), "El RankingEngine no ha devuelto un dict"

    assert debug_path.exists(), f"No se ha generado el debug report: {debug_path}"

    assert output_path.exists(), (
        "No se ha generado el archivo de output. "
        f"Revisa el debug report en: {debug_path}"
    )

    saved_result = read_json(output_path)

    assert saved_result == result, (
        "El archivo guardado no coincide con el resultado devuelto por rank_patient_candidate_file."
    )

    assert "ranking_status" in result
    assert "ranked_trials" in result
    assert "summary" in result
    assert "flags" in result

    if not result["ranked_trials"]:
        pytest.fail(
            "El ranking se ha generado, pero ranked_trials está vacío. "
            f"Revisa el debug report en: {debug_path}"
        )