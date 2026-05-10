from pathlib import Path
from datetime import datetime, timezone
import json
import requests

class ClinicalTrialsClient:
    def __init__(self):
        self.base_url = "https://clinicaltrials.gov/api/v2/studies"
        self.timeout = 20
    
    def search_from_plan(self, plan, output_path=None):
        result = {
            "patient_id": plan.get("patient_id"),
            "status": "success",
            "results": [],
            "errors": [],
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
        #Requests monta la URL juntando la base_url con los parametros de query
        response = requests.get(
            self.base_url,
            params=query,
            timeout=self.timeout,
        )
        #Comprueba si la respuesta es correcta (status code 200), si no lo es lanza una excepcion
        response.raise_for_status()

        #Convierte la respuesta JSON en un diccionario de Python
        data = response.json()
        studies = self._extract_studies(data)
        status = "success"
        if(len (studies) == 0):
            status = "no_results"
        
        return {
            "query_id": query_id,
            "query_type": query_type,
            "query": query,
            "status": status,
            "total_found": len(studies),
            "studies": studies,
            "api_metadata": {
                "source": "ClinicalTrials.gov",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    #Funcion para quedarnos con el ntc_id y la informacion de cada estudio de forma ordenada
    def _extract_studies(self, data):
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
    
    def _write_json(self, result, output_path):
        if output_path is None:
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
