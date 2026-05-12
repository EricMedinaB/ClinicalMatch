from pydantic import BaseModel, Field

from LLM.LLM_factory import LLMSize, create_llm
from LLM.prompt_loader import load_prompt

from normalization.dictionaries import (
    ATTRIBUTE_SYNONYMS,
    BIOMARKER_ATTRIBUTE_IDS,
    CONDITION_MESH,
    CONDITION_SYNONYMS,
    DRUG_SYNONYMS,
    SEX_SYNONYMS,
    STATUS_SYNONYMS,
)

from normalization.mesh_client import MeshClient

from normalization.schemas import (
    NormalizedAttribute,
    NormalizedBiomarker,
    NormalizedConcept,
    NormalizedValue,
)


class MeshDisambiguationResult(BaseModel):
    selected_mesh_id: str | None = None
    selected_mesh_term: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class ClinicalNormalizer:
    def __init__(self):
        self.mesh_client = MeshClient()
        self.llm = create_llm(LLMSize.SMALL)
        self.llm_confidence_threshold = 0.75

    # Funcion para quitar espacios al principio/final y pasar a minusculas
    def clean_text(self, text):
        return str(text).strip().lower()

    def normalize_condition(self, text, raw_text=None):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        # 1. Primero buscamos en diccionario local
        if cleaned in CONDITION_SYNONYMS:
            normalized_condition = CONDITION_SYNONYMS[cleaned]

            # 2. Si la condicion normalizada tiene MeSH local, lo usamos
            if normalized_condition in CONDITION_MESH:
                mesh_info = CONDITION_MESH[normalized_condition]

                return NormalizedConcept(
                    raw=text,
                    normalized=normalized_condition,
                    concept_type="condition",
                    method="dictionary_mesh_mapping",
                    confidence=1.0,
                    status="normalized",
                    ontology="MeSH",
                    ontology_id=mesh_info["mesh_id"],
                    ontology_term=mesh_info["mesh_term"],
                    aliases=mesh_info.get("aliases", []),
                    parents=mesh_info.get("parents", []),
                )

            # 3. Si esta en diccionario pero no tenemos MeSH local,
            # consultamos MeSH API usando la condicion normalizada
            return self._normalize_with_mesh_api(
                original_text=text,
                search_text=normalized_condition,
                raw_text=raw_text,
                fallback_normalized=normalized_condition,
                fallback_method="dictionary_without_mesh",
                fallback_confidence=0.8,
            )

        # 4. Si NO esta en diccionario local, consultamos MeSH API
        return self._normalize_with_mesh_api(
            original_text=text,
            search_text=cleaned,
            raw_text=raw_text,
            fallback_normalized=cleaned,
            fallback_method="not_normalized",
            fallback_confidence=0.3,
        )

    def _normalize_with_mesh_api(
        self,
        original_text,
        search_text,
        raw_text=None,
        fallback_normalized=None,
        fallback_method="not_normalized",
        fallback_confidence=0.3,
    ):
        if fallback_normalized is None:
            fallback_normalized = search_text

        try:
            mesh_result = self.mesh_client.find_best_descriptor(search_text)

            if mesh_result["status"] in {"normalized", "low_confidence"}:
                return NormalizedConcept(
                    raw=original_text,
                    normalized=mesh_result["mesh_term"],
                    concept_type="condition",
                    method=mesh_result["method"],
                    confidence=mesh_result["confidence"],
                    status=mesh_result["status"],
                    ontology="MeSH",
                    ontology_id=mesh_result["mesh_id"],
                    ontology_term=mesh_result["mesh_term"],
                    aliases=[],
                    parents=[],
                )

            if mesh_result["status"] == "multiple_candidates":
                candidates = mesh_result.get("candidates", [])

                # Si hay raw_text, usamos Gemini para elegir entre candidatos reales de MeSH
                if raw_text:
                    llm_result = self._disambiguate_mesh_candidates_with_llm(
                        ambiguous_term=original_text,
                        raw_text=raw_text,
                        candidates=candidates,
                    )

                    if (
                        llm_result.selected_mesh_id is not None
                        and llm_result.selected_mesh_term is not None
                        and llm_result.confidence >= self.llm_confidence_threshold
                        and self._selected_candidate_is_valid(
                            selected_mesh_id=llm_result.selected_mesh_id,
                            candidates=candidates,
                        )
                    ):
                        return NormalizedConcept(
                            raw=original_text,
                            normalized=llm_result.selected_mesh_term,
                            concept_type="condition",
                            method="mesh_api_multiple_candidates_llm_disambiguation",
                            confidence=llm_result.confidence,
                            status="normalized",
                            ontology="MeSH",
                            ontology_id=llm_result.selected_mesh_id,
                            ontology_term=llm_result.selected_mesh_term,
                            aliases=[],
                            parents=[],
                        )

                    return NormalizedConcept(
                        raw=original_text,
                        normalized=fallback_normalized,
                        concept_type="condition",
                        method="mesh_api_multiple_candidates_llm_low_confidence",
                        confidence=llm_result.confidence,
                        status="manual_review_recommended",
                        ontology="MeSH",
                        aliases=[],
                        parents=[],
                    )

                # Si no hay raw_text, no podemos desambiguar con contexto
                return NormalizedConcept(
                    raw=original_text,
                    normalized=fallback_normalized,
                    concept_type="condition",
                    method=mesh_result["method"],
                    confidence=mesh_result["confidence"],
                    status="multiple_candidates",
                    ontology="MeSH",
                    aliases=[],
                    parents=[],
                )

            if mesh_result["status"] == "no_match":
                return NormalizedConcept(
                    raw=original_text,
                    normalized=fallback_normalized,
                    concept_type="condition",
                    method=mesh_result["method"],
                    confidence=mesh_result["confidence"],
                    status="no_match",
                    ontology="MeSH",
                    aliases=[],
                    parents=[],
                )

        except Exception:
            return NormalizedConcept(
                raw=original_text,
                normalized=fallback_normalized,
                concept_type="condition",
                method="mesh_api_error",
                confidence=fallback_confidence,
                status="manual_review_recommended",
            )

        return NormalizedConcept(
            raw=original_text,
            normalized=fallback_normalized,
            concept_type="condition",
            method=fallback_method,
            confidence=fallback_confidence,
            status="no_match",
        )

    def _disambiguate_mesh_candidates_with_llm(
        self,
        ambiguous_term,
        raw_text,
        candidates,
    ):
        prompt = self._build_mesh_disambiguation_prompt(
            ambiguous_term=ambiguous_term,
            raw_text=raw_text,
            candidates=candidates,
        )

        return self.llm.generate_json(
            prompt=prompt,
            response_schema=MeshDisambiguationResult,
            system_instruction=load_prompt("mesh_disambiguation.md"),
            temperature=0.0,
        )

    def _build_mesh_disambiguation_prompt(
        self,
        ambiguous_term,
        raw_text,
        candidates,
    ):
        return f"""
Ambiguous clinical term:
{ambiguous_term}

Patient raw text:
{raw_text}

MeSH candidates:
{candidates}

Task:
Choose the MeSH candidate that best matches the ambiguous clinical term in the context of the patient raw text.

Return:
- selected_mesh_id
- selected_mesh_term
- confidence
- reason

If none is clearly supported, return selected_mesh_id = null and selected_mesh_term = null.
""".strip()

    def _selected_candidate_is_valid(self, selected_mesh_id, candidates):
        for candidate in candidates:
            if candidate.get("mesh_id") == selected_mesh_id:
                return True

        return False

    def normalize_drug(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        if cleaned in DRUG_SYNONYMS:
            return NormalizedConcept(
                raw=text,
                normalized=DRUG_SYNONYMS[cleaned],
                concept_type="drug",
                method="alias_match",
                confidence=1.0,
                status="normalized",
            )

        return NormalizedConcept(
            raw=text,
            normalized=cleaned,
            concept_type="drug",
            method="not_normalized",
            confidence=0.3,
            status="no_match",
        )

    def normalize_sex(self, value):
        if value is None:
            return None

        cleaned = self.clean_text(value)

        if cleaned in SEX_SYNONYMS:
            return NormalizedValue(
                raw=value,
                normalized=SEX_SYNONYMS[cleaned],
                value_type="categorical",
                method="dictionary",
                confidence=1.0,
            )

        return NormalizedValue(
            raw=value,
            normalized="unknown",
            value_type="categorical",
            method="not_normalized",
            confidence=0.2,
        )

    def normalize_status(self, value):
        if value is None:
            return NormalizedValue(
                raw=value,
                normalized="unknown",
                value_type="categorical",
                method="missing",
                confidence=0.0,
            )

        cleaned = self.clean_text(value)

        if cleaned in STATUS_SYNONYMS:
            return NormalizedValue(
                raw=value,
                normalized=STATUS_SYNONYMS[cleaned],
                value_type="categorical",
                method="dictionary",
                confidence=1.0,
            )

        return NormalizedValue(
            raw=value,
            normalized="unknown",
            value_type="categorical",
            method="not_normalized",
            confidence=0.2,
        )

    def normalize_biomarker_text(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        biomarkers = ["EGFR", "ALK", "BRAF", "KRAS", "HER2", "ROS1", "PD-L1"]

        biomarker = None

        for item in biomarkers:
            if item.lower() in cleaned:
                biomarker = item
                break

        if biomarker is None:
            return NormalizedBiomarker(
                raw=text,
                biomarker="unknown",
                attribute_id="unknown_biomarker_status",
                normalized_value="unknown",
                method="not_detected",
                confidence=0.2,
            )

        negative_markers = [
            "negative",
            "wild-type",
            "wild type",
            "not detected",
            "no mutation",
        ]

        positive_markers = [
            "positive",
            "mutation",
            "mutated",
            "detected",
            "rearranged",
            "amplified",
            "fusion",
        ]

        if cleaned.endswith("-") or any(marker in cleaned for marker in negative_markers):
            status = "negative"
            method = "simple_negative_match"
            confidence = 0.9

        elif cleaned.endswith("+") or any(marker in cleaned for marker in positive_markers):
            status = "positive"
            method = "simple_positive_match"
            confidence = 0.9

        else:
            status = "unknown"
            method = "status_unknown"
            confidence = 0.6

        attribute_id = BIOMARKER_ATTRIBUTE_IDS.get(
            biomarker,
            f"{biomarker}_status",
        )

        return NormalizedBiomarker(
            raw=text,
            biomarker=biomarker,
            attribute_id=attribute_id,
            normalized_value=status,
            method=method,
            confidence=confidence,
        )

    def normalize_attribute(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        if cleaned in ATTRIBUTE_SYNONYMS:
            attribute_id, canonical_name, value_type = ATTRIBUTE_SYNONYMS[cleaned]

            return NormalizedAttribute(
                raw=text,
                attribute_id=attribute_id,
                canonical_name=canonical_name,
                value_type=value_type,
                method="dictionary",
                confidence=1.0,
            )

        return NormalizedAttribute(
            raw=text,
            attribute_id=cleaned.replace(" ", "_"),
            canonical_name=str(text).strip(),
            value_type="unknown",
            method="not_normalized",
            confidence=0.3,
        )
