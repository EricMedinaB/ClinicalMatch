# -*- coding: utf-8 -*-
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

sys.path.append(str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from patient_extractor import PatientExtractor

def main() -> None:
    project_root = PROJECT_ROOT

    output_path = (
        project_root
        / "data"
        / "extracted_patients"
        / "runner_patient_extracted.json"
    )

    input_patient = {
        "patient_id": "RUNNER-PAC-001",
        "raw_text": (
            "Paciente varón de 65 años diagnosticado de adenocarcinoma de pulmón en estadio IV. "
            "Metástasis óseas confirmadas. La biopsia es positiva para la mutación EGFR (deleción en el exón 19). "
            "Previamente tratado con Osimertinib. ECOG actual de 1."
        )
    }

    extractor = PatientExtractor()

    print(f"Ejecutando PatientExtractor con Gemini...")
    print(f"Analizando paciente: {input_patient['patient_id']}")
    
    result = extractor.extract(
        patient=input_patient,
        output_path=output_path
    )

    metadata = result.get("extractor_metadata", {})
    profile = result.get("patient_profile", {})

    print("\n" + "="*40)
    print("Patient Extractor generado")
    print("="*40)
    print(f"Archivo de salida: {output_path}")
    print(f"Patient ID: {result.get('patient_id')}")
    print(f"Status: {result.get('extraction_status')}")
    
    if result.get("extraction_status") == "failed":
        print(f"Error: {result.get('extraction_error')}")
    else:
        print(f"Intentos de LLM: {metadata.get('attempts')}")
        if profile:
            print(f"Condición: {profile.get('condition')}")
            print(f"Edad: {profile.get('age')}")
            print(f"Sexo: {profile.get('sex')}")
            
            biomarcadores = profile.get("biomarkers", [])
            if biomarcadores:
                print(f"Biomarcadores detectados: {len(biomarcadores)}")
                for b in biomarcadores:
                    print(f"  - {b.get('name')}: {b.get('status')} ({b.get('variant')})")

if __name__ == "__main__":
    main()