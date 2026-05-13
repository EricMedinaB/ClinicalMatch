# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from attribute_registry import AttributeRegistryBuilder

def main() -> None:
    project_root = PROJECT_ROOT

    input_path = (
        project_root
        / "data"
        / "parsed_trial_criteria"
        / "trial_candidates_with_criteria_real.json"
    )

    output_path = (
        project_root
        / "data"
        / "attribute_registries"
        / "attribute_registry.json"
    )

    print(" Ejecutando Módulo 9 (Attribute Registry Builder) con datos reales...")
    
    if not input_path.exists():
        print(f" ERROR: No se encuentra el archivo de criterios en {input_path}")
        print("Asegúrate de haber ejecutado el Módulo 8 antes de correr este test.")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        candidate_json = json.load(f)

    builder = AttributeRegistryBuilder(
        include_soft_criteria=True,
        include_administrative_criteria=False  
    )

    registry_result = builder.build_from_candidate_json(
        candidate_json=candidate_json,
        output_path=output_path
    )

    status = registry_result.get("registry_status")
    summary = registry_result.get("summary", {})
    flags = registry_result.get("flags", [])

    print("\n" + "="*50)
    print("Registro de Atributos Clínicos Consolidado")
    print("="*50)
    print(f" Archivo de entrada: {input_path.name}")
    print(f" Archivo de salida:  {output_path.name}")
    print(f"\n👤 Patient ID:           {registry_result.get('patient_id')}")
    print(f" Estado del Registro:  {status.upper()}")
    print("-" * 50)
    print(" RESUMEN DE CONSOLIDACIÓN:")
    print(f"  Ensayos analizados:    {summary.get('total_trials', 0)}")
    print(f"  Criterios mapeados:    {summary.get('total_source_criteria', 0)}")
    print(f"  Variables únicas:      {summary.get('total_attributes', 0)} (¡Atributos deduplicados!)")
    print("-" * 50)
    print(" CRITICIDAD Y RAZONAMIENTO:")
    print(f"  Prioridad Alta (High): {summary.get('high_criticality_attributes', 0)}")
    print(f"  Prioridad Media (Med): {summary.get('medium_criticality_attributes', 0)}")
    print(f"  Lógica Temporal:       {summary.get('temporal_attributes', 0)}")
    print(f"  Sensibles a Negación:  {summary.get('negation_sensitive_attributes', 0)}")
    print("="*50)

    if flags:
        print(f"\n Se registraron {len(flags)} advertencias menores durante el proceso:")
        for flag in flags:
            print(f"  ↳ [{flag.get('type')}]: {flag.get('message')}")

    print(f"\n Proceso completado. Datos listos para el Extractor Dirigido.")

if __name__ == "__main__":
    main()

