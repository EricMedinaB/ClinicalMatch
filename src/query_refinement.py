from pathlib import Path
from typing import Any
import json


class QueryRefinementLoop:
    def __init__(
        self,
        min_candidates: int = 20,
        target_candidates: int = 50,
        max_candidates: int = 150,
        max_queries_per_patient: int = 8,
        allow_fallback_queries: bool = True,
    ) -> None:
        if min_candidates < 0:
            raise ValueError("min_candidates no puede ser negativo")

        if target_candidates < min_candidates:
            raise ValueError("target_candidates debe ser >= min_candidates")

        if max_candidates < target_candidates:
            raise ValueError("max_candidates debe ser >= target_candidates")

        if max_queries_per_patient <= 0:
            raise ValueError("max_queries_per_patient debe ser > 0")

        self.min_candidates = min_candidates
        self.target_candidates = target_candidates
        self.max_candidates = max_candidates
        self.max_queries_per_patient = max_queries_per_patient
        self.allow_fallback_queries = allow_fallback_queries

    def refine_from_api_result(
        self,
        api_result: dict[str, Any],
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        self._validate_api_result(api_result)

        warnings: list[dict[str, Any]] = []

        patient_id = api_result.get("patient_id")

        selected_results = self._select_query_results(
            api_result=api_result,
            warnings=warnings,
        )

        unique_studies = self._deduplicate_studies(
            query_results=selected_results,
            warnings=warnings,
        )

        total_unique_candidates_before_truncation = len(unique_studies)
        was_truncated = False

        if len(unique_studies) > self.max_candidates:
            was_truncated = True
            warnings.append({
                "type": "candidates_truncated",
                "message": "Se han truncado candidatos para no saturar etapas posteriores",
                "before": len(unique_studies),
                "after": self.max_candidates,
            })
            unique_studies = unique_studies[: self.max_candidates]

        total_raw_candidates = sum(
            len(query_result.get("studies", []))
            for query_result in selected_results
            if isinstance(query_result.get("studies", []), list)
        )

        total_unique_candidates = len(unique_studies)

        status = self._decide_status(
            total_unique_candidates=total_unique_candidates_before_truncation,
            api_errors=api_result.get("errors", []),
        )

        refined_result: dict[str, Any] = {
            "patient_id": patient_id,
            "status": status,
            "total_raw_candidates": total_raw_candidates,
            "total_unique_candidates_before_truncation": total_unique_candidates_before_truncation,
            "total_unique_candidates": total_unique_candidates,
            "was_truncated": was_truncated,
            "min_candidates": self.min_candidates,
            "target_candidates": self.target_candidates,
            "max_candidates": self.max_candidates,
            "max_queries_per_patient": self.max_queries_per_patient,
            "allow_fallback_queries": self.allow_fallback_queries,
            "used_query_ids": [
                query_result.get("query_id")
                for query_result in selected_results
            ],
            "used_query_types": self._get_used_query_types(selected_results),
            "unique_studies": unique_studies,
            "errors": api_result.get("errors", []),
            "warnings": warnings,
        }

        self._write_json(refined_result, output_path)

        return refined_result

    def _validate_api_result(self, api_result: dict[str, Any]) -> None:
        if not isinstance(api_result, dict):
            raise TypeError("api_result debe ser un diccionario")

        if "results" not in api_result:
            raise ValueError("api_result no contiene la clave obligatoria 'results'")

        if not isinstance(api_result["results"], list):
            raise TypeError("api_result['results'] debe ser una lista")

        if "errors" in api_result and not isinstance(api_result["errors"], list):
            raise TypeError("api_result['errors'] debe ser una lista")

    def _select_query_results(
        self,
        api_result: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = api_result.get("results", [])

        valid_results: list[dict[str, Any]] = []

        for index, result in enumerate(results):
            if not isinstance(result, dict):
                warnings.append({
                    "type": "invalid_query_result",
                    "message": "Se ha ignorado un resultado porque no es un diccionario",
                    "index": index,
                })
                continue

            query_id = result.get("query_id")
            query_type = result.get("query_type")
            studies = result.get("studies", [])

            if query_id is None:
                warnings.append({
                    "type": "missing_query_id",
                    "message": "Resultado sin query_id",
                    "index": index,
                })

            if query_type not in {
                "base_queries",
                "refined_queries",
                "fallback_queries",
            }:
                warnings.append({
                    "type": "unknown_query_type",
                    "message": "Resultado con query_type desconocido",
                    "index": index,
                    "query_id": query_id,
                    "query_type": query_type,
                })
                continue

            if not isinstance(studies, list):
                warnings.append({
                    "type": "invalid_studies",
                    "message": "Resultado con studies no válido; se tratará como lista vacía",
                    "index": index,
                    "query_id": query_id,
                })
                result = dict(result)
                result["studies"] = []

            valid_results.append(result)

        selected_results: list[dict[str, Any]] = []

        refined_results = [
            result for result in valid_results
            if result.get("query_type") == "refined_queries"
        ]

        base_results = [
            result for result in valid_results
            if result.get("query_type") == "base_queries"
        ]

        fallback_results = [
            result for result in valid_results
            if result.get("query_type") == "fallback_queries"
        ]

        # 1. Primero refined queries: suelen ser más específicas.
        self._append_until_threshold(
            selected_results=selected_results,
            candidate_results=refined_results,
            stop_threshold=self.target_candidates,
            warnings=warnings,
        )

        # 2. Si hay pocos candidatos, añadimos base queries para mejorar recall.
        # Importante: no pasamos `warnings` para evitar warnings duplicados
        # durante cálculos internos.
        unique_count = len(self._deduplicate_studies(selected_results))

        if unique_count < self.min_candidates:
            self._append_until_threshold(
                selected_results=selected_results,
                candidate_results=base_results,
                stop_threshold=self.min_candidates,
                warnings=warnings,
            )

        # 3. Si todavía hay pocos, añadimos fallback queries.
        # Importante: no pasamos `warnings` para evitar warnings duplicados
        # durante cálculos internos.
        unique_count = len(self._deduplicate_studies(selected_results))

        if unique_count < self.min_candidates and self.allow_fallback_queries:
            self._append_until_threshold(
                selected_results=selected_results,
                candidate_results=fallback_results,
                stop_threshold=self.min_candidates,
                warnings=warnings,
            )

        if len(selected_results) == 0:
            warnings.append({
                "type": "no_selected_results",
                "message": "No se ha seleccionado ninguna query válida",
            })

        return selected_results

    def _append_until_threshold(
        self,
        selected_results: list[dict[str, Any]],
        candidate_results: list[dict[str, Any]],
        stop_threshold: int,
        warnings: list[dict[str, Any]],
    ) -> None:
        for result in candidate_results:
            if len(selected_results) >= self.max_queries_per_patient:
                warnings.append({
                    "type": "max_queries_reached",
                    "message": "Se ha alcanzado el máximo de queries por paciente",
                    "max_queries_per_patient": self.max_queries_per_patient,
                })
                break

            selected_results.append(result)

            # Importante: no pasamos `warnings` para evitar warnings duplicados
            # durante cálculos internos.
            unique_count = len(self._deduplicate_studies(selected_results))

            if unique_count >= stop_threshold:
                break

    def _deduplicate_studies(
        self,
        query_results: list[dict[str, Any]],
        warnings: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        studies_by_nct_id: dict[str, dict[str, Any]] = {}

        if warnings is None:
            warnings = []

        for query_index, query_result in enumerate(query_results):
            if not isinstance(query_result, dict):
                warnings.append({
                    "type": "invalid_query_result",
                    "message": "Query result ignorado durante deduplicación porque no es un diccionario",
                    "index": query_index,
                })
                continue

            query_id = query_result.get("query_id")
            query_type = query_result.get("query_type")
            studies = query_result.get("studies", [])

            if not isinstance(studies, list):
                warnings.append({
                    "type": "invalid_studies",
                    "message": "Studies ignorado durante deduplicación porque no es una lista",
                    "query_id": query_id,
                })
                continue

            for study_index, study in enumerate(studies):
                if not isinstance(study, dict):
                    warnings.append({
                        "type": "invalid_study",
                        "message": "Estudio ignorado porque no es un diccionario",
                        "query_id": query_id,
                        "study_index": study_index,
                    })
                    continue

                nct_id = study.get("nct_id")

                if not isinstance(nct_id, str) or not nct_id.strip():
                    warnings.append({
                        "type": "missing_nct_id",
                        "message": "Estudio ignorado porque no tiene nct_id válido",
                        "query_id": query_id,
                        "study_index": study_index,
                    })
                    continue

                nct_id = nct_id.strip()

                if nct_id not in studies_by_nct_id:
                    studies_by_nct_id[nct_id] = {
                        "nct_id": nct_id,
                        "raw": study.get("raw"),
                        "retrieved_by": [],
                    }

                retrieved_entry = {
                    "query_id": query_id,
                    "query_type": query_type,
                }

                if retrieved_entry not in studies_by_nct_id[nct_id]["retrieved_by"]:
                    studies_by_nct_id[nct_id]["retrieved_by"].append(retrieved_entry)

        return list(studies_by_nct_id.values())

    def _decide_status(
        self,
        total_unique_candidates: int,
        api_errors: list[Any],
    ) -> str:
        if total_unique_candidates == 0:
            return "retrieval_failed"

        if total_unique_candidates < self.min_candidates:
            return "too_few_candidates"

        if total_unique_candidates > self.max_candidates:
            return "too_many_candidates"

        if len(api_errors) > 0:
            return "partial_result"

        return "within_target_range"

    def _write_json(
        self,
        result: dict[str, Any],
        output_path: str | Path | None,
    ) -> None:
        if output_path is None:
            return

        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8") as file:
                json.dump(result, file, ensure_ascii=False, indent=2)

        except OSError as error:
            raise OSError(f"No se pudo escribir el archivo JSON en {output_path}: {error}") from error

    def _get_used_query_types(
        self,
        selected_results: list[dict[str, Any]],
    ) -> list[str]:
        query_types: set[str] = set()

        for query_result in selected_results:
            query_type = query_result.get("query_type")

            if isinstance(query_type, str):
                query_types.add(query_type)

        return sorted(query_types)