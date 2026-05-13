"""
Runner real para TrialCriteriaParser.

Entrada:
    data/trial_candidate_store/trial_candidates.json

Salida:
    data/parsed_trial_criteria/trial_candidates_with_criteria_real.json

Ejecución directa:
    python test/test_trial_criteria_parser_real.py

Ejecución con pytest:
    pytest test/test_trial_criteria_parser_real.py -s

Opcionalmente puedes limitar el número de estudios para no gastar tantos tokens:

    python test/test_trial_criteria_parser_real.py --max-studies 3

o:

    TRIAL_CRITERIA_MAX_STUDIES=3 python test/test_trial_criteria_parser_real.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from trial_criteria_parser import (  # noqa: E402
    TrialCriteriaParser,
    TrialCriteriaParserConfig,
)


INPUT_PATH = PROJECT_ROOT / "data" / "trial_candidate_store" / "trial_candidates.json"

OUTPUT_DIR = PROJECT_ROOT / "data" / "parsed_trial_criteria"
OUTPUT_PATH = OUTPUT_DIR / "trial_candidates_with_criteria_real.json"
SUMMARY_PATH = OUTPUT_DIR / "trial_candidates_with_criteria_real_summary.json"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def load_input_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el fichero de entrada: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("El fichero de entrada debe contener un JSON object en la raíz.")

    if "unique_studies" not in data:
        raise ValueError("El JSON de entrada debe contener el campo `unique_studies`.")

    if not isinstance(data["unique_studies"], list):
        raise ValueError("El campo `unique_studies` debe ser una lista.")

    return data


def maybe_limit_studies(
    candidate_json: dict[str, Any],
    max_studies: int | None,
) -> dict[str, Any]:
    if max_studies is None or max_studies <= 0:
        return candidate_json

    limited = dict(candidate_json)
    original_studies = candidate_json.get("unique_studies", [])

    limited["unique_studies"] = original_studies[:max_studies]
    limited.setdefault("warnings", [])
    limited["warnings"] = list(limited["warnings"])
    limited["warnings"].append(
        f"TrialCriteriaParser real test limited to first {max_studies} studies."
    )

    limited.setdefault("test_metadata", {})
    limited["test_metadata"] = dict(limited["test_metadata"])
    limited["test_metadata"]["max_studies"] = max_studies
    limited["test_metadata"]["original_unique_studies"] = len(original_studies)

    return limited


def build_summary(parsed_json: dict[str, Any]) -> dict[str, Any]:
    studies = parsed_json.get("unique_studies", [])

    parsed_status_counts: dict[str, int] = {}
    total_inclusion = 0
    total_exclusion = 0
    total_all = 0
    total_llm_calls = 0
    total_parse_errors = 0
    total_parse_warnings = 0

    study_summaries: list[dict[str, Any]] = []

    for study in studies:
        nct_id = study.get("nct_id")
        criteria = study.get("criteria", {})

        parsed_status = criteria.get("parsed_status", "missing")
        parsed_status_counts[parsed_status] = parsed_status_counts.get(parsed_status, 0) + 1

        inclusion = criteria.get("inclusion", [])
        exclusion = criteria.get("exclusion", [])
        all_criteria = criteria.get("all", [])

        parse_errors = criteria.get("parse_errors", [])
        parse_warnings = criteria.get("parse_warnings", [])

        parser_metadata = criteria.get("parser_metadata", {})
        llm_calls = parser_metadata.get("llm_calls", [])

        total_inclusion += len(inclusion)
        total_exclusion += len(exclusion)
        total_all += len(all_criteria)
        total_llm_calls += len(llm_calls)
        total_parse_errors += len(parse_errors)
        total_parse_warnings += len(parse_warnings)

        study_summaries.append(
            {
                "nct_id": nct_id,
                "parsed_status": parsed_status,
                "n_inclusion": len(inclusion),
                "n_exclusion": len(exclusion),
                "n_all": len(all_criteria),
                "n_llm_calls": len(llm_calls),
                "n_parse_errors": len(parse_errors),
                "n_parse_warnings": len(parse_warnings),
            }
        )

    return {
        "input_path": str(INPUT_PATH),
        "output_path": str(OUTPUT_PATH),
        "total_studies": len(studies),
        "parsed_status_counts": parsed_status_counts,
        "total_inclusion_criteria": total_inclusion,
        "total_exclusion_criteria": total_exclusion,
        "total_all_criteria": total_all,
        "total_llm_calls": total_llm_calls,
        "total_parse_errors": total_parse_errors,
        "total_parse_warnings": total_parse_warnings,
        "studies": study_summaries,
    }


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------


def run_trial_criteria_parser_real(
    max_studies: int | None = None,
) -> dict[str, Any]:
    candidate_json = load_input_json(INPUT_PATH)
    candidate_json = maybe_limit_studies(candidate_json, max_studies)

    config = TrialCriteriaParserConfig(
        enable_cache=False,
        enable_hardness_llm=False,
    )

    parser = TrialCriteriaParser(
        config=config,
        # No pasamos inclusion_llm/exclusion_llm/hardness_llm.
        # Así se crean usando LLM_factory.create_llm(...)
        cache=None,
        logger=None,
        normalizer=None,
    )

    parsed_json = parser.parse_patient_candidate_file(candidate_json)

    save_json(parsed_json, OUTPUT_PATH)

    summary = build_summary(parsed_json)
    save_json(summary, SUMMARY_PATH)

    return parsed_json


# ---------------------------------------------------------------------
# Pytest test
# ---------------------------------------------------------------------


def test_trial_criteria_parser_real_generates_output_file() -> None:
    max_studies_env = os.getenv("TRIAL_CRITERIA_MAX_STUDIES")
    max_studies = int(max_studies_env) if max_studies_env else 1

    parsed_json = run_trial_criteria_parser_real(max_studies=max_studies)

    assert OUTPUT_PATH.exists(), f"No se ha generado la salida: {OUTPUT_PATH}"
    assert SUMMARY_PATH.exists(), f"No se ha generado el resumen: {SUMMARY_PATH}"

    assert isinstance(parsed_json, dict)
    assert "unique_studies" in parsed_json
    assert isinstance(parsed_json["unique_studies"], list)

    assert len(parsed_json["unique_studies"]) > 0

    first_study = parsed_json["unique_studies"][0]

    assert "nct_id" in first_study
    assert "trial" in first_study
    assert "criteria" in first_study

    criteria = first_study["criteria"]

    assert "raw" in criteria
    assert "parsed_status" in criteria
    assert "inclusion" in criteria
    assert "exclusion" in criteria
    assert "all" in criteria
    assert "parse_warnings" in criteria
    assert "parse_errors" in criteria
    assert "parser_metadata" in criteria

    assert isinstance(criteria["inclusion"], list)
    assert isinstance(criteria["exclusion"], list)
    assert isinstance(criteria["all"], list)

    parser_metadata = criteria["parser_metadata"]

    assert "parser_version" in parser_metadata
    assert "schema_version" in parser_metadata
    assert "llm_calls" in parser_metadata


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta TrialCriteriaParser real sobre trial_candidates.json."
    )

    parser.add_argument(
        "--max-studies",
        type=int,
        default=None,
        help=(
            "Número máximo de estudios a procesar. "
            "Si no se indica, procesa todos los estudios."
        ),
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    env_max_studies = os.getenv("TRIAL_CRITERIA_MAX_STUDIES")

    if args.max_studies is not None:
        max_studies = args.max_studies
    elif env_max_studies:
        max_studies = int(env_max_studies)
    else:
        max_studies = None

    result = run_trial_criteria_parser_real(max_studies=max_studies)
    summary = build_summary(result)

    print("TrialCriteriaParser real ejecutado correctamente.")
    print(f"Entrada: {INPUT_PATH}")
    print(f"Salida: {OUTPUT_PATH}")
    print(f"Resumen: {SUMMARY_PATH}")
    print(f"Estudios procesados: {summary['total_studies']}")
    print(f"Criterios inclusion: {summary['total_inclusion_criteria']}")
    print(f"Criterios exclusion: {summary['total_exclusion_criteria']}")
    print(f"Criterios totales: {summary['total_all_criteria']}")
    print(f"Llamadas LLM registradas: {summary['total_llm_calls']}")
    print(f"Errores de parseo: {summary['total_parse_errors']}")
    print(f"Warnings de parseo: {summary['total_parse_warnings']}")
    print(f"Estados: {summary['parsed_status_counts']}")
