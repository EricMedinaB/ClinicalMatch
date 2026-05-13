from pathlib import Path

from metrics.metrics_evaluator import MetricsEvaluator


def main():
    evaluator = MetricsEvaluator()

    predictions_path = Path("outputs/predictions/test_predictions.json")
    qrels_path = Path("data/trec/qrels2022.txt")
    output_path = Path("outputs/metrics/test_metrics.json")

    predictions = evaluator.load_predictions(predictions_path)
    qrels = evaluator.load_qrels(qrels_path)

    metrics = evaluator.evaluate(
        predictions_data=predictions,
        qrels=qrels,
    )

    evaluator.save_metrics(metrics, output_path)

    print("MÉTRICAS GENERADAS")
    print("==================")
    print(metrics["metrics"])
    print()
    print("Guardado en:", output_path.absolute())


if __name__ == "__main__":
    main()