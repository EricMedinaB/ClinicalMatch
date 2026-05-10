from pathlib import Path
import json


class QueryPlanner:
    def __init__(self):
        self.default_statuses = "RECRUITING,NOT_YET_RECRUITING"
        self.default_page_size = 20

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
            "status": "ready",
            "warnings": [],
        }

        if profile is None:
            plan["status"] = "failed"
            plan["error"] = "El paciente no tiene patient_profile válido"
            self._write_json(plan, output_path)
            return plan

        condition = self._clean_text(profile.get("condition"))
        condition_confidence = profile.get("condition_confidence")

        if condition is None:
            plan["status"] = "failed"
            plan["error"] = "El perfil del paciente no tiene condición"
            self._write_json(plan, output_path)
            return plan

        if condition_confidence is not None and condition_confidence < 0.6:
            plan["warnings"].append(
                f"Condition confidence is low: {condition_confidence}"
            )

        biomarkers = profile.get("biomarkers") or []
        prior_treatments = profile.get("prior_treatments") or []
        current_treatments = profile.get("current_treatments") or []
        progression_after = profile.get("progression_after") or []

        subtype = self._clean_text(profile.get("subtype"))
        stage = self._clean_text(profile.get("stage"))
        metastatic = profile.get("metastatic")
        location = profile.get("location") or {}

        # 1. Base query: condition only
        self._add_query(
            plan["base_queries"],
            {
                "query.cond": condition,
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
                self._add_query(
                    plan["refined_queries"],
                    {
                        "query.cond": condition,
                        "query.term": treatment,
                        "filter.overallStatus": self.default_statuses,
                        "pageSize": self.default_page_size,
                        "format": "json",
                    },
                )

        # 7. Refined queries with progression-after treatments
        for treatment in progression_after:
            treatment = self._clean_text(treatment)

            if treatment is not None:
                self._add_query(
                    plan["refined_queries"],
                    {
                        "query.cond": condition,
                        "query.term": f"progression after {treatment}",
                        "filter.overallStatus": self.default_statuses,
                        "pageSize": self.default_page_size,
                        "format": "json",
                    },
                )

        # 8. Optional query using current treatments
        for treatment in current_treatments:
            treatment = self._clean_text(treatment)

            if treatment is not None:
                self._add_query(
                    plan["refined_queries"],
                    {
                        "query.cond": condition,
                        "query.term": treatment,
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

    def _biomarker_to_query_terms(self, biomarker) -> list[str]:
        """
        Converts a biomarker object into useful ClinicalTrials.gov search terms.
        """

        if not isinstance(biomarker, dict):
            return []

        name = self._clean_text(biomarker.get("name"))
        status = self._clean_text(biomarker.get("status"))
        variant = self._clean_text(biomarker.get("variant"))

        terms = []

        if name is not None:
            terms.append(name)

        if name is not None and variant is not None:
            terms.append(f"{name} {variant}")

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