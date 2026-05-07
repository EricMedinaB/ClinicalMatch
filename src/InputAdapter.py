import json
import xmltodict
from pathlib import Path

class InputAdapter:
    def __init__(self, output_path: str):
        project_root = Path(__file__).resolve().parent.parent

        self.root = project_root / "data" / "input"

        self.ruta_json = Path(output_path)

        if not self.root.exists():
            raise FileNotFoundError(f"No existe la carpeta: {self.root}")
        
        if not self.root.is_dir():
            raise NotADirectoryError(f"La ruta no es una carpeta: {self.root}")

    def adapt_files(self) -> Path:
        data = []

        for file in self.root.rglob("*"):

            if not file.is_file():
                continue

            if self.is_xml(file):
                data.append(self.xml_adapter(file))
            else:
                raise ValueError(
                    f"Tipo de archivo no soportado: {file}"
                )

        if not data:
            raise ValueError(
                "La lista 'data' está vacía. No hay datos para unificar."
            )

        data = self.unify_json(data)

        self.ruta_json.parent.mkdir(parents=True, exist_ok=True)

        with open(self.ruta_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        return self.ruta_json
    

    def xml_adapter(self, ruta_xml: Path) -> dict:
        with open(ruta_xml, "r", encoding="utf-8") as f:
            parsed = xmltodict.parse(f.read())

        topics = parsed.get("topics")

        if not topics:
            raise ValueError(f"El XML no contiene la clave 'topics': {ruta_xml}")
        
        topic_list = topics.get("topic", [])

        if isinstance(topic_list, dict):
            topic_list = [topic_list]

        return {
            "patients": [
                {
                    "patient_id": f"{self.normalize_source_name(topics['@task'])}_{topic['@number']}",
                    "source_patient_id": str(topic["@number"]),
                    "source": topics["@task"],
                    "source_file": str(ruta_xml),
                    "input_format": "xml",
                    "raw_text": topic.get("#text", "").strip()
                }
                for topic in topic_list
            ]
        }
    
    def unify_json(self, data: list[dict]) -> dict:
        if not data:
            raise ValueError("La lista 'data' está vacía")

        if len(data) == 1:
            return data[0]

        unified = {
            "patients": []
        }

        for item in data:
            patients = item.get("patients", [])

            unified["patients"].extend(patients)

        self.validate_unique_patient_ids(unified["patients"])

        return unified


    def is_xml(self, file: Path) -> bool:
        return file.suffix.lower() == ".xml"
    
    def normalize_source_name(self, value: str) -> str:
        value = value.lower().strip()
        value = value.replace("trec clinical trials", "trec_ct")
        value = value.replace(" ", "_")
        return value
    
    def validate_unique_patient_ids(self, patients: list[dict]) -> None:
        seen = set()

        for patient in patients:
            patient_id = patient["patient_id"]

            if patient_id in seen:
                raise ValueError(f"patient_id duplicado: {patient_id}")

            seen.add(patient_id)
    


if __name__ == "__main__":
    inAd = InputAdapter(r"D:\Documents\ClinicalMatch\data\raw JSON\outPut.json")
    inAd.adapt_files()