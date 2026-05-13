from pathlib import Path
from datetime import datetime, timezone
import json
import requests
import re

from rank_bm25 import BM25Okapi


class ClinicalTrialsClient:
    def __init__(
        self,
        mode="live",
        trec_year=None,
        max_results=100,
    ):
        """
        mode:
            - "live": usa la API real de ClinicalTrials.gov
            - "trec": usa el snapshot histórico de TREC / ClinicalTrials 2021

        trec_year:
            - 2021 o 2022
            - Ambos usan el mismo corpus histórico clinicaltrials/2021.
              Lo que cambia son topics/qrels, no el corpus.
        """
        self.mode = mode
        self.trec_year = trec_year
        self.max_results = max_results

        self.base_url = "https://clinicaltrials.gov/api/v2/studies"
        self.timeout = 20

        self._trec_index = None

        if self.mode not in {"live", "trec"}:
            raise ValueError("mode debe ser 'live' o 'trec'")

        if self.mode == "trec":
            if self.trec_year not in {2021, 2022}:
                raise ValueError("Para mode='trec', trec_year debe ser 2021 o 2022")

            self._load_trec_snapshot()

    def search_from_plan(self, plan, output_path=None):
        result = {
            "patient_id": plan.get("patient_id"),
            "status": "success",
            "results": [],
            "errors": [],
            "metadata": {
                "mode": self.mode,
                "trec_year": self.trec_year,
            },
        }

        query_groups = [
            ("base_queries", plan.get("base_queries", [])),
            ("refined_queries", plan.get("refined_queries", [])),
            ("fallback_queries", plan.get("fallback_queries", [])),
        ]

        for query_type, queries in query_groups:
            for index, query in enumerate(queries, start=1):
                query_id = f"{query_type}_{index}"

                try:
                    query_result = self.search_query(
                        query=query,
                        query_id=query_id,
                        query_type=query_type,
                    )

                    result["results"].append(query_result)

                except Exception as error:
                    result["errors"].append({
                        "query_id": query_id,
                        "query_type": query_type,
                        "query": query,
                        "error": str(error),
                    })

        if len(result["results"]) == 0:
            result["status"] = "api_error"

        elif len(result["errors"]) > 0:
            result["status"] = "partial_result"

        self._write_json(result, output_path)

        return result

    def search_query(self, query, query_id, query_type):
        if self.mode == "live":
            return self._search_query_live(query, query_id, query_type)

        if self.mode == "trec":
            return self._search_query_trec(query, query_id, query_type)

        raise ValueError(f"Modo no soportado: {self.mode}")

    # ------------------------------------------------------------------
    # MODO LIVE: ClinicalTrials.gov actual
    # ------------------------------------------------------------------

    def _search_query_live(self, query, query_id, query_type):
        response = requests.get(
            self.base_url,
            params=query,
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()
        studies = self._extract_studies_from_live_api(data)

        status = "success"
        if len(studies) == 0:
            status = "no_results"

        return {
            "query_id": query_id,
            "query_type": query_type,
            "query": query,
            "status": status,
            "total_found": len(studies),
            "studies": studies,
            "api_metadata": {
                "source": "ClinicalTrials.gov live API",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _extract_studies_from_live_api(self, data):
        studies = []

        for study in data.get("studies", []):
            protocol = study.get("protocolSection", {})
            identification = protocol.get("identificationModule", {})
            nct_id = identification.get("nctId")

            if nct_id is not None:
                studies.append({
                    "nct_id": nct_id,
                    "raw": study,
                })

        return studies

    # ------------------------------------------------------------------
    # MODO TREC: snapshot histórico local
    # ------------------------------------------------------------------

    def _load_trec_snapshot(self):
        """
        Carga el snapshot histórico clinicaltrials/2021 usando ir_datasets.

        Este corpus es el que debes usar para evaluar contra qrels antiguos.
        TREC 2021 y TREC 2022 usan la misma colección documental.
        """
        import ir_datasets

        dataset = ir_datasets.load("clinicaltrials/2021")

        docs = []
        tokenized_docs = []

        for doc in dataset.docs_iter():
            raw = self._convert_ir_dataset_doc_to_api_like_raw(doc)

            searchable_text = self._build_searchable_text_from_doc(doc)
            tokens = self._tokenize(searchable_text)

            docs.append({
                "nct_id": doc.doc_id,
                "raw": raw,
                "searchable_text": searchable_text,
            })

            tokenized_docs.append(tokens)

        self._trec_index = {
            "docs": docs,
            "bm25": BM25Okapi(tokenized_docs),
        }

    def _search_query_trec(self, query, query_id, query_type):
        if self._trec_index is None:
            raise RuntimeError("El índice TREC no está cargado")

        query_text = self._query_dict_to_text(query)
        query_tokens = self._tokenize(query_text)

        if not query_tokens:
            studies = []
        else:
            bm25 = self._trec_index["bm25"]
            docs = self._trec_index["docs"]

            scores = bm25.get_scores(query_tokens)

            ranked_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True,
            )

            studies = []

            for rank, doc_index in enumerate(ranked_indices[:self.max_results], start=1):
                score = float(scores[doc_index])

                if score <= 0:
                    continue

                doc = docs[doc_index]

                studies.append({
                    "nct_id": doc["nct_id"],
                    "score": score,
                    "rank": rank,
                    "raw": doc["raw"],
                })

        status = "success"
        if len(studies) == 0:
            status = "no_results"

        return {
            "query_id": query_id,
            "query_type": query_type,
            "query": query,
            "status": status,
            "total_found": len(studies),
            "studies": studies,
            "api_metadata": {
                "source": "TREC ClinicalTrials 2021 snapshot",
                "trec_year": self.trec_year,
                "corpus": "clinicaltrials/2021",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _convert_ir_dataset_doc_to_api_like_raw(self, doc):
        """
        Convierte un documento de ir_datasets a una estructura parecida
        a la API v2 de ClinicalTrials.gov.

        No es idéntica a la API real, pero mantiene una estructura cómoda
        para tu pipeline.
        """
        return {
            "protocolSection": {
                "identificationModule": {
                    "nctId": doc.doc_id,
                    "briefTitle": getattr(doc, "title", None),
                },
                "conditionsModule": {
                    "conditions": self._as_list(getattr(doc, "condition", None)),
                },
                "descriptionModule": {
                    "briefSummary": getattr(doc, "summary", None),
                    "detailedDescription": getattr(doc, "detailed_description", None),
                },
                "eligibilityModule": {
                    "eligibilityCriteria": getattr(doc, "eligibility", None),
                },
            }
        }

    def _build_searchable_text_from_doc(self, doc):
        fields = [
            getattr(doc, "title", ""),
            getattr(doc, "condition", ""),
            getattr(doc, "summary", ""),
            getattr(doc, "detailed_description", ""),
            getattr(doc, "eligibility", ""),
        ]

        return " ".join(str(field) for field in fields if field)

    def _query_dict_to_text(self, query):
        """
        Convierte los parámetros de la API a texto para buscar localmente.

        Ejemplo de query real:
            {
                "query.cond": "breast cancer",
                "query.term": "HER2",
                "pageSize": 50
            }

        Para el modo TREC nos quedamos solo con el contenido semántico.
        """
        if isinstance(query, str):
            return query

        if not isinstance(query, dict):
            return str(query)

        ignored_keys = {
            "pageSize",
            "pageToken",
            "format",
            "countTotal",
            "sort",
            "fields",
        }

        useful_parts = []

        preferred_keys = [
            "query.term",
            "query.cond",
            "query.intr",
            "query.titles",
            "query.outc",
            "query.spons",
            "query.lead",
            "query.id",
            "filter.ids",
        ]

        for key in preferred_keys:
            value = query.get(key)
            if value:
                useful_parts.append(str(value))

        for key, value in query.items():
            if key in ignored_keys:
                continue

            if key in preferred_keys:
                continue

            if value is None:
                continue

            useful_parts.append(str(value))

        return " ".join(useful_parts)

    def _tokenize(self, text):
        if text is None:
            return []

        text = str(text).lower()

        return re.findall(r"[a-z0-9]+", text)

    def _as_list(self, value):
        if value is None:
            return []

        if isinstance(value, list):
            return value

        return [value]

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    def _write_json(self, result, output_path):
        if output_path is None:
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)