# -*- coding: utf-8 -*-
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

sys.path.append(str(SRC_PATH))

from InputAdapter import InputAdapter

def main() -> None:
    project_root = PROJECT_ROOT

    output_path = (
        project_root
        / "data"
        / "input_adapted"
        / "runner_input_adapted_patients.json"
    )

    print("Buscando archivos XML en la carpeta data/input...")

    print("Ejecutando InputAdapter...")
    
    try:
        adapter = InputAdapter(output_path=output_path)
        ruta_guardada, datos_unificados = adapter.adapt_files()
        
    except Exception as e:
        print(f"\n Error durante la ejecución: {e}")
        return

    pacientes = datos_unificados.get("patients", [])

    print("\n" + "="*50)
    print(" Input Adapter Completado")
    print("="*50)
    print(f"Archivo JSON unificado en: {ruta_guardada}")
    print(f"Total de pacientes extraídos: {len(pacientes)}")
    print("-" * 50)
    
    if pacientes:
        print("VISTA PREVIA DE LOS PACIENTES (Primeros 5):")
        for idx, p in enumerate(pacientes[:5]):
            texto_corto = p.get('raw_text', '')[:70].replace('\n', ' ') + "..."
            print(f" [{idx+1}] ID: {p.get('patient_id')} (Source: {p.get('source')})")
            print(f"     Texto: {texto_corto}")
        
        if len(pacientes) > 5:
            print(f"     ... y {len(pacientes) - 5} pacientes más.")
    print("="*50)

if __name__ == "__main__":
    main()