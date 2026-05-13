import json
from pathlib import Path

import matplotlib.pyplot as plt


class MetricsPlotter:
    def load_metrics(self, metrics_path):
        metrics_path = Path(metrics_path)

        with metrics_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def plot_metrics(self, metrics_data, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        metrics = metrics_data.get("metrics", {})

        labels = []
        values = []

        metric_names = {
            "recall_at_20": "Recall@20",
            "ndcg_at_10": "NDCG@10",
            "micro_f1": "Micro-F1",
        }

        for key, label in metric_names.items():
            value = metrics.get(key)

            # Si la métrica es None, no la dibujamos.
            # Por ahora Micro-F1 saldrá como None porque aún no tenemos criterios evaluados.
            if value is None:
                continue

            labels.append(label)
            values.append(value)

        if len(labels) == 0:
            raise ValueError("No hay métricas disponibles para graficar")

        plt.figure(figsize=(8, 5))
        bars = plt.bar(labels, values)

        plt.ylim(0, 1)
        plt.ylabel("Score")
        plt.title("ClinicalMatch Evaluation Metrics")

        for bar, value in zip(bars, values):
            plt.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.02,
                f"{value:.3f}",
                ha="center",
                va="bottom",
            )

        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()

        return output_path


def main():
    plotter = MetricsPlotter()

    metrics_path = Path("outputs/metrics/test_metrics.json")
    output_path = Path("outputs/plots/test_metrics.png")

    metrics_data = plotter.load_metrics(metrics_path)
    plotter.plot_metrics(metrics_data, output_path)

    print("Gráfica generada en:", output_path.absolute())


if __name__ == "__main__":
    main()