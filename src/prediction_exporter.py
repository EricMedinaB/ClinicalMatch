# -*- coding: utf-8 -*-

"""
Prediction Exporter.

Módulo 16 del pipeline.

Responsabilidad:
    - Leer todos los JSON generados por RankingEngine desde un directorio.
    - Reunificar rankings individuales por paciente/topic.
    - Generar un JSON final de predicciones.
    - Generar opcionalmente un archivo TREC run .txt.
    - Mantener el output simple, determinista y compatible con submission.

No hace:
    - Ranking.
    - Evaluación de criterios.
    - Extracción clínica.
    - Parsing de criterios.
    - Llamadas a LLM.
    - Consultas externas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------


ExportStatus = Literal[
    "completed",
    "completed_with_warnings",
    "empty",
    "failed",
]

FlagSeverity = Literal[
    "low",
    "medium",
    "high",
]


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------


class ExportedTrialPrediction(BaseModel):
    """
    Predicción final de un trial para un paciente/topic.
    """

    model_config = ConfigDict(extra="forbid")

    rank: int
    nct_id: str
    score: float


class TopicPrediction(BaseModel):
    """
    Predicciones finales para un paciente/topic.
    """

    model_config = ConfigDict(extra="forbid")

    topic_id: str
    patient_id: str | None = None
    source_file: str | None = None

    trials: list[ExportedTrialPrediction] = Field(default_factory=list)


class PredictionExportSummary(BaseModel):
    """
    Resumen global de la exportación.
    """

    model_config = ConfigDict(extra="forbid")

    total_input_files: int = 0
    total_valid_ranking_files: int = 0
    total_invalid_ranking_files: int = 0

    total_topics: int = 0
    total_predictions: int = 0

    max_predictions_per_topic: int = 1000

    topics_without_predictions: int = 0
    duplicate_topic_files: int = 0
    duplicate_trials_removed: int = 0
    invalid_trials_removed: int = 0


class PredictionExportFlag(BaseModel):
    """
    Flag global de exportación.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    severity: FlagSeverity
    message: str
    source_file: str | None = None
    topic_id: str | None = None


class PredictionExportResult(BaseModel):
    """
    Resultado final del PredictionExporter.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "prediction_export_v1"
    run_name: str
    export_status: ExportStatus

    predictions: list[TopicPrediction] = Field(default_factory=list)
    trec_run_lines: list[str] = Field(default_factory=list)

    summary: PredictionExportSummary
    flags: list[PredictionExportFlag] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Prediction Exporter
# -----------------------------------------------------------------------------


class PredictionExporter:
    def __init__(
        self,
        run_name: str = "CLINMATCH1",
        max_predictions_per_topic: int = 1000,
    ) -> None:
        """
        Inicializa el exportador.

        Args:
            run_name:
                Identificador del run final.
                Reglas:
                    - alfanumérico
                    - máximo 12 caracteres

            max_predictions_per_topic:
                Número máximo de trials exportados por paciente/topic.
        """
        self.run_name = self._validate_run_name(run_name)

        if not isinstance(max_predictions_per_topic, int):
            raise TypeError("max_predictions_per_topic debe ser un entero")

        if max_predictions_per_topic <= 0:
            raise ValueError("max_predictions_per_topic debe ser > 0")

        self.max_predictions_per_topic = max_predictions_per_topic

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_from_directory(
        self,
        input_dir: str | Path,
        output_json_path: str | Path,
        output_trec_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Lee todos los JSON de RankingEngine dentro de un directorio
        y genera la exportación final.

        Args:
            input_dir:
                Carpeta que contiene los JSON individuales del RankingEngine.

            output_json_path:
                Ruta donde guardar el JSON final unificado.

            output_trec_path:
                Ruta opcional donde guardar el archivo .txt estilo TREC.

        Returns:
            Diccionario con el resultado final de exportación.
        """
        ranking_files = self._collect_ranking_files(input_dir)

        ranking_items: list[tuple[Path, dict[str, Any] | None]] = []

        for path in ranking_files:
            ranking_items.append(
                (
                    path,
                    self._read_ranking_file(path),
                )
            )

        result = self._build_export_result(ranking_items)

        self._write_outputs(
            result=result,
            output_json_path=output_json_path,
            output_trec_path=output_trec_path,
        )

        return result.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Directory and file loading
    # ------------------------------------------------------------------

    def _collect_ranking_files(
        self,
        input_dir: str | Path,
    ) -> list[Path]:
        """
        Recoge todos los archivos .json del directorio.

        Valida que input_dir exista y sea un directorio.
        Devuelve los JSON ordenados por nombre para reproducibilidad.
        """
        input_dir = Path(input_dir)

        if not input_dir.exists():
            raise FileNotFoundError(f"No existe el directorio: {input_dir}")

        if not input_dir.is_dir():
            raise NotADirectoryError(f"La ruta no es un directorio: {input_dir}")

        return sorted(
            [
                path
                for path in input_dir.glob("*.json")
                if path.is_file()
            ],
            key=lambda item: item.name.lower(),
        )

    def _read_ranking_file(
        self,
        path: Path,
    ) -> dict[str, Any] | None:
        """
        Lee un archivo JSON individual del RankingEngine.

        Si el archivo no es válido, devuelve None.
        """
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return None

            return data

        except Exception:
            return None

    # ------------------------------------------------------------------
    # Export building
    # ------------------------------------------------------------------

    def _build_export_result(
        self,
        ranking_items: list[tuple[Path, dict[str, Any] | None]],
    ) -> PredictionExportResult:
        """
        Construye el resultado final a partir de varios ranking results.
        """
        flags: list[PredictionExportFlag] = []
        predictions: list[TopicPrediction] = []

        for source_path, ranking_result in ranking_items:
            source_file = source_path.name

            if ranking_result is None:
                self._add_flag(
                    flags=flags,
                    type_="invalid_ranking_file",
                    severity="medium",
                    message="Ranking file could not be parsed as a valid JSON object.",
                    source_file=source_file,
                )
                continue

            prediction = self._prediction_from_ranking_result(
                ranking_result=ranking_result,
                source_file=source_file,
                flags=flags,
            )

            if prediction is not None:
                predictions.append(prediction)

        predictions = self._handle_duplicate_topics(
            predictions=predictions,
            flags=flags,
        )

        predictions = sorted(
            predictions,
            key=lambda item: self._topic_sort_key(item.topic_id),
        )

        trec_run_lines = self._build_trec_run_lines(predictions)

        summary = self._build_summary(
            ranking_items=ranking_items,
            predictions=predictions,
            flags=flags,
        )

        export_status = self._infer_export_status(
            predictions=predictions,
            flags=flags,
        )

        return PredictionExportResult(
            run_name=self.run_name,
            export_status=export_status,
            predictions=predictions,
            trec_run_lines=trec_run_lines,
            summary=summary,
            flags=flags,
        )

    def _prediction_from_ranking_result(
        self,
        ranking_result: dict[str, Any],
        source_file: str | None,
        flags: list[PredictionExportFlag],
    ) -> TopicPrediction | None:
        """
        Convierte un JSON de RankingEngine en un bloque TopicPrediction.

        Debe:
            - extraer topic_id / patient_id
            - extraer ranked_trials
            - normalizar cada trial
            - eliminar trials inválidos
            - eliminar duplicados
            - limitar a max_predictions_per_topic
            - reasignar ranks 1..N
        """
        topic_id = self._extract_topic_id(
            ranking_result=ranking_result,
            source_file=source_file,
        )

        if topic_id is None:
            self._add_flag(
                flags=flags,
                type_="missing_topic_id",
                severity="high",
                message="Could not extract topic_id from ranking result or filename.",
                source_file=source_file,
            )
            return None

        patient_id = self._extract_patient_id(
            ranking_result=ranking_result,
            topic_id=topic_id,
        )

        ranked_trials = self._extract_ranked_trials(ranking_result)

        if not ranked_trials:
            self._add_flag(
                flags=flags,
                type_="topic_without_ranked_trials",
                severity="medium",
                message="Ranking result contains no ranked_trials.",
                source_file=source_file,
                topic_id=topic_id,
            )

        normalized_trials: list[ExportedTrialPrediction] = []

        for index, trial in enumerate(ranked_trials, start=1):
            if not isinstance(trial, dict):
                self._add_flag(
                    flags=flags,
                    type_="invalid_trial_prediction",
                    severity="low",
                    message="A ranked trial is not a dictionary and was removed.",
                    source_file=source_file,
                    topic_id=topic_id,
                )
                continue

            normalized_trial = self._normalize_trial_prediction(
                trial=trial,
                fallback_rank=index,
                source_file=source_file,
                topic_id=topic_id,
                flags=flags,
            )

            if normalized_trial is not None:
                normalized_trials.append(normalized_trial)

        normalized_trials = self._deduplicate_trials(
            trials=normalized_trials,
            source_file=source_file,
            topic_id=topic_id,
            flags=flags,
        )

        normalized_trials = self._rerank_trials(normalized_trials)

        if len(normalized_trials) > self.max_predictions_per_topic:
            self._add_flag(
                flags=flags,
                type_="max_predictions_per_topic_applied",
                severity="low",
                message=(
                    f"Topic had {len(normalized_trials)} predictions; "
                    f"limited to {self.max_predictions_per_topic}."
                ),
                source_file=source_file,
                topic_id=topic_id,
            )

        normalized_trials = normalized_trials[: self.max_predictions_per_topic]
        normalized_trials = self._rerank_trials(normalized_trials)

        return TopicPrediction(
            topic_id=topic_id,
            patient_id=patient_id,
            source_file=source_file,
            trials=normalized_trials,
        )

    def _extract_topic_id(
        self,
        ranking_result: dict[str, Any],
        source_file: str | None = None,
    ) -> str | None:
        """
        Extrae topic_id.

        Orden:
            1. ranking_result["patient_id"]
            2. número detectado en source_file
            3. None
        """
        patient_id = ranking_result.get("patient_id")

        if isinstance(patient_id, str) and patient_id.strip():
            return patient_id.strip()

        if isinstance(patient_id, int):
            return str(patient_id)

        filename_number = self._extract_number_from_filename(source_file)

        if filename_number:
            return filename_number

        return None

    def _extract_patient_id(
        self,
        ranking_result: dict[str, Any],
        topic_id: str | None,
    ) -> str | None:
        """
        Extrae patient_id.

        Normalmente será igual que topic_id.
        """
        patient_id = ranking_result.get("patient_id")

        if isinstance(patient_id, str) and patient_id.strip():
            return patient_id.strip()

        if isinstance(patient_id, int):
            return str(patient_id)

        return topic_id

    def _extract_ranked_trials(
        self,
        ranking_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Extrae ranking_result["ranked_trials"] si existe y es lista.
        """
        ranked_trials = ranking_result.get("ranked_trials", [])

        if not isinstance(ranked_trials, list):
            return []

        return [
            trial
            for trial in ranked_trials
            if isinstance(trial, dict)
        ]

    def _normalize_trial_prediction(
        self,
        trial: dict[str, Any],
        fallback_rank: int,
        source_file: str | None,
        topic_id: str | None,
        flags: list[PredictionExportFlag],
    ) -> ExportedTrialPrediction | None:
        """
        Convierte un ranked_trial del RankingEngine en ExportedTrialPrediction.
        """
        nct_id = (
            trial.get("nct_id")
            or trial.get("trial_id")
        )

        if nct_id is None and isinstance(trial.get("trial"), dict):
            nct_id = (
                trial["trial"].get("nct_id")
                or trial["trial"].get("trial_id")
            )

        nct_id = self._normalize_nct_id(nct_id)

        if nct_id is None:
            self._add_flag(
                flags=flags,
                type_="invalid_trial_nct_id",
                severity="low",
                message="A ranked trial had no valid NCT ID and was removed.",
                source_file=source_file,
                topic_id=topic_id,
            )
            return None

        score = self._safe_float(trial.get("score"))

        if score is None:
            self._add_flag(
                flags=flags,
                type_="invalid_trial_score",
                severity="low",
                message=f"Trial {nct_id} had no valid numeric score and was removed.",
                source_file=source_file,
                topic_id=topic_id,
            )
            return None

        rank = self._safe_int(trial.get("rank"), default=fallback_rank)

        if rank is None or rank <= 0:
            rank = fallback_rank

        return ExportedTrialPrediction(
            rank=rank,
            nct_id=nct_id,
            score=score,
        )

    def _deduplicate_trials(
        self,
        trials: list[ExportedTrialPrediction],
        source_file: str | None,
        topic_id: str | None,
        flags: list[PredictionExportFlag],
    ) -> list[ExportedTrialPrediction]:
        """
        Elimina duplicados de NCT ID dentro de un mismo topic.

        Conserva:
            - el de mejor rank
            - si rank empata, el de mayor score
        """
        if not trials:
            return []

        sorted_trials = sorted(
            trials,
            key=lambda item: (
                item.rank,
                -item.score,
                item.nct_id,
            ),
        )

        seen: set[str] = set()
        deduplicated: list[ExportedTrialPrediction] = []
        removed = 0

        for trial in sorted_trials:
            if trial.nct_id in seen:
                removed += 1
                continue

            seen.add(trial.nct_id)
            deduplicated.append(trial)

        if removed > 0:
            self._add_flag(
                flags=flags,
                type_="duplicate_trials_removed",
                severity="low",
                message=f"{removed} duplicate trial prediction(s) were removed.",
                source_file=source_file,
                topic_id=topic_id,
            )

        return deduplicated

    def _rerank_trials(
        self,
        trials: list[ExportedTrialPrediction],
    ) -> list[ExportedTrialPrediction]:
        """
        Ordena y reasigna ranks 1..N.

        Orden:
            1. rank ascendente
            2. score descendente
            3. nct_id ascendente
        """
        sorted_trials = sorted(
            trials,
            key=lambda item: (
                item.rank,
                -item.score,
                item.nct_id,
            ),
        )

        reranked: list[ExportedTrialPrediction] = []

        for index, trial in enumerate(sorted_trials, start=1):
            reranked.append(
                ExportedTrialPrediction(
                    rank=index,
                    nct_id=trial.nct_id,
                    score=trial.score,
                )
            )

        return reranked

    # ------------------------------------------------------------------
    # TREC output
    # ------------------------------------------------------------------

    def _build_trec_run_lines(
        self,
        predictions: list[TopicPrediction],
    ) -> list[str]:
        """
        Genera todas las líneas TREC.

        Formato:
            TOPIC_NO Q0 ID RANK SCORE RUN_NAME
        """
        lines: list[str] = []

        for prediction in sorted(
            predictions,
            key=lambda item: self._topic_sort_key(item.topic_id),
        ):
            for trial in sorted(prediction.trials, key=lambda item: item.rank):
                lines.append(
                    self._build_trec_line(
                        topic_id=prediction.topic_id,
                        trial=trial,
                    )
                )

        return lines

    def _build_trec_line(
        self,
        topic_id: str,
        trial: ExportedTrialPrediction,
    ) -> str:
        """
        Genera una línea TREC.

        Ejemplo:
            3 Q0 NCT01234567 1 92.4187 CLINMATCH1
        """
        return (
            f"{topic_id} "
            f"Q0 "
            f"{trial.nct_id} "
            f"{trial.rank} "
            f"{trial.score:.4f} "
            f"{self.run_name}"
        )

    # ------------------------------------------------------------------
    # Summary and status
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        ranking_items: list[tuple[Path, dict[str, Any] | None]],
        predictions: list[TopicPrediction],
        flags: list[PredictionExportFlag],
    ) -> PredictionExportSummary:
        """
        Construye el summary global de la exportación.
        """
        total_input_files = len(ranking_items)
        total_invalid_ranking_files = sum(
            1
            for _, data in ranking_items
            if data is None
        )
        total_valid_ranking_files = total_input_files - total_invalid_ranking_files

        total_topics = len(predictions)
        total_predictions = sum(len(item.trials) for item in predictions)

        topics_without_predictions = sum(
            1
            for item in predictions
            if len(item.trials) == 0
        )

        duplicate_topic_files = sum(
            1
            for flag in flags
            if flag.type == "duplicate_topic_file"
        )

        duplicate_trials_removed = 0
        invalid_trials_removed = 0

        for flag in flags:
            if flag.type == "duplicate_trials_removed":
                duplicate_trials_removed += self._extract_first_int(flag.message)

            if flag.type in {
                "invalid_trial_prediction",
                "invalid_trial_nct_id",
                "invalid_trial_score",
            }:
                invalid_trials_removed += 1

        return PredictionExportSummary(
            total_input_files=total_input_files,
            total_valid_ranking_files=total_valid_ranking_files,
            total_invalid_ranking_files=total_invalid_ranking_files,
            total_topics=total_topics,
            total_predictions=total_predictions,
            max_predictions_per_topic=self.max_predictions_per_topic,
            topics_without_predictions=topics_without_predictions,
            duplicate_topic_files=duplicate_topic_files,
            duplicate_trials_removed=duplicate_trials_removed,
            invalid_trials_removed=invalid_trials_removed,
        )

    def _infer_export_status(
        self,
        predictions: list[TopicPrediction],
        flags: list[PredictionExportFlag],
    ) -> ExportStatus:
        """
        Determina export_status.

        Reglas:
            - failed si hay flags high y no hay predicciones útiles
            - empty si no hay predicciones útiles
            - completed_with_warnings si hay flags
            - completed si todo correcto
        """
        total_trial_predictions = sum(len(item.trials) for item in predictions)
        has_high_flags = any(flag.severity == "high" for flag in flags)

        if total_trial_predictions == 0 and has_high_flags:
            return "failed"

        if total_trial_predictions == 0:
            return "empty"

        if flags:
            return "completed_with_warnings"

        return "completed"

    def _handle_duplicate_topics(
        self,
        predictions: list[TopicPrediction],
        flags: list[PredictionExportFlag],
    ) -> list[TopicPrediction]:
        """
        Detecta topic_id repetidos.

        MVP:
            - conserva el primer topic encontrado
            - descarta duplicados posteriores
            - añade flag
        """
        seen: set[str] = set()
        unique_predictions: list[TopicPrediction] = []

        for prediction in predictions:
            if prediction.topic_id in seen:
                self._add_flag(
                    flags=flags,
                    type_="duplicate_topic_file",
                    severity="medium",
                    message=(
                        f"Duplicate topic_id '{prediction.topic_id}' was found. "
                        "Only the first occurrence was kept."
                    ),
                    source_file=prediction.source_file,
                    topic_id=prediction.topic_id,
                )
                continue

            seen.add(prediction.topic_id)
            unique_predictions.append(prediction)

        return unique_predictions

    # ------------------------------------------------------------------
    # Output writing
    # ------------------------------------------------------------------

    def _write_outputs(
        self,
        result: PredictionExportResult,
        output_json_path: str | Path,
        output_trec_path: str | Path | None,
    ) -> None:
        """
        Guarda:
            - JSON final obligatorio
            - TXT TREC opcional
        """
        self._write_json(
            data=result.model_dump(mode="json"),
            output_path=output_json_path,
        )

        if output_trec_path is not None:
            self._write_trec_txt(
                trec_run_lines=result.trec_run_lines,
                output_path=output_trec_path,
            )

    def _write_json(
        self,
        data: dict[str, Any],
        output_path: str | Path,
    ) -> None:
        """
        Guarda JSON creando la carpeta padre si no existe.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def _write_trec_txt(
        self,
        trec_run_lines: list[str],
        output_path: str | Path,
    ) -> None:
        """
        Guarda archivo .txt con líneas TREC.

        Acaba con salto de línea final si hay contenido.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = "\n".join(trec_run_lines)

        if content:
            content += "\n"

        with output_path.open("w", encoding="utf-8") as file:
            file.write(content)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_run_name(
        self,
        run_name: str,
    ) -> str:
        """
        Valida run_name.

        Reglas:
            - no vacío
            - alfanumérico
            - máximo 12 caracteres
        """
        if not isinstance(run_name, str):
            raise TypeError("run_name debe ser un string")

        run_name = run_name.strip()

        if not run_name:
            raise ValueError("run_name no puede estar vacío")

        if len(run_name) > 12:
            raise ValueError("run_name debe tener máximo 12 caracteres")

        if not re.fullmatch(r"[A-Za-z0-9]+", run_name):
            raise ValueError("run_name solo puede contener caracteres alfanuméricos")

        return run_name

    def _is_valid_nct_id(
        self,
        value: Any,
    ) -> bool:
        """
        Valida un NCT ID.

        Regla:
            - string
            - empieza por NCT
            - seguido de dígitos
        """
        if not isinstance(value, str):
            return False

        return bool(re.fullmatch(r"NCT\d+", value.strip().upper()))

    def _normalize_nct_id(
        self,
        value: Any,
    ) -> str | None:
        """
        Normaliza NCT ID.
        """
        if value is None:
            return None

        text = str(value).strip().upper()

        if not text:
            return None

        match = re.search(r"NCT\d+", text)

        if not match:
            return None

        nct_id = match.group(0)

        if not self._is_valid_nct_id(nct_id):
            return None

        return nct_id

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _safe_float(
        self,
        value: Any,
        default: float | None = None,
    ) -> float | None:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        if isinstance(value, int | float):
            return float(value)

        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return default

        return default

    def _safe_int(
        self,
        value: Any,
        default: int | None = None,
    ) -> int | None:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str):
            try:
                return int(float(value.strip()))
            except ValueError:
                return default

        return default

    def _safe_str(
        self,
        value: Any,
        default: str | None = None,
    ) -> str | None:
        if value is None:
            return default

        text = str(value).strip()

        return text or default

    def _extract_number_from_filename(
        self,
        filename: str | None,
    ) -> str | None:
        """
        Extrae número del nombre del archivo.

        Ejemplos:
            patient_3.json -> "3"
            ranking_patient12.json -> "12"
            2021_topic_45.json -> "45"
        """
        if not filename:
            return None

        stem = Path(filename).stem

        preferred_patterns = [
            r"(?:patient|topic|case|id)[_\-\s]*(\d+)",
            r"(\d+)",
        ]

        for pattern in preferred_patterns:
            match = re.search(pattern, stem, flags=re.IGNORECASE)

            if match:
                return match.group(1)

        return None

    def _add_flag(
        self,
        flags: list[PredictionExportFlag],
        type_: str,
        severity: FlagSeverity,
        message: str,
        source_file: str | None = None,
        topic_id: str | None = None,
    ) -> None:
        """
        Añade una flag al listado global.
        """
        flags.append(
            PredictionExportFlag(
                type=type_,
                severity=severity,
                message=message,
                source_file=source_file,
                topic_id=topic_id,
            )
        )

    def _topic_sort_key(
        self,
        topic_id: str,
    ) -> tuple[int, int | str]:
        """
        Ordena topic_id numéricamente cuando sea posible.
        """
        if str(topic_id).isdigit():
            return 0, int(topic_id)

        return 1, str(topic_id)

    def _extract_first_int(
        self,
        text: str,
    ) -> int:
        """
        Extrae el primer entero de un texto.
        Si no encuentra ninguno, devuelve 0.
        """
        match = re.search(r"\d+", text or "")

        if not match:
            return 0

        try:
            return int(match.group(0))
        except ValueError:
            return 0