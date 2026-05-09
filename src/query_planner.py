class QueryPlanner:
    def build_plan(self, patient):
        condition = patient.get("condition")
        biomarkers = patient.get("biomarkers") or []
        prior_treatments = patient.get("prior_treatments") or []

        plan = {
            #Busca ensayos cuya condicion sea condition
            "base_queries": [],
            #Busca ensayos cuya condicion sea condition y relacionado con un biomarker o tratamiento
            "refined_queries": [],
            #Busca ensayos en los que se mencione en el titulo u otro espacio condition
            "fallback_queries": [],
            "status": "ready"
        }

        if condition is None:
            plan["status"] = "failed"
            plan["error"] = "El paciente no tiene condición"
            return plan

        base_query = {
            "query.cond": condition,
            "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING",
            "pageSize": 20,
            "format": "json"
        }

        plan["base_queries"].append(base_query)

        for biomarker in biomarkers:
            biomarker_name = biomarker.get("name")

            if biomarker_name is not None:
                query = {
                    "query.cond": condition,
                    "query.term": biomarker_name,
                    "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING",
                    "pageSize": 20,
                    "format": "json"
                }

                plan["refined_queries"].append(query)

        for treatment in prior_treatments:
            query = {
                "query.cond": condition,
                "query.term": treatment,
                "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING",
                "pageSize": 20,
                "format": "json"
            }

            plan["refined_queries"].append(query)

        fallback_query = {
            "query.term": condition,
            "pageSize": 20,
            "format": "json"
        }

        plan["fallback_queries"].append(fallback_query)

        if len(plan["refined_queries"]) == 0:
            plan["status"] = "fallback_required"

        return plan