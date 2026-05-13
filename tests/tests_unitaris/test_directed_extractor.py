# -*- coding: utf-8 -*-
import sys
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

os.environ["GEMINI_FLASH_MODEL"] = "gemini-3-flash-preview"
os.environ["GEMINI_FLASH_LITE_MODEL"] = "gemini-3.1-flash-lite-preview"

from src.LLM.LLM_factory import LLMSize, create_llm
from src.directed_extractor import DirectedPatientExtractor

def run_tests():
    print("Iniciando pruebas del Módulo 10 (Directed Patient Extractor)...\n")
    print(" Cargando modelo LLM (SMALL para pruebas ágiles)...")
    
    client = create_llm(LLMSize.SMALL)
    extractor = DirectedPatientExtractor(llm_client=client, registry_id="test_registry_v1")
    
    registro_ensayos_test = {
        "attributes": [
            {"name": "prior_temozolomide", "type": "boolean", "required_by_trials": ["NCT_001"]},
            {"name": "prior_bevacizumab", "type": "boolean", "aliases": ["Avastin"], "required_by_trials": ["NCT_001"]},
            {"name": "tumor_resectability", "type": "string", "required_by_trials": ["NCT_002"]},
            {"name": "prior_radiation", "type": "boolean", "required_by_trials": ["NCT_001", "NCT_002"]},
            {"name": "ECOG", "type": "integer", "required_by_trials": ["NCT_001"]}
        ]
    }
    
    perfil_alex_test = {
        "patient_id": "2021_trec_ct_6",
        "source_patient_id": "6",
        "source": "2021 TREC Clinical Trials",
        "source_file": "topics2021.xml",
        "input_format": "xml",
        "raw_text": (
            "Patient is a 55yo woman with a history of recurrent glioblastoma. "
            "She has undergone prior radiation therapy and completed a prior course of chemotherapy "
            "with temozolomide (TMZ) as well as treatment with bevacizumab (Avastin). "
            "Recent brain MRI shows tumor progression, and the neurosurgical evaluation concluded "
            "that the tumor status is unresectable. No official ECOG performance score was recorded in this session."
        ),
        "patient_profile": {
            "condition": "Glioblastoma",
            "condition_confidence": 1.0,
            "subtype": "recurrent",
            "stage": "IV",
            "metastatic": True,
            "age": 55,
            "sex": "female",
            "biomarkers": [],
            "prior_treatments": ["radiation", "temozolomide", "bevacizumab"],
            "current_treatments": [],
            "treatment_line": None,
            "progression_after": [],
            "location": None,
            "evidence": [],
            "extraction_notes": []
        },
        "extraction_status": "rich",
        "extraction_error": None,
        "extractor_metadata": {
            "module": "PatientExtractor",
            "model_size": "SMALL",
            "attempts": 1
        }
    }
    
    print("\n Ejecutando extracción dirigida con Gemini...")
    ruta_salida = PROJECT_ROOT / "data" / "directed_extractions" / "resultado_test_mod10.json"
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        resultado = extractor.extract(
            normalized_profile=perfil_alex_test,
            attribute_registry=registro_ensayos_test,
            output_path=ruta_salida
        )
    except Exception as e:
        print(f"  ERROR CRÍTICO durante la extracción: {e}")
        return

    print("\n" + "="*50)
    print(" RESULTADOS DE LA PRUEBA (TOPIC 1)")
    print("="*50)

    def buscar_atributo(lista_atributos, palabra_clave):
        for attr in lista_atributos:
            if palabra_clave.lower() in attr.attribute_id.lower() or palabra_clave.lower() in attr.canonical_name.lower():
                return attr
        return None

    attr_tmz = buscar_atributo(resultado.attributes, "temozolomide")
    if attr_tmz and attr_tmz.status == "found" and str(attr_tmz.value).lower() == "true":
        print(" TEST 1 PASADO: 'prior_temozolomide' detectado correctamente.")
    else:
        print(f" TEST 1 FALLADO: temozolomide incorrecto. Estado: {attr_tmz.status if attr_tmz else 'No encontrado'}")

    attr_bev = buscar_atributo(resultado.attributes, "bevacizumab") or buscar_atributo(resultado.attributes, "avastin")
    if attr_bev and attr_bev.status == "found" and str(attr_bev.value).lower() == "true":
        print(" TEST 2 PASADO: 'prior_bevacizumab' detectado correctamente.")
    else:
        print(f" TEST 2 FALLADO: bevacizumab incorrecto. Estado: {attr_bev.status if attr_bev else 'No encontrado'}")

    attr_ecog = buscar_atributo(resultado.attributes, "ecog")
    if attr_ecog and attr_ecog.status == "not_found":
        print(" TEST 3 PASADO: 'ECOG' detectado como not_found de forma segura.")
        print(f"   ↳ Pregunta generada: {getattr(attr_ecog, 'missing_question', 'Ninguna')}")
    else:
        print(f" TEST 3 FALLADO: ECOG incorrecto. Estado: {attr_ecog.status if attr_ecog else 'No encontrado'}")

    attr_resect = buscar_atributo(resultado.attributes, "resectability") or buscar_atributo(resultado.attributes, "tumor")
    if attr_resect and attr_resect.status == "found" and "unresectable" in str(attr_resect.value).lower():
        print("TEST 4 PASADO: 'tumor_resectability' extraído correctamente como unresectable.")
    else:
         print(f" TEST 4 FALLADO: tumor_resectability incorrecto. Valor: {attr_resect.value if attr_resect else 'No encontrado'}")

    print("-" * 50)
    print(f" El JSON completo se ha guardado en:\n  ↳ {ruta_salida}")
    print("="*50)

if __name__ == "__main__":
    run_tests()
