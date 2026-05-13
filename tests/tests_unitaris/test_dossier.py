from pathlib import Path

from dossier_generator import DossierGenerator


def main():
    input_path = Path("data/fixtures/test_ranking_output.json")
    output_path = Path("outputs/dossiers/test_dossier.pdf")

    generator = DossierGenerator()

    ranking_output = generator.load_json(input_path)

    generator.generate_pdf(
        ranking_output=ranking_output,
        output_path=output_path,
        top_k=5,
    )

    print("Dossier PDF generado en:", output_path.absolute())


if __name__ == "__main__":
    main()