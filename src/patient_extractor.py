from pathlib import Path
from typing import Literal

import json
from pydantic import BaseModel, Field

from LLM.LLM_factory import LLMSize, create_llm
from LLM.prompt_loader import load_prompt


class Biomarker(BaseModel):
    name: str | None = None
    status: Literal["positive", "negative", "unknown", "not_tested"] | None = None
    variant: str | None = None
    evidence: str | None = None


class Location(BaseModel):
    country: str | None = None
    city: str | None = None
    evidence: str | None = None


class FieldEvidence(BaseModel):
    field: str
    evidence: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ExtractedPatient(BaseModel):
    condition: str | None = None
    condition_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    subtype: str | None = None
    stage: str | None = None
    metastatic: bool | None = None

    age: int | None = Field(default=None, ge=0, le=120)
    sex: Literal["male", "female", "unknown"] | str | None = None

    biomarkers: list[Biomarker] = Field(default_factory=list)
    prior_treatments: list[str] = Field(default_factory=list)
    current_treatments: list[str] = Field(default_factory=list)
    treatment_line: str | None = None
    progression_after: list[str] = Field(default_factory=list)

    location: Location | None = None

    evidence: list[FieldEvidence] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)


class PatientExtractor:
    def __init__(self):
        self.client = create_llm(LLMSize.SMALL)
        self.prompt_version = "patient_extractor_v1"
        self.schema_version = "patient_profile_v1"
        self.temperature = 0.0
        self.max_attempts = 2

    def extract(self, patient: dict, output_path: Path | str | None = None) -> dict:
        result = patient.copy()
        raw_text = patient.get("raw_text")

        if raw_text is None or raw_text.strip() == "":
            result["patient_profile"] = None
            result["extraction_status"] = "failed"
            result["extraction_error"] = "El paciente no tiene raw_text"
            result["extractor_metadata"] = self._build_metadata(attempts=0)

            self._write_json(result, output_path)
            return result

        last_error: Exception | None = None

        prompt = self._build_prompt(raw_text)

        for attempt in range(self.max_attempts):
            try:
                extracted = self.client.generate_json(
                    prompt=prompt,
                    response_schema=ExtractedPatient,
                    system_instruction=load_prompt("patient_extractor.md"),
                    temperature=self.temperature,
                )

                extracted = self._postprocess(extracted)

                result["patient_profile"] = extracted.model_dump()
                result["extraction_status"] = self._compute_status(extracted)
                result["extraction_error"] = None
                result["extractor_metadata"] = self._build_metadata(
                    attempts=attempt + 1
                )

                self._write_json(result, output_path)
                return result

            except Exception as error:
                last_error = error

        result["patient_profile"] = None
        result["extraction_status"] = "failed"
        result["extraction_error"] = str(last_error)
        result["extractor_metadata"] = self._build_metadata(
            attempts=self.max_attempts
        )

        self._write_json(result, output_path)
        return result

    def _build_prompt(self, raw_text: str) -> str:
        return f"""
Patient record:
{raw_text}

Task:
Extract a structured clinical profile from the patient record according to the schema.

Rules:
- Do not infer information that is not explicitly stated.
- Use null when a field is missing.
- Preserve short evidence snippets where possible.
- For biomarkers, use status: positive, negative, unknown, or not_tested.
- If a biomarker is mentioned but the result is not stated, use status: unknown.
- For sex, use male, female, or unknown.
- For metastatic, use true, false, or null if not stated.
- Keep treatments as medication/procedure names exactly as written when possible.
""".strip()

    def _compute_status(self, extracted: ExtractedPatient) -> str:
        if not extracted.condition:
            return "no_condition_found"

        if (
            extracted.condition_confidence is not None
            and extracted.condition_confidence < 0.6
        ):
            return "low_confidence"

        useful_fields = [
            extracted.subtype,
            extracted.stage,
            extracted.metastatic,
            extracted.age,
            extracted.sex,
            extracted.biomarkers,
            extracted.prior_treatments,
            extracted.current_treatments,
            extracted.treatment_line,
            extracted.progression_after,
            extracted.location,
        ]

        score = sum(1 for field in useful_fields if self._has_value(field))

        if score >= 5:
            return "rich"

        if score >= 2:
            return "partial"

        return "minimal"

    def _has_value(self, value) -> bool:
        if value is None:
            return False

        if isinstance(value, str):
            return value.strip() != ""

        if isinstance(value, list):
            return len(value) > 0

        return True

    def _postprocess(self, extracted: ExtractedPatient) -> ExtractedPatient:
        if extracted.sex:
            extracted.sex = self._normalize_sex(extracted.sex)

        extracted.prior_treatments = self._clean_string_list(
            extracted.prior_treatments
        )
        extracted.current_treatments = self._clean_string_list(
            extracted.current_treatments
        )
        extracted.progression_after = self._clean_string_list(
            extracted.progression_after
        )

        extracted.biomarkers = self._clean_biomarkers(extracted.biomarkers)
        extracted.evidence = self._clean_evidence(extracted.evidence)
        extracted.extraction_notes = self._clean_string_list(
            extracted.extraction_notes
        )

        return extracted

    def _normalize_sex(self, sex: str) -> str:
        value = sex.strip().lower()

        mapping = {
            "f": "female",
            "female": "female",
            "woman": "female",
            "women": "female",
            "girl": "female",
            "m": "male",
            "male": "male",
            "man": "male",
            "men": "male",
            "boy": "male",
            "unknown": "unknown",
            "not stated": "unknown",
            "not mentioned": "unknown",
        }

        return mapping.get(value, value)

    def _clean_string_list(self, values: list[str]) -> list[str]:
        cleaned_values: list[str] = []

        for value in values:
            if value is None:
                continue

            cleaned = str(value).strip()

            if cleaned:
                cleaned_values.append(cleaned)

        return cleaned_values

    def _clean_biomarkers(self, biomarkers: list[Biomarker]) -> list[Biomarker]:
        cleaned_biomarkers: list[Biomarker] = []

        for biomarker in biomarkers:
            if biomarker is None:
                continue

            if biomarker.name:
                biomarker.name = biomarker.name.strip()

            if biomarker.status:
                biomarker.status = self._normalize_biomarker_status(
                    biomarker.status
                )

            if biomarker.variant:
                biomarker.variant = biomarker.variant.strip()

            if biomarker.evidence:
                biomarker.evidence = biomarker.evidence.strip()

            if biomarker.name or biomarker.status or biomarker.variant:
                cleaned_biomarkers.append(biomarker)

        return cleaned_biomarkers

    def _normalize_biomarker_status(
        self,
        status: str,
    ) -> Literal["positive", "negative", "unknown", "not_tested"]:
        value = status.strip().lower()

        positive_values = {
            "positive",
            "+",
            "detected",
            "present",
            "mutated",
            "mutation",
            "activating mutation",
            "rearranged",
            "amplified",
        }

        negative_values = {
            "negative",
            "-",
            "not detected",
            "absent",
            "wild type",
            "wild-type",
            "wt",
        }

        unknown_values = {
            "unknown",
            "unclear",
            "not stated",
            "not mentioned",
            "pending",
            "n/a",
            "na",
        }

        not_tested_values = {
            "not tested",
            "untested",
            "not performed",
            "not done",
        }

        if value in positive_values:
            return "positive"

        if value in negative_values:
            return "negative"

        if value in not_tested_values:
            return "not_tested"

        if value in unknown_values:
            return "unknown"

        return "unknown"

    def _clean_evidence(self, evidence_items: list[FieldEvidence]) -> list[FieldEvidence]:
        cleaned_items: list[FieldEvidence] = []

        for item in evidence_items:
            if item is None:
                continue

            item.field = item.field.strip() if item.field else ""
            item.evidence = item.evidence.strip() if item.evidence else ""

            if item.field and item.evidence:
                cleaned_items.append(item)

        return cleaned_items

    def _build_metadata(self, attempts: int) -> dict:
        return {
            "module": "PatientExtractor",
            "model_size": "SMALL",
            "model_name": getattr(self.client, "model_name", None),
            "temperature": self.temperature,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "attempts": attempts,
        }

    def _write_json(self, result: dict, output_path: Path | str | None) -> None:
        if output_path is None:
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)