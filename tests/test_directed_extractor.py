# -*- coding: utf-8 -*-
import json
import os
from pathlib import Path


# ==========================================
# OPCIÓN NUCLEAR: INYECTAR VARIABLES DIRECTAMENTE
# ==========================================q 

# Ponemos el modelo que pide vuestra factoría
os.environ["GEMINI_FLASH_MODEL"] = "gemini-3-flash-preview"
os.environ["GEMINI_FLASH_LITE_MODEL"] = "gemini-3.1-flash-lite-preview"

# ==========================================
# AHORA SÍ, IMPORTAMOS LA IA Y TU CÓDIGO
# ==========================================
from src.LLM.LLM_factory import LLMSize, create_llm
from src.directed_extractor import DirectedPatientExtractor

def run_tests():
    print("Iniciando pruebas del Módulo 10 (Directed Patient Extractor)...\n")

    # 1. INICIALIZAR EL CLIENTE LLM (Usando tu factoría)
    print("Cargando modelo LLM (LARGE recomendado para extracciones complejas)...")
    client = create_llm(LLMSize.SMALL)
    extractor = DirectedPatientExtractor(llm_client=client, registry_id="test_registry_v1")

# 2. DATOS DE PRUEBA SIMULADOS (MOCK DATA)
    
    # Simulamos qué atributos pedirían los ensayos para este cáncer:
    registro_ensayos_test = {
        "attributes": [
            {"name": "prior_temozolomide", "type": "boolean", "required_by_trials": ["NCT_001"]},
            {"name": "prior_bevacizumab", "type": "boolean", "aliases": ["Avastin"], "required_by_trials": ["NCT_001"]},
            {"name": "tumor_resectability", "type": "string", "required_by_trials": ["NCT_002"]},
            {"name": "prior_radiation", "type": "boolean", "required_by_trials": ["NCT_001", "NCT_002"]},
            {"name": "ECOG", "type": "integer", "required_by_trials": ["NCT_001"]}
        ]
    }

    # Simulamos lo que te mandaría Alex, metiendo tu Topic 1 en el raw_text:
    perfil_alex_test = {
        "patient_id": "2021_trec_ct_6",
        "source_patient_id": "6",
        "source": "2021 TREC Clinical Trials",
        "source_file": "D:\\Documents\\ClinicalMatch\\data\\input\\topics2021.xml",
        "input_format": "xml",
        "raw_text": "Patient is a 55yo woman with h/o ESRD on HD and peritoneal dialysis who presented with watery, non bloody diarrhea and weakness. She has a history of 2 prior C diff infections, the most recent just 1 month ago. Recent antibx use in the last month on prior admission. Was also txd for Cdiff at that time for 14 d. course with po vanco. Pt was initially admitted to the ICU and was septic on pressors (levophed) until the morning of [**8-26**] with leukocytosis but no fever. C diff assay positive on admission, and pt had leukocytosis consistent with C diff. Patient was placed on Vanco po, Flagyl IV and Flagyl po initially, and when patient improved she was transitioned to Vanco oral and Flagyl oral on [**8-29**]. Patient was treated with Vanco for an extended course of 6 weeks given her recurrent C diff. Pt was also encouraged to take probiotics and to bleach her home when she was discharged.",
        "patient_profile": {
          "condition": "recurrent Clostridioides difficile infection",
          "condition_confidence": 1.0,
          "subtype": "recurrent",
          "stage": None,
          "metastatic": None,
          "age": 55,
          "sex": "female",
          "biomarkers": [],
          "prior_treatments": [
            "antibiotics",
            "vancomycin"
          ],
          "current_treatments": [
            "vancomycin",
            "metronidazole",
            "probiotics"
          ],
          "treatment_line": None,
          "progression_after": [],
          "location": None,
          "evidence": [
            {
              "field": "condition",
              "evidence": "recurrent C diff infections",
              "confidence": None
            },
            {
              "field": "age",
              "evidence": "55yo",
              "confidence": None
            },
            {
              "field": "sex",
              "evidence": "woman",
              "confidence": None
            },
            {
              "field": "prior_treatments",
              "evidence": "txd for Cdiff at that time for 14 d. course with po vanco",
              "confidence": None
            },
            {
              "field": "current_treatments",
              "evidence": "transitioned to Vanco oral and Flagyl oral",
              "confidence": None
            }
          ],
          "extraction_notes": [
            "Patient has ESRD on HD and PD, but recurrent C. difficile infection is the primary reason for admission and trial-relevant condition.",
            "Flagyl is normalized to metronidazole per instructions.",
            "Vanco is normalized to vancomycin per instructions."
          ]
        },
        "extraction_status": "rich",
        "extraction_error": None,
        "extractor_metadata": {
          "module": "PatientExtractor",
          "model_size": "SMALL",
          "model_name": "gemini-3.1-flash-lite-preview",
          "temperature": 0.0,
          "prompt_version": "patient_extractor_v1",
          "schema_version": "patient_profile_v1",
          "attempts": 1
        }
    }

    # 3. EJECUTAR EL EXTRACTOR
    print("\nEjecutando extracción...")
    ruta_salida = Path("outputs/tests/resultado_test_mod10.json")
    
    try:
        resultado = extractor.extract(
            normalized_profile=perfil_alex_test,
            attribute_registry=registro_ensayos_test,
            output_path=ruta_salida
        )
    except Exception as e:
        print(f"❌ ERROR CRÍTICO durante la extracción: {e}")
        return

# 4. EVALUAR LOS RESULTADOS (ASSERTIONS) PARA EL TOPIC 1
    print("\n" + "="*40)
    print("📊 RESULTADOS DE LA PRUEBA (TOPIC 1)")
    print("="*40)

    # Función a prueba de balas para buscar el atributo aunque Gemini le cambie el nombre
    def buscar_atributo(lista_atributos, palabra_clave):
        for attr in lista_atributos:
            if palabra_clave.lower() in attr.attribute_id.lower() or palabra_clave.lower() in attr.canonical_name.lower():
                return attr
        return None

    # Comprobación 1: Temozolomida
    attr_tmz = buscar_atributo(resultado.attributes, "temozolomide")
    if attr_tmz and attr_tmz.status == "found" and str(attr_tmz.value).lower() == "true":
        print("✅ TEST 1 PASADO: 'prior_temozolomide' detectado correctamente.")
    else:
        print(f"❌ TEST 1 FALLADO: temozolomide incorrecto. ¿Qué devolvió Gemini? -> {attr_tmz.status if attr_tmz else 'No encontrado'}")

    # Comprobación 2: Bevacizumab / Avastin
    attr_bev = buscar_atributo(resultado.attributes, "bevacizumab") or buscar_atributo(resultado.attributes, "avastin")
    if attr_bev and attr_bev.status == "found" and str(attr_bev.value).lower() == "true":
        print("✅ TEST 2 PASADO: 'prior_bevacizumab' detectado correctamente.")
    else:
        print(f"❌ TEST 2 FALLADO: bevacizumab incorrecto. ¿Qué devolvió Gemini? -> {attr_bev.status if attr_bev else 'No encontrado'}")

    # Comprobación 3: ECOG
    attr_ecog = buscar_atributo(resultado.attributes, "ecog")
    if attr_ecog and attr_ecog.status == "not_found":
        print("✅ TEST 3 PASADO: 'ECOG' detectado como not_found de forma segura.")
        print(f"   -> Pregunta generada: {attr_ecog.missing_question}")
    else:
        print(f"❌ TEST 3 FALLADO: ECOG incorrecto. ¿Qué devolvió Gemini? -> {attr_ecog.status if attr_ecog else 'No encontrado'}")

    # Comprobación 4: Tumor resectability
    attr_resect = buscar_atributo(resultado.attributes, "resectability") or buscar_atributo(resultado.attributes, "tumor")
    if attr_resect and attr_resect.status == "found" and "unresectable" in str(attr_resect.value).lower():
        print("✅ TEST 4 PASADO: 'tumor_resectability' extraído correctamente como unresectable.")
    else:
         print(f"❌ TEST 4 FALLADO: tumor_resectability incorrecto. ¿Qué devolvió Gemini? -> {attr_resect.value if attr_resect else 'No encontrado'}")

    print("\n📁 El JSON completo de esta prueba se ha guardado en:", ruta_salida.absolute())
if __name__ == "__main__":
    run_tests()