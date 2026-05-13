# -*- coding: utf-8 -*-

#pytest tests/tests_unitaris/test_criterion_evaluator_patient3.py -v

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from criterion_evaluator import CriterionEvaluator


def read_json(path: Path) -> dict:
    assert path.exists(), f"No existe el archivo: {path}"
    assert path.is_file(), f"La ruta no es un archivo: {path}"

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    assert isinstance(data, dict), f"El JSON raíz debe ser un objeto: {path}"
    return data


def test_criterion_evaluator_patient3_real_files():
    """
    Test unitario/integración ligera del CriterionEvaluator.

    Inputs:
        - data/extracted_patients/patient3.json
        - data/parsed_trial_criteria/trial_candidates_with_criteria_real.json

    Output:
        - data/criterion_evaluations/patient3_criterion_evaluation.json
    """

    patient_path = PROJECT_ROOT / "data" / "extracted_patients" / "patient3.json"
    candidates_path = (
        PROJECT_ROOT
        / "data"
        / "parsed_trial_criteria"
        / "trial_candidates_with_criteria_real.json"
    )

    output_dir = PROJECT_ROOT / "data" / "criterion_evaluations"
    output_path = output_dir / "patient3_criterion_evaluation.json"

    patient_attribute_set = read_json(patient_path)
    candidate_json = read_json(candidates_path)

    evaluator = CriterionEvaluator()

    result = evaluator.evaluate_patient_candidate_file(
        candidate_json=candidate_json,
        patient_attribute_set=patient_attribute_set,
        output_path=output_path,
    )

    assert isinstance(result, dict)

    assert output_path.exists(), f"No se ha generado el output: {output_path}"
    assert output_path.is_file(), f"El output no es un archivo: {output_path}"

    saved_result = read_json(output_path)

    assert saved_result == result

    assert "unique_studies" in saved_result
    assert isinstance(saved_result["unique_studies"], list)

    assert "criterion_evaluator_summary" in saved_result
    assert isinstance(saved_result["criterion_evaluator_summary"], dict)

    if len(saved_result["unique_studies"]) == 0:
        pytest.skip("El archivo de candidatos no contiene unique_studies.")

    first_study = saved_result["unique_studies"][0]

    assert isinstance(first_study, dict)
    assert "criterion_evaluation" in first_study

    evaluation = first_study["criterion_evaluation"]

    assert isinstance(evaluation, dict)
    assert "trial_id" in evaluation
    assert "evaluation_status" in evaluation
    assert "summary" in evaluation
    assert "inclusion" in evaluation
    assert "exclusion" in evaluation
    assert "all" in evaluation

    assert isinstance(evaluation["inclusion"], list)
    assert isinstance(evaluation["exclusion"], list)
    assert isinstance(evaluation["all"], list)
    assert isinstance(evaluation["summary"], dict)

    valid_trial_statuses = {
        "completed",
        "completed_with_unknowns",
        "completed_with_blockers",
        "completed_with_errors",
        "no_criteria",
        "failed",
    }

    assert evaluation["evaluation_status"] in valid_trial_statuses

    for criterion_evaluation in evaluation["all"]:
        assert "criterion_id" in criterion_evaluation
        assert "trial_id" in criterion_evaluation
        assert "criterion_type" in criterion_evaluation
        assert "raw_text" in criterion_evaluation
        assert "evaluation_status" in criterion_evaluation
        assert "eligibility_impact" in criterion_evaluation

        assert criterion_evaluation["evaluation_status"] in {
            "met",
            "not_met",
            "unknown",
            "not_applicable",
            "evaluation_error",
        }

        assert criterion_evaluation["eligibility_impact"] in {
            "supports_eligibility",
            "hurts_eligibility",
            "neutral",
            "unknown",
        }