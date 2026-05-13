import json
import math
from pathlib import Path


class MetricsEvaluator:
    def __init__(self):
        pass

    def load_predictions(self, predictions_path):
        """
        Carga el JSON de predicciones.

        Soporta:
        - Formato antiguo/fake:
            {
              "predictions": [
                {
                  "patient_id": "patient_001",
                  "ranked_trials": [...]
                }
              ]
            }

        - Formato PredictionExporter:
            {
              "predictions": [
                {
                  "topic_id": "1",
                  "patient_id": "1",
                  "trials": [...]
                }
              ]
            }
        """

        predictions_path = Path(predictions_path)

        with predictions_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def load_qrels(self, qrels_path):
        """
        Carga qrels.

        Soporta formato simple:
            patient_id nct_id relevance

        Ejemplo:
            patient_001 NCT001 2

        Y formato oficial TREC:
            topic_id 0 nct_id relevance

        Ejemplo:
            1 0 NCT00000409 2
        """

        qrels_path = Path(qrels_path)
        qrels = {}

        with qrels_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if line == "" or line.startswith("#"):
                    continue

                parts = line.split()

                if len(parts) == 3:
                    patient_id = parts[0]
                    nct_id = parts[1]
                    relevance = int(parts[2])

                elif len(parts) >= 4:
                    patient_id = parts[0]
                    nct_id = parts[2]
                    relevance = int(parts[3])

                else:
                    continue

                if patient_id not in qrels:
                    qrels[patient_id] = {}

                qrels[patient_id][nct_id] = relevance

        return qrels

    def recall_at_k(self, predicted_trials, relevant_trials, k=20):
        """
        Recall@K:
        De todos los ensayos relevantes reales, cuántos aparecen en el top K.
        """

        if len(relevant_trials) == 0:
            return None

        top_k = predicted_trials[:k]

        found = 0

        for nct_id in relevant_trials:
            if nct_id in top_k:
                found += 1

        return found / len(relevant_trials)

    def dcg_at_k(self, predicted_trials, relevance_by_trial, k=10):
        """
        DCG@K:
        Premia que los ensayos más relevantes estén arriba del ranking.
        """

        score = 0.0

        for index, nct_id in enumerate(predicted_trials[:k], start=1):
            relevance = relevance_by_trial.get(nct_id, 0)

            if relevance > 0:
                score += (2 ** relevance - 1) / math.log2(index + 1)

        return score

    def ndcg_at_k(self, predicted_trials, relevance_by_trial, k=10):
        """
        NDCG@K:
        DCG real dividido entre el DCG ideal.
        """

        dcg = self.dcg_at_k(
            predicted_trials=predicted_trials,
            relevance_by_trial=relevance_by_trial,
            k=k,
        )

        ideal_relevances = sorted(
            relevance_by_trial.values(),
            reverse=True,
        )

        ideal_score = 0.0

        for index, relevance in enumerate(ideal_relevances[:k], start=1):
            if relevance > 0:
                ideal_score += (2 ** relevance - 1) / math.log2(index + 1)

        if ideal_score == 0:
            return None

        return dcg / ideal_score

    def micro_f1(self, predicted_labels, gold_labels):
        """
        Micro-F1 para evaluación criterio a criterio.

        De momento queda preparado, pero no se usa en la evaluación TREC
        de ranking porque no tenemos gold labels criterio a criterio.

        predicted_labels y gold_labels deberían ser listas con valores tipo:
            met
            not_met
            not_enough_info
        """

        if not predicted_labels or not gold_labels:
            return None

        if len(predicted_labels) != len(gold_labels):
            return None

        labels = ["met", "not_met", "not_enough_info"]

        tp = 0
        fp = 0
        fn = 0

        for predicted, gold in zip(predicted_labels, gold_labels):
            for label in labels:
                if predicted == label and gold == label:
                    tp += 1
                elif predicted == label and gold != label:
                    fp += 1
                elif predicted != label and gold == label:
                    fn += 1

        if tp + fp == 0 or tp + fn == 0:
            return None

        precision = tp / (tp + fp)
        recall = tp / (tp + fn)

        if precision + recall == 0:
            return None

        return 2 * precision * recall / (precision + recall)

    def evaluate(self, predictions_data, qrels):
        """
        Calcula métricas globales sobre todos los pacientes/topics.

        Soporta dos formatos de predictions:

        1. Formato antiguo/fake:
            {
              "predictions": [
                {
                  "patient_id": "patient_001",
                  "ranked_trials": [
                    {"nct_id": "NCT001", "rank": 1, "score": 0.9}
                  ]
                }
              ]
            }

        2. Formato PredictionExporter:
            {
              "predictions": [
                {
                  "topic_id": "1",
                  "patient_id": "1",
                  "trials": [
                    {"nct_id": "NCT001", "rank": 1, "score": 0.9}
                  ]
                }
              ]
            }
        """

        patient_results = []

        recall_values = []
        ndcg_values = []

        predictions = predictions_data.get("predictions", [])

        for patient_prediction in predictions:
            patient_id = self._get_prediction_patient_id(patient_prediction)
            predicted_nct_ids = self._get_predicted_nct_ids(patient_prediction)

            relevance_by_trial = qrels.get(patient_id, {})

            relevant_trials = [
                nct_id
                for nct_id, relevance in relevance_by_trial.items()
                if relevance > 0
            ]

            recall_20 = self.recall_at_k(
                predicted_trials=predicted_nct_ids,
                relevant_trials=relevant_trials,
                k=20,
            )

            ndcg_10 = self.ndcg_at_k(
                predicted_trials=predicted_nct_ids,
                relevance_by_trial=relevance_by_trial,
                k=10,
            )

            if recall_20 is not None:
                recall_values.append(recall_20)

            if ndcg_10 is not None:
                ndcg_values.append(ndcg_10)

            patient_results.append(
                {
                    "patient_id": patient_id,
                    "num_predicted_trials": len(predicted_nct_ids),
                    "num_relevant_trials": len(relevant_trials),
                    "recall_at_20": recall_20,
                    "ndcg_at_10": ndcg_10,
                }
            )

        global_recall = (
            sum(recall_values) / len(recall_values)
            if len(recall_values) > 0
            else None
        )

        global_ndcg = (
            sum(ndcg_values) / len(ndcg_values)
            if len(ndcg_values) > 0
            else None
        )

        return {
            "metrics": {
                "recall_at_20": global_recall,
                "ndcg_at_10": global_ndcg,
                "micro_f1": None,
            },
            "notes": {
                "micro_f1": "not_available: criterion-level gold labels are not available yet",
            },
            "patients": patient_results,
        }

    def save_metrics(self, metrics, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(metrics, file, ensure_ascii=False, indent=2)

    def _get_prediction_patient_id(self, patient_prediction):
        """
        Obtiene el ID del paciente/topic desde una predicción.

        Prioridad:
        1. topic_id       -> formato PredictionExporter
        2. patient_id     -> formato antiguo o compatible
        """

        patient_id = (
            patient_prediction.get("topic_id")
            or patient_prediction.get("patient_id")
        )

        if patient_id is None:
            return None

        return str(patient_id)

    def _get_predicted_nct_ids(self, patient_prediction):
        """
        Extrae los NCT IDs predichos desde una predicción.

        Soporta:
        - ranked_trials
        - trials

        Y dentro de cada trial:
        - nct_id
        - trial_id
        """

        ranked_trials = (
            patient_prediction.get("ranked_trials")
            or patient_prediction.get("trials")
            or []
        )

        predicted_nct_ids = []

        for trial in ranked_trials:
            if not isinstance(trial, dict):
                continue

            nct_id = trial.get("nct_id") or trial.get("trial_id")

            if nct_id is None:
                continue

            predicted_nct_ids.append(str(nct_id))

        return predicted_nct_ids
