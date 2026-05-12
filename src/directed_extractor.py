# -*- coding: utf-8 -*-
import hashlib
import json
from pathlib import Path
from typing import Literal, Any, List, Optional, Dict, Tuple

from pydantic import BaseModel, Field

from LLM.prompt_loader import load_prompt


AttributeStatus = Literal[
    "found",
    "not_found",
    "negated",
    "ambiguous",
    "conflicting",
    "outdated",
    "derived",
    "low_confidence",
    "not_applicable",
    "extraction_error",
]

ATTRIBUTE_STATUSES = (
    "found",
    "not_found",
    "negated",
    "ambiguous",
    "conflicting",
    "outdated",
    "derived",
    "low_confidence",
    "not_applicable",
    "extraction_error",
)


class EvidenceSpan(BaseModel):
    text: str
    source: str = "raw_text"
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    confidence: Optional[float] = None


class TemporalInfo(BaseModel):
    status: Literal[
        "current",
        "historical",
        "future",
        "unclear",
        "not_temporal",
    ] = "unclear"
    date_text: Optional[str] = None
    normalized_date: Optional[str] = None
    relation: Optional[str] = None


class NegationInfo(BaseModel):
    is_negated: bool = False
    negation_cue: Optional[str] = None
    scope: Optional[str] = None


class RequiredByCriterion(BaseModel):
    trial_id: str
    criterion_id: str = "unknown"
    criterion_text: Optional[str] = None


class AttributeImpact(BaseModel):
    affected_trials: int = 0
    affected_criteria: int = 0
    is_ranking_critical: bool = False


class ExtractedPatientAttribute(BaseModel):
    attribute_id: str
    canonical_name: str

    value: Optional[str] = None
    normalized_value: Optional[str] = None
    unit: Optional[str] = None

    status: AttributeStatus
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    evidence: List[EvidenceSpan] = Field(default_factory=list)

    date: Optional[str] = None
    temporality: Optional[TemporalInfo] = None
    negation: Optional[NegationInfo] = None

    missing_question: Optional[str] = None

    required_by: List[RequiredByCriterion] = Field(default_factory=list)
    impact: Optional[AttributeImpact] = None

    notes: Optional[str] = None
    error: Optional[str] = None


class ExtractionSummary(BaseModel):
    total_attributes: int

    found: int = 0
    not_found: int = 0
    negated: int = 0
    ambiguous: int = 0
    conflicting: int = 0
    outdated: int = 0
    derived: int = 0
    low_confidence: int = 0
    not_applicable: int = 0
    extraction_error: int = 0

    coverage: float = 0.0


class ExtractionFlag(BaseModel):
    type: str
    severity: Literal["low", "medium", "high"]
    message: str


class ExtractorMetadata(BaseModel):
    module: str = "DirectedPatientExtractor"
    model_size: Optional[str] = None
    model_name: Optional[str] = None
    temperature: float = 0.0
    prompt_version: str = "directed_patient_extractor_v1"
    schema_version: str = "patient_attribute_set_v1"
    attempts: int = 1

    registry_hash: Optional[str] = None

    source_patient_id: Optional[str] = None
    source: Optional[str] = None
    source_file: Optional[str] = None
    input_format: Optional[str] = None

    upstream_module: Optional[str] = None
    upstream_model_size: Optional[str] = None
    upstream_model_name: Optional[str] = None
    upstream_prompt_version: Optional[str] = None
    upstream_schema_version: Optional[str] = None
    upstream_extraction_status: Optional[str] = None

    error: Optional[str] = None


class PatientAttributeSet(BaseModel):
    patient_id: str
    registry_id: str
    extraction_status: Literal[
        "completed",
        "completed_with_missing",
        "completed_with_warnings",
        "partial",
        "failed",
    ]
    attributes: List[ExtractedPatientAttribute]
    summary: ExtractionSummary
    flags: List[ExtractionFlag] = Field(default_factory=list)
    extractor_metadata: ExtractorMetadata = Field(default_factory=ExtractorMetadata)

    @property
    def metadata(self) -> ExtractorMetadata:
        """
        Compatibilidad interna con código antiguo que accedía a `.metadata`.
        En JSON se exporta como `extractor_metadata`.
        """
        return self.extractor_metadata


class LLMExtractionResponse(BaseModel):
    """
    Respuesta mínima esperada del LLM.

    El LLM solo extrae atributos.
    El sistema calcula después:
    - required_by
    - impact
    - summary
    - extraction_status
    - extractor_metadata
    """
    attributes: List[ExtractedPatientAttribute] = Field(default_factory=list)
    flags: List[ExtractionFlag] = Field(default_factory=list)


class DirectedPatientExtractor:
    def __init__(
        self,
        llm_client,
        registry_id: str = "default_registry_v1",
        model_size: Optional[str] = "SMALL",
        model_name: Optional[str] = None,
        temperature: float = 0.0,
        prompt_version: str = "directed_patient_extractor_v1",
        prompt_filename: str = "directed_patient_extractor.md",
        schema_version: str = "patient_attribute_set_v1",
        max_attempts: int = 1,
        question_generator: Optional[Any] = None,
    ):
        self.llm_client = llm_client
        self.registry_id = registry_id

        self.model_size = model_size
        self.model_name = model_name
        self.temperature = temperature
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.max_attempts = max(1, max_attempts)
        self.prompt_filename = prompt_filename

        self.question_generator = question_generator

    def extract(
        self,
        normalized_profile: dict,
        attribute_registry: dict,
        output_path: Optional[Path] = None,
    ) -> PatientAttributeSet:
        patient_id = normalized_profile.get("patient_id", "unknown_patient")
        raw_text = normalized_profile.get("raw_text", "")
        registry_attributes = attribute_registry.get("attributes", [])

        attempts = 0

        try:
            if not registry_attributes:
                response_data = self._build_empty_registry_response(
                    patient_id=patient_id,
                    normalized_profile=normalized_profile,
                    registry_attributes=registry_attributes,
                )
                self._write_output_if_needed(response_data, output_path)
                return response_data

            user_prompt = self._build_user_prompt(
                patient_id=patient_id,
                raw_text=raw_text,
                normalized_profile=normalized_profile,
                attribute_registry=attribute_registry,
            )

            llm_response, attempts = self._run_llm(user_prompt)

            attributes, registry_flags = self._prepare_attributes_from_registry(
                llm_attributes=llm_response.attributes,
                registry_attributes=registry_attributes,
                patient_id=patient_id,
            )

            flags = []
            flags.extend(llm_response.flags)
            flags.extend(registry_flags)

            summary = self._build_summary(attributes)
            extraction_status = self._infer_extraction_status(summary, flags)

            response_data = PatientAttributeSet(
                patient_id=patient_id,
                registry_id=self.registry_id,
                extraction_status=extraction_status,
                attributes=attributes,
                summary=summary,
                flags=flags,
                extractor_metadata=self._build_metadata(
                    normalized_profile=normalized_profile,
                    registry_attributes=registry_attributes,
                    attempts=attempts,
                ),
            )

        except Exception as e:
            attempts = attempts or self.max_attempts

            failed_attributes = self._build_failed_attributes(
                attribute_registry=attribute_registry,
                error=str(e),
                patient_id=patient_id,
            )

            response_data = PatientAttributeSet(
                patient_id=patient_id,
                registry_id=self.registry_id,
                extraction_status="failed",
                attributes=failed_attributes,
                summary=self._build_summary(failed_attributes),
                flags=[
                    ExtractionFlag(
                        type="system_error",
                        severity="high",
                        message=str(e),
                    )
                ],
                extractor_metadata=self._build_metadata(
                    normalized_profile=normalized_profile,
                    registry_attributes=registry_attributes,
                    attempts=attempts,
                    error=str(e),
                ),
            )

        self._write_output_if_needed(response_data, output_path)
        return response_data

    def _build_user_prompt(
        self,
        patient_id: str,
        raw_text: str,
        normalized_profile: dict,
        attribute_registry: dict,
    ) -> str:
        patient_profile = self._get_patient_profile(normalized_profile)
        upstream_metadata = self._get_upstream_metadata(normalized_profile)

        input_metadata = {
            "patient_id": normalized_profile.get("patient_id"),
            "source_patient_id": normalized_profile.get("source_patient_id"),
            "source": normalized_profile.get("source"),
            "source_file": normalized_profile.get("source_file"),
            "input_format": normalized_profile.get("input_format"),
            "extraction_status": normalized_profile.get("extraction_status"),
            "extraction_error": normalized_profile.get("extraction_error"),
            "upstream_extractor_metadata": upstream_metadata,
        }

        return f"""
        ID del Paciente: {patient_id}

        === METADATOS DE ENTRADA ===
        {json.dumps(input_metadata, indent=2, ensure_ascii=False)}

        === TEXTO CLÍNICO ORIGINAL ===
        {raw_text}

        === PERFIL CLÍNICO ESTRUCTURADO PREVIO ===
        {json.dumps(patient_profile, indent=2, ensure_ascii=False)}

        === ATRIBUTOS REQUERIDOS ===
        {json.dumps(attribute_registry.get('attributes', []), indent=2, ensure_ascii=False)}
        """

    def _run_llm(self, user_prompt: str) -> Tuple[LLMExtractionResponse, int]:
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                raw_response = self.llm_client.generate_json(
                    prompt=user_prompt,
                    system_instruction=load_prompt(self.prompt_filename),
                    temperature=self.temperature,
                    response_schema=LLMExtractionResponse,
                )
                parsed_response = self._parse_llm_response(raw_response)
                return parsed_response, attempt

            except Exception as e:
                last_error = e

        raise RuntimeError(
            f"Directed extraction failed after {self.max_attempts} attempt(s): {last_error}"
        )

    def _parse_llm_response(self, raw_response: Any) -> LLMExtractionResponse:
        if isinstance(raw_response, LLMExtractionResponse):
            return raw_response

        if isinstance(raw_response, PatientAttributeSet):
            return LLMExtractionResponse(
                attributes=raw_response.attributes,
                flags=raw_response.flags,
            )

        if isinstance(raw_response, BaseModel):
            raw_response = raw_response.model_dump()

        if isinstance(raw_response, list):
            raw_response = {"attributes": raw_response}

        if not isinstance(raw_response, dict):
            raise TypeError(
                f"LLM response must be dict, list or Pydantic model. Got {type(raw_response)}"
            )

        if "attributes" not in raw_response:
            raise ValueError("LLM response does not contain an 'attributes' field.")

        return LLMExtractionResponse.model_validate(raw_response)

    def _prepare_attributes_from_registry(
        self,
        llm_attributes: List[ExtractedPatientAttribute],
        registry_attributes: List[dict],
        patient_id: Optional[str] = None,
    ) -> Tuple[List[ExtractedPatientAttribute], List[ExtractionFlag]]:
        flags: List[ExtractionFlag] = []

        attributes_by_key: Dict[str, ExtractedPatientAttribute] = {}
        matched_llm_object_ids = set()

        for attr in llm_attributes:
            keys = self._keys_from_llm_attribute(attr)

            for key in keys:
                if key not in attributes_by_key:
                    attributes_by_key[key] = attr
                else:
                    flags.append(
                        ExtractionFlag(
                            type="duplicate_attribute_from_llm",
                            severity="medium",
                            message=f"Duplicate extracted attribute ignored for key '{key}'.",
                        )
                    )

        final_attributes: List[ExtractedPatientAttribute] = []

        for registry_item in registry_attributes:
            registry_keys = self._keys_from_registry_item(registry_item)
            matched_attr: Optional[ExtractedPatientAttribute] = None

            for key in registry_keys:
                if key in attributes_by_key:
                    matched_attr = attributes_by_key[key]
                    matched_llm_object_ids.add(id(matched_attr))
                    break

            if matched_attr is None:
                matched_attr = self._attribute_from_registry_item(
                    registry_item=registry_item,
                    status="not_found",
                    error=None,
                    patient_id=patient_id,
                )
                flags.append(
                    ExtractionFlag(
                        type="missing_attribute_from_llm",
                        severity="medium",
                        message=(
                            f"LLM did not return required attribute "
                            f"'{matched_attr.attribute_id}'. Added as not_found."
                        ),
                    )
                )
            else:
                matched_attr = matched_attr.model_copy(deep=True)
                matched_attr.attribute_id = self._registry_attribute_id(registry_item)
                matched_attr.canonical_name = self._registry_canonical_name(registry_item)

                if matched_attr.unit is None:
                    matched_attr.unit = registry_item.get("unit")

            matched_attr.required_by = self._required_by_from_registry_item(registry_item)
            matched_attr.impact = self._compute_attribute_impact(
                attr=matched_attr,
                registry_item=registry_item,
            )

            if matched_attr.status in {"not_found", "extraction_error"}:
                matched_attr.missing_question = self._generate_missing_question(
                    registry_item=registry_item,
                    status=matched_attr.status,
                    patient_id=patient_id,
                    error=matched_attr.error,
                )

            final_attributes.append(matched_attr)

        for attr in llm_attributes:
            if id(attr) not in matched_llm_object_ids:
                flags.append(
                    ExtractionFlag(
                        type="extra_attribute_ignored",
                        severity="low",
                        message=(
                            f"LLM returned attribute '{attr.attribute_id}', "
                            "but it is not present in the Attribute Registry."
                        ),
                    )
                )

        return final_attributes, flags

    def _attribute_from_registry_item(
        self,
        registry_item: dict,
        status: AttributeStatus,
        error: Optional[str] = None,
        patient_id: Optional[str] = None,
    ) -> ExtractedPatientAttribute:
        canonical_name = self._registry_canonical_name(registry_item)

        missing_question = None
        if status in {"not_found", "extraction_error"}:
            missing_question = self._generate_missing_question(
                registry_item=registry_item,
                status=status,
                patient_id=patient_id,
                error=error,
            )

        return ExtractedPatientAttribute(
            attribute_id=self._registry_attribute_id(registry_item),
            canonical_name=canonical_name,
            value=None,
            normalized_value=None,
            unit=registry_item.get("unit"),
            status=status,
            confidence=0.0,
            evidence=[],
            date=None,
            temporality=None,
            negation=None,
            missing_question=missing_question,
            required_by=self._required_by_from_registry_item(registry_item),
            impact=None,
            notes=None,
            error=error,
        )

    def _build_failed_attributes(
        self,
        attribute_registry: dict,
        error: str,
        patient_id: Optional[str] = None,
    ) -> List[ExtractedPatientAttribute]:
        failed_attributes: List[ExtractedPatientAttribute] = []

        for registry_item in attribute_registry.get("attributes", []):
            attr = self._attribute_from_registry_item(
                registry_item=registry_item,
                status="extraction_error",
                error=error,
                patient_id=patient_id,
            )
            attr.impact = self._compute_attribute_impact(attr, registry_item)
            failed_attributes.append(attr)

        return failed_attributes

    def _required_by_from_registry_item(
        self,
        registry_item: dict,
    ) -> List[RequiredByCriterion]:
        required_by: List[RequiredByCriterion] = []
        seen = set()

        def add_required_by(
            trial_id: Optional[str],
            criterion_id: Optional[str] = None,
            criterion_text: Optional[str] = None,
        ) -> None:
            trial_id_clean = trial_id or "unknown"
            criterion_id_clean = criterion_id or "unknown"
            key = (trial_id_clean, criterion_id_clean, criterion_text)

            if key in seen:
                return

            seen.add(key)

            required_by.append(
                RequiredByCriterion(
                    trial_id=trial_id_clean,
                    criterion_id=criterion_id_clean,
                    criterion_text=criterion_text,
                )
            )

        raw_required_by = registry_item.get("required_by", [])

        if isinstance(raw_required_by, dict):
            raw_required_by = [raw_required_by]

        for item in raw_required_by:
            if isinstance(item, str):
                add_required_by(trial_id=item)
            elif isinstance(item, dict):
                add_required_by(
                    trial_id=(
                        item.get("trial_id")
                        or item.get("nct_id")
                        or item.get("trial")
                    ),
                    criterion_id=(
                        item.get("criterion_id")
                        or item.get("id")
                        or item.get("criterion")
                    ),
                    criterion_text=(
                        item.get("criterion_text")
                        or item.get("raw_text")
                        or item.get("text")
                    ),
                )

        required_by_trials = registry_item.get("required_by_trials", [])

        if isinstance(required_by_trials, str):
            required_by_trials = [required_by_trials]

        for trial_id in required_by_trials:
            add_required_by(trial_id=trial_id)

        required_by_criteria = registry_item.get("required_by_criteria", [])

        if isinstance(required_by_criteria, dict):
            required_by_criteria = [required_by_criteria]

        for item in required_by_criteria:
            if isinstance(item, dict):
                add_required_by(
                    trial_id=item.get("trial_id") or item.get("nct_id"),
                    criterion_id=item.get("criterion_id") or item.get("id"),
                    criterion_text=item.get("criterion_text") or item.get("raw_text"),
                )

        return required_by

    def _compute_attribute_impact(
        self,
        attr: ExtractedPatientAttribute,
        registry_item: dict,
    ) -> AttributeImpact:
        affected_trials = {
            item.trial_id
            for item in attr.required_by
            if item.trial_id and item.trial_id != "unknown"
        }

        affected_criteria = {
            (item.trial_id, item.criterion_id)
            for item in attr.required_by
            if item.criterion_id and item.criterion_id != "unknown"
        }

        criticality = str(registry_item.get("criticality", "")).lower()

        is_ranking_critical = (
            criticality == "high"
            or len(affected_trials) >= 3
            or len(affected_criteria) >= 5
        )

        return AttributeImpact(
            affected_trials=len(affected_trials),
            affected_criteria=len(affected_criteria),
            is_ranking_critical=is_ranking_critical,
        )

    def _build_summary(
        self,
        attributes: List[ExtractedPatientAttribute],
    ) -> ExtractionSummary:
        counts = {status: 0 for status in ATTRIBUTE_STATUSES}

        for attr in attributes:
            counts[attr.status] = counts.get(attr.status, 0) + 1

        total = len(attributes)

        covered = (
            counts["found"]
            + counts["negated"]
            + counts["derived"]
        )

        coverage = round(covered / total, 4) if total else 0.0

        return ExtractionSummary(
            total_attributes=total,
            found=counts["found"],
            not_found=counts["not_found"],
            negated=counts["negated"],
            ambiguous=counts["ambiguous"],
            conflicting=counts["conflicting"],
            outdated=counts["outdated"],
            derived=counts["derived"],
            low_confidence=counts["low_confidence"],
            not_applicable=counts["not_applicable"],
            extraction_error=counts["extraction_error"],
            coverage=coverage,
        )

    def _infer_extraction_status(
        self,
        summary: ExtractionSummary,
        flags: List[ExtractionFlag],
    ) -> Literal[
        "completed",
        "completed_with_missing",
        "completed_with_warnings",
        "partial",
        "failed",
    ]:
        if summary.total_attributes == 0:
            return "completed_with_warnings"

        if summary.extraction_error == summary.total_attributes:
            return "failed"

        if summary.extraction_error > 0:
            return "partial"

        if any(flag.severity == "high" for flag in flags):
            return "completed_with_warnings"

        has_missing_or_uncertain = any(
            [
                summary.not_found > 0,
                summary.ambiguous > 0,
                summary.conflicting > 0,
                summary.outdated > 0,
                summary.low_confidence > 0,
            ]
        )

        if has_missing_or_uncertain:
            return "completed_with_missing"

        return "completed"

    def _build_empty_registry_response(
        self,
        patient_id: str,
        normalized_profile: dict,
        registry_attributes: List[dict],
    ) -> PatientAttributeSet:
        return PatientAttributeSet(
            patient_id=patient_id,
            registry_id=self.registry_id,
            extraction_status="completed_with_warnings",
            attributes=[],
            summary=ExtractionSummary(total_attributes=0, coverage=0.0),
            flags=[
                ExtractionFlag(
                    type="empty_attribute_registry",
                    severity="medium",
                    message="Attribute Registry contains no attributes.",
                )
            ],
            extractor_metadata=self._build_metadata(
                normalized_profile=normalized_profile,
                registry_attributes=registry_attributes,
                attempts=0,
            ),
        )

    def _build_metadata(
        self,
        normalized_profile: dict,
        registry_attributes: List[dict],
        attempts: int,
        error: Optional[str] = None,
    ) -> ExtractorMetadata:
        upstream_metadata = self._get_upstream_metadata(normalized_profile)

        return ExtractorMetadata(
            module="DirectedPatientExtractor",
            model_size=self.model_size,
            model_name=self._resolve_model_name(),
            temperature=self.temperature,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            attempts=attempts,
            registry_hash=self._stable_hash(registry_attributes),

            source_patient_id=normalized_profile.get("source_patient_id"),
            source=normalized_profile.get("source"),
            source_file=normalized_profile.get("source_file"),
            input_format=normalized_profile.get("input_format"),

            upstream_module=upstream_metadata.get("module"),
            upstream_model_size=upstream_metadata.get("model_size"),
            upstream_model_name=upstream_metadata.get("model_name"),
            upstream_prompt_version=upstream_metadata.get("prompt_version"),
            upstream_schema_version=upstream_metadata.get("schema_version"),
            upstream_extraction_status=normalized_profile.get("extraction_status"),

            error=error,
        )

    def _resolve_model_name(self) -> str:
        if self.model_name:
            return self.model_name

        for attr_name in ("model_name", "model", "model_id", "deployment_name"):
            value = getattr(self.llm_client, attr_name, None)
            if value:
                return str(value)

        return "unknown"

    def _write_output_if_needed(
        self,
        response_data: PatientAttributeSet,
        output_path: Optional[Path],
    ) -> None:
        if output_path is None:
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(response_data.model_dump_json(indent=2))

    def _stable_hash(self, data: Any) -> str:
        payload = json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def _get_patient_profile(self, normalized_profile: dict) -> dict:
        """
        Nuevo formato:
            normalized_profile["patient_profile"]

        Compatibilidad antigua:
            normalized_profile["normalized_profile"]
        """
        patient_profile = normalized_profile.get("patient_profile")

        if isinstance(patient_profile, dict):
            return patient_profile

        legacy_profile = normalized_profile.get("normalized_profile")

        if isinstance(legacy_profile, dict):
            return legacy_profile

        return {}

    def _get_upstream_metadata(self, normalized_profile: dict) -> dict:
        """
        Nuevo formato:
            normalized_profile["extractor_metadata"]

        Compatibilidad antigua:
            normalized_profile["metadata"]
        """
        metadata = normalized_profile.get("extractor_metadata")

        if isinstance(metadata, dict):
            return metadata

        legacy_metadata = normalized_profile.get("metadata")

        if isinstance(legacy_metadata, dict):
            return legacy_metadata

        return {}

    def _registry_attribute_id(self, registry_item: dict) -> str:
        return str(
            registry_item.get("attribute_id")
            or registry_item.get("id")
            or registry_item.get("name")
            or registry_item.get("canonical_name")
            or registry_item.get("normalized_attribute")
            or "unknown_attribute"
        )

    def _registry_canonical_name(self, registry_item: dict) -> str:
        return str(
            registry_item.get("canonical_name")
            or registry_item.get("name")
            or registry_item.get("attribute_id")
            or registry_item.get("id")
            or registry_item.get("normalized_attribute")
            or "unknown_attribute"
        )

    def _keys_from_registry_item(self, registry_item: dict) -> List[str]:
        candidates: List[Any] = [
            registry_item.get("attribute_id"),
            registry_item.get("id"),
            registry_item.get("canonical_name"),
            registry_item.get("name"),
            registry_item.get("normalized_attribute"),
        ]

        aliases = registry_item.get("aliases", [])

        if isinstance(aliases, str):
            candidates.append(aliases)
        elif isinstance(aliases, list):
            candidates.extend(aliases)

        return self._normalize_keys(candidates)

    def _keys_from_llm_attribute(
        self,
        attr: ExtractedPatientAttribute,
    ) -> List[str]:
        candidates = [
            attr.attribute_id,
            attr.canonical_name,
        ]

        return self._normalize_keys(candidates)

    def _normalize_keys(self, values: List[Any]) -> List[str]:
        keys: List[str] = []

        for value in values:
            if value is None:
                continue

            key = str(value).strip().lower()

            if key and key not in keys:
                keys.append(key)

        return keys
    
    def _generate_missing_question(
        self,
        registry_item: dict,
        status: AttributeStatus,
        patient_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[str]:
        """
        Delega la generación de preguntas faltantes al módulo MissingInfoQuestionGenerator.

        El método externo esperado es:
            generate_question(input_dict: dict) -> dict

        Se espera que devuelva algo como:
            {
                "question": "...",
                ...
            }

        También se acepta:
            {
                "missing_question": "...",
                ...
            }
        """
        if self.question_generator is None:
            return None

        payload = {
            "patient_id": patient_id,
            "attribute": {
                "attribute_id": self._registry_attribute_id(registry_item),
                "canonical_name": self._registry_canonical_name(registry_item),
                "unit": registry_item.get("unit"),
                "type": registry_item.get("type"),
                "allowed_values": registry_item.get("allowed_values"),
                "aliases": registry_item.get("aliases", []),
            },
            "registry_item": registry_item,
            "status": status,
            "error": error,
            "required_by": [
                item.model_dump()
                for item in self._required_by_from_registry_item(registry_item)
            ],
        }
        
        try:
            result = self.question_generator.generate_question(payload)
        except Exception:
            return None

        if not isinstance(result, dict):
            return None

        question = (
            result.get("question")
            or result.get("missing_question")
            or result.get("text")
        )

        if question is None:
            return None

        return str(question)