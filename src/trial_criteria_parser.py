"""
Trial Criteria Parser.

Este módulo define el contrato de datos y la implementación de la clase encargada de
parsear criterios de elegibilidad de ensayos clínicos.

Responsabilidad del módulo:
    - Recibir el JSON de candidatos de un paciente.
    - Leer los criterios raw desde cada trial.
    - Separar secciones de inclusión y exclusión.
    - Dividir cada sección en criterios individuales.
    - Parsear criterios con LLM en una estructura parcial.
    - Ensamblar criterios finales con IDs deterministas.
    - Detectar categoría, temporalidad, negación y hardness.
    - Usar normalizer opcional para rellenar `normalized_attribute`.
    - Devolver el mismo JSON de entrada, preservando su estructura original,
      pero añadiendo `criteria` dentro de cada estudio de `unique_studies`.

No hace:
    - Evaluación contra paciente.
    - Generación de preguntas faltantes.
    - Ranking.
    - Retrieval.
    - Decisión de elegibilidad.
"""

from __future__ import annotations

import copy
import json
import re
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from LLM.LLM_factory import LLMSize, create_llm
from LLM.base import LLMClient
from LLM.prompt_loader import load_prompt


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class CriterionType(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class CriterionParseStatus(str, Enum):
    PARSED = "parsed"
    PARTIALLY_PARSED = "partially_parsed"
    UNSTRUCTURED = "unstructured"
    COMPOUND_UNRESOLVED = "compound_unresolved"
    TEMPORAL_COMPLEX = "temporal_complex"
    NEGATION_SENSITIVE = "negation_sensitive"
    PARSE_FAILED = "parse_failed"


class CriteriaParseStatus(str, Enum):
    PARSED = "parsed"
    PARTIALLY_PARSED = "partially_parsed"
    NO_CRITERIA_AVAILABLE = "no_criteria_available"
    UNSTRUCTURED = "unstructured"
    PARSE_FAILED = "parse_failed"


class CriterionHardness(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    UNKNOWN = "unknown"


class CriterionCategory(str, Enum):
    DEMOGRAPHIC = "demographic"
    FUNCTIONAL_STATUS = "functional_status"
    DISEASE_STATUS = "disease_status"
    PRIOR_TREATMENT = "prior_treatment"
    CURRENT_TREATMENT = "current_treatment"
    LABORATORY = "laboratory"
    BIOMARKER = "biomarker"
    IMAGING = "imaging"
    COMORBIDITY = "comorbidity"
    INFECTION = "infection"
    REPRODUCTIVE = "reproductive"
    ADMINISTRATIVE = "administrative"
    LOGISTICAL = "logistical"
    OTHER = "other"
    UNKNOWN = "unknown"


class CriterionOperator(str, Enum):
    EQUALS = "=="
    NOT_EQUALS = "!="
    GREATER_THAN = ">"
    GREATER_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_OR_EQUAL = "<="
    IN = "in"
    NOT_IN = "not_in"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    IS_PRESENT = "is_present"
    IS_ABSENT = "is_absent"
    ANY_OF = "any_of"
    ALL_OF = "all_of"
    NOT_APPLICABLE_IF = "not_applicable_if"
    UNKNOWN = "unknown"


class CriterionSource(str, Enum):
    RULES = "rules"
    LLM = "llm"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class LogicOperator(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    UNKNOWN = "UNKNOWN"


class LLMTaskName(str, Enum):
    PARSE_INCLUSION_CRITERIA = "parse_inclusion_criteria"
    PARSE_EXCLUSION_CRITERIA = "parse_exclusion_criteria"
    DETECT_UNKNOWN_HARDNESS = "detect_unknown_hardness"


# -----------------------------------------------------------------------------
# Pydantic schemas: LLM metadata
# -----------------------------------------------------------------------------


class LLMGenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float = 0.0
    max_retries: int = 1
    structured_output: bool = True
    response_format: str = "json"


class LLMTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_name: LLMTaskName
    llm_size: LLMSize
    prompt_filename: str
    prompt_version: str
    schema_version: str
    generation_config: LLMGenerationConfig = Field(
        default_factory=LLMGenerationConfig
    )


class LLMRuntimeInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_name: LLMTaskName
    provider: str | None = None
    model_name: str | None = None
    llm_size: LLMSize
    prompt_filename: str
    prompt_version: str
    schema_version: str
    temperature: float
    max_retries: int
    structured_output: bool
    response_format: str

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_seconds: float | None = None


class ParserMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    parser_name: str = "TrialCriteriaParser"
    parser_version: str
    schema_version: str
    llm_calls: list[LLMRuntimeInfo] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Pydantic schemas: criteria structure
# -----------------------------------------------------------------------------


class ConditionalClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute: str
    normalized_attribute: str | None = None
    operator: CriterionOperator | str
    value: Any | None = None
    unit: str | None = None


class CriterionLogicNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: LogicOperator
    children: list["CriterionLogicNode"] = Field(default_factory=list)

    raw_text: str | None = None
    attribute: str | None = None
    normalized_attribute: str | None = None
    criterion_operator: CriterionOperator | str | None = None
    target_value: Any | None = None
    unit: str | None = None


class ParsedCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    nct_id: str
    type: CriterionType
    raw_text: str

    attribute: str | None = None
    normalized_attribute: str | None = None

    operator: CriterionOperator | str | None = None
    target_value: Any | None = None
    unit: str | None = None

    category: CriterionCategory | str = CriterionCategory.UNKNOWN
    hardness: CriterionHardness = CriterionHardness.UNKNOWN
    parse_status: CriterionParseStatus = CriterionParseStatus.UNSTRUCTURED

    requires_temporal_reasoning: bool = False
    requires_negation_handling: bool = False

    conditional_on: list[ConditionalClause] = Field(default_factory=list)
    logic: CriterionLogicNode | None = None

    source: CriterionSource = CriterionSource.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CriteriaSectionSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inclusion_text: str | None = None
    exclusion_text: str | None = None
    unclassified_text: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ParsedCriteriaBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    raw: str | None = None
    parsed_status: CriteriaParseStatus

    inclusion: list[ParsedCriterion] = Field(default_factory=list)
    exclusion: list[ParsedCriterion] = Field(default_factory=list)
    all_criteria: list[ParsedCriterion] = Field(default_factory=list, alias="all")

    parse_warnings: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)

    parser_metadata: ParserMetadata


class ParsedCriteriaResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nct_id: str
    criteria: ParsedCriteriaBlock


# -----------------------------------------------------------------------------
# Pydantic schemas: LLM response
# -----------------------------------------------------------------------------


class LLMParsedCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str

    attribute: str | None = None
    operator: CriterionOperator | str | None = None
    target_value: Any | None = None
    unit: str | None = None

    category: CriterionCategory | str = CriterionCategory.UNKNOWN
    parse_status: CriterionParseStatus = CriterionParseStatus.UNSTRUCTURED

    requires_temporal_reasoning: bool = False
    requires_negation_handling: bool = False

    conditional_on: list[ConditionalClause] = Field(default_factory=list)
    logic: CriterionLogicNode | None = None

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class LLMParsedCriteriaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[LLMParsedCriterion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class HardnessClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hardness: CriterionHardness
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str | None = None


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------


class TrialCriteriaParserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_version: str = "trial_criteria_parser_v1"
    schema_version: str = "trial_criteria_schema_v1"

    inclusion_llm: LLMTaskConfig = Field(
        default_factory=lambda: LLMTaskConfig(
            task_name=LLMTaskName.PARSE_INCLUSION_CRITERIA,
            llm_size=LLMSize.SMALL,
            prompt_filename="criteria_parser_inclusion.md",
            prompt_version="criteria_parser_inclusion_v1",
            schema_version="trial_criteria_schema_v1",
        )
    )

    exclusion_llm: LLMTaskConfig = Field(
        default_factory=lambda: LLMTaskConfig(
            task_name=LLMTaskName.PARSE_EXCLUSION_CRITERIA,
            llm_size=LLMSize.SMALL,
            prompt_filename="criteria_parser_exclusion.md",
            prompt_version="criteria_parser_exclusion_v1",
            schema_version="trial_criteria_schema_v1",
        )
    )

    hardness_llm: LLMTaskConfig = Field(
        default_factory=lambda: LLMTaskConfig(
            task_name=LLMTaskName.DETECT_UNKNOWN_HARDNESS,
            llm_size=LLMSize.SMALL,
            prompt_filename="criteria_hardness_classifier.md",
            prompt_version="criteria_hardness_classifier_v1",
            schema_version="trial_criteria_schema_v1",
        )
    )

    enable_hardness_llm: bool = False


# -----------------------------------------------------------------------------
# TrialCriteriaParser class
# -----------------------------------------------------------------------------


class TrialCriteriaParser:
    config: TrialCriteriaParserConfig

    inclusion_llm: LLMClient
    exclusion_llm: LLMClient
    hardness_llm: LLMClient | None

    inclusion_system_prompt: str
    exclusion_system_prompt: str
    hardness_system_prompt: str

    logger: Any | None
    normalizer: Any | None

    category_keywords: dict[str, list[str]]
    temporal_keywords: list[str]
    negation_keywords: list[str]

    def __init__(
        self,
        config: TrialCriteriaParserConfig | None = None,
        inclusion_llm: LLMClient | None = None,
        exclusion_llm: LLMClient | None = None,
        hardness_llm: LLMClient | None = None,
        logger: Any | None = None,
        normalizer: Any | None = None,
    ) -> None:
        self.config = config or TrialCriteriaParserConfig()

        self.inclusion_llm = inclusion_llm or create_llm(
            self.config.inclusion_llm.llm_size
        )
        self.exclusion_llm = exclusion_llm or create_llm(
            self.config.exclusion_llm.llm_size
        )

        if self.config.enable_hardness_llm:
            self.hardness_llm = hardness_llm or create_llm(
                self.config.hardness_llm.llm_size
            )
        else:
            self.hardness_llm = hardness_llm

        self.inclusion_system_prompt = self._load_prompt_or_default(
            self.config.inclusion_llm.prompt_filename,
            self._default_inclusion_prompt(),
        )
        self.exclusion_system_prompt = self._load_prompt_or_default(
            self.config.exclusion_llm.prompt_filename,
            self._default_exclusion_prompt(),
        )
        self.hardness_system_prompt = self._load_prompt_or_default(
            self.config.hardness_llm.prompt_filename,
            self._default_hardness_prompt(),
        )

        self.logger = logger
        self.normalizer = normalizer

        self.category_keywords = self._default_category_keywords()

        self.temporal_keywords = [
            "within",
            "for at least",
            "after",
            "before",
            "prior to",
            "previous",
            "previously",
            "recent",
            "recently",
            "since",
            "during",
            "ongoing",
            "current",
            "history of",
            "days",
            "weeks",
            "months",
            "years",
            "line of therapy",
            "progression after",
            "not responding",
        ]

        self.negation_keywords = [
            "no",
            "not",
            "without",
            "absence of",
            "negative for",
            "must not",
            "unable",
            "excludes",
            "excluded",
            "no evidence of",
            "free of",
            "lack of",
        ]

        self._llm_runtime_buffer: list[LLMRuntimeInfo] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_patient_candidate_file(
        self,
        candidate_json: dict[str, Any],
    ) -> dict[str, Any]:
        output = copy.deepcopy(candidate_json)
        unique_studies = output.get("unique_studies")

        if unique_studies is None:
            output.setdefault("warnings", []).append(
                "TrialCriteriaParser: input JSON does not contain `unique_studies`."
            )
            return output

        if not isinstance(unique_studies, list):
            output.setdefault("errors", []).append(
                "TrialCriteriaParser: `unique_studies` must be a list."
            )
            return output

        output["unique_studies"] = self.parse_trials(unique_studies)
        return output

    def parse_trials(
        self,
        unique_studies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        parsed_studies: list[dict[str, Any]] = []
        total_ensayos = len(unique_studies)

        for index, study in enumerate(unique_studies):
            if not isinstance(study, dict):
                parsed_studies.append(
                    self._build_invalid_study_result(
                        index=index,
                        error="Study item is not a dictionary.",
                    )
                )
                continue

            nct_id = study.get("nct_id") or study.get("trial", {}).get("nct_id") or "Desconocido"
            print(f"       [M8-LLM] Parseando ensayo {index + 1}/{total_ensayos} ({nct_id})...")

            parsed_studies.append(self.parse_trial(study))



        return parsed_studies

    def parse_trial(
        self,
        study: dict[str, Any],
    ) -> dict[str, Any]:
        output = copy.deepcopy(study)

        nct_id = str(
            output.get("nct_id")
            or output.get("trial", {}).get("nct_id")
            or "unknown_nct"
        )

        raw_criteria = self._get_raw_criteria(output)

        try:
            parsed_result = self.parse_raw_criteria(raw_criteria, nct_id)
        except Exception as exc:
            self._log_error(f"TrialCriteriaParser: parse failed for {nct_id}: {exc}")
            parsed_result = self._build_empty_criteria_result(
                nct_id=nct_id,
                raw_criteria=raw_criteria,
                status=CriteriaParseStatus.PARSE_FAILED,
                errors=[str(exc)],
            )

        output["criteria"] = parsed_result.criteria.model_dump(
            mode="json",
            by_alias=True,
        )

        return output

    def parse_raw_criteria(
        self,
        raw_criteria: str | None,
        nct_id: str,
    ) -> ParsedCriteriaResult:
        if raw_criteria is None or not str(raw_criteria).strip():
            return self._build_empty_criteria_result(
                nct_id=nct_id,
                raw_criteria=raw_criteria,
                status=CriteriaParseStatus.NO_CRITERIA_AVAILABLE,
                warnings=["No raw eligibility criteria available."],
            )

        raw_criteria = self._normalize_whitespace(raw_criteria)

        section_split = self._split_sections(raw_criteria)
        warnings = list(section_split.warnings)
        errors = list(section_split.errors)

        inclusion_items = self._split_items(section_split.inclusion_text)
        exclusion_items = self._split_items(section_split.exclusion_text)

        if not inclusion_items and not exclusion_items and section_split.unclassified_text:
            warnings.append(
                "Could not identify inclusion/exclusion sections. "
                "Unclassified criteria were preserved as unstructured inclusion-like criteria."
            )
            inclusion_items = self._split_items(section_split.unclassified_text)

        self._llm_runtime_buffer = []
        llm_calls: list[LLMRuntimeInfo] = []

        inclusion_response = LLMParsedCriteriaResponse()
        exclusion_response = LLMParsedCriteriaResponse()

        if inclusion_items:
            inclusion_response, inclusion_info = self._parse_inclusion_with_llm(
                inclusion_items,
                nct_id,
            )
            if inclusion_info is not None:
                llm_calls.append(inclusion_info)

            warnings.extend(inclusion_response.warnings)
            errors.extend(inclusion_response.errors)

        if exclusion_items:
            exclusion_response, exclusion_info = self._parse_exclusion_with_llm(
                exclusion_items,
                nct_id,
            )
            if exclusion_info is not None:
                llm_calls.append(exclusion_info)

            warnings.extend(exclusion_response.warnings)
            errors.extend(exclusion_response.errors)

        if inclusion_items and not inclusion_response.criteria:
            warnings.append(
                "Inclusion LLM parsing returned no criteria; using unstructured fallback."
            )
            inclusion = self._build_unstructured_criteria(
                inclusion_items,
                nct_id,
                CriterionType.INCLUSION,
                reason="inclusion_llm_empty_or_failed",
            )
        else:
            inclusion = self._assemble_parsed_criteria(
                inclusion_response.criteria,
                inclusion_items,
                nct_id,
                CriterionType.INCLUSION,
            )

        if exclusion_items and not exclusion_response.criteria:
            warnings.append(
                "Exclusion LLM parsing returned no criteria; using unstructured fallback."
            )
            exclusion = self._build_unstructured_criteria(
                exclusion_items,
                nct_id,
                CriterionType.EXCLUSION,
                reason="exclusion_llm_empty_or_failed",
            )
        else:
            exclusion = self._assemble_parsed_criteria(
                exclusion_response.criteria,
                exclusion_items,
                nct_id,
                CriterionType.EXCLUSION,
            )

        llm_calls.extend(self._llm_runtime_buffer)

        status = self._infer_block_status(
            inclusion=inclusion,
            exclusion=exclusion,
            errors=errors,
        )

        result = self._build_parsed_criteria_result(
            nct_id=nct_id,
            raw_criteria=raw_criteria,
            inclusion=inclusion,
            exclusion=exclusion,
            status=status,
            warnings=warnings,
            errors=errors,
            llm_calls=llm_calls,
        )

        return self._validate_result(result)

    # ------------------------------------------------------------------
    # Raw criteria extraction and text splitting
    # ------------------------------------------------------------------

    def _get_raw_criteria(
        self,
        study: dict[str, Any],
    ) -> str | None:
        candidates = [
            self._safe_get(study, ["criteria", "raw"]),
            self._safe_get(study, ["trial", "criteria", "raw"]),
            self._safe_get(study, ["trial", "eligibility", "raw_criteria"]),
        ]

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return None

    def _split_sections(
        self,
        raw_criteria: str,
    ) -> CriteriaSectionSplit:
        text = self._normalize_whitespace(raw_criteria)

        if not text:
            return CriteriaSectionSplit(
                warnings=["Raw criteria text is empty after whitespace normalization."]
            )

        heading_pattern = re.compile(
            r"(?im)^\s*(?:#+\s*)?"
            r"(?P<label>"
            r"(?:key\s+)?inclusion(?:\s+criteria)?|"
            r"(?:main\s+)?inclusion(?:\s+criteria)?|"
            r"(?:principal\s+)?inclusion(?:\s+criteria)?|"
            r"(?:key\s+)?exclusion(?:\s+criteria)?|"
            r"(?:main\s+)?exclusion(?:\s+criteria)?|"
            r"(?:major\s+)?exclusion(?:\s+criteria)?|"
            r"inclusions?|exclusions?"
            r")"
            r"\s*:?\s*",
        )

        matches = list(heading_pattern.finditer(text))

        if not matches:
            return CriteriaSectionSplit(
                unclassified_text=text,
                warnings=["No explicit inclusion/exclusion headings found."],
            )

        inclusion_chunks: list[str] = []
        exclusion_chunks: list[str] = []
        unclassified_chunks: list[str] = []

        first_heading_start = matches[0].start()

        if first_heading_start > 0:
            prefix = text[:first_heading_start].strip()
            if prefix:
                unclassified_chunks.append(prefix)

        for index, match in enumerate(matches):
            section_start = match.end()
            section_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(text)
            )

            section_text = text[section_start:section_end].strip()

            if not section_text:
                continue

            label = match.group("label").lower()

            if "exclusion" in label:
                exclusion_chunks.append(section_text)
            elif "inclusion" in label:
                inclusion_chunks.append(section_text)
            else:
                unclassified_chunks.append(section_text)

        warnings: list[str] = []

        if not inclusion_chunks:
            warnings.append("No inclusion criteria section found.")

        if not exclusion_chunks:
            warnings.append("No exclusion criteria section found.")

        return CriteriaSectionSplit(
            inclusion_text="\n\n".join(inclusion_chunks).strip() or None,
            exclusion_text="\n\n".join(exclusion_chunks).strip() or None,
            unclassified_text="\n\n".join(unclassified_chunks).strip() or None,
            warnings=warnings,
        )

    def _split_items(
        self,
        section_text: str | None,
    ) -> list[str]:
        if section_text is None or not section_text.strip():
            return []

        text = self._normalize_whitespace(section_text)
        lines = text.splitlines()

        bullet_pattern = re.compile(
            r"^(?P<indent>\s*)(?P<marker>\d+[\.)]|[-*•])\s+(?P<body>.+?)\s*$"
        )

        items: list[str] = []
        current: list[str] = []
        saw_top_level_bullet = False

        for raw_line in lines:
            line = raw_line.rstrip()

            if not line.strip():
                if current:
                    current.append("")
                continue

            match = bullet_pattern.match(line)

            if match:
                indent = len(match.group("indent").replace("\t", "    "))
                marker = match.group("marker")
                body = match.group("body").strip()
                is_numbered = bool(re.match(r"^\d+[\.)]$", marker))
                is_top_level = is_numbered or indent <= 1

                if is_top_level:
                    saw_top_level_bullet = True

                    if current:
                        item = self._clean_item_text("\n".join(current))
                        if item:
                            items.append(item)

                    current = [body]
                else:
                    current.append(line.strip())

                continue

            if current:
                current.append(line.strip())
            else:
                current = [line.strip()]

        if current:
            item = self._clean_item_text("\n".join(current))
            if item:
                items.append(item)

        if saw_top_level_bullet:
            return items

        paragraphs = [
            self._clean_item_text(paragraph)
            for paragraph in re.split(r"\n\s*\n", text)
            if paragraph.strip()
        ]

        if len(paragraphs) > 1:
            return paragraphs

        non_empty_lines = [
            self._clean_item_text(line)
            for line in lines
            if line.strip()
        ]

        if len(non_empty_lines) > 1:
            return non_empty_lines

        return [self._clean_item_text(text)] if text.strip() else []

    # ------------------------------------------------------------------
    # LLM parsing
    # ------------------------------------------------------------------

    def _parse_inclusion_with_llm(
        self,
        inclusion_items: list[str],
        nct_id: str,
    ) -> tuple[LLMParsedCriteriaResponse, LLMRuntimeInfo | None]:
        if not inclusion_items:
            return LLMParsedCriteriaResponse(), None

        payload = self._build_llm_payload(
            criteria_items=inclusion_items,
            nct_id=nct_id,
            criterion_type=CriterionType.INCLUSION,
        )

        return self._call_llm_and_parse_json(
            llm=self.inclusion_llm,
            system_prompt=self.inclusion_system_prompt,
            payload=payload,
            task_config=self.config.inclusion_llm,
        )

    def _parse_exclusion_with_llm(
        self,
        exclusion_items: list[str],
        nct_id: str,
    ) -> tuple[LLMParsedCriteriaResponse, LLMRuntimeInfo | None]:
        if not exclusion_items:
            return LLMParsedCriteriaResponse(), None

        payload = self._build_llm_payload(
            criteria_items=exclusion_items,
            nct_id=nct_id,
            criterion_type=CriterionType.EXCLUSION,
        )

        return self._call_llm_and_parse_json(
            llm=self.exclusion_llm,
            system_prompt=self.exclusion_system_prompt,
            payload=payload,
            task_config=self.config.exclusion_llm,
        )

    def _build_llm_payload(
        self,
        criteria_items: list[str],
        nct_id: str,
        criterion_type: CriterionType,
    ) -> dict[str, Any]:
        return {
            "nct_id": nct_id,
            "criterion_type": criterion_type.value,
            "instructions": {
                "do_not_evaluate_patient": True,
                "do_not_generate_criterion_id": True,
                "do_not_generate_nct_id": True,
                "do_not_generate_type": True,
                "preserve_raw_text": True,
                "one_output_object_per_input_item": True,
                "keep_same_order_as_input": True,
                "return_json_only": True,
                "exclusion_polarity_rule": (
                    "For exclusion criteria, represent what activates the exclusion. "
                    "Do not invert the criterion into a favorable patient state."
                ),
            },
            "allowed_categories": [
                category.value for category in CriterionCategory
            ],
            "allowed_parse_statuses": [
                status.value for status in CriterionParseStatus
            ],
            "allowed_operators": [
                operator.value for operator in CriterionOperator
            ],
            "expected_response_schema": {
                "criteria": [
                    {
                        "raw_text": "string, exactly matching the input item if possible",
                        "attribute": "string|null",
                        "operator": "one of allowed_operators|string|null",
                        "target_value": "any|null",
                        "unit": "string|null",
                        "category": "one of allowed_categories|string",
                        "parse_status": "one of allowed_parse_statuses",
                        "requires_temporal_reasoning": "boolean",
                        "requires_negation_handling": "boolean",
                        "conditional_on": [],
                        "logic": None,
                        "confidence": "float between 0 and 1",
                        "warnings": [],
                        "errors": [],
                    }
                ],
                "warnings": [],
                "errors": [],
            },
            "criteria_items": criteria_items,
        }

    def _call_llm_and_parse_json(
        self,
        llm: LLMClient,
        system_prompt: str,
        payload: dict[str, Any],
        task_config: LLMTaskConfig,
    ) -> tuple[LLMParsedCriteriaResponse, LLMRuntimeInfo]:
        start = time.perf_counter()
        attempts = max(1, task_config.generation_config.max_retries + 1)
        last_error: str | None = None
        last_response_obj: Any = None

        user_prompt = self._build_user_prompt(payload)

        for _attempt in range(attempts):
            try:
                response_obj = self._invoke_llm(
                    llm=llm,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    task_config=task_config,
                )

                last_response_obj = response_obj

                parsed_data = self._coerce_llm_response_to_json(response_obj)
                parsed_data = self._normalize_llm_criteria_response_data(parsed_data)
                response = LLMParsedCriteriaResponse.model_validate(parsed_data)

                latency = time.perf_counter() - start
                usage = self._extract_usage(response_obj)

                runtime_info = self._build_llm_runtime_info(
                    task_config=task_config,
                    llm=llm,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    latency_seconds=latency,
                )

                return response, runtime_info

            except Exception as exc:
                last_error = str(exc)
                continue

        latency = time.perf_counter() - start
        usage = self._extract_usage(last_response_obj)

        runtime_info = self._build_llm_runtime_info(
            task_config=task_config,
            llm=llm,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_seconds=latency,
        )

        return (
            LLMParsedCriteriaResponse(
                criteria=[],
                warnings=[],
                errors=[last_error or "Unknown LLM parsing error."],
            ),
            runtime_info,
        )

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def _assemble_parsed_criteria(
        self,
        llm_criteria: list[LLMParsedCriterion],
        original_items: list[str],
        nct_id: str,
        criterion_type: CriterionType,
        start_index: int = 1,
    ) -> list[ParsedCriterion]:
        assembled: list[ParsedCriterion] = []
        max_len = max(len(original_items), len(llm_criteria))

        for offset in range(max_len):
            index = start_index + offset
            original_text = (
                original_items[offset]
                if offset < len(original_items)
                else None
            )
            llm_item = (
                llm_criteria[offset]
                if offset < len(llm_criteria)
                else None
            )

            if llm_item is None:
                fallback_text = original_text or ""
                assembled.extend(
                    self._build_unstructured_criteria(
                        [fallback_text],
                        nct_id=nct_id,
                        criterion_type=criterion_type,
                        start_index=index,
                        reason="missing_llm_item_for_original_criterion",
                    )
                )
                continue

            raw_text = original_text or llm_item.raw_text
            warnings = list(llm_item.warnings)
            errors = list(llm_item.errors)

            if original_text is None:
                warnings.append(
                    "LLM returned an extra criterion not aligned with original input items."
                )
            elif llm_item.raw_text.strip() != original_text.strip():
                warnings.append(
                    "LLM raw_text differed from original item; original item was preserved."
                )

            category = self._normalize_category(llm_item.category)

            if category in {CriterionCategory.UNKNOWN, "unknown", None}:
                category = self._detect_category(raw_text)

            parse_status = self._normalize_parse_status(llm_item.parse_status)

            temporal = (
                bool(llm_item.requires_temporal_reasoning)
                or self._requires_temporal_reasoning(raw_text)
            )
            negation = (
                bool(llm_item.requires_negation_handling)
                or self._requires_negation_handling(raw_text)
            )

            criterion = ParsedCriterion(
                criterion_id=self._make_criterion_id(
                    nct_id,
                    criterion_type,
                    index,
                ),
                nct_id=nct_id,
                type=criterion_type,
                raw_text=raw_text,
                attribute=llm_item.attribute,
                normalized_attribute=None,
                operator=self._normalize_operator(llm_item.operator),
                target_value=llm_item.target_value,
                unit=llm_item.unit,
                category=category,
                hardness=CriterionHardness.UNKNOWN,
                parse_status=parse_status,
                requires_temporal_reasoning=temporal,
                requires_negation_handling=negation,
                conditional_on=llm_item.conditional_on,
                logic=llm_item.logic,
                source=CriterionSource.LLM,
                confidence=llm_item.confidence,
                warnings=warnings,
                errors=errors,
            )

            criterion = self._apply_attribute_normalizer(criterion)

            hardness, runtime_info = self._detect_hardness(criterion)
            criterion.hardness = hardness

            if runtime_info is not None:
                self._llm_runtime_buffer.append(runtime_info)

            assembled.append(self._validate_criterion(criterion))

        return assembled

    def _make_criterion_id(
        self,
        nct_id: str,
        criterion_type: CriterionType,
        index: int,
    ) -> str:
        prefix = "inc" if criterion_type == CriterionType.INCLUSION else "exc"
        safe_nct_id = re.sub(r"[^A-Za-z0-9_-]", "_", nct_id.strip()) or "unknown_nct"
        return f"{safe_nct_id}_{prefix}_{index:03d}"

    def _build_unstructured_criteria(
        self,
        items: list[str],
        nct_id: str,
        criterion_type: CriterionType,
        start_index: int = 1,
        reason: str | None = None,
    ) -> list[ParsedCriterion]:
        criteria: list[ParsedCriterion] = []

        for offset, item in enumerate(items):
            raw_text = self._clean_item_text(item)

            if not raw_text:
                continue

            category = self._detect_category(raw_text)

            criterion = ParsedCriterion(
                criterion_id=self._make_criterion_id(
                    nct_id,
                    criterion_type,
                    start_index + offset,
                ),
                nct_id=nct_id,
                type=criterion_type,
                raw_text=raw_text,
                attribute=None,
                normalized_attribute=None,
                operator=None,
                target_value=None,
                unit=None,
                category=category,
                hardness=CriterionHardness.UNKNOWN,
                parse_status=CriterionParseStatus.UNSTRUCTURED,
                requires_temporal_reasoning=self._requires_temporal_reasoning(raw_text),
                requires_negation_handling=self._requires_negation_handling(raw_text),
                conditional_on=[],
                logic=None,
                source=CriterionSource.RULES,
                confidence=0.0,
                warnings=[reason] if reason else [],
                errors=[],
            )

            hardness, runtime_info = self._detect_hardness(criterion)
            criterion.hardness = hardness

            if runtime_info is not None:
                self._llm_runtime_buffer.append(runtime_info)

            criteria.append(self._validate_criterion(criterion))

        return criteria

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _apply_attribute_normalizer(
        self,
        criterion: ParsedCriterion,
    ) -> ParsedCriterion:
        if self.normalizer is None or not criterion.attribute:
            return criterion

        try:
            normalize_fn = None

            if hasattr(self.normalizer, "normalize_attribute"):
                normalize_fn = self.normalizer.normalize_attribute
            elif hasattr(self.normalizer, "normalize"):
                normalize_fn = self.normalizer.normalize
            elif callable(self.normalizer):
                normalize_fn = self.normalizer

            if normalize_fn is None:
                criterion.warnings.append(
                    "Normalizer provided but no normalize_attribute/normalize/callable interface found."
                )
                return criterion

            normalized = normalize_fn(criterion.attribute)
            normalized_value = self._extract_normalized_attribute_value(normalized)

            if normalized_value:
                criterion.normalized_attribute = normalized_value

        except Exception as exc:
            criterion.warnings.append(f"Attribute normalizer failed: {exc}")

        return criterion

    def _normalize_operator(
        self,
        operator: Any,
    ) -> CriterionOperator | str | None:
        if operator is None:
            return None

        if isinstance(operator, CriterionOperator):
            return operator

        raw = str(operator).strip()

        if not raw:
            return None

        for candidate in CriterionOperator:
            if raw == candidate.value:
                return candidate

        normalized = raw.lower().strip().replace(" ", "_").replace("-", "_")

        mapping: dict[str, CriterionOperator] = {
            "==": CriterionOperator.EQUALS,
            "=": CriterionOperator.EQUALS,
            "eq": CriterionOperator.EQUALS,
            "equals": CriterionOperator.EQUALS,
            "equal": CriterionOperator.EQUALS,
            "is": CriterionOperator.EQUALS,
            "!=": CriterionOperator.NOT_EQUALS,
            "ne": CriterionOperator.NOT_EQUALS,
            "neq": CriterionOperator.NOT_EQUALS,
            "not_equals": CriterionOperator.NOT_EQUALS,
            "not_equal": CriterionOperator.NOT_EQUALS,
            ">": CriterionOperator.GREATER_THAN,
            "gt": CriterionOperator.GREATER_THAN,
            "greater_than": CriterionOperator.GREATER_THAN,
            "more_than": CriterionOperator.GREATER_THAN,
            "<": CriterionOperator.LESS_THAN,
            "lt": CriterionOperator.LESS_THAN,
            "less_than": CriterionOperator.LESS_THAN,
            ">=": CriterionOperator.GREATER_OR_EQUAL,
            "gte": CriterionOperator.GREATER_OR_EQUAL,
            "ge": CriterionOperator.GREATER_OR_EQUAL,
            "gteq": CriterionOperator.GREATER_OR_EQUAL,
            "geq": CriterionOperator.GREATER_OR_EQUAL,
            "greater_or_equal": CriterionOperator.GREATER_OR_EQUAL,
            "greater_than_or_equal": CriterionOperator.GREATER_OR_EQUAL,
            "at_least": CriterionOperator.GREATER_OR_EQUAL,
            "minimum": CriterionOperator.GREATER_OR_EQUAL,
            "min": CriterionOperator.GREATER_OR_EQUAL,
            "<=": CriterionOperator.LESS_OR_EQUAL,
            "lte": CriterionOperator.LESS_OR_EQUAL,
            "le": CriterionOperator.LESS_OR_EQUAL,
            "lteq": CriterionOperator.LESS_OR_EQUAL,
            "leq": CriterionOperator.LESS_OR_EQUAL,
            "less_or_equal": CriterionOperator.LESS_OR_EQUAL,
            "less_than_or_equal": CriterionOperator.LESS_OR_EQUAL,
            "at_most": CriterionOperator.LESS_OR_EQUAL,
            "maximum": CriterionOperator.LESS_OR_EQUAL,
            "max": CriterionOperator.LESS_OR_EQUAL,
            "in": CriterionOperator.IN,
            "inside": CriterionOperator.IN,
            "one_of": CriterionOperator.IN,
            "one_of_values": CriterionOperator.IN,
            "not_in": CriterionOperator.NOT_IN,
            "not_in_values": CriterionOperator.NOT_IN,
            "not_one_of": CriterionOperator.NOT_IN,
            "is_true": CriterionOperator.IS_TRUE,
            "true": CriterionOperator.IS_TRUE,
            "is_yes": CriterionOperator.IS_TRUE,
            "yes": CriterionOperator.IS_TRUE,
            "is_false": CriterionOperator.IS_FALSE,
            "false": CriterionOperator.IS_FALSE,
            "is_no": CriterionOperator.IS_FALSE,
            "no": CriterionOperator.IS_FALSE,
            "is_present": CriterionOperator.IS_PRESENT,
            "present": CriterionOperator.IS_PRESENT,
            "presence": CriterionOperator.IS_PRESENT,
            "has": CriterionOperator.IS_PRESENT,
            "is_absent": CriterionOperator.IS_ABSENT,
            "absent": CriterionOperator.IS_ABSENT,
            "absence": CriterionOperator.IS_ABSENT,
            "does_not_have": CriterionOperator.IS_ABSENT,
            "any_of": CriterionOperator.ANY_OF,
            "any": CriterionOperator.ANY_OF,
            "or": CriterionOperator.ANY_OF,
            "all_of": CriterionOperator.ALL_OF,
            "all": CriterionOperator.ALL_OF,
            "and": CriterionOperator.ALL_OF,
            "not_applicable_if": CriterionOperator.NOT_APPLICABLE_IF,
            "unknown": CriterionOperator.UNKNOWN,
        }

        return mapping.get(normalized, raw)

    def _normalize_category(
        self,
        category: Any,
    ) -> CriterionCategory | str:
        if category is None:
            return CriterionCategory.UNKNOWN

        if isinstance(category, CriterionCategory):
            return category

        raw = str(category).strip()

        if not raw:
            return CriterionCategory.UNKNOWN

        normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")

        mapping: dict[str, CriterionCategory] = {
            "demographic": CriterionCategory.DEMOGRAPHIC,
            "demographics": CriterionCategory.DEMOGRAPHIC,
            "age": CriterionCategory.DEMOGRAPHIC,
            "sex": CriterionCategory.DEMOGRAPHIC,
            "gender": CriterionCategory.DEMOGRAPHIC,
            "functional_status": CriterionCategory.FUNCTIONAL_STATUS,
            "performance_status": CriterionCategory.FUNCTIONAL_STATUS,
            "ecog": CriterionCategory.FUNCTIONAL_STATUS,
            "kps": CriterionCategory.FUNCTIONAL_STATUS,
            "karnofsky": CriterionCategory.FUNCTIONAL_STATUS,
            "disease": CriterionCategory.DISEASE_STATUS,
            "disease_status": CriterionCategory.DISEASE_STATUS,
            "clinical_status": CriterionCategory.DISEASE_STATUS,
            "diagnosis": CriterionCategory.DISEASE_STATUS,
            "condition": CriterionCategory.DISEASE_STATUS,
            "prior_treatment": CriterionCategory.PRIOR_TREATMENT,
            "previous_treatment": CriterionCategory.PRIOR_TREATMENT,
            "prior_therapy": CriterionCategory.PRIOR_TREATMENT,
            "current_treatment": CriterionCategory.CURRENT_TREATMENT,
            "ongoing_treatment": CriterionCategory.CURRENT_TREATMENT,
            "lab": CriterionCategory.LABORATORY,
            "labs": CriterionCategory.LABORATORY,
            "laboratory": CriterionCategory.LABORATORY,
            "biomarker": CriterionCategory.BIOMARKER,
            "molecular": CriterionCategory.BIOMARKER,
            "genomic": CriterionCategory.BIOMARKER,
            "imaging": CriterionCategory.IMAGING,
            "radiology": CriterionCategory.IMAGING,
            "comorbidity": CriterionCategory.COMORBIDITY,
            "comorbidities": CriterionCategory.COMORBIDITY,
            "medical_history": CriterionCategory.COMORBIDITY,
            "infection": CriterionCategory.INFECTION,
            "infectious": CriterionCategory.INFECTION,
            "reproductive": CriterionCategory.REPRODUCTIVE,
            "pregnancy": CriterionCategory.REPRODUCTIVE,
            "administrative": CriterionCategory.ADMINISTRATIVE,
            "admin": CriterionCategory.ADMINISTRATIVE,
            "consent": CriterionCategory.ADMINISTRATIVE,
            "logistical": CriterionCategory.LOGISTICAL,
            "logistics": CriterionCategory.LOGISTICAL,
            "location": CriterionCategory.LOGISTICAL,
            "other": CriterionCategory.OTHER,
            "unknown": CriterionCategory.UNKNOWN,
        }

        return mapping.get(normalized, raw)

    def _normalize_parse_status(
        self,
        parse_status: Any,
    ) -> CriterionParseStatus:
        if parse_status is None:
            return CriterionParseStatus.UNSTRUCTURED

        if isinstance(parse_status, CriterionParseStatus):
            return parse_status

        raw = str(parse_status).strip()

        if not raw:
            return CriterionParseStatus.UNSTRUCTURED

        normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")

        mapping: dict[str, CriterionParseStatus] = {
            "parsed": CriterionParseStatus.PARSED,
            "structured": CriterionParseStatus.PARSED,
            "fully_parsed": CriterionParseStatus.PARSED,
            "partial": CriterionParseStatus.PARTIALLY_PARSED,
            "partially_parsed": CriterionParseStatus.PARTIALLY_PARSED,
            "unstructured": CriterionParseStatus.UNSTRUCTURED,
            "raw": CriterionParseStatus.UNSTRUCTURED,
            "compound": CriterionParseStatus.COMPOUND_UNRESOLVED,
            "compound_unresolved": CriterionParseStatus.COMPOUND_UNRESOLVED,
            "temporal": CriterionParseStatus.TEMPORAL_COMPLEX,
            "temporal_complex": CriterionParseStatus.TEMPORAL_COMPLEX,
            "negation_sensitive": CriterionParseStatus.NEGATION_SENSITIVE,
            "parse_failed": CriterionParseStatus.PARSE_FAILED,
            "failed": CriterionParseStatus.PARSE_FAILED,
            "error": CriterionParseStatus.PARSE_FAILED,
        }

        return mapping.get(normalized, CriterionParseStatus.UNSTRUCTURED)

    # ------------------------------------------------------------------
    # Hardness detection
    # ------------------------------------------------------------------

    def _detect_hardness(
        self,
        criterion: ParsedCriterion,
    ) -> tuple[CriterionHardness, LLMRuntimeInfo | None]:
        heuristic_value = self._detect_hardness_with_heuristic(criterion)

        if heuristic_value != CriterionHardness.UNKNOWN:
            return heuristic_value, None

        if not self.config.enable_hardness_llm:
            return CriterionHardness.UNKNOWN, None

        return self._detect_unknown_hardness_with_llm(criterion)

    def _detect_hardness_with_heuristic(
        self,
        criterion: ParsedCriterion,
    ) -> CriterionHardness:
        text = criterion.raw_text.lower()
        category = criterion.category

        if isinstance(category, str):
            category_value = category
        else:
            category_value = category.value

        if criterion.parse_status == CriterionParseStatus.PARSE_FAILED:
            return CriterionHardness.UNKNOWN

        if category_value in {
            CriterionCategory.ADMINISTRATIVE.value,
            CriterionCategory.LOGISTICAL.value,
        }:
            return CriterionHardness.SOFT

        soft_patterns = [
            "informed consent",
            "willing",
            "willingness",
            "agree",
            "agreed",
            "able to comply",
            "comply with",
            "study procedures",
            "protocol requirements",
            "available for follow-up",
            "contraception",
            "birth control",
        ]

        if any(pattern in text for pattern in soft_patterns):
            if "pregnant" not in text and "pregnancy" not in text:
                return CriterionHardness.SOFT

        hard_categories = {
            CriterionCategory.DEMOGRAPHIC.value,
            CriterionCategory.FUNCTIONAL_STATUS.value,
            CriterionCategory.DISEASE_STATUS.value,
            CriterionCategory.PRIOR_TREATMENT.value,
            CriterionCategory.CURRENT_TREATMENT.value,
            CriterionCategory.LABORATORY.value,
            CriterionCategory.BIOMARKER.value,
            CriterionCategory.IMAGING.value,
            CriterionCategory.COMORBIDITY.value,
            CriterionCategory.INFECTION.value,
            CriterionCategory.REPRODUCTIVE.value,
        }

        if category_value in hard_categories:
            return CriterionHardness.HARD

        hard_patterns = [
            "age",
            "years old",
            "ecog",
            "performance status",
            "karnofsky",
            "kps",
            "diagnosis",
            "histologically",
            "confirmed",
            "stage",
            "metastatic",
            "metastases",
            "measurable disease",
            "progression",
            "refractory",
            "relapsed",
            "recurrent",
            "prior therapy",
            "prior treatment",
            "chemotherapy",
            "radiotherapy",
            "surgery",
            "infection",
            "organ function",
            "creatinine",
            "bilirubin",
            "platelet",
            "hemoglobin",
            "neutrophil",
            "pregnant",
            "pregnancy",
            "hiv",
            "hepatitis",
        ]

        if any(pattern in text for pattern in hard_patterns):
            return CriterionHardness.HARD

        if criterion.attribute or criterion.operator or criterion.target_value is not None:
            return CriterionHardness.HARD

        return CriterionHardness.UNKNOWN

    def _detect_unknown_hardness_with_llm(
        self,
        criterion: ParsedCriterion,
    ) -> tuple[CriterionHardness, LLMRuntimeInfo | None]:
        if self.hardness_llm is None:
            criterion.warnings.append(
                "Hardness LLM was enabled but no hardness_llm client is available."
            )
            return CriterionHardness.UNKNOWN, None

        payload = {
            "task": "classify_criterion_hardness",
            "allowed_values": [value.value for value in CriterionHardness],
            "criterion": criterion.model_dump(mode="json", by_alias=True),
            "guidance": {
                "hard": (
                    "objective clinical/demographic/lab/diagnostic criteria "
                    "that can rule eligibility in or out"
                ),
                "soft": (
                    "administrative, logistical, willingness, consent, "
                    "or procedural criteria"
                ),
                "unknown": "not enough information to classify",
            },
            "expected_response_schema": {
                "hardness": "hard|soft|unknown",
                "confidence": "float between 0 and 1",
                "rationale": "string|null",
            },
        }

        user_prompt = self._build_user_prompt(payload)
        start = time.perf_counter()
        response_obj: Any = None

        try:
            response_obj = self._invoke_llm(
                llm=self.hardness_llm,
                system_prompt=self.hardness_system_prompt,
                user_prompt=user_prompt,
                task_config=self.config.hardness_llm,
            )

            parsed_data = self._coerce_llm_response_to_json(response_obj)
            classification = HardnessClassificationResponse.model_validate(parsed_data)
            usage = self._extract_usage(response_obj)

            runtime_info = self._build_llm_runtime_info(
                task_config=self.config.hardness_llm,
                llm=self.hardness_llm,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                latency_seconds=time.perf_counter() - start,
            )

            if classification.rationale:
                criterion.warnings.append(
                    f"Hardness LLM rationale: {classification.rationale}"
                )

            return classification.hardness, runtime_info

        except Exception as exc:
            usage = self._extract_usage(response_obj)

            runtime_info = self._build_llm_runtime_info(
                task_config=self.config.hardness_llm,
                llm=self.hardness_llm,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                latency_seconds=time.perf_counter() - start,
            )

            criterion.warnings.append(f"Hardness LLM failed: {exc}")
            return CriterionHardness.UNKNOWN, runtime_info

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    def _detect_category(
        self,
        text: str,
    ) -> CriterionCategory:
        if not text or not text.strip():
            return CriterionCategory.UNKNOWN

        normalized_text = text.lower()

        for category_value, keywords in self.category_keywords.items():
            if any(keyword in normalized_text for keyword in keywords):
                return CriterionCategory(category_value)

        return CriterionCategory.OTHER

    def _requires_temporal_reasoning(
        self,
        text: str,
    ) -> bool:
        if not text:
            return False

        normalized_text = text.lower()

        age_patterns = [
            r"\bage\s*(?:>=|>|≤|<=|<|=)?\s*\d+",
            r"\b\d+\s+years?\s+old\b",
            r"\byears?\s+of\s+age\b",
            r"\bat\s+least\s+\d+\s+years?\s+old\b",
            r"\bsubject\s+is\s+at\s+least\s+\d+\s+years?\s+old\b",
        ]

        if any(re.search(pattern, normalized_text) for pattern in age_patterns):
            return False

        if any(keyword in normalized_text for keyword in self.temporal_keywords):
            return True

        temporal_regexes = [
            r"\bwithin\s+\d+\s+(?:day|days|week|weeks|month|months|year|years)\b",
            r"\bat\s+least\s+\d+\s+(?:day|days|week|weeks|month|months|year|years)\b",
            r"\bat\s+most\s+\d+\s+(?:day|days|week|weeks|month|months|year|years)\b",
            r"\b\d+\s*[-–]\s*\d+\s+(?:day|days|week|weeks|month|months|year|years)\b",
            r"\b(?:first|second|third|fourth|\d+)(?:st|nd|rd|th)?\s+line\b",
            r"\bprogression\s+after\b",
            r"\bfailed\s+(?:prior|previous|standard)\b",
        ]

        return any(re.search(pattern, normalized_text) for pattern in temporal_regexes)

    def _requires_negation_handling(
        self,
        text: str,
    ) -> bool:
        if not text:
            return False

        normalized_text = text.lower()

        keyword_match = any(
            re.search(rf"\b{re.escape(keyword)}\b", normalized_text)
            for keyword in self.negation_keywords
            if keyword.strip()
        )

        if keyword_match:
            return True

        negation_regexes = [
            r"\bno\s+evidence\s+of\b",
            r"\bmust\s+not\s+have\b",
            r"\bnot\s+eligible\b",
            r"\bnegative\s+for\b",
            r"\bfree\s+of\b",
        ]

        return any(re.search(pattern, normalized_text) for pattern in negation_regexes)

    # ------------------------------------------------------------------
    # Validation and assembly
    # ------------------------------------------------------------------

    def _validate_criterion(
        self,
        criterion: dict[str, Any] | ParsedCriterion,
    ) -> ParsedCriterion:
        if isinstance(criterion, ParsedCriterion):
            return ParsedCriterion.model_validate(
                criterion.model_dump(mode="python", by_alias=True)
            )

        try:
            return ParsedCriterion.model_validate(criterion)

        except ValidationError as exc:
            raw_text = (
                str(criterion.get("raw_text") or "")
                if isinstance(criterion, dict)
                else ""
            )
            nct_id = (
                str(criterion.get("nct_id") or "unknown_nct")
                if isinstance(criterion, dict)
                else "unknown_nct"
            )
            criterion_type = (
                criterion.get("type", CriterionType.INCLUSION)
                if isinstance(criterion, dict)
                else CriterionType.INCLUSION
            )

            if not isinstance(criterion_type, CriterionType):
                criterion_type = (
                    CriterionType(str(criterion_type))
                    if str(criterion_type) in {"inclusion", "exclusion"}
                    else CriterionType.INCLUSION
                )

            criterion_id = (
                str(
                    criterion.get("criterion_id")
                    or self._make_criterion_id(nct_id, criterion_type, 1)
                )
                if isinstance(criterion, dict)
                else self._make_criterion_id(nct_id, criterion_type, 1)
            )

            return ParsedCriterion(
                criterion_id=criterion_id,
                nct_id=nct_id,
                type=criterion_type,
                raw_text=raw_text,
                parse_status=CriterionParseStatus.PARSE_FAILED,
                source=CriterionSource.UNKNOWN,
                confidence=0.0,
                errors=[f"Criterion validation failed: {exc}"],
            )

    def _validate_result(
        self,
        result: ParsedCriteriaResult,
    ) -> ParsedCriteriaResult:
        all_criteria = [*result.criteria.inclusion, *result.criteria.exclusion]
        result.criteria.all_criteria = all_criteria

        return ParsedCriteriaResult.model_validate(
            result.model_dump(mode="python", by_alias=True)
        )

    def _infer_block_status(
        self,
        inclusion: list[ParsedCriterion],
        exclusion: list[ParsedCriterion],
        errors: list[str] | None = None,
    ) -> CriteriaParseStatus:
        errors = errors or []
        all_criteria = [*inclusion, *exclusion]

        if not all_criteria:
            return (
                CriteriaParseStatus.PARSE_FAILED
                if errors
                else CriteriaParseStatus.NO_CRITERIA_AVAILABLE
            )

        statuses = [criterion.parse_status for criterion in all_criteria]

        if all(status == CriterionParseStatus.PARSED for status in statuses) and not errors:
            return CriteriaParseStatus.PARSED

        if all(status == CriterionParseStatus.UNSTRUCTURED for status in statuses):
            return CriteriaParseStatus.UNSTRUCTURED

        if all(status == CriterionParseStatus.PARSE_FAILED for status in statuses):
            return CriteriaParseStatus.PARSE_FAILED

        return CriteriaParseStatus.PARTIALLY_PARSED

    def _build_empty_criteria_result(
        self,
        nct_id: str,
        raw_criteria: str | None = None,
        status: CriteriaParseStatus = CriteriaParseStatus.NO_CRITERIA_AVAILABLE,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> ParsedCriteriaResult:
        metadata = ParserMetadata(
            parser_version=self.config.parser_version,
            schema_version=self.config.schema_version,
            llm_calls=[],
        )

        block = ParsedCriteriaBlock(
            raw=raw_criteria,
            parsed_status=status,
            inclusion=[],
            exclusion=[],
            all=[],
            parse_warnings=warnings or [],
            parse_errors=errors or [],
            parser_metadata=metadata,
        )

        return ParsedCriteriaResult(nct_id=nct_id, criteria=block)

    def _build_parsed_criteria_result(
        self,
        nct_id: str,
        raw_criteria: str,
        inclusion: list[ParsedCriterion],
        exclusion: list[ParsedCriterion],
        status: CriteriaParseStatus,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        llm_calls: list[LLMRuntimeInfo] | None = None,
    ) -> ParsedCriteriaResult:
        metadata = ParserMetadata(
            parser_version=self.config.parser_version,
            schema_version=self.config.schema_version,
            llm_calls=llm_calls or [],
        )

        block = ParsedCriteriaBlock(
            raw=raw_criteria,
            parsed_status=status,
            inclusion=inclusion,
            exclusion=exclusion,
            all=[*inclusion, *exclusion],
            parse_warnings=warnings or [],
            parse_errors=errors or [],
            parser_metadata=metadata,
        )

        return ParsedCriteriaResult(nct_id=nct_id, criteria=block)

    def _build_invalid_study_result(
        self,
        index: int,
        error: str,
    ) -> dict[str, Any]:
        parsed_result = self._build_empty_criteria_result(
            nct_id=f"invalid_study_{index}",
            raw_criteria=None,
            status=CriteriaParseStatus.PARSE_FAILED,
            errors=[error],
        )

        return {
            "nct_id": f"invalid_study_{index}",
            "criteria": parsed_result.criteria.model_dump(
                mode="json",
                by_alias=True,
            ),
        }

    # ------------------------------------------------------------------
    # LLM metadata
    # ------------------------------------------------------------------

    def _build_llm_runtime_info(
        self,
        task_config: LLMTaskConfig,
        llm: LLMClient,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_seconds: float | None = None,
    ) -> LLMRuntimeInfo:
        return LLMRuntimeInfo(
            task_name=task_config.task_name,
            provider=self._get_llm_provider_name(llm),
            model_name=self._get_llm_model_name(llm),
            llm_size=task_config.llm_size,
            prompt_filename=task_config.prompt_filename,
            prompt_version=task_config.prompt_version,
            schema_version=task_config.schema_version,
            temperature=task_config.generation_config.temperature,
            max_retries=task_config.generation_config.max_retries,
            structured_output=task_config.generation_config.structured_output,
            response_format=task_config.generation_config.response_format,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_seconds=latency_seconds,
        )

    def _get_llm_model_name(
        self,
        llm: LLMClient,
    ) -> str | None:
        for attribute_name in (
            "model_name",
            "model",
            "model_id",
            "deployment_name",
            "name",
            "_model_name",
            "_model",
        ):
            value = getattr(llm, attribute_name, None)

            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _get_llm_provider_name(
        self,
        llm: LLMClient,
    ) -> str | None:
        for attribute_name in ("provider", "provider_name", "vendor"):
            value = getattr(llm, attribute_name, None)

            if isinstance(value, str) and value.strip():
                return value.strip()

        return llm.__class__.__name__ if llm is not None else None

    # ------------------------------------------------------------------
    # Internal helpers: LLM invocation and JSON parsing
    # ------------------------------------------------------------------

    def _get_response_schema_for_task(
        self,
        task_config: LLMTaskConfig,
    ) -> type[BaseModel]:
        if task_config.task_name in {
            LLMTaskName.PARSE_INCLUSION_CRITERIA,
            LLMTaskName.PARSE_EXCLUSION_CRITERIA,
        }:
            return LLMParsedCriteriaResponse

        if task_config.task_name == LLMTaskName.DETECT_UNKNOWN_HARDNESS:
            return HardnessClassificationResponse

        raise ValueError(
            f"No response schema configured for task: {task_config.task_name}"
        )

    def _invoke_llm(
        self,
        llm: LLMClient,
        system_prompt: str,
        user_prompt: str,
        task_config: LLMTaskConfig,
    ) -> Any:
        temperature = task_config.generation_config.temperature
        response_schema = self._get_response_schema_for_task(task_config)

        last_error: Exception | None = None

        generate_json = getattr(llm, "generate_json", None)

        if callable(generate_json):
            try:
                return generate_json(
                    prompt=user_prompt,
                    response_schema=response_schema,
                    system_instruction=system_prompt,
                    temperature=temperature,
                )
            except Exception as exc:
                last_error = exc

        generate_text = getattr(llm, "generate_text", None)

        if callable(generate_text):
            try:
                return generate_text(
                    prompt=user_prompt,
                    system_instruction=system_prompt,
                    temperature=temperature,
                )
            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "Could not invoke LLM client with generate_json or generate_text. "
            f"Last error: {last_error}"
        )

    def _build_user_prompt(
        self,
        payload: dict[str, Any],
    ) -> str:
        return (
            "Return valid JSON only. Do not wrap the JSON in markdown.\n\n"
            f"Payload:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

    def _coerce_llm_response_to_json(
        self,
        response_obj: Any,
    ) -> dict[str, Any]:
        if isinstance(response_obj, dict):
            return response_obj

        if isinstance(response_obj, BaseModel):
            return response_obj.model_dump(mode="python", by_alias=True)

        text: str | None = None

        for attr in ("content", "text", "message", "response", "output"):
            value = getattr(response_obj, attr, None)

            if isinstance(value, str):
                text = value
                break

            if isinstance(value, dict):
                return value

        if text is None and isinstance(response_obj, str):
            text = response_obj

        if text is None:
            text = str(response_obj)

        return self._extract_json_from_text(text)

    def _extract_json_from_text(
        self,
        text: str,
    ) -> dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)

            if isinstance(parsed, list):
                return {"criteria": parsed}

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")

        if first_brace >= 0 and last_brace > first_brace:
            candidate = cleaned[first_brace:last_brace + 1]
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        first_bracket = cleaned.find("[")
        last_bracket = cleaned.rfind("]")

        if first_bracket >= 0 and last_bracket > first_bracket:
            candidate = cleaned[first_bracket:last_bracket + 1]
            parsed = json.loads(candidate)

            if isinstance(parsed, list):
                return {"criteria": parsed}

        raise ValueError("Could not extract valid JSON from LLM response.")

    def _normalize_llm_criteria_response_data(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if "criteria" in data and isinstance(data["criteria"], list):
            return data

        for key in ("items", "parsed_criteria", "results", "eligibility_criteria"):
            if key in data and isinstance(data[key], list):
                return {
                    "criteria": data[key],
                    "warnings": data.get("warnings", []),
                    "errors": data.get("errors", []),
                }

        if "raw_text" in data:
            return {
                "criteria": [data],
                "warnings": [],
                "errors": [],
            }

        return {
            "criteria": [],
            "warnings": data.get("warnings", []),
            "errors": data.get(
                "errors",
                ["LLM response did not contain a criteria list."],
            ),
        }

    def _extract_usage(
        self,
        response_obj: Any,
    ) -> dict[str, int | None]:
        usage_candidates: list[Any] = []

        if isinstance(response_obj, dict):
            usage_candidates.extend(
                [
                    response_obj.get("usage"),
                    response_obj.get("usage_metadata"),
                    response_obj.get("token_usage"),
                ]
            )

        elif response_obj is not None:
            for attr in ("usage", "usage_metadata", "token_usage"):
                usage_candidates.append(getattr(response_obj, attr, None))

        usage: dict[str, Any] = {}

        for candidate in usage_candidates:
            if isinstance(candidate, dict):
                usage = candidate
                break

            if candidate is not None:
                try:
                    usage = candidate.model_dump()
                    break
                except Exception:
                    continue

        input_tokens = self._first_int(
            usage,
            ["input_tokens", "prompt_tokens", "inputTokenCount", "prompt_token_count"],
        )
        output_tokens = self._first_int(
            usage,
            [
                "output_tokens",
                "completion_tokens",
                "outputTokenCount",
                "candidates_token_count",
            ],
        )
        total_tokens = self._first_int(
            usage,
            ["total_tokens", "totalTokenCount", "total_token_count"],
        )

        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    # ------------------------------------------------------------------
    # Internal helpers: prompts and defaults
    # ------------------------------------------------------------------

    def _load_prompt_or_default(
        self,
        filename: str,
        default: str,
    ) -> str:
        try:
            return load_prompt(filename)
        except Exception as exc:
            self._log_warning(
                f"Could not load prompt `{filename}`; using default. Error: {exc}"
            )
            return default

    def _default_inclusion_prompt(self) -> str:
        return """
You are a clinical trial eligibility criteria parser.

Task:
Parse INCLUSION eligibility criteria into structured JSON.

Rules:
- Do not evaluate against a patient.
- Do not invent thresholds, values, or attributes.
- Preserve raw_text as closely as possible.
- Return one object per input criterion item.
- Keep the same order as the input criteria.
- Do not generate criterion_id, nct_id, or type.
- Mark complex/compound criteria as partially_parsed or compound_unresolved.
- Return valid JSON only, no markdown.
""".strip()

    def _default_exclusion_prompt(self) -> str:
        return """
You are a clinical trial eligibility criteria parser.

Task:
Parse EXCLUSION eligibility criteria into structured JSON.

Critical polarity rule:
Represent what activates the exclusion. Do NOT invert it into a favorable patient state.
Example:
- Exclusion: "Active brain metastases"
- Correct: attribute="active brain metastases", operator="is_present"
- Incorrect: operator="is_absent"

Rules:
- Do not evaluate against a patient.
- Do not invent thresholds, values, or attributes.
- Preserve raw_text as closely as possible.
- Return one object per input criterion item.
- Keep the same order as the input criteria.
- Do not generate criterion_id, nct_id, or type.
- Return valid JSON only, no markdown.
""".strip()

    def _default_hardness_prompt(self) -> str:
        return """
You classify whether an eligibility criterion is hard, soft, or unknown.

Definitions:
- hard: objective clinical/demographic/lab/diagnostic criteria that can strongly determine eligibility.
- soft: administrative, logistical, willingness, consent, or procedural criteria.
- unknown: insufficient information to classify.

Return valid JSON only:
{
  "hardness": "hard|soft|unknown",
  "confidence": 0.0,
  "rationale": "short explanation or null"
}
""".strip()

    def _default_category_keywords(self) -> dict[str, list[str]]:
        return {
            CriterionCategory.ADMINISTRATIVE.value: [
                "informed consent",
                "consent",
                "willing",
                "able to comply",
                "comply with",
                "study procedures",
                "protocol requirements",
            ],
            CriterionCategory.LOGISTICAL.value: [
                "distance",
                "travel",
                "transportation",
                "site",
                "visit",
                "follow-up",
                "availability",
            ],
            CriterionCategory.REPRODUCTIVE.value: [
                "pregnant",
                "pregnancy",
                "breastfeeding",
                "lactating",
                "childbearing",
                "contraception",
                "birth control",
                "fertile",
            ],
            CriterionCategory.DEMOGRAPHIC.value: [
                "age",
                "years old",
                "year-old",
                "sex",
                "male",
                "female",
                "gender",
                "adult",
                "pediatric",
            ],
            CriterionCategory.FUNCTIONAL_STATUS.value: [
                "ecog",
                "performance status",
                "karnofsky",
                "kps",
                "functional status",
            ],
            CriterionCategory.BIOMARKER.value: [
                "egfr",
                "alk",
                "ros1",
                "braf",
                "kras",
                "her2",
                "brca",
                "pd-l1",
                "pdl1",
                "mutation",
                "biomarker",
                "genomic",
                "molecular",
                "expression",
            ],
            CriterionCategory.LABORATORY.value: [
                "hemoglobin",
                "platelet",
                "neutrophil",
                "anc",
                "creatinine",
                "bilirubin",
                "ast",
                "alt",
                "alkaline phosphatase",
                "laboratory",
                "lab",
                "organ function",
                "renal function",
                "hepatic function",
            ],
            CriterionCategory.IMAGING.value: [
                "imaging",
                "radiographic",
                "mri",
                "ct scan",
                "pet",
                "measurable disease",
                "recist",
            ],
            CriterionCategory.CURRENT_TREATMENT.value: [
                "current treatment",
                "ongoing treatment",
                "currently receiving",
                "concomitant",
                "concurrent therapy",
            ],
            CriterionCategory.PRIOR_TREATMENT.value: [
                "prior therapy",
                "prior treatment",
                "previous therapy",
                "previous treatment",
                "chemotherapy",
                "radiotherapy",
                "radiation therapy",
                "surgery",
                "failed",
                "failure of",
                "treated with",
                "treatment with",
                "line of therapy",
            ],
            CriterionCategory.INFECTION.value: [
                "infection",
                "infectious",
                "hiv",
                "hepatitis",
                "hbv",
                "hcv",
                "clostridium",
                "c. difficile",
                "cdi",
                "sepsis",
            ],
            CriterionCategory.COMORBIDITY.value: [
                "comorbidity",
                "cardiovascular",
                "heart failure",
                "myocardial infarction",
                "hypertension",
                "diabetes",
                "autoimmune",
                "intercurrent illness",
                "medical condition",
                "psychiatric",
            ],
            CriterionCategory.DISEASE_STATUS.value: [
                "diagnosis",
                "histologically",
                "confirmed",
                "disease",
                "cancer",
                "carcinoma",
                "tumor",
                "tumour",
                "malignancy",
                "stage",
                "metastatic",
                "metastases",
                "recurrent",
                "relapsed",
                "refractory",
                "progression",
                "severe",
                "moderate",
                "mild",
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers: small utilities
    # ------------------------------------------------------------------

    def _safe_get(
        self,
        data: dict[str, Any],
        path: list[str],
    ) -> Any:
        current: Any = data

        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None

            current = current[key]

        return current

    def _normalize_whitespace(
        self,
        text: str,
    ) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\t\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _clean_item_text(
        self,
        text: str,
    ) -> str:
        text = self._normalize_whitespace(text)
        text = re.sub(r"^\s*(?:\d+[\.)]|[-*•])\s+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_normalized_attribute_value(
        self,
        normalized: Any,
    ) -> str | None:
        if normalized is None:
            return None

        if isinstance(normalized, str):
            return normalized.strip() or None

        if isinstance(normalized, BaseModel):
            normalized = normalized.model_dump(mode="python")

        if isinstance(normalized, dict):
            for key in (
                "normalized_attribute",
                "attribute_id",
                "canonical_attribute",
                "canonical_name",
                "normalized_name",
                "normalized_term",
                "name",
                "term",
                "value",
            ):
                value = normalized.get(key)

                if isinstance(value, str) and value.strip():
                    return value.strip()

            return None

        for attr in (
            "normalized_attribute",
            "attribute_id",
            "canonical_attribute",
            "canonical_name",
            "normalized_name",
            "normalized_term",
            "name",
            "term",
            "value",
        ):
            value = getattr(normalized, attr, None)

            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _first_int(
        self,
        data: dict[str, Any],
        keys: list[str],
    ) -> int | None:
        for key in keys:
            value = data.get(key)

            if isinstance(value, int):
                return value

            if isinstance(value, str) and value.isdigit():
                return int(value)

        return None

    def _log_warning(
        self,
        message: str,
    ) -> None:
        if self.logger is not None and hasattr(self.logger, "warning"):
            try:
                self.logger.warning(message)
            except Exception:
                return

    def _log_error(
        self,
        message: str,
    ) -> None:
        if self.logger is not None and hasattr(self.logger, "error"):
            try:
                self.logger.error(message)
            except Exception:
                return
