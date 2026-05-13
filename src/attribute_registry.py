from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Literal
import json
from pathlib import Path

from pydantic import BaseModel, Field


AttributeCriticality = Literal["low", "medium", "high"]
RegistryStatus = Literal["built", "built_with_warnings", "empty", "failed"]


class RequiredBy(BaseModel):
    trial_id: str
    criterion_id: str
    criterion_text: str
    criterion_type: str
    operator: Any | None = None
    target_value: Any | None = None
    unit: str | None = None


class RegistryAttribute(BaseModel):
    attribute_id: str
    canonical_name: str
    normalized_attribute: str

    type: str = "unknown"
    value_type: str = "unknown"
    unit: str | None = None
    allowed_values: list[Any] | None = None
    aliases: list[str] = Field(default_factory=list)
    source_attribute_names: list[str] = Field(default_factory=list)

    criticality: AttributeCriticality = "medium"
    requires_temporal_reasoning: bool = False
    requires_negation_handling: bool = False

    normalization_method: str | None = None
    normalization_confidence: float | None = None

    required_by: list[RequiredBy] = Field(default_factory=list)


class SourceTrial(BaseModel):
    trial_id: str
    title: str | None = None


class SourceCriterion(BaseModel):
    trial_id: str
    criterion_id: str
    type: str
    raw_text: str

    attribute: str | None = None
    attribute_id: str | None = None
    normalized_attribute: str | None = None

    operator: Any | None = None
    target_value: Any | None = None
    unit: str | None = None

    hardness: str | None = None
    category: str | None = None
    requires_temporal_reasoning: bool = False
    requires_negation_handling: bool = False


class AttributeRegistrySummary(BaseModel):
    total_trials: int = 0
    total_source_criteria: int = 0
    total_attributes: int = 0

    high_criticality_attributes: int = 0
    medium_criticality_attributes: int = 0
    low_criticality_attributes: int = 0

    temporal_attributes: int = 0
    negation_sensitive_attributes: int = 0
    compound_attributes: int = 0


class RegistryFlag(BaseModel):
    type: str
    severity: Literal["low", "medium", "high"]
    message: str


class AttributeRegistry(BaseModel):
    patient_id: str | None = None
    registry_id: str
    schema_version: str
    registry_status: RegistryStatus

    source_trials: list[SourceTrial] = Field(default_factory=list)
    source_criteria: list[SourceCriterion] = Field(default_factory=list)
    attributes: list[RegistryAttribute] = Field(default_factory=list)

    summary: AttributeRegistrySummary
    flags: list[RegistryFlag] = Field(default_factory=list)


class AttributeRegistryBuilder:
    def __init__(
        self,
        normalizer: Any | None = None,
        schema_version: str = "attribute_registry_v1",
        include_soft_criteria: bool = True,
        include_administrative_criteria: bool = False,
    ) -> None:
        self.normalizer = normalizer
        self.schema_version = schema_version
        self.include_soft_criteria = include_soft_criteria
        self.include_administrative_criteria = include_administrative_criteria

    def build_from_candidate_json(
        self,
        candidate_json: dict[str, Any],
        output_path: str | Any | None = None,
    ) -> dict[str, Any]:
        """
        Public API principal.

        Recibe el JSON después de TrialCriteriaParser.
        Devuelve AttributeRegistry como dict.

        Si output_path se informa, también escribe el resultado en un fichero JSON.
        Si la carpeta padre no existe, la crea.

        El método nunca lanza una excepción hacia fuera: si ocurre un error no
        recuperable, devuelve un registry con registry_status="failed" y flags.
        """

        flags: list[RegistryFlag] = []
        patient_id = self._extract_patient_id(candidate_json)

        def write_output_if_needed(registry_dict: dict[str, Any]) -> None:
            if output_path is None:
                return

            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            with path.open("w", encoding="utf-8") as f:
                json.dump(
                    registry_dict,
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

        try:
            if not isinstance(candidate_json, dict):
                raise TypeError(
                    f"candidate_json must be a dict. Got {type(candidate_json)}"
                )

            payload = copy.deepcopy(candidate_json)

            try:
                source_trials = self._extract_source_trials(payload)
            except Exception as e:
                source_trials = []
                flags.append(
                    RegistryFlag(
                        type="source_trial_extraction_error",
                        severity="medium",
                        message=f"Could not extract source trials: {e}",
                    )
                )

            try:
                source_criteria = self._extract_source_criteria(payload, flags)
            except Exception as e:
                source_criteria = []
                flags.append(
                    RegistryFlag(
                        type="source_criteria_extraction_error",
                        severity="high",
                        message=f"Could not extract source criteria: {e}",
                    )
                )

            try:
                attributes = self._build_attributes(source_criteria, flags)
            except Exception as e:
                attributes = []
                flags.append(
                    RegistryFlag(
                        type="attribute_build_error",
                        severity="high",
                        message=f"Could not build registry attributes: {e}",
                    )
                )

            if not source_criteria:
                flags.append(
                    RegistryFlag(
                        type="empty_source_criteria",
                        severity="medium",
                        message="No source criteria were found in the candidate JSON.",
                    )
                )

            if source_criteria and not attributes:
                flags.append(
                    RegistryFlag(
                        type="no_extractable_attributes",
                        severity="medium",
                        message=(
                            "Source criteria were found, but no extractable attributes "
                            "could be built."
                        ),
                    )
                )

            summary = self._build_summary(
                source_trials=source_trials,
                source_criteria=source_criteria,
                attributes=attributes,
            )

            if not attributes:
                registry_status: RegistryStatus = "empty"
            elif flags:
                registry_status = "built_with_warnings"
            else:
                registry_status = "built"

            registry = AttributeRegistry(
                patient_id=patient_id,
                registry_id=self._make_registry_id(patient_id),
                schema_version=self.schema_version,
                registry_status=registry_status,
                source_trials=source_trials,
                source_criteria=source_criteria,
                attributes=attributes,
                summary=summary,
                flags=flags,
            )

            registry_dict = registry.model_dump(mode="json")

            try:
                write_output_if_needed(registry_dict)
            except Exception as e:
                registry_dict.setdefault("flags", []).append(
                    RegistryFlag(
                        type="output_write_error",
                        severity="medium",
                        message=f"Could not write Attribute Registry JSON to output_path: {e}",
                    ).model_dump(mode="json")
                )
                registry_dict["registry_status"] = "built_with_warnings"

            return registry_dict

        except Exception as e:
            failure_flag = RegistryFlag(
                type="registry_builder_failed",
                severity="high",
                message=str(e),
            )

            registry = AttributeRegistry(
                patient_id=patient_id,
                registry_id=self._make_registry_id(patient_id),
                schema_version=self.schema_version,
                registry_status="failed",
                source_trials=[],
                source_criteria=[],
                attributes=[],
                summary=AttributeRegistrySummary(),
                flags=[failure_flag],
            )

            registry_dict = registry.model_dump(mode="json")

            try:
                write_output_if_needed(registry_dict)
            except Exception as write_error:
                registry_dict.setdefault("flags", []).append(
                    RegistryFlag(
                        type="output_write_error",
                        severity="medium",
                        message=f"Could not write failed Attribute Registry JSON to output_path: {write_error}",
                    ).model_dump(mode="json")
                )

            return registry_dict

    def _extract_source_trials(
        self,
        candidate_json: dict[str, Any],
    ) -> list[SourceTrial]:
        """
        Extrae lista de ensayos fuente.

        Soporta varios formatos habituales:
        - {"source_trials": [...]}
        - {"unique_studies": [...]}
        - {"studies": [...]}
        - {"trials": [...]}
        - {"candidates": [...]}
        - un único estudio como dict con nct_id/trial_id y criteria.
        """
        raw_trials = candidate_json.get("source_trials")
        if raw_trials is None:
            raw_trials = self._get_studies(candidate_json)

        if isinstance(raw_trials, dict):
            if self._looks_like_study(raw_trials):
                raw_trials = [raw_trials]
            else:
                raw_trials = list(raw_trials.values())

        if raw_trials is None:
            raw_trials = []

        source_trials: list[SourceTrial] = []
        seen: set[str] = set()

        for raw_trial in raw_trials:
            if not isinstance(raw_trial, dict):
                continue

            trial_id = self._extract_trial_id(raw_trial)
            if not trial_id:
                continue

            if trial_id in seen:
                continue

            seen.add(trial_id)

            title = (
                raw_trial.get("title")
                or raw_trial.get("brief_title")
                or raw_trial.get("official_title")
                or raw_trial.get("study_title")
            )

            source_trials.append(
                SourceTrial(
                    trial_id=str(trial_id),
                    title=str(title) if title is not None else None,
                )
            )

        # Fallback: si no hay lista de ensayos pero hay criterios top-level,
        # derivamos los trial_id desde ellos.
        if not source_trials:
            raw_criteria = candidate_json.get("source_criteria") or candidate_json.get(
                "criteria"
            )
            for raw_criterion in self._flatten_criteria(raw_criteria):
                trial_id = self._extract_trial_id(raw_criterion)
                if trial_id and trial_id not in seen:
                    seen.add(trial_id)
                    source_trials.append(SourceTrial(trial_id=str(trial_id)))

        return source_trials

    def _extract_source_criteria(
        self,
        candidate_json: dict[str, Any],
        flags: list[RegistryFlag],
    ) -> list[SourceCriterion]:
        """
        Extrae todos los criterios parseados desde unique_studies.

        También soporta formatos alternativos con criteria/source_criteria a nivel raíz.
        """
        source_criteria: list[SourceCriterion] = []
        seen: set[tuple[str, str]] = set()

        def add_criterion(
            raw_criterion: dict[str, Any],
            default_trial_id: str | None,
            default_type: str | None,
            ordinal: int,
        ) -> None:
            if not isinstance(raw_criterion, dict):
                return

            if not self._should_include_criterion(raw_criterion):
                return

            trial_id = (
                raw_criterion.get("trial_id")
                or raw_criterion.get("nct_id")
                or raw_criterion.get("study_id")
                or raw_criterion.get("nctId")
                or default_trial_id
                or "unknown_trial"
            )

            criterion_type = (
                raw_criterion.get("type")
                or raw_criterion.get("criterion_type")
                or raw_criterion.get("section")
                or default_type
                or "unknown"
            )

            raw_text = (
                raw_criterion.get("raw_text")
                or raw_criterion.get("criterion_text")
                or raw_criterion.get("text")
                or raw_criterion.get("description")
                or raw_criterion.get("criterion")
                or ""
            )

            if not str(raw_text).strip():
                flags.append(
                    RegistryFlag(
                        type="criterion_without_text_skipped",
                        severity="low",
                        message=(
                            f"Criterion from trial '{trial_id}' was skipped because "
                            "it has no raw_text."
                        ),
                    )
                )
                return

            criterion_id = (
                raw_criterion.get("criterion_id")
                or raw_criterion.get("id")
                or raw_criterion.get("criterionId")
                or self._make_criterion_id(criterion_type, ordinal)
            )

            key = (str(trial_id), str(criterion_id))
            if key in seen:
                flags.append(
                    RegistryFlag(
                        type="duplicate_criterion_skipped",
                        severity="low",
                        message=(
                            f"Duplicate criterion '{criterion_id}' for trial "
                            f"'{trial_id}' was skipped."
                        ),
                    )
                )
                return

            seen.add(key)

            source_criteria.append(
                SourceCriterion(
                    trial_id=str(trial_id),
                    criterion_id=str(criterion_id),
                    type=str(criterion_type),
                    raw_text=str(raw_text),
                    attribute=self._optional_str(
                        raw_criterion.get("attribute")
                        or raw_criterion.get("attribute_name")
                        or raw_criterion.get("name")
                    ),
                    attribute_id=self._optional_str(
                        raw_criterion.get("attribute_id")
                        or raw_criterion.get("attributeId")
                    ),
                    normalized_attribute=self._optional_str(
                        raw_criterion.get("normalized_attribute")
                        or raw_criterion.get("normalizedAttribute")
                    ),
                    operator=raw_criterion.get("operator"),
                    target_value=raw_criterion.get("target_value")
                    if "target_value" in raw_criterion
                    else raw_criterion.get("targetValue"),
                    unit=self._optional_str(raw_criterion.get("unit")),
                    hardness=self._optional_str(raw_criterion.get("hardness")),
                    category=self._optional_str(raw_criterion.get("category")),
                    requires_temporal_reasoning=self._to_bool(
                        raw_criterion.get("requires_temporal_reasoning")
                        if "requires_temporal_reasoning" in raw_criterion
                        else raw_criterion.get("requiresTemporalReasoning")
                    ),
                    requires_negation_handling=self._to_bool(
                        raw_criterion.get("requires_negation_handling")
                        if "requires_negation_handling" in raw_criterion
                        else raw_criterion.get("requiresNegationHandling")
                    ),
                )
            )

        root_criteria = candidate_json.get("source_criteria")
        if root_criteria is None:
            root_criteria = candidate_json.get("criteria")

        ordinal = 1

        for raw_criterion in self._flatten_criteria(root_criteria):
            add_criterion(
                raw_criterion=raw_criterion,
                default_trial_id=None,
                default_type=None,
                ordinal=ordinal,
            )
            ordinal += 1

        studies = self._get_studies(candidate_json)

        for study in studies:
            if not isinstance(study, dict):
                continue

            trial_id = self._extract_trial_id(study)
            raw_criteria_containers = self._get_criteria_containers_from_study(study)

            for default_type, container in raw_criteria_containers:
                for raw_criterion in self._flatten_criteria(
                    container,
                    default_type=default_type,
                ):
                    add_criterion(
                        raw_criterion=raw_criterion,
                        default_trial_id=trial_id,
                        default_type=default_type,
                        ordinal=ordinal,
                    )
                    ordinal += 1

        return source_criteria

    def _should_include_criterion(
        self,
        criterion: dict[str, Any],
    ) -> bool:
        """
        Decide si un criterio debe contribuir al registry.

        Reglas:
        - Excluye criterios marcados como fallidos/invalidos.
        - Excluye criterios soft si include_soft_criteria=False.
        - Excluye administrativos/logísticos si include_administrative_criteria=False.
        """
        if not isinstance(criterion, dict):
            return False

        status = self._slugify(
            str(
                criterion.get("status")
                or criterion.get("parsing_status")
                or criterion.get("parse_status")
                or ""
            )
        )

        if status in {"failed", "parse_failed", "invalid", "error"}:
            return False

        hardness = self._slugify(str(criterion.get("hardness") or ""))
        if not self.include_soft_criteria and hardness in {
            "soft",
            "optional",
            "preference",
            "preferred",
            "nice_to_have",
        }:
            return False

        category = self._slugify(str(criterion.get("category") or ""))
        raw_text = str(
            criterion.get("raw_text")
            or criterion.get("criterion_text")
            or criterion.get("text")
            or criterion.get("description")
            or criterion.get("criterion")
            or ""
        ).lower()

        administrative_categories = {
            "administrative",
            "admin",
            "logistic",
            "logistical",
            "consent",
            "compliance",
        }

        administrative_cues = (
            "informed consent",
            "sign consent",
            "willing to",
            "willingness",
            "comply with",
            "compliance with",
            "able to understand",
            "agree to",
            "available for",
        )

        is_administrative = (
            category in administrative_categories
            or any(cue in raw_text for cue in administrative_cues)
        )

        if is_administrative and not self.include_administrative_criteria:
            return False

        return True

    def _build_attributes(
        self,
        source_criteria: list[SourceCriterion],
        flags: list[RegistryFlag],
    ) -> list[RegistryAttribute]:
        """
        Agrupa criterios por attribute_id y construye atributos únicos.
        """
        attributes_by_id: dict[str, RegistryAttribute] = {}
        hard_by_attribute: dict[str, bool] = {}

        for criterion in source_criteria:
            try:
                identity = self._resolve_attribute_identity(criterion)
            except Exception as e:
                identity = None
                flags.append(
                    RegistryFlag(
                        type="attribute_identity_resolution_error",
                        severity="medium",
                        message=(
                            f"Could not resolve attribute identity for criterion "
                            f"'{criterion.criterion_id}' in trial '{criterion.trial_id}': {e}"
                        ),
                    )
                )

            if identity is None:
                flags.append(
                    RegistryFlag(
                        type="attribute_identity_not_resolved",
                        severity="medium",
                        message=(
                            f"Criterion '{criterion.criterion_id}' in trial "
                            f"'{criterion.trial_id}' could not be mapped to an attribute."
                        ),
                    )
                )
                continue

            attribute_id = identity["attribute_id"]
            canonical_name = identity["canonical_name"]
            normalized_attribute = identity["normalized_attribute"]

            value_type = identity.get("value_type") or self._infer_value_type(
                criterion=criterion,
                attribute_id=attribute_id,
            )

            attribute_type = identity.get("type") or self._infer_attribute_type(
                criterion=criterion,
                attribute_id=attribute_id,
            )

            aliases = self._dedupe_strings(
                [
                    *identity.get("aliases", []),
                    criterion.attribute,
                    criterion.attribute_id,
                    criterion.normalized_attribute,
                    canonical_name,
                ]
            )

            source_attribute_names = self._dedupe_strings(
                [
                    criterion.attribute,
                    criterion.attribute_id,
                    criterion.normalized_attribute,
                    canonical_name,
                ]
            )

            required_by = RequiredBy(
                trial_id=criterion.trial_id,
                criterion_id=criterion.criterion_id,
                criterion_text=criterion.raw_text,
                criterion_type=criterion.type,
                operator=criterion.operator,
                target_value=criterion.target_value,
                unit=criterion.unit,
            )

            is_hard = self._slugify(str(criterion.hardness or "")) == "hard"

            if attribute_id not in attributes_by_id:
                attr = RegistryAttribute(
                    attribute_id=attribute_id,
                    canonical_name=canonical_name,
                    normalized_attribute=normalized_attribute,
                    type=attribute_type,
                    value_type=value_type,
                    unit=criterion.unit,
                    allowed_values=self._infer_allowed_values(
                        attribute_id=attribute_id,
                        value_type=value_type,
                    ),
                    aliases=aliases,
                    source_attribute_names=source_attribute_names,
                    criticality="high" if is_hard else "medium",
                    requires_temporal_reasoning=criterion.requires_temporal_reasoning,
                    requires_negation_handling=criterion.requires_negation_handling,
                    normalization_method=identity.get("normalization_method"),
                    normalization_confidence=identity.get("normalization_confidence"),
                    required_by=[required_by],
                )
                attributes_by_id[attribute_id] = attr
                hard_by_attribute[attribute_id] = is_hard

                if identity.get("normalization_method") == "slug_raw_text":
                    flags.append(
                        RegistryFlag(
                            type="low_confidence_attribute_identity",
                            severity="medium",
                            message=(
                                f"Criterion '{criterion.criterion_id}' in trial "
                                f"'{criterion.trial_id}' had no parsed attribute; "
                                f"attribute_id was derived from raw_text as '{attribute_id}'."
                            ),
                        )
                    )

                continue

            attr = attributes_by_id[attribute_id]
            hard_by_attribute[attribute_id] = hard_by_attribute[attribute_id] or is_hard

            if canonical_name and canonical_name not in attr.aliases:
                attr.aliases.append(canonical_name)

            attr.aliases = self._dedupe_strings([*attr.aliases, *aliases])
            attr.source_attribute_names = self._dedupe_strings(
                [*attr.source_attribute_names, *source_attribute_names]
            )

            if attr.type == "unknown" and attribute_type != "unknown":
                attr.type = attribute_type
            elif (
                attribute_type != "unknown"
                and attr.type != "unknown"
                and attr.type != attribute_type
            ):
                flags.append(
                    RegistryFlag(
                        type="attribute_type_conflict",
                        severity="low",
                        message=(
                            f"Attribute '{attribute_id}' was associated with multiple "
                            f"types: '{attr.type}' and '{attribute_type}'. Keeping '{attr.type}'."
                        ),
                    )
                )

            if attr.value_type == "unknown" and value_type != "unknown":
                attr.value_type = value_type

            if attr.unit is None and criterion.unit is not None:
                attr.unit = criterion.unit
            elif (
                attr.unit is not None
                and criterion.unit is not None
                and attr.unit != criterion.unit
            ):
                flags.append(
                    RegistryFlag(
                        type="attribute_unit_conflict",
                        severity="medium",
                        message=(
                            f"Attribute '{attribute_id}' has conflicting units: "
                            f"'{attr.unit}' and '{criterion.unit}'. Keeping '{attr.unit}'."
                        ),
                    )
                )

            attr.requires_temporal_reasoning = (
                attr.requires_temporal_reasoning
                or criterion.requires_temporal_reasoning
            )
            attr.requires_negation_handling = (
                attr.requires_negation_handling
                or criterion.requires_negation_handling
            )

            existing_required_by_keys = {
                (item.trial_id, item.criterion_id) for item in attr.required_by
            }

            if (required_by.trial_id, required_by.criterion_id) not in existing_required_by_keys:
                attr.required_by.append(required_by)

        attributes = list(attributes_by_id.values())

        for attr in attributes:
            if hard_by_attribute.get(attr.attribute_id):
                attr.criticality = "high"
            else:
                attr.criticality = self._infer_criticality(attr)

            attr.allowed_values = self._infer_allowed_values(
                attribute_id=attr.attribute_id,
                value_type=attr.value_type,
            )

        return attributes

    def _resolve_attribute_identity(
        self,
        criterion: SourceCriterion,
    ) -> dict[str, Any] | None:
        """
        Decide attribute_id, canonical_name, value_type, method, confidence.

        Regla principal:
            Si hay normalizer, todos los nombres de atributo pasan por
            normalizer.normalize_attribute().

        Orden de candidato textual:
            1. criterion.attribute
            2. criterion.normalized_attribute
            3. criterion.attribute_id
            4. slug de raw_text como fallback de baja confianza
        """
        attribute_text = (
            criterion.attribute
            or criterion.normalized_attribute
            or criterion.attribute_id
        )

        if attribute_text:
            normalized_identity = self._normalize_attribute_identity(attribute_text)
            if normalized_identity is not None:
                return normalized_identity

            attribute_id = self._slugify(attribute_text)
            if attribute_id:
                return {
                    "attribute_id": attribute_id,
                    "canonical_name": str(attribute_text).strip(),
                    "normalized_attribute": attribute_id,
                    "normalization_method": "slug_attribute_fallback",
                    "normalization_confidence": 0.3,
                }

        if criterion.raw_text:
            attribute_id = self._slugify(criterion.raw_text)
            if not attribute_id:
                return None

            if len(attribute_id) > 80:
                attribute_id = attribute_id[:80].rstrip("_")

            canonical_name = criterion.raw_text.strip()
            if len(canonical_name) > 120:
                canonical_name = canonical_name[:117].rstrip() + "..."

            return {
                "attribute_id": attribute_id,
                "canonical_name": canonical_name,
                "normalized_attribute": attribute_id,
                "normalization_method": "slug_raw_text",
                "normalization_confidence": 0.2,
            }

        return None

    def _normalize_attribute_identity(
        self,
        attribute_text: str,
    ) -> dict[str, Any] | None:
        """
        Usa ClinicalNormalizer.normalize_attribute() como fuente única de
        normalización de identidad del atributo.

        Acepta objetos Pydantic, dicts o strings para que el builder sea robusto
        ante pequeñas variaciones del normalizer.
        """
        if self.normalizer is None:
            return None

        normalized = self.normalizer.normalize_attribute(attribute_text)

        if normalized is None:
            return None

        if isinstance(normalized, BaseModel):
            normalized = normalized.model_dump()

        if isinstance(normalized, str):
            attribute_id = self._slugify(normalized)
            if not attribute_id:
                return None

            return {
                "attribute_id": attribute_id,
                "canonical_name": str(attribute_text).strip(),
                "normalized_attribute": attribute_id,
                "normalization_method": "normalizer.normalize_attribute",
                "normalization_confidence": 0.9,
            }

        if not isinstance(normalized, dict):
            return None

        raw_identifier = (
            normalized.get("attribute_id")
            or normalized.get("normalized_attribute")
            or normalized.get("id")
            or normalized.get("name")
            or normalized.get("canonical_name")
        )

        if raw_identifier is None:
            return None

        attribute_id = self._slugify(str(raw_identifier))
        if not attribute_id:
            return None

        canonical_name = (
            normalized.get("canonical_name")
            or normalized.get("display_name")
            or normalized.get("name")
            or str(attribute_text).strip()
            or self._humanize_slug(attribute_id)
        )

        aliases = normalized.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        elif not isinstance(aliases, list):
            aliases = []

        method = normalized.get("method") or "normalize_attribute"
        confidence = normalized.get("confidence")

        return {
            "attribute_id": attribute_id,
            "canonical_name": str(canonical_name),
            "normalized_attribute": attribute_id,
            "value_type": normalized.get("value_type"),
            "aliases": aliases,
            "normalization_method": f"normalizer.{method}",
            "normalization_confidence": confidence,
        }

    def _infer_value_type(
        self,
        criterion: SourceCriterion,
        attribute_id: str,
    ) -> str:
        """
        Infere value_type si el normalizer no lo da.
        """
        attr = self._slugify(attribute_id)
        operator = self._slugify(str(criterion.operator or ""))

        if attr in {"age", "ecog", "ecog_status", "ecog_performance_status"}:
            return "integer"

        if any(token in attr for token in ["karnofsky", "score", "grade"]):
            return "integer"

        if attr.endswith("_date") or attr.startswith("date_"):
            return "date"

        if attr.startswith("days_since") or "days_since" in attr:
            return "integer"

        boolean_cues = (
            "active_",
            "has_",
            "history_of_",
            "prior_",
            "current_",
            "pregnancy",
            "metastases",
            "infection",
            "contraindication",
            "eligible",
            "measurable_disease",
        )

        if operator in {"is_true", "is_false", "exists", "not_exists"}:
            return "boolean"

        if any(cue in attr for cue in boolean_cues):
            return "boolean"

        if attr in {"sex", "gender"}:
            return "categorical"

        if attr.endswith("_status") or any(
            token in attr
            for token in [
                "biomarker",
                "mutation",
                "stage",
                "subtype",
                "histology",
                "condition",
                "diagnosis",
            ]
        ):
            return "categorical"

        target = criterion.target_value

        if isinstance(target, bool):
            return "boolean"

        if isinstance(target, int) and not isinstance(target, bool):
            return "integer"

        if isinstance(target, float):
            return "float"

        if isinstance(target, list) and target:
            if all(isinstance(v, bool) for v in target):
                return "boolean"

            if all(isinstance(v, int) and not isinstance(v, bool) for v in target):
                return "integer"

            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in target):
                return "float"

            return "categorical"

        if operator in {">", ">=", "<", "<=", "between"}:
            return "float"

        return "unknown"

    def _infer_allowed_values(
        self,
        attribute_id: str,
        value_type: str,
    ) -> list[Any] | None:
        """
        Devuelve allowed_values generales del atributo, no target_value del criterio.
        """
        attr = self._slugify(attribute_id)

        if value_type == "boolean":
            return [True, False]

        if attr in {"sex", "gender"}:
            return ["male", "female", "other", "unknown"]

        if attr in {"ecog", "ecog_status", "ecog_performance_status"}:
            return [0, 1, 2, 3, 4]

        if "karnofsky" in attr:
            return list(range(0, 101, 10))

        if attr in {"stage", "cancer_stage", "disease_stage"} or attr.endswith("_stage"):
            return ["I", "II", "III", "IV", "unknown"]

        if attr.endswith("_status") and any(
            token in attr
            for token in [
                "egfr",
                "alk",
                "ros1",
                "braf",
                "her2",
                "kras",
                "met",
                "ret",
                "ntrk",
            ]
        ):
            return ["positive", "negative", "unknown"]

        if value_type in {
            "integer",
            "float",
            "date",
            "string",
            "list",
            "object",
            "unknown",
        }:
            return None

        return None

    def _infer_criticality(
        self,
        attribute: RegistryAttribute,
    ) -> AttributeCriticality:
        """
        Calcula criticality con heurísticas.
        """
        if attribute.criticality == "high":
            return "high"

        affected_trials = {
            item.trial_id
            for item in attribute.required_by
            if item.trial_id and item.trial_id != "unknown_trial"
        }

        affected_criteria = {
            (item.trial_id, item.criterion_id)
            for item in attribute.required_by
            if item.criterion_id
        }

        attr_type = self._slugify(attribute.type)
        attr_id = self._slugify(attribute.attribute_id)

        if attr_type in {"administrative", "admin", "logistic", "logistical"}:
            return "low"

        if len(affected_trials) >= 3 or len(affected_criteria) >= 5:
            return "high"

        high_value_types = {
            "biomarker",
            "disease_status",
            "treatment_history",
            "functional_status",
            "lab",
            "laboratory",
        }

        if attr_type in high_value_types:
            return "high"

        if attribute.requires_negation_handling:
            return "high"

        if attribute.requires_temporal_reasoning:
            return "medium"

        if any(
            token in attr_id
            for token in [
                "ecog",
                "metastases",
                "mutation",
                "progression",
                "pregnancy",
                "infection",
                "prior_treatment",
                "organ_function",
            ]
        ):
            return "high"

        if len(affected_criteria) >= 2:
            return "medium"

        if attr_type == "unknown" and attribute.value_type == "unknown":
            return "low"

        return "medium"

    def _build_summary(
        self,
        source_trials: list[SourceTrial],
        source_criteria: list[SourceCriterion],
        attributes: list[RegistryAttribute],
    ) -> AttributeRegistrySummary:
        """
        Genera summary del registry.
        """
        trial_ids = {trial.trial_id for trial in source_trials if trial.trial_id}
        trial_ids.update(
            criterion.trial_id
            for criterion in source_criteria
            if criterion.trial_id and criterion.trial_id != "unknown_trial"
        )

        return AttributeRegistrySummary(
            total_trials=len(trial_ids),
            total_source_criteria=len(source_criteria),
            total_attributes=len(attributes),
            high_criticality_attributes=sum(
                1 for attr in attributes if attr.criticality == "high"
            ),
            medium_criticality_attributes=sum(
                1 for attr in attributes if attr.criticality == "medium"
            ),
            low_criticality_attributes=sum(
                1 for attr in attributes if attr.criticality == "low"
            ),
            temporal_attributes=sum(
                1 for attr in attributes if attr.requires_temporal_reasoning
            ),
            negation_sensitive_attributes=sum(
                1 for attr in attributes if attr.requires_negation_handling
            ),
            compound_attributes=sum(
                1
                for attr in attributes
                if self._slugify(attr.type) == "compound"
                or "compound" in self._slugify(attr.attribute_id)
            ),
        )

    def _make_registry_id(
        self,
        patient_id: str | None,
    ) -> str:
        """
        Genera ID estable del registry.
        """
        patient_part = self._slugify(patient_id or "global")
        version_part = self._slugify(self.schema_version)
        return f"attribute_registry_{patient_part}_{version_part}"

    def _slugify(
        self,
        value: str,
    ) -> str:
        """
        Convierte texto en identificador.
        """
        if value is None:
            return ""

        value = str(value).strip().lower()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"[^a-z0-9]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value

    # ---------------------------------------------------------------------
    # Helpers internos deterministas.
    # ---------------------------------------------------------------------

    def _extract_patient_id(self, candidate_json: Any) -> str | None:
        if not isinstance(candidate_json, dict):
            return None

        patient_id = candidate_json.get("patient_id")

        if patient_id is None and isinstance(candidate_json.get("patient"), dict):
            patient_id = candidate_json["patient"].get("patient_id")

        if patient_id is None and isinstance(candidate_json.get("metadata"), dict):
            patient_id = candidate_json["metadata"].get("patient_id")

        return str(patient_id) if patient_id is not None else None

    def _get_studies(self, candidate_json: dict[str, Any]) -> list[dict[str, Any]]:
        for key in (
            "unique_studies",
            "studies",
            "trials",
            "candidate_trials",
            "candidates",
            "parsed_trials",
            "trial_candidates",
        ):
            raw = candidate_json.get(key)
            if raw is None:
                continue

            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]

            if isinstance(raw, dict):
                if self._looks_like_study(raw):
                    return [raw]
                return [item for item in raw.values() if isinstance(item, dict)]

        if self._looks_like_study(candidate_json):
            return [candidate_json]

        return []

    def _looks_like_study(self, value: dict[str, Any]) -> bool:
        if not isinstance(value, dict):
            return False

        has_trial_id = any(
            key in value
            for key in ["trial_id", "nct_id", "nctId", "study_id", "id"]
        )

        has_criteria = any(
            key in value
            for key in [
                "criteria",
                "source_criteria",
                "parsed_criteria",
                "eligibility",
                "eligibility_criteria",
                "inclusion_criteria",
                "exclusion_criteria",
            ]
        )

        return has_trial_id or has_criteria

    def _looks_like_criterion(self, value: dict[str, Any]) -> bool:
        if not isinstance(value, dict):
            return False

        criterion_keys = {
            "criterion_id",
            "criterionId",
            "raw_text",
            "criterion_text",
            "text",
            "description",
            "criterion",
            "attribute",
            "attribute_id",
            "normalized_attribute",
            "operator",
            "target_value",
        }

        return bool(criterion_keys.intersection(value.keys()))

    def _extract_trial_id(self, value: dict[str, Any]) -> str | None:
        if not isinstance(value, dict):
            return None

        trial_id = (
            value.get("trial_id")
            or value.get("nct_id")
            or value.get("nctId")
            or value.get("study_id")
            or value.get("studyId")
            or value.get("id")
        )

        if trial_id is None:
            protocol = value.get("protocolSection")
            if isinstance(protocol, dict):
                identification = protocol.get("identificationModule")
                if isinstance(identification, dict):
                    trial_id = identification.get("nctId")

        return str(trial_id) if trial_id is not None else None

    def _get_criteria_containers_from_study(
        self,
        study: dict[str, Any],
    ) -> list[tuple[str | None, Any]]:
        containers: list[tuple[str | None, Any]] = []

        for key in ("source_criteria", "criteria", "parsed_criteria"):
            if key in study:
                containers.append((None, study.get(key)))

        if "inclusion_criteria" in study:
            containers.append(("inclusion", study.get("inclusion_criteria")))

        if "exclusion_criteria" in study:
            containers.append(("exclusion", study.get("exclusion_criteria")))

        eligibility = study.get("eligibility")
        if isinstance(eligibility, dict):
            for key in ("criteria", "parsed_criteria"):
                if key in eligibility:
                    containers.append((None, eligibility.get(key)))

            if "inclusion_criteria" in eligibility:
                containers.append(("inclusion", eligibility.get("inclusion_criteria")))

            if "exclusion_criteria" in eligibility:
                containers.append(("exclusion", eligibility.get("exclusion_criteria")))

        eligibility_criteria = study.get("eligibility_criteria")
        if eligibility_criteria is not None:
            containers.append((None, eligibility_criteria))

        protocol = study.get("protocolSection")
        if isinstance(protocol, dict):
            eligibility_module = protocol.get("eligibilityModule")
            if isinstance(eligibility_module, dict):
                criteria = eligibility_module.get("eligibilityCriteria")
                if criteria:
                    containers.append((None, criteria))

        return containers

    def _flatten_criteria(
        self,
        container: Any,
        default_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if container is None:
            return []

        if isinstance(container, str):
            return [
                {
                    "raw_text": container,
                    "type": default_type or "unknown",
                }
            ]

        if isinstance(container, list):
            flattened: list[dict[str, Any]] = []
            for item in container:
                flattened.extend(
                    self._flatten_criteria(item, default_type=default_type)
                )
            return flattened

        if isinstance(container, dict):
            if self._looks_like_criterion(container):
                criterion = copy.deepcopy(container)
                if default_type and not criterion.get("type"):
                    criterion["type"] = default_type
                return [criterion]

            flattened = []

            known_type_keys = {
                "inclusion": "inclusion",
                "inclusions": "inclusion",
                "include": "inclusion",
                "inclusion_criteria": "inclusion",
                "exclusion": "exclusion",
                "exclusions": "exclusion",
                "exclude": "exclusion",
                "exclusion_criteria": "exclusion",
            }

            for key, value in container.items():
                key_slug = self._slugify(str(key))
                child_type = known_type_keys.get(key_slug, default_type)
                flattened.extend(
                    self._flatten_criteria(value, default_type=child_type)
                )

            return flattened

        return []

    def _make_criterion_id(self, criterion_type: str, ordinal: int) -> str:
        type_slug = self._slugify(criterion_type or "criterion")
        prefix = "crit"

        if type_slug.startswith("inc"):
            prefix = "inc"
        elif type_slug.startswith("exc"):
            prefix = "exc"

        return f"{prefix}_{ordinal:03d}"

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text if text else None

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value

        if value is None:
            return False

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()
        return text in {"true", "1", "yes", "y", "si", "sí"}

    def _dedupe_strings(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            if value is None:
                continue

            if isinstance(value, list):
                candidates = value
            else:
                candidates = [value]

            for candidate in candidates:
                text = str(candidate).strip()
                if not text:
                    continue

                key = self._slugify(text)
                if not key or key in seen:
                    continue

                seen.add(key)
                result.append(text)

        return result

    def _humanize_slug(self, value: str) -> str:
        value = self._slugify(value)
        if not value:
            return "unknown attribute"
        return value.replace("_", " ")

    def _infer_attribute_type(
        self,
        criterion: SourceCriterion,
        attribute_id: str,
    ) -> str:
        if criterion.category:
            return self._slugify(criterion.category) or "unknown"

        attr = self._slugify(attribute_id)

        if attr in {"age", "sex", "gender"}:
            return "demographic"

        if any(token in attr for token in ["ecog", "karnofsky", "performance_status"]):
            return "functional_status"

        if any(
            token in attr
            for token in [
                "egfr",
                "alk",
                "ros1",
                "braf",
                "her2",
                "kras",
                "met",
                "ret",
                "ntrk",
                "mutation",
                "biomarker",
            ]
        ):
            return "biomarker"

        if any(
            token in attr
            for token in [
                "hemoglobin",
                "platelet",
                "neutrophil",
                "creatinine",
                "bilirubin",
                "ast",
                "alt",
                "wbc",
                "anc",
                "lab",
                "laboratory",
            ]
        ):
            return "lab"

        if any(
            token in attr
            for token in [
                "treatment",
                "therapy",
                "chemotherapy",
                "radiotherapy",
                "immunotherapy",
                "prior_",
                "current_",
                "previous_",
            ]
        ):
            return "treatment_history"

        if any(
            token in attr
            for token in [
                "metastases",
                "metastatic",
                "stage",
                "progression",
                "disease",
                "diagnosis",
                "histology",
                "subtype",
                "infection",
            ]
        ):
            return "disease_status"

        if any(token in attr for token in ["consent", "willing", "comply"]):
            return "administrative"

        if any(token in attr for token in ["location", "distance", "site", "travel"]):
            return "logistic"

        if any(token in attr for token in ["adequate", "organ_function", "compound"]):
            return "compound"

        return "unknown"
