# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from prediction_exporter import PredictionExporter


def read_json(path: Path) -> dict:
    assert path.exists(), f"No existe el archivo: {path}"
    assert path.is_file(), f"La ruta no es un archivo: {path}"

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    assert isinstance(data, dict), f"El JSON raíz debe ser un objeto: {path}"
    return data


def test_prediction_exporter_from_ranking_directory():
    """
    Test del Módulo 16: PredictionExporter.

    Input:
        data/ranking/

    Outputs:
        data/output/final_predictions.json
        data/output/submission.txt
    """

    input_dir = PROJECT_ROOT / "data" / "ranking"

    output_json_path = PROJECT_ROOT / "data" / "output" / "final_predictions.json"
    output_trec_path = PROJECT_ROOT / "data" / "output" / "submission.txt"

    assert input_dir.exists(), f"No existe la carpeta de entrada: {input_dir}"
    assert input_dir.is_dir(), f"La entrada no es una carpeta: {input_dir}"

    ranking_files = sorted(input_dir.glob("*.json"))

    assert ranking_files, f"No hay archivos .json en la carpeta: {input_dir}"

    exporter = PredictionExporter(
        run_name="CLINMATCH1",
        max_predictions_per_topic=1000,
    )

    result = exporter.export_from_directory(
        input_dir=input_dir,
        output_json_path=output_json_path,
        output_trec_path=output_trec_path,
    )

    assert isinstance(result, dict)

    assert output_json_path.exists(), (
        f"No se ha generado el JSON final: {output_json_path}"
    )
    assert output_json_path.is_file(), (
        f"El output JSON no es un archivo: {output_json_path}"
    )

    assert output_trec_path.exists(), (
        f"No se ha generado el TXT TREC: {output_trec_path}"
    )
    assert output_trec_path.is_file(), (
        f"El output TREC no es un archivo: {output_trec_path}"
    )

    saved_result = read_json(output_json_path)

    assert saved_result == result

    assert saved_result["schema_version"] == "prediction_export_v1"
    assert saved_result["run_name"] == "CLINMATCH1"

    assert saved_result["export_status"] in {
        "completed",
        "completed_with_warnings",
        "empty",
        "failed",
    }

    assert "predictions" in saved_result
    assert isinstance(saved_result["predictions"], list)

    assert "trec_run_lines" in saved_result
    assert isinstance(saved_result["trec_run_lines"], list)

    assert "summary" in saved_result
    assert isinstance(saved_result["summary"], dict)

    assert "flags" in saved_result
    assert isinstance(saved_result["flags"], list)

    summary = saved_result["summary"]

    assert summary["total_input_files"] == len(ranking_files)
    assert summary["max_predictions_per_topic"] == 1000
    assert summary["total_topics"] == len(saved_result["predictions"])
    assert summary["total_predictions"] == sum(
        len(prediction["trials"])
        for prediction in saved_result["predictions"]
    )

    assert summary["total_predictions"] == len(saved_result["trec_run_lines"])

    if summary["total_predictions"] == 0:
        pytest.skip(
            "El exporter se ha ejecutado, pero no hay predicciones finales. "
            "Revisa flags en data/output/final_predictions.json."
        )

    seen_topics = set()

    for prediction in saved_result["predictions"]:
        assert "topic_id" in prediction
        assert "patient_id" in prediction
        assert "source_file" in prediction
        assert "trials" in prediction

        topic_id = prediction["topic_id"]

        assert isinstance(topic_id, str)
        assert topic_id.strip()

        assert topic_id not in seen_topics, (
            f"Topic duplicado en output final: {topic_id}"
        )
        seen_topics.add(topic_id)

        trials = prediction["trials"]

        assert isinstance(trials, list)
        assert len(trials) <= 1000

        ranks = [trial["rank"] for trial in trials]

        assert ranks == list(range(1, len(trials) + 1)), (
            f"Ranks no consecutivos para topic {topic_id}"
        )

        seen_nct_ids = set()

        for trial in trials:
            assert "rank" in trial
            assert "nct_id" in trial
            assert "score" in trial

            assert isinstance(trial["rank"], int)
            assert trial["rank"] >= 1

            assert isinstance(trial["nct_id"], str)
            assert trial["nct_id"].startswith("NCT")

            assert trial["nct_id"] not in seen_nct_ids, (
                f"NCT duplicado en topic {topic_id}: {trial['nct_id']}"
            )
            seen_nct_ids.add(trial["nct_id"])

            assert isinstance(trial["score"], int | float)

    with output_trec_path.open("r", encoding="utf-8") as file:
        trec_lines = [
            line.strip()
            for line in file.readlines()
            if line.strip()
        ]

    assert trec_lines == saved_result["trec_run_lines"]

    for line in trec_lines:
        parts = line.split()

        assert len(parts) == 6, f"Línea TREC inválida: {line}"

        topic_id, q0, nct_id, rank, score, run_name = parts

        assert q0 == "Q0"
        assert nct_id.startswith("NCT")
        assert rank.isdigit()
        assert int(rank) >= 1
        assert float(score) >= 0
        assert run_name == "CLINMATCH1"