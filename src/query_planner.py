from pathlib import Path
import json

from normalization.normalizer import ClinicalNormalizer


class QueryPlanner:
    def __init__(self, normalizer=None):
        self.default_statuses = "RECRUITING,NOT_YET_RECRUITING"
        self.default_page_size = 20

        # Usamos el normalizer, pero desactivamos LLM aquí para que el QueryPlanner sea rápido.
        # La API MeSH sí queda activa para normalizar condiciones si hace falta.
        self.normalizer = normalizer or ClinicalNormalizer(
            use_mesh_api=True,
            use_llm_disambiguation=False,
        )

    def build_plan(
        self,
        patient: dict,
        output_path: Path | str | None = None,
    ) -> dict:
        """
        Build a ClinicalTrials.gov query plan from the output of PatientExtractor.

        If output_path is provided, the generated plan is saved as JSON.
        """

        profile = self._get_patient_profile(patient)

        plan = {
            "patient_id": patient.get("patient_id"),
            "base_queries": [],
            "refined_queries": [],
            "fallback_queries": [],
            "normalized_inputs": {
                "condition": None,
                "prior_treatments": [],
                "current_treatments": [],
                "progression_after": [],
                "biomarkers": [],
            },
            "status": "ready",
            "warnings": [],
        }

        if profile is None:
            plan["status"] = "failed"
            plan["error"] = "El paciente no tiene patient_profile válido"
            self._write_json(plan, output_path)
            return plan

        raw_condition = self._clean_text(profile.get("condition"))
        condition_confidence = profile.get("condition_confidence")

        if raw_condition is None:
            plan["status"] = "failed"
            plan["error"] = "El perfil del paciente no tiene condición"
            self._write_json(plan, output_path)
            return plan

        if condition_confidence is not None and condition_confidence < 0.6:
            plan["warnings"].append(
                f"Condition confidence is low: {condition_confidence}"
            )

        raw_text = patient.get("raw_text")

        normalized_condition = self.normalizer.normalize_condition(
            raw_condition,
            raw_text=raw_text,
        )

        plan["normalized_inputs"]["condition"] = normalized_condition.model_dump()

        condition = self._clean_text(normalized_condition.normalized)

        if condition is None:
            plan["status"] = "failed"
            plan["error"] = "No se pudo normalizar la condición del paciente"
            self._write_json(plan, output_path)
            return plan

        biomarkers = profile.get("biomarkers") or []
        prior_treatments = profile.get("prior_treatments") or []
        current_treatments = profile.get("current_treatments") or []
        progression_after = profile.get("progression_after") or []

        subtype = self._clean_text(profile.get("subtype"))
        stage = self._clean_text(profile.get("stage"))
        metastatic = profile.get("metastatic")
        location = profile.get("location") or {}

        # 1. Base query: condición normalizada
        self._add_query(
            plan["base_queries"],
            {
                "query.cond": condition,
                "filter.overallStatus": self.default_statuses,
                "pageSize": self.default_page_size,
                "format": "json",
            },
        )

        # 1.b Base query adicional con término oficial MeSH, si existe y es diferente
        ontology_term = self._clean_text(normalized_condition.ontology_term)

        if ontology_term is not None and ontology_term.lower() != condition.lower():
            self._add_query(
                plan["base_queries"],
                {
                    "query.cond": ontology_term,
                    "filter.overallStatus": self.default_statuses,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        # 1.c Refined queries con aliases locales, si existen
        for alias in normalized_condition.aliases:
            alias = self._clean_text(alias)

            if alias is not None and alias.lower() != condition.lower():
                self._add_query(
                    plan["refined_queries"],
                    {
                        "query.cond": condition,
                        "query.term": alias,
                        "filter.overallStatus": self.default_statuses,
                        "pageSize": self.default_page_size,
                        "format": "json",
                    },
                )

        # 1.d Refined queries con parents MeSH básicos, si existen
        for parent in normalized_condition.parents:
            if not isinstance(parent, dict):
                continue

            parent_term = self._clean_text(parent.get("mesh_term"))

            if parent_term is not None:
                self._add_query(
                    plan["refined_queries"],
                    {
                        "query.cond": parent_term,
                        "query.term": condition,
                        "filter.overallStatus": self.default_statuses,
                        "pageSize": self.default_page_size,
                        "format": "json",
                    },
                )

        # 2. Refined query with subtype, if available
        if subtype is not None:
            self._add_query(
                plan["refined_queries"],
                {
                    "query.cond": condition,
                    "query.term": subtype,
                    "filter.overallStatus": self.default_statuses,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        # 3. Refined query with stage, if available
        if stage is not None:
            self._add_query(
                plan["refined_queries"],
                {
                    "query.cond": condition,
                    "query.term": stage,
                    "filter.overallStatus": self.default_statuses,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        # 4. Refined query for metastatic disease
        if metastatic is True:
            self._add_query(
                plan["refined_queries"],
                {
                    "query.cond": condition,
                    "query.term": "metastatic",
                    "filter.overallStatus": self.default_statuses,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        # 5. Refined queries with biomarkers
        for biomarker in biomarkers:
            normalized_biomarker = self._normalize_biomarker_for_plan(biomarker)

            if normalized_biomarker is not None:
                plan["normalized_inputs"]["biomarkers"].append(
                    normalized_biomarker.model_dump()
                )

            biomarker_terms = self._biomarker_to_query_terms(biomarker)

            for term in biomarker_terms:
                self._add_query(
                    plan["refined_queries"],
                    {
                        "query.cond": condition,
                        "query.term": term,
                        "filter.overallStatus": self.default_statuses,
                        "pageSize": self.default_page_size,
                        "format": "json",
                    },
                )

        # 6. Refined queries with prior treatments
        for treatment in prior_treatments:
            treatment = self._clean_text(treatment)

            if treatment is not None:
                normalized_treatment = self.normalizer.normalize_drug(treatment)
                plan["normalized_inputs"]["prior_treatments"].append(
                    normalized_treatment.model_dump()
                )

                treatment_query_term = self._clean_text(
                    normalized_treatment.normalized
                )

                if treatment_query_term is not None:
                    self._add_query(
                        plan["refined_queries"],
                        {
                            "query.cond": condition,
                            "query.term": treatment_query_term,
                            "filter.overallStatus": self.default_statuses,
                            "pageSize": self.default_page_size,
                            "format": "json",
                        },
                    )

        # 7. Refined queries with progression-after treatments
        for treatment in progression_after:
            treatment = self._clean_text(treatment)

            if treatment is not None:
                normalized_treatment = self.normalizer.normalize_drug(treatment)
                plan["normalized_inputs"]["progression_after"].append(
                    normalized_treatment.model_dump()
                )

                treatment_query_term = self._clean_text(
                    normalized_treatment.normalized
                )

                if treatment_query_term is not None:
                    self._add_query(
                        plan["refined_queries"],
                        {
                            "query.cond": condition,
                            "query.term": f"progression after {treatment_query_term}",
                            "filter.overallStatus": self.default_statuses,
                            "pageSize": self.default_page_size,
                            "format": "json",
                        },
                    )

        # 8. Optional query using current treatments
        for treatment in current_treatments:
            treatment = self._clean_text(treatment)

            if treatment is not None:
                normalized_treatment = self.normalizer.normalize_drug(treatment)
                plan["normalized_inputs"]["current_treatments"].append(
                    normalized_treatment.model_dump()
                )

                treatment_query_term = self._clean_text(
                    normalized_treatment.normalized
                )

                if treatment_query_term is not None:
                    self._add_query(
                        plan["refined_queries"],
                        {
                            "query.cond": condition,
                            "query.term": treatment_query_term,
                            "filter.overallStatus": self.default_statuses,
                            "pageSize": self.default_page_size,
                            "format": "json",
                        },
                    )

        # 9. Optional location refinement
        country = (
            self._clean_text(location.get("country"))
            if isinstance(location, dict)
            else None
        )
        city = (
            self._clean_text(location.get("city"))
            if isinstance(location, dict)
            else None
        )

        if country is not None:
            self._add_query(
                plan["refined_queries"],
                {
                    "query.cond": condition,
                    "filter.overallStatus": self.default_statuses,
                    "query.locn": country,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        if city is not None:
            self._add_query(
                plan["refined_queries"],
                {
                    "query.cond": condition,
                    "filter.overallStatus": self.default_statuses,
                    "query.locn": city,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        # 10. Fallback queries
        self._add_query(
            plan["fallback_queries"],
            {
                "query.term": condition,
                "pageSize": self.default_page_size,
                "format": "json",
            },
        )

        if ontology_term is not None and ontology_term.lower() != condition.lower():
            self._add_query(
                plan["fallback_queries"],
                {
                    "query.term": ontology_term,
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        if subtype is not None:
            self._add_query(
                plan["fallback_queries"],
                {
                    "query.term": f"{condition} {subtype}",
                    "pageSize": self.default_page_size,
                    "format": "json",
                },
            )

        # 11. Status
        if len(plan["refined_queries"]) == 0:
            plan["status"] = "fallback_required"

        self._write_json(plan, output_path)

        return plan

    def _write_json(
        self,
        plan: dict,
        output_path: Path | str | None,
    ) -> None:
        """
        Save the generated query plan as JSON if output_path is provided.
        """

        if output_path is None:
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(plan, file, ensure_ascii=False, indent=2)

    def _get_patient_profile(self, patient: dict) -> dict | None:
        """
        Accepts both the new format and, for compatibility, the old flat format.
        """

        profile = patient.get("patient_profile")

        if isinstance(profile, dict):
            return profile

        # Backward compatibility with the previous flat extractor output
        if patient.get("condition") is not None:
            return patient

        return None

    def _normalize_biomarker_for_plan(self, biomarker):
        """
        Normalizes a biomarker object using ClinicalNormalizer.
        """

        if not isinstance(biomarker, dict):
            return None

        name = self._clean_text(biomarker.get("name"))
        status = self._clean_text(biomarker.get("status"))
        variant = self._clean_text(biomarker.get("variant"))

        text_parts = []

        if name is not None:
            text_parts.append(name)

        if status is not None:
            text_parts.append(status)

        if variant is not None:
            text_parts.append(variant)

        raw_biomarker_text = " ".join(text_parts).strip()

        if raw_biomarker_text == "":
            return None

        return self.normalizer.normalize_biomarker_text(raw_biomarker_text)

    def _biomarker_to_query_terms(self, biomarker) -> list[str]:
        """
        Converts a biomarker object into useful ClinicalTrials.gov search terms.
        """

        if not isinstance(biomarker, dict):
            return []

        name = self._clean_text(biomarker.get("name"))
        status = self._clean_text(biomarker.get("status"))
        variant = self._clean_text(biomarker.get("variant"))

        normalized_biomarker = self._normalize_biomarker_for_plan(biomarker)

        if normalized_biomarker is None:
            return []

        if normalized_biomarker.biomarker == "unknown":
            return []

        biomarker_name = normalized_biomarker.biomarker
        normalized_status = self._clean_text(normalized_biomarker.normalized_value)

        terms = []

        terms.append(biomarker_name)

        if variant is not None:
            terms.append(f"{biomarker_name} {variant}")

        if normalized_status is not None and normalized_status != "unknown":
            terms.append(f"{biomarker_name} {normalized_status}")

        # Conservamos también el nombre original si era distinto.
        # Ejemplo: PDL1 -> PD-L1, pero puede interesar buscar ambos.
        if name is not None and name.lower() != biomarker_name.lower():
            terms.append(name)

        if name is not None and status is not None:
            terms.append(f"{name} {status}")

        return terms

    def _add_query(self, queries: list[dict], query: dict) -> None:
        """
        Adds a query only if it is not already present.
        """

        if query not in queries:
            queries.append(query)

    def _clean_text(self, value) -> str | None:
        """
        Normalizes empty strings to None.
        """

        if value is None:
            return None

        if not isinstance(value, str):
            return str(value)

        value = value.strip()

        if value == "":
            return None

        return value