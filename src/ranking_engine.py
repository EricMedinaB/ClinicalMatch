# -*- coding: utf-8 -*-

"""
Ranking Engine.

Módulo 14 del pipeline.

Responsabilidad:
    - Recibir candidatos ya evaluados por CriterionEvaluator.
    - Calcular una puntuación por ensayo.
    - Ordenar ensayos por score descendente.
    - Añadir explicación, breakdown y ranking.
    - Guardar output opcionalmente en archivo JSON.

No hace:
    - Retrieval.
    - Parsing de criterios.
    - Extracción de atributos del paciente.
    - Evaluación criterio-a-criterio.
    - Llamadas a LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------
# Ranking formula constants
# -----------------------------------------------------------------------------


EvaluationStatus = Literal[
    "met",
    "not_met",
    "unknown",
    "not_applicable",
    "evaluation_error",
]

EligibilityImpact = Literal[
    "supports_eligibility",
    "hurts_eligibility",
    "neutral",
    "unknown",
]

CriterionType = Literal[
    "inclusion",
    "exclusion",
]

CriterionHardness = Literal[
    "hard",
    "soft",
    "unknown",
]

CriterionCategory = Literal[
    "demographic",
    "functional_status",
    "disease_status",
    "prior_treatment",
    "current_treatment",
    "laboratory",
    "biomarker",
    "imaging",
    "comorbidity",
    "infection",
    "reproductive",
    "administrative",
    "logistical",
    "other",
    "unknown",
]

RankingStatus = Literal[
    "completed",
    "completed_with_warnings",
    "empty",
    "failed",
]


CRITERION_VALUE: dict[tuple[str, str], dict[str, float]] = {
    ("inclusion", "hard"): {
        "met": 1.00,
        "unknown": 0.35,
        "not_met": 0.00,
        "not_applicable": 0.55,
        "evaluation_error": 0.25,
    },
    ("inclusion", "soft"): {
        "met": 1.00,
        "unknown": 0.55,
        "not_met": 0.35,
        "not_applicable": 0.70,
        "evaluation_error": 0.45,
    },
    ("inclusion", "unknown"): {
        "met": 1.00,
        "unknown": 0.45,
        "not_met": 0.20,
        "not_applicable": 0.60,
        "evaluation_error": 0.35,
    },
    ("exclusion", "hard"): {
        "not_met": 1.00,
        "unknown": 0.45,
        "met": 0.05,
        "not_applicable": 1.00,
        "evaluation_error": 0.35,
    },
    ("exclusion", "soft"): {
        "not_met": 1.00,
        "unknown": 0.65,
        "met": 0.35,
        "not_applicable": 1.00,
        "evaluation_error": 0.50,
    },
    ("exclusion", "unknown"): {
        "not_met": 1.00,
        "unknown": 0.55,
        "met": 0.20,
        "not_applicable": 1.00,
        "evaluation_error": 0.40,
    },
}


HARDNESS_WEIGHT: dict[str, float] = {
    "hard": 1.00,
    "soft": 0.45,
    "unknown": 0.60,
}


CATEGORY_WEIGHT: dict[str, float] = {
    "biomarker": 1.15,
    "disease_status": 1.12,
    "prior_treatment": 1.10,
    "current_treatment": 1.07,
    "functional_status": 1.05,
    "demographic": 1.00,
    "laboratory": 0.92,
    "imaging": 0.92,
    "comorbidity": 0.90,
    "infection": 0.90,
    "reproductive": 0.90,
    "administrative": 0.50,
    "logistical": 0.40,
    "other": 0.80,
    "unknown": 1.00,
}


CONFIDENCE_FLOOR: float = 0.70
CONFIDENCE_WEIGHT: float = 0.30

HARD_BLOCKER_MULTIPLIER: float = 0.35
SOFT_BLOCKER_MULTIPLIER: float = 0.90

UNKNOWN_HARD_PENALTY_PER_CRITERION: float = 0.03
MAX_UNKNOWN_HARD_PENALTY: float = 0.20

EVALUATION_ERROR_PENALTY_PER_CRITERION: float = 0.02
MAX_EVALUATION_ERROR_PENALTY: float = 0.15

MANY_UNKNOWN_THRESHOLD: float = 0.50
MANY_UNKNOWN_MULTIPLIER: float = 0.92

NO_BLOCKERS_BONUS: float = 1.03
HIGH_KNOWN_COVERAGE_THRESHOLD: float = 0.75
HIGH_KNOWN_COVERAGE_BONUS: float = 1.03

MAX_SCORE: float = 100.0
MIN_SCORE: float = 0.0


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------


class CriterionScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    criterion_type: str
    evaluation_status: str
    eligibility_impact: str | None = None

    hardness: str
    category: str

    criterion_value: float
    hardness_weight: float
    category_weight: float
    confidence_factor: float

    weighted_score: float
    max_weighted_score: float

    contribution_ratio: float
    reason: str | None = None


class TrialScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weighted_score_sum: float = 0.0
    max_weighted_score_sum: float = 0.0

    base_score_ratio: float = 0.0
    base_score: float = 0.0

    penalty_multiplier: float = 1.0
    bonus_multiplier: float = 1.0

    final_score: float = 0.0

    criterion_scores: list[CriterionScoreBreakdown] = Field(default_factory=list)


class RankedTrialSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_criteria: int = 0

    met: int = 0
    not_met: int = 0
    unknown: int = 0
    not_applicable: int = 0
    evaluation_error: int = 0

    inclusion_total: int = 0
    inclusion_met: int = 0
    inclusion_not_met: int = 0
    inclusion_unknown: int = 0

    exclusion_total: int = 0
    exclusion_triggered: int = 0
    exclusion_not_triggered: int = 0
    exclusion_unknown: int = 0

    hard_fail_count: int = 0
    unknown_hard_count: int = 0
    soft_unknown_count: int = 0

    known_coverage: float = 0.0


class RankedTrial(BaseModel):
    model_config = ConfigDict(extra="allow")

    rank: int | None = None

    trial_id: str
    nct_id: str | None = None

    score: float
    ranking_bucket: str

    score_breakdown: TrialScoreBreakdown
    summary: RankedTrialSummary

    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    trial: dict[str, Any] | None = None
    source_study: dict[str, Any] | None = None


class RankingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_trials: int = 0
    ranked_trials: int = 0

    excellent_matches: int = 0
    good_matches: int = 0
    possible_matches: int = 0
    low_matches: int = 0

    trials_with_blockers: int = 0
    trials_with_unknown_critical: int = 0
    trials_with_errors: int = 0

    best_score: float | None = None
    median_score: float | None = None
    worst_score: float | None = None


class RankingFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    severity: Literal["low", "medium", "high"]
    message: str


class RankingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str | None = None

    ranking_status: RankingStatus
    ranking_version: str = "ranking_engine_v1"

    ranked_trials: list[RankedTrial] = Field(default_factory=list)

    summary: RankingSummary
    flags: list[RankingFlag] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Ranking Engine
# -----------------------------------------------------------------------------


class RankingEngine:
    def __init__(self) -> None:
        """
        RankingEngine determinista.

        La fórmula está definida por constantes globales del módulo:
            - CRITERION_VALUE
            - HARDNESS_WEIGHT
            - CATEGORY_WEIGHT
            - penalizaciones
            - bonuses

        No recibe configuración externa para evitar inconsistencias entre runs.
        """
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank_patient_candidate_file(
        self,
        candidate_json: dict[str, Any],
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Public API principal.

        Recibe el JSON después de CriterionEvaluator.

        Espera:
            candidate_json["unique_studies"][i]["criterion_evaluation"]

        Devuelve:
            {
                "patient_id": ...,
                "ranking_status": ...,
                "ranked_trials": [...],
                "summary": ...,
                "flags": [...]
            }

        Si output_path se proporciona, guarda el resultado en JSON.
        """
        if not isinstance(candidate_json, dict):
            result = RankingResult(
                patient_id=None,
                ranking_status="failed",
                ranked_trials=[],
                summary=RankingSummary(total_trials=0, ranked_trials=0),
                flags=[
                    RankingFlag(
                        type="invalid_input",
                        severity="high",
                        message="candidate_json must be a dictionary.",
                    )
                ],
            )
            output = result.model_dump(mode="json", by_alias=True)
            self._write_json_if_needed(output, output_path)
            return output

        patient_id = self._get_patient_id(candidate_json)
        unique_studies = candidate_json.get("unique_studies", [])

        flags: list[RankingFlag] = []

        if not isinstance(unique_studies, list):
            result = RankingResult(
                patient_id=patient_id,
                ranking_status="failed",
                ranked_trials=[],
                summary=RankingSummary(total_trials=0, ranked_trials=0),
                flags=[
                    RankingFlag(
                        type="invalid_unique_studies",
                        severity="high",
                        message="candidate_json['unique_studies'] must be a list.",
                    )
                ],
            )
            output = result.model_dump(mode="json", by_alias=True)
            self._write_json_if_needed(output, output_path)
            return output

        ranked_trials = self.rank_trials(unique_studies)
        summary = self._build_ranking_summary(
            ranked_trials=ranked_trials,
            total_trials=len(unique_studies),
        )

        flags.extend(
            self._build_flags(
                ranked_trials=ranked_trials,
                total_trials=len(unique_studies),
            )
        )

        status = self._infer_ranking_status(
            ranked_trials=ranked_trials,
            flags=flags,
        )

        result = RankingResult(
            patient_id=patient_id,
            ranking_status=status,
            ranked_trials=ranked_trials,
            summary=summary,
            flags=flags,
        )

        output = result.model_dump(mode="json", by_alias=True)
        self._write_json_if_needed(output, output_path)

        return output

    def rank_trials(
        self,
        studies: list[dict[str, Any]],
    ) -> list[RankedTrial]:
        """
        Calcula score de todos los estudios válidos y los ordena de mayor a menor.
        """
        ranked_trials: list[RankedTrial] = []

        for study in studies:
            if not isinstance(study, dict):
                continue

            ranked_trial = self.score_trial(study)
            ranked_trials.append(ranked_trial)

        ranked_trials.sort(
            key=lambda item: (
                item.score,
                -item.summary.hard_fail_count,
                -item.summary.unknown_hard_count,
                item.summary.known_coverage,
                item.trial_id,
            ),
            reverse=True,
        )

        return self._assign_ranks(ranked_trials)

    def score_trial(
        self,
        study: dict[str, Any],
    ) -> RankedTrial:
        """
        Calcula el score completo de un ensayo.
        """
        trial_id = self._get_trial_id(study)
        trial_evaluation = self._get_criterion_evaluation_block(study)

        warnings: list[str] = []

        if trial_evaluation is None:
            warnings.append(
                "Study has no valid criterion_evaluation block. Assigned score 0."
            )

            summary = RankedTrialSummary(total_criteria=0, known_coverage=0.0)
            breakdown = TrialScoreBreakdown(
                weighted_score_sum=0.0,
                max_weighted_score_sum=0.0,
                base_score_ratio=0.0,
                base_score=0.0,
                penalty_multiplier=1.0,
                bonus_multiplier=1.0,
                final_score=0.0,
                criterion_scores=[],
            )

            ranked_trial = RankedTrial(
                rank=None,
                trial_id=trial_id,
                nct_id=trial_id,
                score=0.0,
                ranking_bucket="low_match",
                score_breakdown=breakdown,
                summary=summary,
                reasons=[
                    "No criterion evaluation was available for this trial."
                ],
                warnings=warnings,
                trial=study.get("trial") if isinstance(study.get("trial"), dict) else None,
                source_study=None,
            )
            return ranked_trial

        criterion_evaluations = self._get_all_criterion_evaluations(
            trial_evaluation
        )

        criterion_scores = [
            self.score_criterion(criterion_evaluation)
            for criterion_evaluation in criterion_evaluations
            if isinstance(criterion_evaluation, dict)
        ]

        summary = self._build_ranked_trial_summary(trial_evaluation)
        summary.known_coverage = self._compute_known_coverage(summary)

        (
            weighted_score_sum,
            max_weighted_score_sum,
            base_score_ratio,
        ) = self._compute_base_score(criterion_scores)

        base_score = base_score_ratio * 100.0

        penalty_multiplier = self._compute_penalty_multiplier(
            trial_evaluation=trial_evaluation,
            summary=summary,
        )
        bonus_multiplier = self._compute_bonus_multiplier(summary)

        final_score = self._clip_score(
            base_score * penalty_multiplier * bonus_multiplier
        )

        breakdown = TrialScoreBreakdown(
            weighted_score_sum=round(weighted_score_sum, 6),
            max_weighted_score_sum=round(max_weighted_score_sum, 6),
            base_score_ratio=round(base_score_ratio, 6),
            base_score=round(base_score, 4),
            penalty_multiplier=round(penalty_multiplier, 6),
            bonus_multiplier=round(bonus_multiplier, 6),
            final_score=round(final_score, 4),
            criterion_scores=criterion_scores,
        )

        ranked_trial = RankedTrial(
            rank=None,
            trial_id=trial_id,
            nct_id=trial_id,
            score=round(final_score, 4),
            ranking_bucket=self._build_ranking_bucket(final_score, summary),
            score_breakdown=breakdown,
            summary=summary,
            reasons=[],
            warnings=warnings,
            trial=study.get("trial") if isinstance(study.get("trial"), dict) else None,
            source_study=None,
        )

        ranked_trial.reasons = self._build_reasons(
            study=study,
            ranked_trial=ranked_trial,
        )

        return ranked_trial

    def score_criterion(
        self,
        criterion_evaluation: dict[str, Any],
    ) -> CriterionScoreBreakdown:
        """
        Calcula la contribución ponderada de un criterio ya evaluado.
        """
        criterion_id = self._safe_str(
            criterion_evaluation.get("criterion_id"),
            default="unknown_criterion",
        )
        criterion_type = self._safe_str(
            criterion_evaluation.get("criterion_type"),
            default="inclusion",
        )
        evaluation_status = self._safe_str(
            criterion_evaluation.get("evaluation_status"),
            default="unknown",
        )
        eligibility_impact = criterion_evaluation.get("eligibility_impact")

        hardness = self._safe_str(
            criterion_evaluation.get("hardness"),
            default="unknown",
        )
        category = self._safe_str(
            criterion_evaluation.get("category"),
            default="unknown",
        )

        if criterion_type not in {"inclusion", "exclusion"}:
            criterion_type = "inclusion"

        if hardness not in HARDNESS_WEIGHT:
            hardness = "unknown"

        if category not in CATEGORY_WEIGHT:
            category = "unknown"

        if evaluation_status not in {
            "met",
            "not_met",
            "unknown",
            "not_applicable",
            "evaluation_error",
        }:
            evaluation_status = "unknown"

        criterion_value = self._get_criterion_value(
            criterion_type=criterion_type,
            hardness=hardness,
            evaluation_status=evaluation_status,
        )
        hardness_weight = self._get_hardness_weight(hardness)
        category_weight = self._get_category_weight(category)
        confidence_factor = self._get_confidence_factor(criterion_evaluation)

        weighted_score = (
            criterion_value
            * hardness_weight
            * category_weight
            * confidence_factor
        )
        max_weighted_score = hardness_weight * category_weight

        contribution_ratio = (
            weighted_score / max_weighted_score
            if max_weighted_score > 0
            else 0.0
        )

        reason = (
            f"{criterion_type} / {hardness} / {category}: "
            f"{evaluation_status} -> value={criterion_value:.2f}, "
            f"weighted contribution={weighted_score:.4f}."
        )

        return CriterionScoreBreakdown(
            criterion_id=criterion_id,
            criterion_type=criterion_type,
            evaluation_status=evaluation_status,
            eligibility_impact=(
                str(eligibility_impact)
                if eligibility_impact is not None
                else None
            ),
            hardness=hardness,
            category=category,
            criterion_value=round(criterion_value, 6),
            hardness_weight=round(hardness_weight, 6),
            category_weight=round(category_weight, 6),
            confidence_factor=round(confidence_factor, 6),
            weighted_score=round(weighted_score, 6),
            max_weighted_score=round(max_weighted_score, 6),
            contribution_ratio=round(contribution_ratio, 6),
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Formula helpers
    # ------------------------------------------------------------------

    def _get_criterion_value(
        self,
        criterion_type: str,
        hardness: str,
        evaluation_status: str,
    ) -> float:
        """
        Devuelve el valor base del criterio según:
            - inclusion/exclusion
            - hard/soft/unknown
            - met/not_met/unknown/not_applicable/evaluation_error
        """
        criterion_type = self._safe_str(criterion_type, default="inclusion")
        hardness = self._safe_str(hardness, default="unknown")
        evaluation_status = self._safe_str(evaluation_status, default="unknown")

        if criterion_type not in {"inclusion", "exclusion"}:
            criterion_type = "inclusion"

        if hardness not in HARDNESS_WEIGHT:
            hardness = "unknown"

        values = CRITERION_VALUE.get(
            (criterion_type, hardness),
            CRITERION_VALUE[(criterion_type, "unknown")],
        )

        return values.get(evaluation_status, values.get("unknown", 0.0))

    def _get_hardness_weight(
        self,
        hardness: str | None,
    ) -> float:
        """
        Devuelve el peso de hardness usando HARDNESS_WEIGHT.
        """
        key = self._safe_str(hardness, default="unknown")

        return HARDNESS_WEIGHT.get(key, HARDNESS_WEIGHT["unknown"])

    def _get_category_weight(
        self,
        category: str | None,
    ) -> float:
        """
        Devuelve el peso de categoría usando CATEGORY_WEIGHT.
        """
        key = self._safe_str(category, default="unknown")

        return CATEGORY_WEIGHT.get(key, CATEGORY_WEIGHT["unknown"])

    def _get_confidence_factor(
        self,
        criterion_evaluation: dict[str, Any],
    ) -> float:
        """
        Convierte confidence en factor suave.

        Fórmula:
            confidence_factor = CONFIDENCE_FLOOR + CONFIDENCE_WEIGHT * confidence

        Con confidence desconocida, usar 1.0 para no penalizar artificialmente
        criterios que el evaluator resolvió de forma determinista.
        """
        if "confidence" not in criterion_evaluation:
            return 1.0

        raw_confidence = criterion_evaluation.get("confidence")

        if raw_confidence is None:
            return 1.0

        confidence = self._safe_float(raw_confidence, default=1.0)
        confidence = max(0.0, min(1.0, confidence))

        return CONFIDENCE_FLOOR + CONFIDENCE_WEIGHT * confidence

    def _compute_base_score(
        self,
        criterion_scores: list[CriterionScoreBreakdown],
    ) -> tuple[float, float, float]:
        """
        Devuelve:
            weighted_score_sum
            max_weighted_score_sum
            base_score_ratio
        """
        weighted_score_sum = sum(
            item.weighted_score
            for item in criterion_scores
        )
        max_weighted_score_sum = sum(
            item.max_weighted_score
            for item in criterion_scores
        )

        if max_weighted_score_sum <= 0:
            return weighted_score_sum, max_weighted_score_sum, 0.0

        base_score_ratio = weighted_score_sum / max_weighted_score_sum
        base_score_ratio = max(0.0, min(1.0, base_score_ratio))

        return weighted_score_sum, max_weighted_score_sum, base_score_ratio

    def _compute_penalty_multiplier(
        self,
        trial_evaluation: dict[str, Any],
        summary: RankedTrialSummary,
    ) -> float:
        """
        Calcula penalizaciones suaves.

        Penaliza:
            - hard blockers
            - soft blockers
            - unknown hard criteria
            - exceso de unknowns
            - evaluation errors
        """
        multiplier = 1.0

        blocking_criteria = self._coerce_list(
            trial_evaluation.get("blocking_criteria")
        )

        for criterion in blocking_criteria:
            if not isinstance(criterion, dict):
                continue

            hardness = self._safe_str(
                criterion.get("hardness"),
                default="unknown",
            )

            if hardness == "hard":
                multiplier *= HARD_BLOCKER_MULTIPLIER
            elif hardness == "soft":
                multiplier *= SOFT_BLOCKER_MULTIPLIER

        all_criteria = self._get_all_criterion_evaluations(trial_evaluation)

        soft_hurts = 0

        for criterion in all_criteria:
            if not isinstance(criterion, dict):
                continue

            hardness = self._safe_str(
                criterion.get("hardness"),
                default="unknown",
            )
            impact = self._safe_str(
                criterion.get("eligibility_impact"),
                default="unknown",
            )

            if hardness == "soft" and impact == "hurts_eligibility":
                soft_hurts += 1

        for _ in range(soft_hurts):
            multiplier *= SOFT_BLOCKER_MULTIPLIER

        unknown_hard_penalty = min(
            MAX_UNKNOWN_HARD_PENALTY,
            summary.unknown_hard_count * UNKNOWN_HARD_PENALTY_PER_CRITERION,
        )
        multiplier *= 1.0 - unknown_hard_penalty

        evaluation_error_penalty = min(
            MAX_EVALUATION_ERROR_PENALTY,
            summary.evaluation_error * EVALUATION_ERROR_PENALTY_PER_CRITERION,
        )
        multiplier *= 1.0 - evaluation_error_penalty

        unknown_ratio = (
            summary.unknown / summary.total_criteria
            if summary.total_criteria > 0
            else 0.0
        )

        if unknown_ratio > MANY_UNKNOWN_THRESHOLD:
            multiplier *= MANY_UNKNOWN_MULTIPLIER

        return max(0.05, min(1.0, multiplier))

    def _compute_bonus_multiplier(
        self,
        summary: RankedTrialSummary,
    ) -> float:
        """
        Calcula bonus suaves.

        Bonifica:
            - ausencia de hard blockers
            - buena cobertura conocida
        """
        multiplier = 1.0

        if summary.total_criteria > 0 and summary.hard_fail_count == 0:
            multiplier *= NO_BLOCKERS_BONUS

        if summary.known_coverage >= HIGH_KNOWN_COVERAGE_THRESHOLD:
            multiplier *= HIGH_KNOWN_COVERAGE_BONUS

        return max(1.0, multiplier)

    def _clip_score(
        self,
        value: float,
    ) -> float:
        """
        Limita score final a [0, 100].
        """
        return max(MIN_SCORE, min(MAX_SCORE, value))

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _get_patient_id(
        self,
        candidate_json: dict[str, Any],
    ) -> str | None:
        """
        Extrae patient_id si existe.
        """
        for key in (
            "patient_id",
            "id",
            "source_patient_id",
        ):
            value = candidate_json.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

            if isinstance(value, int):
                return str(value)

        return None

    def _get_trial_id(
        self,
        study: dict[str, Any],
    ) -> str:
        """
        Extrae trial_id / nct_id del study.
        """
        candidates = [
            study.get("nct_id"),
            study.get("trial_id"),
        ]

        trial = study.get("trial")

        if isinstance(trial, dict):
            candidates.extend(
                [
                    trial.get("nct_id"),
                    trial.get("trial_id"),
                    trial.get("id"),
                ]
            )

            identification = trial.get("identification")

            if isinstance(identification, dict):
                candidates.extend(
                    [
                        identification.get("nct_id"),
                        identification.get("trial_id"),
                    ]
                )

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return "unknown_trial"

    def _get_trial_title(
        self,
        study: dict[str, Any],
    ) -> str | None:
        """
        Extrae título del ensayo si está disponible.
        """
        candidates: list[Any] = [
            study.get("title"),
            study.get("brief_title"),
            study.get("official_title"),
        ]

        trial = study.get("trial")

        if isinstance(trial, dict):
            candidates.extend(
                [
                    trial.get("title"),
                    trial.get("brief_title"),
                    trial.get("official_title"),
                ]
            )

            identification = trial.get("identification")

            if isinstance(identification, dict):
                candidates.extend(
                    [
                        identification.get("brief_title"),
                        identification.get("official_title"),
                        identification.get("title"),
                    ]
                )

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return None

    def _get_criterion_evaluation_block(
        self,
        study: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Devuelve study["criterion_evaluation"] si existe y es válido.
        """
        block = study.get("criterion_evaluation")

        if isinstance(block, dict):
            return block

        return None

    def _get_all_criterion_evaluations(
        self,
        trial_evaluation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Devuelve criterion_evaluation["all"] si existe.
        Si no existe, concatena inclusion + exclusion.
        """
        all_criteria = trial_evaluation.get("all")

        if isinstance(all_criteria, list):
            return [
                item
                for item in all_criteria
                if isinstance(item, dict)
            ]

        all_criteria_alt = trial_evaluation.get("all_criteria")

        if isinstance(all_criteria_alt, list):
            return [
                item
                for item in all_criteria_alt
                if isinstance(item, dict)
            ]

        inclusion = self._coerce_list(trial_evaluation.get("inclusion"))
        exclusion = self._coerce_list(trial_evaluation.get("exclusion"))

        return [
            item
            for item in [*inclusion, *exclusion]
            if isinstance(item, dict)
        ]

    def _build_ranked_trial_summary(
        self,
        trial_evaluation: dict[str, Any],
    ) -> RankedTrialSummary:
        """
        Construye summary del ranking usando el summary del CriterionEvaluator.
        """
        source_summary = trial_evaluation.get("summary")

        if not isinstance(source_summary, dict):
            source_summary = {}

        summary = RankedTrialSummary(
            total_criteria=self._safe_int(source_summary.get("total_criteria")),
            met=self._safe_int(source_summary.get("met")),
            not_met=self._safe_int(source_summary.get("not_met")),
            unknown=self._safe_int(source_summary.get("unknown")),
            not_applicable=self._safe_int(source_summary.get("not_applicable")),
            evaluation_error=self._safe_int(source_summary.get("evaluation_error")),
            inclusion_total=self._safe_int(source_summary.get("inclusion_total")),
            inclusion_met=self._safe_int(source_summary.get("inclusion_met")),
            inclusion_not_met=self._safe_int(source_summary.get("inclusion_not_met")),
            inclusion_unknown=self._safe_int(source_summary.get("inclusion_unknown")),
            exclusion_total=self._safe_int(source_summary.get("exclusion_total")),
            exclusion_triggered=self._safe_int(source_summary.get("exclusion_triggered")),
            exclusion_not_triggered=self._safe_int(source_summary.get("exclusion_not_triggered")),
            exclusion_unknown=self._safe_int(source_summary.get("exclusion_unknown")),
            hard_fail_count=self._safe_int(source_summary.get("hard_fail_count")),
            unknown_hard_count=self._safe_int(source_summary.get("unknown_hard_count")),
            soft_unknown_count=self._safe_int(source_summary.get("soft_unknown_count")),
        )

        if summary.total_criteria == 0:
            all_criteria = self._get_all_criterion_evaluations(trial_evaluation)
            summary.total_criteria = len(all_criteria)

            for item in all_criteria:
                status = self._safe_str(item.get("evaluation_status"))
                criterion_type = self._safe_str(item.get("criterion_type"))
                hardness = self._safe_str(item.get("hardness"))

                if status == "met":
                    summary.met += 1
                elif status == "not_met":
                    summary.not_met += 1
                elif status == "unknown":
                    summary.unknown += 1
                elif status == "not_applicable":
                    summary.not_applicable += 1
                elif status == "evaluation_error":
                    summary.evaluation_error += 1

                if criterion_type == "inclusion":
                    summary.inclusion_total += 1
                    if status == "met":
                        summary.inclusion_met += 1
                    elif status == "not_met":
                        summary.inclusion_not_met += 1
                    elif status == "unknown":
                        summary.inclusion_unknown += 1

                elif criterion_type == "exclusion":
                    summary.exclusion_total += 1
                    if status == "met":
                        summary.exclusion_triggered += 1
                    elif status == "not_met":
                        summary.exclusion_not_triggered += 1
                    elif status == "unknown":
                        summary.exclusion_unknown += 1

                impact = self._safe_str(item.get("eligibility_impact"))

                if hardness == "hard" and impact == "hurts_eligibility":
                    summary.hard_fail_count += 1

                if hardness == "hard" and status == "unknown":
                    summary.unknown_hard_count += 1

                if hardness == "soft" and status == "unknown":
                    summary.soft_unknown_count += 1

        summary.known_coverage = self._compute_known_coverage(summary)

        return summary

    def _compute_known_coverage(
        self,
        summary: RankedTrialSummary,
    ) -> float:
        """
        Calcula proporción de criterios con información evaluable.

        known = met + not_met + not_applicable
        total = total_criteria
        """
        if summary.total_criteria <= 0:
            return 0.0

        known = summary.met + summary.not_met + summary.not_applicable

        return round(known / summary.total_criteria, 6)

    # ------------------------------------------------------------------
    # Reason generation
    # ------------------------------------------------------------------

    def _build_reasons(
        self,
        study: dict[str, Any],
        ranked_trial: RankedTrial,
    ) -> list[str]:
        """
        Genera explicaciones cortas para mostrar en frontend o reporte.
        """
        reasons: list[str] = []

        title = self._get_trial_title(study)

        if title:
            reasons.append(f"Trial: {title}")

        score = ranked_trial.score
        summary = ranked_trial.summary

        if ranked_trial.ranking_bucket == "excellent_match":
            reasons.append("Excellent overall match based on evaluated eligibility criteria.")
        elif ranked_trial.ranking_bucket == "good_match":
            reasons.append("Good overall match, with most known criteria favorable.")
        elif ranked_trial.ranking_bucket == "possible_match":
            reasons.append("Possible match, but some criteria are unknown or unfavorable.")
        else:
            reasons.append("Low match based on current criterion evaluation.")

        if summary.hard_fail_count > 0:
            reasons.append(
                f"{summary.hard_fail_count} hard blocking criterion/criteria were found."
            )
        else:
            reasons.append("No hard blocking criteria were found.")

        if summary.unknown_hard_count > 0:
            reasons.append(
                f"{summary.unknown_hard_count} hard criterion/criteria remain unknown."
            )

        if summary.known_coverage >= HIGH_KNOWN_COVERAGE_THRESHOLD:
            reasons.append(
                f"Known criterion coverage is high ({summary.known_coverage:.0%})."
            )
        elif summary.total_criteria > 0:
            reasons.append(
                f"Known criterion coverage is limited ({summary.known_coverage:.0%})."
            )

        if summary.exclusion_triggered > 0:
            reasons.append(
                f"{summary.exclusion_triggered} exclusion criterion/criteria were triggered."
            )
        elif summary.exclusion_total > 0:
            reasons.append("No evaluated exclusion criteria were triggered.")

        reasons.append(f"Final ranking score: {score:.2f}/100.")

        return reasons

    def _build_ranking_bucket(
        self,
        score: float,
        summary: RankedTrialSummary,
    ) -> str:
        """
        Clasifica el resultado en buckets interpretables.

        Sugerencia:
            >= 85: excellent_match
            >= 70: good_match
            >= 50: possible_match
            < 50: low_match
        """
        if score >= 85:
            return "excellent_match"

        if score >= 70:
            return "good_match"

        if score >= 50:
            return "possible_match"

        return "low_match"

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    def _assign_ranks(
        self,
        ranked_trials: list[RankedTrial],
    ) -> list[RankedTrial]:
        """
        Asigna rank 1..N tras ordenar por score descendente.
        """
        for index, trial in enumerate(ranked_trials, start=1):
            trial.rank = index

        return ranked_trials

    def _build_ranking_summary(
        self,
        ranked_trials: list[RankedTrial],
        total_trials: int,
    ) -> RankingSummary:
        """
        Genera summary global del ranking.
        """
        summary = RankingSummary(
            total_trials=total_trials,
            ranked_trials=len(ranked_trials),
        )

        scores = [trial.score for trial in ranked_trials]

        for trial in ranked_trials:
            if trial.ranking_bucket == "excellent_match":
                summary.excellent_matches += 1
            elif trial.ranking_bucket == "good_match":
                summary.good_matches += 1
            elif trial.ranking_bucket == "possible_match":
                summary.possible_matches += 1
            elif trial.ranking_bucket == "low_match":
                summary.low_matches += 1

            if trial.summary.hard_fail_count > 0:
                summary.trials_with_blockers += 1

            if trial.summary.unknown_hard_count > 0:
                summary.trials_with_unknown_critical += 1

            if trial.summary.evaluation_error > 0:
                summary.trials_with_errors += 1

        if scores:
            summary.best_score = max(scores)
            summary.median_score = self._median(scores)
            summary.worst_score = min(scores)

        return summary

    def _build_flags(
        self,
        ranked_trials: list[RankedTrial],
        total_trials: int,
    ) -> list[RankingFlag]:
        """
        Genera flags globales del ranking.
        """
        flags: list[RankingFlag] = []

        if total_trials == 0:
            flags.append(
                RankingFlag(
                    type="no_trials",
                    severity="high",
                    message="No trials were provided for ranking.",
                )
            )
            return flags

        if not ranked_trials:
            flags.append(
                RankingFlag(
                    type="no_ranked_trials",
                    severity="high",
                    message="No trials could be ranked.",
                )
            )
            return flags

        if len(ranked_trials) < total_trials:
            flags.append(
                RankingFlag(
                    type="partial_ranking",
                    severity="medium",
                    message=(
                        f"Only {len(ranked_trials)} out of {total_trials} "
                        "trials could be ranked."
                    ),
                )
            )

        trials_with_errors = sum(
            1
            for trial in ranked_trials
            if trial.summary.evaluation_error > 0
        )

        if trials_with_errors > 0:
            flags.append(
                RankingFlag(
                    type="evaluation_errors_present",
                    severity="medium",
                    message=(
                        f"{trials_with_errors} ranked trial(s) contain "
                        "criterion evaluation errors."
                    ),
                )
            )

        trials_with_unknown_critical = sum(
            1
            for trial in ranked_trials
            if trial.summary.unknown_hard_count > 0
        )

        if trials_with_unknown_critical > 0:
            flags.append(
                RankingFlag(
                    type="unknown_critical_criteria_present",
                    severity="medium",
                    message=(
                        f"{trials_with_unknown_critical} ranked trial(s) have "
                        "unknown hard criteria."
                    ),
                )
            )

        return flags

    def _infer_ranking_status(
        self,
        ranked_trials: list[RankedTrial],
        flags: list[RankingFlag],
    ) -> RankingStatus:
        """
        Determina estado global del ranking.
        """
        if not ranked_trials:
            if any(flag.severity == "high" for flag in flags):
                return "failed"
            return "empty"

        if any(flag.severity in {"medium", "high"} for flag in flags):
            return "completed_with_warnings"

        return "completed"

    # ------------------------------------------------------------------
    # IO helpers
    # ------------------------------------------------------------------

    def _write_json_if_needed(
        self,
        data: dict[str, Any],
        output_path: str | Path | None,
    ) -> None:
        """
        Guarda JSON si output_path no es None.
        Crea la carpeta padre si no existe.
        """
        if output_path is None:
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _safe_float(
        self,
        value: Any,
        default: float = 0.0,
    ) -> float:
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
        default: int = 0,
    ) -> int:
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
        default: str = "unknown",
    ) -> str:
        if value is None:
            return default

        text = str(value).strip().lower()

        return text or default

    def _coerce_list(
        self,
        value: Any,
    ) -> list[Any]:
        if value is None:
            return []

        if isinstance(value, list):
            return value

        return [value]

    def _median(
        self,
        values: list[float],
    ) -> float | None:
        if not values:
            return None

        sorted_values = sorted(values)
        n = len(sorted_values)
        middle = n // 2

        if n % 2 == 1:
            return sorted_values[middle]

        return (sorted_values[middle - 1] + sorted_values[middle]) / 2