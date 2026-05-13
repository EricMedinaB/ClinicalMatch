# -*- coding: utf-8 -*-

"""
Criterion Evaluator.

Módulo 11 del pipeline.

Responsabilidad:
    - Recibir criterios parseados de TrialCriteriaParser.
    - Recibir atributos extraídos del paciente desde DirectedPatientExtractor.
    - Evaluar criterio a criterio si el paciente cumple, no cumple o falta información.
    - Distinguir correctamente inclusión vs exclusión.
    - Generar summary, blocking_criteria y unknown_critical_criteria.

No hace:
    - Retrieval.
    - Parsing de criterios.
    - Extracción desde expediente médico.
    - Ranking final.
    - Llamadas a LLM.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Literal
from pathlib import Path
import json

from pydantic import BaseModel, ConfigDict, Field


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

TrialEvaluationStatus = Literal[
    "completed",
    "completed_with_unknowns",
    "completed_with_blockers",
    "completed_with_errors",
    "no_criteria",
    "failed",
]


EVALUABLE_ATTRIBUTE_STATUSES = {
    "found",
    "derived",
    "negated",
}

UNKNOWN_ATTRIBUTE_STATUSES = {
    "not_found",
    "ambiguous",
    "conflicting",
    "outdated",
    "low_confidence",
}

ERROR_ATTRIBUTE_STATUSES = {
    "extraction_error",
}


class CriterionEvaluation(BaseModel):
    model_config = ConfigDict(extra="allow")

    criterion_id: str
    trial_id: str
    criterion_type: str
    raw_text: str

    attribute_id: str | None = None
    attribute: str | None = None
    normalized_attribute: str | None = None

    operator: Any | None = None
    target_value: Any | None = None
    unit: str | None = None

    patient_value: Any | None = None
    patient_normalized_value: Any | None = None
    patient_attribute_status: str | None = None
    patient_attribute_confidence: float | None = None

    evaluation_status: EvaluationStatus
    eligibility_impact: EligibilityImpact
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    reason: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)

    requires_missing_info: bool = False
    missing_question: str | None = None

    hardness: str | None = None
    category: str | None = None
    parse_status: str | None = None

    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TrialEvaluationSummary(BaseModel):
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


class TrialCriterionEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    trial_id: str
    nct_id: str | None = None
    evaluation_status: TrialEvaluationStatus

    inclusion: list[CriterionEvaluation] = Field(default_factory=list)
    exclusion: list[CriterionEvaluation] = Field(default_factory=list)
    all_criteria: list[CriterionEvaluation] = Field(default_factory=list, alias="all")

    summary: TrialEvaluationSummary

    blocking_criteria: list[CriterionEvaluation] = Field(default_factory=list)
    unknown_critical_criteria: list[CriterionEvaluation] = Field(default_factory=list)

    flags: list[dict[str, Any]] = Field(default_factory=list)


class CriterionEvaluator:
    def __init__(
        self,
        strict_units: bool = False,
        unknown_on_low_confidence: bool = True,
        low_confidence_threshold: float = 0.5,
        evaluate_logic_nodes: bool = False,
        evaluate_conditional_clauses: bool = False,
    ) -> None:
        self.strict_units = strict_units
        self.unknown_on_low_confidence = unknown_on_low_confidence
        self.low_confidence_threshold = low_confidence_threshold
        self.evaluate_logic_nodes = evaluate_logic_nodes
        self.evaluate_conditional_clauses = evaluate_conditional_clauses

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_patient_candidate_file(
        self,
        candidate_json: dict[str, Any],
        patient_attribute_set: dict[str, Any],
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Evalúa todos los trials de un JSON de candidatos.

        Añade dentro de cada study:
            study["criterion_evaluation"]

        Si output_path se proporciona, guarda el JSON resultante en ese archivo.
        Si la carpeta no existe, la crea automáticamente.
        """
        output = copy.deepcopy(candidate_json)

        unique_studies = output.get("unique_studies", [])

        if not isinstance(unique_studies, list):
            output.setdefault("errors", []).append(
                "CriterionEvaluator: unique_studies must be a list."
            )
            self._write_json_if_needed(output, output_path)
            return output

        evaluated_studies: list[dict[str, Any]] = []

        for index, study in enumerate(unique_studies):
            if not isinstance(study, dict):
                evaluated_studies.append(
                    {
                        "nct_id": f"invalid_study_{index}",
                        "criterion_evaluation": self._build_failed_trial_evaluation(
                            trial_id=f"invalid_study_{index}",
                            error="Study is not a dictionary.",
                        ).model_dump(mode="json", by_alias=True),
                    }
                )
                continue

            evaluated_study = copy.deepcopy(study)

            evaluation = self.evaluate_trial(
                study=evaluated_study,
                patient_attribute_set=patient_attribute_set,
            )

            evaluated_study["criterion_evaluation"] = evaluation
            evaluated_studies.append(evaluated_study)

        output["unique_studies"] = evaluated_studies
        output["criterion_evaluator_summary"] = self._build_global_summary(
            evaluated_studies
        )

        self._write_json_if_needed(output, output_path)

        return output

    def evaluate_trial(
        self,
        study: dict[str, Any],
        patient_attribute_set: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Evalúa todos los criterios de un ensayo.
        """
        trial_id = self._get_trial_id(study)
        nct_id = trial_id

        patient_attributes_by_id = self._build_patient_attribute_index(
            patient_attribute_set
        )

        criteria_block = study.get("criteria", {})
        if not isinstance(criteria_block, dict):
            result = self._build_failed_trial_evaluation(
                trial_id=trial_id,
                error="Study does not contain a valid criteria block.",
            )
            return result.model_dump(mode="json", by_alias=True)

        inclusion_criteria = self._coerce_list(criteria_block.get("inclusion"))
        exclusion_criteria = self._coerce_list(criteria_block.get("exclusion"))

        inclusion_evaluations = [
            self.evaluate_criterion(
                criterion=criterion,
                patient_attributes_by_id=patient_attributes_by_id,
                trial_id=trial_id,
            )
            for criterion in inclusion_criteria
            if isinstance(criterion, dict)
        ]

        exclusion_evaluations = [
            self.evaluate_criterion(
                criterion=criterion,
                patient_attributes_by_id=patient_attributes_by_id,
                trial_id=trial_id,
            )
            for criterion in exclusion_criteria
            if isinstance(criterion, dict)
        ]

        summary = self._build_summary(
            inclusion=inclusion_evaluations,
            exclusion=exclusion_evaluations,
        )

        blocking_criteria = [
            evaluation
            for evaluation in [*inclusion_evaluations, *exclusion_evaluations]
            if self._is_blocking_criterion(evaluation)
        ]

        unknown_critical_criteria = [
            evaluation
            for evaluation in [*inclusion_evaluations, *exclusion_evaluations]
            if self._is_unknown_critical_criterion(evaluation)
        ]

        flags = self._build_trial_flags(
            summary=summary,
            blocking_criteria=blocking_criteria,
            unknown_critical_criteria=unknown_critical_criteria,
        )

        evaluation_status = self._infer_trial_evaluation_status(
            summary=summary,
            blocking_criteria=blocking_criteria,
        )

        result = TrialCriterionEvaluationResult(
            trial_id=trial_id,
            nct_id=nct_id,
            evaluation_status=evaluation_status,
            inclusion=inclusion_evaluations,
            exclusion=exclusion_evaluations,
            all=[*inclusion_evaluations, *exclusion_evaluations],
            summary=summary,
            blocking_criteria=blocking_criteria,
            unknown_critical_criteria=unknown_critical_criteria,
            flags=flags,
        )

        return result.model_dump(mode="json", by_alias=True)

    def evaluate_criterion(
        self,
        criterion: dict[str, Any],
        patient_attributes_by_id: dict[str, dict[str, Any]],
        trial_id: str,
    ) -> CriterionEvaluation:
        """
        Evalúa un único criterio contra los atributos extraídos del paciente.
        """
        try:
            criterion_id = str(
                criterion.get("criterion_id")
                or criterion.get("id")
                or "unknown_criterion"
            )

            criterion_type = str(
                criterion.get("type")
                or criterion.get("criterion_type")
                or "unknown"
            )

            raw_text = str(criterion.get("raw_text") or "")

            attribute = self._clean_optional_string(criterion.get("attribute"))
            normalized_attribute = self._clean_optional_string(
                criterion.get("normalized_attribute")
            )
            attribute_id = self._resolve_criterion_attribute_id(criterion)

            operator = self._normalize_operator(criterion.get("operator"))
            target_value = criterion.get("target_value")
            unit = self._clean_optional_string(criterion.get("unit"))

            hardness = self._clean_optional_string(criterion.get("hardness"))
            category = self._clean_optional_string(criterion.get("category"))
            parse_status = self._clean_optional_string(criterion.get("parse_status"))

            warnings = []
            errors = []

            if criterion.get("conditional_on") and not self.evaluate_conditional_clauses:
                warnings.append(
                    "Criterion has conditional_on clauses, but conditional evaluation is disabled."
                )

            if criterion.get("logic") and not self.evaluate_logic_nodes:
                warnings.append(
                    "Criterion has a logic tree, but logic-node evaluation is disabled."
                )

            if not attribute_id:
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=None,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        "Criterion could not be evaluated because no structured "
                        "attribute or normalized_attribute was available."
                    ),
                    warnings=warnings,
                )

            patient_attr = self._find_patient_attribute(
                attribute_id=attribute_id,
                patient_attributes_by_id=patient_attributes_by_id,
            )

            if patient_attr is None:
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        f"Patient attribute '{attribute_id}' was not found in "
                        "the DirectedPatientExtractor output."
                    ),
                    warnings=warnings,
                    requires_missing_info=True,
                )

            patient_status = str(patient_attr.get("status") or "unknown")
            patient_confidence = self._safe_float(patient_attr.get("confidence"))
            patient_value = patient_attr.get("value")
            patient_normalized_value = patient_attr.get("normalized_value")
            value_for_comparison = self._get_patient_value(patient_attr)

            evidence = self._coerce_evidence(patient_attr.get("evidence"))
            missing_question = patient_attr.get("missing_question")

            if patient_status in ERROR_ATTRIBUTE_STATUSES:
                return self._make_error_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    error=patient_attr.get("error") or "Patient attribute extraction error.",
                    warnings=warnings,
                )

            if patient_status == "not_applicable":
                return self._make_not_applicable_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=f"Patient attribute '{attribute_id}' is marked as not applicable.",
                    warnings=warnings,
                )

            if (
                self.unknown_on_low_confidence
                and patient_confidence is not None
                and patient_confidence < self.low_confidence_threshold
            ):
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        f"Patient attribute '{attribute_id}' has confidence "
                        f"{patient_confidence}, below threshold {self.low_confidence_threshold}."
                    ),
                    warnings=warnings,
                    requires_missing_info=True,
                    missing_question=missing_question,
                )

            if patient_status in UNKNOWN_ATTRIBUTE_STATUSES:
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        f"Patient attribute '{attribute_id}' has status "
                        f"'{patient_status}', so the criterion cannot be evaluated deterministically."
                    ),
                    warnings=warnings,
                    requires_missing_info=True,
                    missing_question=missing_question,
                )

            if patient_status not in EVALUABLE_ATTRIBUTE_STATUSES:
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        f"Patient attribute '{attribute_id}' has unsupported status "
                        f"'{patient_status}'."
                    ),
                    warnings=warnings,
                    requires_missing_info=True,
                    missing_question=missing_question,
                )

            if self.strict_units and not self._units_compatible(
                criterion_unit=unit,
                patient_unit=patient_attr.get("unit"),
            ):
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        f"Unit mismatch: criterion unit={unit}, "
                        f"patient unit={patient_attr.get('unit')}."
                    ),
                    warnings=warnings,
                    requires_missing_info=True,
                    missing_question=missing_question,
                )

            comparison_result = self._compare_values(
                patient_value=value_for_comparison,
                operator=operator,
                target_value=target_value,
                patient_status=patient_status,
            )

            if comparison_result is None:
                return self._make_unknown_evaluation(
                    criterion_id=criterion_id,
                    trial_id=trial_id,
                    criterion_type=criterion_type,
                    raw_text=raw_text,
                    attribute_id=attribute_id,
                    attribute=attribute,
                    normalized_attribute=normalized_attribute,
                    operator=operator,
                    target_value=target_value,
                    unit=unit,
                    patient_value=patient_value,
                    patient_normalized_value=patient_normalized_value,
                    patient_attribute_status=patient_status,
                    patient_attribute_confidence=patient_confidence,
                    evidence=evidence,
                    hardness=hardness,
                    category=category,
                    parse_status=parse_status,
                    reason=(
                        "Criterion could not be evaluated because operator/target_value "
                        "or patient value could not be compared deterministically."
                    ),
                    warnings=warnings,
                    requires_missing_info=True,
                    missing_question=missing_question,
                )

            evaluation_status: EvaluationStatus = "met" if comparison_result else "not_met"

            eligibility_impact = self._compute_eligibility_impact(
                criterion_type=criterion_type,
                evaluation_status=evaluation_status,
            )

            confidence = self._compute_evaluation_confidence(
                criterion=criterion,
                patient_attr=patient_attr,
                deterministic_result=True,
            )

            reason = self._build_reason(
                criterion_type=criterion_type,
                attribute_id=attribute_id,
                patient_value=value_for_comparison,
                operator=operator,
                target_value=target_value,
                evaluation_status=evaluation_status,
                eligibility_impact=eligibility_impact,
            )

            return CriterionEvaluation(
                criterion_id=criterion_id,
                trial_id=trial_id,
                criterion_type=criterion_type,
                raw_text=raw_text,
                attribute_id=attribute_id,
                attribute=attribute,
                normalized_attribute=normalized_attribute,
                operator=operator,
                target_value=target_value,
                unit=unit,
                patient_value=patient_value,
                patient_normalized_value=patient_normalized_value,
                patient_attribute_status=patient_status,
                patient_attribute_confidence=patient_confidence,
                evaluation_status=evaluation_status,
                eligibility_impact=eligibility_impact,
                confidence=confidence,
                reason=reason,
                evidence=evidence,
                requires_missing_info=False,
                missing_question=None,
                hardness=hardness,
                category=category,
                parse_status=parse_status,
                warnings=warnings,
                errors=errors,
            )

        except Exception as error:
            return CriterionEvaluation(
                criterion_id=str(criterion.get("criterion_id") or "unknown_criterion"),
                trial_id=trial_id,
                criterion_type=str(
                    criterion.get("type")
                    or criterion.get("criterion_type")
                    or "unknown"
                ),
                raw_text=str(criterion.get("raw_text") or ""),
                evaluation_status="evaluation_error",
                eligibility_impact="unknown",
                confidence=0.0,
                reason="Unexpected error during criterion evaluation.",
                errors=[str(error)],
            )

    def _write_json_if_needed(
        self,
        data: dict[str, Any],
        output_path: str | Path | None,
    ) -> None:
        if output_path is None:
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Patient attribute indexing
    # ------------------------------------------------------------------

    def _build_patient_attribute_index(
        self,
        patient_attribute_set: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}

        attributes = patient_attribute_set.get("attributes", [])

        if not isinstance(attributes, list):
            return index

        for attr in attributes:
            if not isinstance(attr, dict):
                continue

            attribute_id = attr.get("attribute_id")

            if isinstance(attribute_id, str) and attribute_id.strip():
                key = attribute_id.strip()
                index[key] = attr
                index[key.lower()] = attr

            canonical_name = attr.get("canonical_name")

            if isinstance(canonical_name, str) and canonical_name.strip():
                key = canonical_name.strip()
                index.setdefault(key, attr)
                index.setdefault(key.lower(), attr)

        return index

    def _find_patient_attribute(
        self,
        attribute_id: str,
        patient_attributes_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        return (
            patient_attributes_by_id.get(attribute_id)
            or patient_attributes_by_id.get(attribute_id.lower())
        )

    # ------------------------------------------------------------------
    # Criterion helpers
    # ------------------------------------------------------------------

    def _resolve_criterion_attribute_id(
        self,
        criterion: dict[str, Any],
    ) -> str | None:
        for key in ("normalized_attribute", "attribute_id", "attribute"):
            value = criterion.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _get_patient_value(
        self,
        patient_attr: dict[str, Any],
    ) -> Any:
        normalized_value = patient_attr.get("normalized_value")

        if normalized_value is not None:
            return normalized_value

        if str(patient_attr.get("status") or "") == "negated":
            return False

        return patient_attr.get("value")

    def _compute_eligibility_impact(
        self,
        criterion_type: str,
        evaluation_status: EvaluationStatus,
    ) -> EligibilityImpact:
        criterion_type = str(criterion_type).lower()

        if evaluation_status in {"unknown", "not_applicable", "evaluation_error"}:
            return "unknown"

        if criterion_type == "inclusion":
            if evaluation_status == "met":
                return "supports_eligibility"
            if evaluation_status == "not_met":
                return "hurts_eligibility"

        if criterion_type == "exclusion":
            if evaluation_status == "met":
                return "hurts_eligibility"
            if evaluation_status == "not_met":
                return "supports_eligibility"

        return "neutral"

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def _compare_values(
        self,
        patient_value: Any,
        operator: Any,
        target_value: Any,
        patient_status: str | None = None,
    ) -> bool | None:
        op = self._normalize_operator(operator)

        if op is None or op == "unknown":
            return None

        if patient_status == "negated" and patient_value is None:
            patient_value = False

        if op == "==":
            return self._values_equal(patient_value, target_value)

        if op == "!=":
            equal = self._values_equal(patient_value, target_value)
            return None if equal is None else not equal

        if op in {">", ">=", "<", "<="}:
            patient_num = self._to_number(patient_value)
            target_num = self._to_number(target_value)

            if patient_num is None or target_num is None:
                return None

            if op == ">":
                return patient_num > target_num
            if op == ">=":
                return patient_num >= target_num
            if op == "<":
                return patient_num < target_num
            if op == "<=":
                return patient_num <= target_num

        if op == "in":
            if not isinstance(target_value, list):
                return None
            return self._value_in_list(patient_value, target_value)

        if op == "not_in":
            if not isinstance(target_value, list):
                return None
            result = self._value_in_list(patient_value, target_value)
            return None if result is None else not result

        if op == "is_true":
            truthy = self._to_bool(patient_value)
            return truthy is True

        if op == "is_false":
            truthy = self._to_bool(patient_value)
            return truthy is False

        if op == "is_present":
            return self._is_present(patient_value)

        if op == "is_absent":
            return not self._is_present(patient_value)

        if op == "any_of":
            if not isinstance(target_value, list):
                return None

            if isinstance(patient_value, list):
                return any(self._value_in_list(item, target_value) for item in patient_value)

            return self._value_in_list(patient_value, target_value)

        if op == "all_of":
            if not isinstance(target_value, list):
                return None

            if not isinstance(patient_value, list):
                return None

            return all(self._value_in_list(target, patient_value) for target in target_value)

        if op == "not_applicable_if":
            return None

        return None

    def _normalize_operator(
        self,
        operator: Any,
    ) -> str | None:
        if operator is None:
            return None

        raw = str(operator).strip()

        if not raw:
            return None

        if raw.startswith("CriterionOperator."):
            raw = raw.split(".", 1)[1]

        normalized = raw.lower().strip().replace(" ", "_").replace("-", "_")

        mapping = {
            "==": "==",
            "=": "==",
            "eq": "==",
            "equals": "==",
            "equal": "==",
            "is": "==",
            "!=": "!=",
            "ne": "!=",
            "neq": "!=",
            "not_equals": "!=",
            "not_equal": "!=",
            ">": ">",
            "gt": ">",
            "greater_than": ">",
            "more_than": ">",
            "<": "<",
            "lt": "<",
            "less_than": "<",
            ">=": ">=",
            "gte": ">=",
            "ge": ">=",
            "gteq": ">=",
            "geq": ">=",
            "greater_or_equal": ">=",
            "greater_than_or_equal": ">=",
            "at_least": ">=",
            "minimum": ">=",
            "min": ">=",
            "<=": "<=",
            "lte": "<=",
            "le": "<=",
            "lteq": "<=",
            "leq": "<=",
            "less_or_equal": "<=",
            "less_than_or_equal": "<=",
            "at_most": "<=",
            "maximum": "<=",
            "max": "<=",
            "in": "in",
            "inside": "in",
            "one_of": "in",
            "one_of_values": "in",
            "not_in": "not_in",
            "not_one_of": "not_in",
            "not_in_values": "not_in",
            "is_true": "is_true",
            "true": "is_true",
            "yes": "is_true",
            "is_false": "is_false",
            "false": "is_false",
            "no": "is_false",
            "is_present": "is_present",
            "present": "is_present",
            "presence": "is_present",
            "has": "is_present",
            "is_absent": "is_absent",
            "absent": "is_absent",
            "absence": "is_absent",
            "does_not_have": "is_absent",
            "any_of": "any_of",
            "any": "any_of",
            "or": "any_of",
            "all_of": "all_of",
            "all": "all_of",
            "and": "all_of",
            "not_applicable_if": "not_applicable_if",
            "unknown": "unknown",
        }

        return mapping.get(normalized, normalized)

    def _values_equal(
        self,
        left: Any,
        right: Any,
    ) -> bool | None:
        left_num = self._to_number(left)
        right_num = self._to_number(right)

        if left_num is not None and right_num is not None:
            return left_num == right_num

        left_bool = self._to_bool(left)
        right_bool = self._to_bool(right)

        if left_bool is not None and right_bool is not None:
            return left_bool == right_bool

        if left is None or right is None:
            return None

        return self._normalize_string(left) == self._normalize_string(right)

    def _value_in_list(
        self,
        value: Any,
        candidates: list[Any],
    ) -> bool | None:
        if value is None:
            return None

        for candidate in candidates:
            equal = self._values_equal(value, candidate)
            if equal is True:
                return True

        return False

    def _to_number(
        self,
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        if isinstance(value, int | float):
            if isinstance(value, float) and math.isnan(value):
                return None
            return float(value)

        if isinstance(value, str):
            cleaned = value.strip().lower()
            cleaned = cleaned.replace(",", "")

            match = re.search(r"-?\d+(?:\.\d+)?", cleaned)

            if not match:
                return None

            try:
                return float(match.group(0))
            except ValueError:
                return None

        return None

    def _to_bool(
        self,
        value: Any,
    ) -> bool | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        normalized = self._normalize_string(value)

        truthy = {
            "true",
            "yes",
            "y",
            "positive",
            "present",
            "detected",
            "mutated",
            "active",
            "found",
            "1",
        }

        falsey = {
            "false",
            "no",
            "n",
            "negative",
            "absent",
            "not_detected",
            "wild_type",
            "wild-type",
            "none",
            "0",
        }

        if normalized in truthy:
            return True

        if normalized in falsey:
            return False

        return None

    def _is_present(
        self,
        value: Any,
    ) -> bool:
        if value is None:
            return False

        if isinstance(value, bool):
            return value

        if isinstance(value, list | tuple | set):
            return len(value) > 0

        normalized = self._normalize_string(value)

        absent_values = {
            "",
            "none",
            "null",
            "unknown",
            "not_found",
            "not_available",
            "n/a",
            "na",
            "false",
            "no",
            "negative",
            "absent",
            "not_detected",
            "wild_type",
            "wild-type",
        }

        return normalized not in absent_values

    def _normalize_string(
        self,
        value: Any,
    ) -> str:
        return re.sub(r"\s+", "_", str(value).strip().lower())

    # ------------------------------------------------------------------
    # Summary and flags
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        inclusion: list[CriterionEvaluation],
        exclusion: list[CriterionEvaluation],
    ) -> TrialEvaluationSummary:
        all_evaluations = [*inclusion, *exclusion]

        summary = TrialEvaluationSummary(
            total_criteria=len(all_evaluations),
            inclusion_total=len(inclusion),
            exclusion_total=len(exclusion),
        )

        for evaluation in all_evaluations:
            if evaluation.evaluation_status == "met":
                summary.met += 1
            elif evaluation.evaluation_status == "not_met":
                summary.not_met += 1
            elif evaluation.evaluation_status == "unknown":
                summary.unknown += 1
            elif evaluation.evaluation_status == "not_applicable":
                summary.not_applicable += 1
            elif evaluation.evaluation_status == "evaluation_error":
                summary.evaluation_error += 1

            if evaluation.criterion_type == "inclusion":
                if evaluation.evaluation_status == "met":
                    summary.inclusion_met += 1
                elif evaluation.evaluation_status == "not_met":
                    summary.inclusion_not_met += 1
                elif evaluation.evaluation_status == "unknown":
                    summary.inclusion_unknown += 1

            if evaluation.criterion_type == "exclusion":
                if evaluation.evaluation_status == "met":
                    summary.exclusion_triggered += 1
                elif evaluation.evaluation_status == "not_met":
                    summary.exclusion_not_triggered += 1
                elif evaluation.evaluation_status == "unknown":
                    summary.exclusion_unknown += 1

            if self._is_blocking_criterion(evaluation):
                summary.hard_fail_count += 1

            if self._is_unknown_critical_criterion(evaluation):
                summary.unknown_hard_count += 1

            if (
                evaluation.evaluation_status == "unknown"
                and str(evaluation.hardness).lower() == "soft"
            ):
                summary.soft_unknown_count += 1

        return summary

    def _is_blocking_criterion(
        self,
        evaluation: CriterionEvaluation,
    ) -> bool:
        if str(evaluation.hardness).lower() != "hard":
            return False

        if (
            evaluation.criterion_type == "inclusion"
            and evaluation.evaluation_status == "not_met"
        ):
            return True

        if (
            evaluation.criterion_type == "exclusion"
            and evaluation.evaluation_status == "met"
        ):
            return True

        return False

    def _is_unknown_critical_criterion(
        self,
        evaluation: CriterionEvaluation,
    ) -> bool:
        if evaluation.evaluation_status != "unknown":
            return False

        if str(evaluation.hardness).lower() == "hard":
            return True

        critical_categories = {
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
        }

        return str(evaluation.category).lower() in critical_categories

    def _infer_trial_evaluation_status(
        self,
        summary: TrialEvaluationSummary,
        blocking_criteria: list[CriterionEvaluation],
    ) -> TrialEvaluationStatus:
        if summary.total_criteria == 0:
            return "no_criteria"

        if summary.evaluation_error == summary.total_criteria:
            return "failed"

        if blocking_criteria:
            return "completed_with_blockers"

        if summary.evaluation_error > 0:
            return "completed_with_errors"

        if summary.unknown > 0:
            return "completed_with_unknowns"

        return "completed"

    def _build_trial_flags(
        self,
        summary: TrialEvaluationSummary,
        blocking_criteria: list[CriterionEvaluation],
        unknown_critical_criteria: list[CriterionEvaluation],
    ) -> list[dict[str, Any]]:
        flags: list[dict[str, Any]] = []

        if blocking_criteria:
            flags.append(
                {
                    "type": "blocking_criteria_found",
                    "severity": "high",
                    "message": f"{len(blocking_criteria)} hard blocking criterion/criteria found.",
                }
            )

        if unknown_critical_criteria:
            flags.append(
                {
                    "type": "unknown_critical_criteria",
                    "severity": "medium",
                    "message": (
                        f"{len(unknown_critical_criteria)} critical criterion/criteria "
                        "could not be evaluated."
                    ),
                }
            )

        if summary.evaluation_error > 0:
            flags.append(
                {
                    "type": "evaluation_errors",
                    "severity": "medium",
                    "message": f"{summary.evaluation_error} criterion evaluation error(s).",
                }
            )

        return flags

    def _build_global_summary(
        self,
        evaluated_studies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_trials = len(evaluated_studies)
        trials_with_blockers = 0
        trials_with_unknowns = 0
        failed_trials = 0

        for study in evaluated_studies:
            evaluation = study.get("criterion_evaluation", {})
            status = evaluation.get("evaluation_status")

            if status == "completed_with_blockers":
                trials_with_blockers += 1
            elif status == "completed_with_unknowns":
                trials_with_unknowns += 1
            elif status == "failed":
                failed_trials += 1

        return {
            "total_trials": total_trials,
            "trials_with_blockers": trials_with_blockers,
            "trials_with_unknowns": trials_with_unknowns,
            "failed_trials": failed_trials,
        }

    # ------------------------------------------------------------------
    # Evaluation constructors
    # ------------------------------------------------------------------

    def _make_unknown_evaluation(
        self,
        criterion_id: str,
        trial_id: str,
        criterion_type: str,
        raw_text: str,
        attribute_id: str | None,
        attribute: str | None,
        normalized_attribute: str | None,
        operator: Any | None,
        target_value: Any | None,
        unit: str | None,
        hardness: str | None,
        category: str | None,
        parse_status: str | None,
        reason: str,
        warnings: list[str] | None = None,
        patient_value: Any | None = None,
        patient_normalized_value: Any | None = None,
        patient_attribute_status: str | None = None,
        patient_attribute_confidence: float | None = None,
        evidence: list[dict[str, Any]] | None = None,
        requires_missing_info: bool = True,
        missing_question: str | None = None,
    ) -> CriterionEvaluation:
        return CriterionEvaluation(
            criterion_id=criterion_id,
            trial_id=trial_id,
            criterion_type=criterion_type,
            raw_text=raw_text,
            attribute_id=attribute_id,
            attribute=attribute,
            normalized_attribute=normalized_attribute,
            operator=operator,
            target_value=target_value,
            unit=unit,
            patient_value=patient_value,
            patient_normalized_value=patient_normalized_value,
            patient_attribute_status=patient_attribute_status,
            patient_attribute_confidence=patient_attribute_confidence,
            evaluation_status="unknown",
            eligibility_impact="unknown",
            confidence=0.0,
            reason=reason,
            evidence=evidence or [],
            requires_missing_info=requires_missing_info,
            missing_question=missing_question,
            hardness=hardness,
            category=category,
            parse_status=parse_status,
            warnings=warnings or [],
            errors=[],
        )

    def _make_error_evaluation(
        self,
        criterion_id: str,
        trial_id: str,
        criterion_type: str,
        raw_text: str,
        attribute_id: str | None,
        attribute: str | None,
        normalized_attribute: str | None,
        operator: Any | None,
        target_value: Any | None,
        unit: str | None,
        patient_value: Any | None,
        patient_normalized_value: Any | None,
        patient_attribute_status: str | None,
        patient_attribute_confidence: float | None,
        evidence: list[dict[str, Any]],
        hardness: str | None,
        category: str | None,
        parse_status: str | None,
        error: str,
        warnings: list[str] | None = None,
    ) -> CriterionEvaluation:
        return CriterionEvaluation(
            criterion_id=criterion_id,
            trial_id=trial_id,
            criterion_type=criterion_type,
            raw_text=raw_text,
            attribute_id=attribute_id,
            attribute=attribute,
            normalized_attribute=normalized_attribute,
            operator=operator,
            target_value=target_value,
            unit=unit,
            patient_value=patient_value,
            patient_normalized_value=patient_normalized_value,
            patient_attribute_status=patient_attribute_status,
            patient_attribute_confidence=patient_attribute_confidence,
            evaluation_status="evaluation_error",
            eligibility_impact="unknown",
            confidence=0.0,
            reason="Patient attribute extraction failed.",
            evidence=evidence,
            requires_missing_info=True,
            hardness=hardness,
            category=category,
            parse_status=parse_status,
            warnings=warnings or [],
            errors=[error],
        )

    def _make_not_applicable_evaluation(
        self,
        criterion_id: str,
        trial_id: str,
        criterion_type: str,
        raw_text: str,
        attribute_id: str | None,
        attribute: str | None,
        normalized_attribute: str | None,
        operator: Any | None,
        target_value: Any | None,
        unit: str | None,
        patient_value: Any | None,
        patient_normalized_value: Any | None,
        patient_attribute_status: str | None,
        patient_attribute_confidence: float | None,
        evidence: list[dict[str, Any]],
        hardness: str | None,
        category: str | None,
        parse_status: str | None,
        reason: str,
        warnings: list[str] | None = None,
    ) -> CriterionEvaluation:
        return CriterionEvaluation(
            criterion_id=criterion_id,
            trial_id=trial_id,
            criterion_type=criterion_type,
            raw_text=raw_text,
            attribute_id=attribute_id,
            attribute=attribute,
            normalized_attribute=normalized_attribute,
            operator=operator,
            target_value=target_value,
            unit=unit,
            patient_value=patient_value,
            patient_normalized_value=patient_normalized_value,
            patient_attribute_status=patient_attribute_status,
            patient_attribute_confidence=patient_attribute_confidence,
            evaluation_status="not_applicable",
            eligibility_impact="neutral",
            confidence=patient_attribute_confidence or 0.0,
            reason=reason,
            evidence=evidence,
            requires_missing_info=False,
            hardness=hardness,
            category=category,
            parse_status=parse_status,
            warnings=warnings or [],
            errors=[],
        )

    def _build_failed_trial_evaluation(
        self,
        trial_id: str,
        error: str,
    ) -> TrialCriterionEvaluationResult:
        summary = TrialEvaluationSummary(total_criteria=0)

        return TrialCriterionEvaluationResult(
            trial_id=trial_id,
            nct_id=trial_id,
            evaluation_status="failed",
            inclusion=[],
            exclusion=[],
            all=[],
            summary=summary,
            blocking_criteria=[],
            unknown_critical_criteria=[],
            flags=[
                {
                    "type": "trial_evaluation_failed",
                    "severity": "high",
                    "message": error,
                }
            ],
        )

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _get_trial_id(
        self,
        study: dict[str, Any],
    ) -> str:
        return str(
            study.get("nct_id")
            or study.get("trial_id")
            or study.get("trial", {}).get("nct_id")
            or study.get("trial", {}).get("identification", {}).get("nct_id")
            or "unknown_trial"
        )

    def _coerce_list(
        self,
        value: Any,
    ) -> list[Any]:
        if value is None:
            return []

        if isinstance(value, list):
            return value

        return [value]

    def _coerce_evidence(
        self,
        evidence: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(evidence, list):
            return []

        return [
            item
            for item in evidence
            if isinstance(item, dict)
        ]

    def _safe_float(
        self,
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        if isinstance(value, int | float):
            return max(0.0, min(1.0, float(value)))

        if isinstance(value, str):
            try:
                return max(0.0, min(1.0, float(value)))
            except ValueError:
                return None

        return None

    def _clean_optional_string(
        self,
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        text = str(value).strip()

        return text or None

    def _units_compatible(
        self,
        criterion_unit: str | None,
        patient_unit: str | None,
    ) -> bool:
        if not criterion_unit or not patient_unit:
            return True

        return self._normalize_string(criterion_unit) == self._normalize_string(patient_unit)

    def _compute_evaluation_confidence(
        self,
        criterion: dict[str, Any],
        patient_attr: dict[str, Any],
        deterministic_result: bool,
    ) -> float:
        if not deterministic_result:
            return 0.0

        patient_confidence = self._safe_float(patient_attr.get("confidence"))
        criterion_confidence = self._safe_float(criterion.get("confidence"))

        values = [
            value
            for value in [patient_confidence, criterion_confidence]
            if value is not None
        ]

        if not values:
            return 0.8

        return min(values)

    def _build_reason(
        self,
        criterion_type: str,
        attribute_id: str,
        patient_value: Any,
        operator: Any,
        target_value: Any,
        evaluation_status: EvaluationStatus,
        eligibility_impact: EligibilityImpact,
    ) -> str:
        criterion_type = criterion_type.lower()

        if criterion_type == "inclusion":
            if evaluation_status == "met":
                return (
                    f"Patient value for '{attribute_id}' is {patient_value}, "
                    f"which satisfies inclusion criterion {operator} {target_value}."
                )

            return (
                f"Patient value for '{attribute_id}' is {patient_value}, "
                f"which does not satisfy inclusion criterion {operator} {target_value}."
            )

        if criterion_type == "exclusion":
            if evaluation_status == "met":
                return (
                    f"Patient value for '{attribute_id}' is {patient_value}, "
                    f"which activates exclusion criterion {operator} {target_value}."
                )

            return (
                f"Patient value for '{attribute_id}' is {patient_value}, "
                f"which does not activate exclusion criterion {operator} {target_value}."
            )

        return (
            f"Patient value for '{attribute_id}' is {patient_value}. "
            f"Criterion evaluation status is {evaluation_status}; impact is {eligibility_impact}."
        )