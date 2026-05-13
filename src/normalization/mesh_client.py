import requests


class MeshClient:
    def __init__(self):
        self.lookup_url = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
        self.timeout = 20

    def search_descriptor(self, label, match="exact", limit=5):
        params = {
            "label": label,
            "match": match,
            "limit": limit,
        }

        response = requests.get(
            self.lookup_url,
            params=params,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()

    def normalize_mesh_result(self, result):
        resource = result.get("resource")
        label = result.get("label")

        mesh_id = None

        if resource:
            mesh_id = resource.rstrip("/").split("/")[-1]

        return {
            "mesh_id": mesh_id,
            "mesh_term": label,
            "resource": resource,
        }

    def find_best_descriptor(self, label):
        exact_results = self.search_descriptor(
            label=label,
            match="exact",
            limit=5,
        )

        if len(exact_results) == 1:
            normalized = self.normalize_mesh_result(exact_results[0])
            normalized["status"] = "normalized"
            normalized["method"] = "mesh_api_exact_match"
            normalized["confidence"] = 0.95
            return normalized

        if len(exact_results) > 1:
            return {
                "status": "multiple_candidates",
                "method": "mesh_api_exact_match",
                "confidence": 0.5,
                "candidates": [
                    self.normalize_mesh_result(item)
                    for item in exact_results
                ],
            }

        contains_results = self.search_descriptor(
            label=label,
            match="contains",
            limit=5,
        )

        if len(contains_results) == 1:
            normalized = self.normalize_mesh_result(contains_results[0])
            normalized["status"] = "low_confidence"
            normalized["method"] = "mesh_api_contains_match"
            normalized["confidence"] = 0.65
            return normalized

        if len(contains_results) > 1:
            return {
                "status": "multiple_candidates",
                "method": "mesh_api_contains_match",
                "confidence": 0.4,
                "candidates": [
                    self.normalize_mesh_result(item)
                    for item in contains_results
                ],
            }

        return {
            "status": "no_match",
            "method": "mesh_api_no_match",
            "confidence": 0.0,
        }