from pathlib import Path
from typing import Any
import json


class TrialCandidateStore:
    def build_store_from_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> dict[str, Any]:
        input_path = Path(input_path)
        output_path = Path(output_path)

        refined_result = self._read_json(input_path)

        store_result = self.build_store(
            refined_result=refined_result,
        )

        self._write_json(
            result=store_result,
            output_path=output_path,
        )

        return store_result

    def build_store(
        self,
        refined_result: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_refined_result(refined_result)

        store_result = dict(refined_result)

        unique_studies = refined_result.get("unique_studies", [])
        transformed_studies: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for index, candidate in enumerate(unique_studies):
            try:
                transformed_candidate = self._transform_candidate(candidate)
                transformed_studies.append(transformed_candidate)

            except Exception as error:
                errors.append({
                    "index": index,
                    "nct_id": self._safe_get_nct_id(candidate),
                    "error": str(error),
                })

        store_result["unique_studies"] = transformed_studies
        store_result["candidate_store_metadata"] = {
            "total_input_candidates": len(unique_studies),
            "total_stored_candidates": len(transformed_studies),
            "total_errors": len(errors),
            "status": "success" if len(errors) == 0 else "partial_result",
        }

        if errors:
            store_result["candidate_store_errors"] = errors

        return store_result

    def _transform_candidate(
        self,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise TypeError("Cada candidato debe ser un diccionario")

        if "raw" not in candidate:
            raise ValueError("El candidato no contiene la clave 'raw'")

        raw_trial = candidate.get("raw")

        if not isinstance(raw_trial, dict):
            raise TypeError("candidate['raw'] debe ser un diccionario")
        
        transformed_trial = self.normalize_trial(
            raw_trial = raw_trial,
            candidate=candidate,
        )

        transformed_candidate = {
            key: value
            for key, value in candidate.items()
            if key != "raw"
        }

        transformed_candidate["trial"] = transformed_trial

        return transformed_candidate

    def normalize_trial(
        self,
        raw_trial: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw_trial, dict):
            raise TypeError("raw_trial debe ser un diccionario")

        protocol = raw_trial.get("protocolSection", {})

        if not isinstance(protocol, dict):
            protocol = {}

        identification_module = protocol.get("identificationModule", {}) or {}
        status_module = protocol.get("statusModule", {}) or {}
        design_module = protocol.get("designModule", {}) or {}
        conditions_module = protocol.get("conditionsModule", {}) or {}
        arms_interventions_module = protocol.get("armsInterventionsModule", {}) or {}
        eligibility_module = protocol.get("eligibilityModule", {}) or {}
        contacts_locations_module = protocol.get("contactsLocationsModule", {}) or {}
        description_module = protocol.get("descriptionModule", {}) or {}

        nct_id = (
            candidate.get("nct_id")
            or identification_module.get("nctId")
            or raw_trial.get("nctId")
        )

        flags: list[dict[str, Any]] = []

        if not nct_id:
            flags.append({
                "type": "missing_nct_id",
                "severity": "high",
                "message": "No se ha encontrado NCT ID en candidate ni en raw_trial.",
            })

        raw_criteria = eligibility_module.get("eligibilityCriteria")

        if not raw_criteria:
            flags.append({
                "type": "missing_eligibility_criteria",
                "severity": "high",
                "message": "No se han encontrado criterios de elegibilidad.",
            })

        locations = self._normalize_locations(
            contacts_locations_module.get("locations", [])
        )

        if not locations:
            flags.append({
                "type": "missing_locations",
                "severity": "medium",
                "message": "No se han encontrado localizaciones del ensayo.",
            })

        interventions = self._normalize_interventions(
            arms_interventions_module.get("interventions", [])
        )

        phases = design_module.get("phases", [])

        if isinstance(phases, str):
            phases = [phases]

        if phases is None:
            phases = []

        conditions = conditions_module.get("conditions", [])

        if isinstance(conditions, str):
            conditions = [conditions]

        if conditions is None:
            conditions = []

        normalized_trial = {
            "normalization_status": "normalized",
            "nct_id": nct_id,
            "identification": {
                "brief_title": identification_module.get("briefTitle"),
                "official_title": identification_module.get("officialTitle"),
            },
            "status": {
                "overall_status": status_module.get("overallStatus"),
                "start_date": self._extract_date(status_module.get("startDateStruct")),
                "primary_completion_date": self._extract_date(
                    status_module.get("primaryCompletionDateStruct")
                ),
                "completion_date": self._extract_date(
                    status_module.get("completionDateStruct")
                ),
                "last_update_posted_date": self._extract_date(
                    status_module.get("lastUpdatePostDateStruct")
                ),
            },
            "design": {
                "study_type": design_module.get("studyType"),
                "phases": phases,
                "enrollment_count": self._extract_enrollment_count(design_module),
            },
            "conditions": conditions,
            "interventions": interventions,
            "eligibility": {
                "raw_criteria": raw_criteria,
                "sex": eligibility_module.get("sex"),
                "minimum_age": eligibility_module.get("minimumAge"),
                "maximum_age": eligibility_module.get("maximumAge"),
                "healthy_volunteers": eligibility_module.get("healthyVolunteers"),
            },
            "criteria": {
                "raw": raw_criteria,
                "parsed_status": "not_parsed",
            },
            "locations": locations,
            "description": {
                "brief_summary": description_module.get("briefSummary"),
            },
            "normalized_flags": flags,
            "source": {
                "provider": "clinicaltrials.gov",
                "api_version": "v2",
            },
        }

        return normalized_trial

    def _validate_refined_result(
        self,
        refined_result: dict[str, Any],
    ) -> None:
        if not isinstance(refined_result, dict):
            raise TypeError("refined_result debe ser un diccionario")

        if "unique_studies" not in refined_result:
            raise ValueError("El JSON no contiene la clave 'unique_studies'")

        if not isinstance(refined_result["unique_studies"], list):
            raise TypeError("'unique_studies' debe ser una lista")

    def _read_json(
        self,
        input_path: Path,
    ) -> dict[str, Any]:
        if not input_path.exists():
            raise FileNotFoundError(f"No existe el archivo: {input_path}")

        if not input_path.is_file():
            raise ValueError(f"La ruta no es un archivo: {input_path}")

        try:
            with input_path.open("r", encoding="utf-8") as file:
                data = json.load(file)

        except json.JSONDecodeError as error:
            raise ValueError(f"El archivo no contiene JSON válido: {input_path}") from error

        if not isinstance(data, dict):
            raise TypeError("El JSON raíz debe ser un objeto/diccionario")

        return data

    def _write_json(
        self,
        result: dict[str, Any],
        output_path: Path,
    ) -> None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8") as file:
                json.dump(result, file, ensure_ascii=False, indent=2)

        except OSError as error:
            raise OSError(
                f"No se pudo escribir el archivo JSON en {output_path}: {error}"
            ) from error

    def _safe_get_nct_id(
        self,
        candidate: Any,
    ) -> str | None:
        if not isinstance(candidate, dict):
            return None

        nct_id = candidate.get("nct_id")

        if isinstance(nct_id, str):
            return nct_id

        return None
    
    def _normalize_locations(
        self,
        raw_locations: Any,
    ) -> list[dict[str, Any]]:
        if raw_locations is None:
            return []

        if isinstance(raw_locations, dict):
            raw_locations = [raw_locations]

        if not isinstance(raw_locations, list):
            return []

        locations: list[dict[str, Any]] = []

        for location in raw_locations:
            if not isinstance(location, dict):
                continue

            contacts = location.get("contacts", [])

            if isinstance(contacts, dict):
                contacts = [contacts]

            if not isinstance(contacts, list):
                contacts = []

            normalized_contacts = []

            for contact in contacts:
                if not isinstance(contact, dict):
                    continue

                normalized_contacts.append({
                    "name": contact.get("name"),
                    "role": contact.get("role"),
                    "phone": contact.get("phone"),
                    "email": contact.get("email"),
                })

            locations.append({
                "facility": location.get("facility"),
                "city": location.get("city"),
                "state": location.get("state"),
                "country": location.get("country"),
                "status": location.get("status"),
                "contacts": normalized_contacts,
            })

        return locations
    
    def _normalize_interventions(
        self,
        raw_interventions: Any,
    ) -> list[dict[str, Any]]:
        if raw_interventions is None:
            return []

        if isinstance(raw_interventions, dict):
            raw_interventions = [raw_interventions]

        if not isinstance(raw_interventions, list):
            return []

        interventions: list[dict[str, Any]] = []

        for intervention in raw_interventions:
            if not isinstance(intervention, dict):
                continue

            interventions.append({
                "type": intervention.get("type"),
                "name": intervention.get("name"),
            })

        return interventions
    
    def _extract_date(
        self,
        date_struct: Any,
    ) -> str | None:
        if date_struct is None:
            return None

        if isinstance(date_struct, str):
            return date_struct

        if not isinstance(date_struct, dict):
            return None

        return (
            date_struct.get("date")
            or date_struct.get("year")
            or date_struct.get("monthYear")
        )
    
    def _extract_enrollment_count(
        self,
        design_module: dict[str, Any],
    ) -> int | None:
        enrollment_info = design_module.get("enrollmentInfo")

        if not isinstance(enrollment_info, dict):
            return None

        count = enrollment_info.get("count")

        if isinstance(count, int):
            return count

        if isinstance(count, str):
            try:
                return int(count)
            except ValueError:
                return None

        return None