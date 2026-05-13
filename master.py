# -*- coding: utf-8 -*-
import sys
import json
import os
import shutil
import concurrent.futures
import re
from pathlib import Path
import concurrent.futures

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
DATA_PATH = PROJECT_ROOT / "data"

INPUT_ROOT = DATA_PATH / "input"
OUTPUT_ROOT = DATA_PATH / "output"
QRELS_ROOT = DATA_PATH / "trec" 

for folder in [INPUT_ROOT, OUTPUT_ROOT, DATA_PATH, QRELS_ROOT]:
    folder.mkdir(parents=True, exist_ok=True)

if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_PATH) not in sys.path: sys.path.insert(0, str(SRC_PATH))

METRICS_PATH = SRC_PATH / "metrics"
if str(METRICS_PATH) not in sys.path: sys.path.insert(0, str(METRICS_PATH))

def get_and_increment_batch():
    counter_file = DATA_PATH / "batch_counter.txt"
    if not counter_file.exists(): counter_file.write_text("0")
    current_batch = int(counter_file.read_text().strip())
    new_batch = current_batch + 1
    counter_file.write_text(str(new_batch))
    return new_batch


from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.LLM.LLM_factory import LLMSize, create_llm
from query_refinement import QueryRefinementLoop               
from trial_candidate_store import TrialCandidateStore           
from attribute_registry import AttributeRegistryBuilder         
from directed_extractor import DirectedPatientExtractor         
from criterion_evaluator import CriterionEvaluator               
import question_generator                                       
from question_manager import QuestionManager                     
from ranking_engine import RankingEngine
from dossier_generator import DossierGenerator
from query_planner import QueryPlanner
from clinicaltrials_client import ClinicalTrialsClient

try:
    from prediction_exporter import PredictionExporter
except ImportError:
    pass

try:
    from patient_extractor import PatientExtractor
except ImportError:
    pass

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional

class MissingQuestion(BaseModel):
    attribute: str; question: str; expected_answer_type: Literal["integer", "float", "boolean", "string", "date"]
    valid_answers: Optional[list[Any]] = None; resolves_criteria: list[str] = Field(default_factory=list); status: str = "generated"

question_generator.MissingQuestion = MissingQuestion

class InternalRunnerGen:
    def __init__(self, cli): 
        self.client = cli; self.temperature = 0.0
        self.system_instruction = "Oncólogo experto. Redacta preguntas breves en ESPAÑOL."
    def generate_question(self, d): return question_generator.generate_question(self, d)
    def _safe_expected_answer_type(self, v): return question_generator._safe_expected_answer_type(self, v)


def main():
    print("\n" + "="*80)
    print(" SISTEMA BATCH MULTI-PACIENTE - CLINICALMATCH ")
    print("="*80)

    xml_files = list(INPUT_ROOT.glob("*.xml"))
    if not xml_files:
        print(f" No hay archivos XML en {INPUT_ROOT}.")
        return

    batch_num = get_and_increment_batch()
    batch_folder = DATA_PATH / f"batch_{batch_num}"
    batch_output_folder = OUTPUT_ROOT / f"batch_{batch_num}"
    m16_inputs_folder = batch_folder / "m16_inputs"
    input_archived = batch_folder / "input_archived"
    
    for f in [batch_folder, batch_output_folder, m16_inputs_folder, input_archived]:
        f.mkdir(parents=True, exist_ok=True)

    print(f" BATCH #{batch_num} |  Archivos detectados: {len(xml_files)}")
    llm_client = create_llm(LLMSize.SMALL)

    for xml_path in xml_files:
        print(f"\n PROCESANDO ARCHIVO: {xml_path.name}")
        with open(xml_path, "r", encoding="utf-8") as f:
            xml_text = f.read()

        topics_found = re.findall(r'<topic number="([^"]+)">\s*(.*?)\s*</topic>', xml_text, re.DOTALL)
        
        if topics_found:
            patients_to_process = [{"patient_id": t[0], "raw_text": t[1]} for t in topics_found]
        else:
            patients_to_process = [{"patient_id": xml_path.stem, "raw_text": xml_text}]
            
        print(f"    Se han detectado {len(patients_to_process)} pacientes (topics) en este archivo.")

        for p_idx, p_data in enumerate(patients_to_process, start=1):
            p_id = p_data["patient_id"]
            p_text = p_data["raw_text"]
            
            patient_folder = batch_folder / f"{xml_path.stem}_topic_{p_id}"
            patient_output = batch_output_folder / f"{xml_path.stem}_topic_{p_id}"
            patient_folder.mkdir(exist_ok=True)
            patient_output.mkdir(exist_ok=True)

            print(f"\n   ─────────────────────────────────────────────────────────────")
            print(f"    [{p_idx}/{len(patients_to_process)}] PACIENTE ID: {p_id}")
            print(f"   ─────────────────────────────────────────────────────────────")

            # [M1-M2] Extracción de Perfil
            print(f"    [M1-M2] Extrayendo perfil médico de Topic {p_id}...")
            try:
                extractor = PatientExtractor()
                profile_data = extractor.extract({"patient_id": p_id, "raw_text": p_text})
                if hasattr(profile_data, 'model_dump'):
                    profile_data = profile_data.model_dump()
                profile_data["patient_id"] = p_id
            except Exception as e:
                print(f"       Fallo en M1 ({e}).")
                profile_data = {"patient_id": p_id, "patient_profile": {"condition": "Unknown"}}

            # [M3] Query Planner
            q_plan = QueryPlanner().build_plan(profile_data, output_path=patient_folder / "query_plan.json")

            # [M4-M5] Descarga de Ensayos
            print(f"    [M4-M5] Descargando ensayos médicos...")
            raw_api = patient_folder / "raw_api_data.json"
            ClinicalTrialsClient().search_from_plan(q_plan, output_path=raw_api)

            # [M6-M7] Limpieza e Indexación
            refined = patient_folder / "refined_trials.json"
            with open(raw_api, "r", encoding="utf-8") as f: raw_data = json.load(f)
            QueryRefinementLoop().refine_from_api_result(raw_data, output_path=refined)
            
            store_path = patient_folder / "candidate_store.json"
            TrialCandidateStore().build_store_from_file(refined, output_path=store_path)

            # [M8] Parseo con IA (Turbo Paralelo)
            parsed_criteria_path = patient_folder / "parsed_criteria_with_ai.json"
            try:
                from trial_criteria_parser import TrialCriteriaParser
                parser = TrialCriteriaParser(inclusion_llm=llm_client, exclusion_llm=llm_client, hardness_llm=llm_client)
                
                with open(store_path, "r", encoding="utf-8") as f: store_data = json.load(f)
                unique_studies = store_data.get("unique_studies", [])
                
                print(f"    [M8] MODO TURBO: Procesando {len(unique_studies)} ensayos en paralelo. Sujétate fuerte...")
                
                def procesar_un_ensayo(study): 
                    nct_id = study.get("nct_id") or study.get("trial", {}).get("nct_id") or "Desconocido"
                    print(f"       [Hilo] Enviando a Gemini: {nct_id}...")
                    return parser.parse_trial(study)

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    store_data["unique_studies"] = list(executor.map(procesar_un_ensayo, unique_studies))
                
                with open(parsed_criteria_path, "w", encoding="utf-8") as f:
                    json.dump(store_data, f, ensure_ascii=False, indent=2)
                    
                store_para_m9 = parsed_criteria_path
                print(f"   Parseo semántico en paralelo finalizado con éxito.")
            except Exception as e:
                print(f"       Aviso: Fallo en M8 ({e})")
                store_para_m9 = store_path

            # [M9] Registry
            with open(store_para_m9, "r", encoding="utf-8") as f: c_data = json.load(f)
            registry = AttributeRegistryBuilder().build_from_candidate_json(c_data, output_path=patient_folder / "registry.json")
            
            # [M10] Patient Extractor
            try:
                ext_obj = DirectedPatientExtractor(llm_client, registry_id=p_id).extract(profile_data, registry, output_path=patient_folder / "extraction.json")
                res_ext = ext_obj.model_dump() if hasattr(ext_obj, 'model_dump') else ext_obj
            except: 
                res_ext = {"patient_id": p_id, "attributes": []}

            # [M11] Eligibility Matrix
            eval_path = patient_folder / "eligibility_matrix.json"
            CriterionEvaluator().evaluate_patient_candidate_file(c_data, res_ext, output_path=eval_path)

            # [M12] Preguntas IA
            print(f"   [M12] Localizando incógnitas y redactando preguntas con IA...")
            with open(eval_path, "r", encoding="utf-8") as f: eval_data = json.load(f)
            
            missing_attrs = []
            seen = set()
            for study in eval_data.get("unique_studies", []):
                all_crit = study.get("criterion_evaluation", {}).get("all", []) or study.get("criterion_evaluation", {}).get("all_criteria", [])
                for c in all_crit:
                    if (c.get("evaluation_status") == "unknown" or c.get("requires_missing_info")) and c.get("attribute_id"):
                        if c.get("attribute_id") not in seen:
                            seen.add(c.get("attribute_id"))
                            missing_attrs.append({"attribute_id": c.get("attribute_id"), "canonical_name": c.get("attribute", c.get("attribute_id")), "required_by": [{"trial_id": c.get("trial_id"), "criterion_text": c.get('raw_text')}]})
            
            runner_q = InternalRunnerGen(cli=llm_client)
            preguntas_finales = []
            
            if missing_attrs:
                print(f"      🚀 Redactando {len(missing_attrs)} preguntas en PARALELO...")
                
                def generar_pregunta(item):
                    try:
                        res_q = runner_q.generate_question(item)
                        return res_q.model_dump() if hasattr(res_q, 'model_dump') else res_q
                    except Exception:
                        return {"attribute": item["attribute_id"], "question": f"¿Estado actual para {item['attribute_id']}?", "expected_answer_type": "string", "resolves_criteria": [item["required_by"][0]["trial_id"]], "status": "generated"}

                
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    preguntas_finales = list(executor.map(generar_pregunta, missing_attrs))
                    
            with open(patient_folder / "ai_questions.json", "w", encoding="utf-8") as f: json.dump(preguntas_finales, f, ensure_ascii=False)
            print(f"       Se han redactado {len(preguntas_finales)} preguntas clínicas.")

            print(f"    [M13-M15] Generando reportes finales...")
            q_manager = QuestionManager()
            unified_json = q_manager.unify_patient_questions(p_id, preguntas_finales, res_ext.get("attributes", []))
            local_cuestionario_pdf = patient_folder / "Cuestionario_Faltante.pdf"
            q_manager.export_to_pdf(unified_json, str(local_cuestionario_pdf))

            ranking_path = patient_folder / "ranking_resultados.json"
            with open(eval_path, "r", encoding="utf-8") as f: ev_data = json.load(f)
            ranking_output = RankingEngine().rank_patient_candidate_file(ev_data, output_path=ranking_path)
            
            ranking_output["topic_id"] = p_id
            with open(ranking_path, "w", encoding="utf-8") as f:
                json.dump(ranking_output, f, ensure_ascii=False, indent=2)
            
            shutil.copy(str(ranking_path), str(m16_inputs_folder / f"topic_{p_id}_ranking.json"))

            local_dossier_pdf = patient_folder / "Dossier_Ejecutivo.pdf"
            try:
                DossierGenerator().generate_pdf(ranking_output=ranking_output, output_path=local_dossier_pdf)
            except: pass

            shutil.copy(str(local_cuestionario_pdf), str(patient_output / f"1_Topic_{p_id}_Cuestionario.pdf"))
            shutil.copy(str(ranking_path), str(patient_output / f"3_Topic_{p_id}_Ranking.json"))
            if local_dossier_pdf.exists():
                shutil.copy(str(local_dossier_pdf), str(patient_output / f"2_Topic_{p_id}_Dossier.pdf"))

        shutil.move(str(xml_path), str(input_archived / xml_path.name))


    json_submission = None
    print("\n" + "─"*80)
    print(f" [M16] Consolidando resultados globales del Batch #{batch_num} (Prediction Exporter)...")
    try:
        from prediction_exporter import PredictionExporter
        exporter = PredictionExporter(run_name=f"BATCH{batch_num}")
        
        json_submission = batch_output_folder / f"Batch{batch_num}_Predictions.json"
        trec_submission = batch_output_folder / f"Batch{batch_num}_TREC_Run.txt"
        
        export_result = exporter.export_from_directory(
            input_dir=m16_inputs_folder,
            output_json_path=json_submission,
            output_trec_path=trec_submission
        )
        
        total_topics = export_result.get("summary", {}).get("total_topics", 0)
        total_preds = export_result.get("summary", {}).get("total_predictions", 0)
        
        print(f"    Exportación completada: {total_topics} pacientes, {total_preds} predicciones.")
        print(f"    JSON consolidado: {json_submission.name}")
        print(f"    Archivo TREC: {trec_submission.name}")
    except Exception as e:
        print(f"    Fallo en M16 ({e}).")

    print("\n" + "─"*80)
    print(f"[M17] Evaluando Métricas de Rendimiento y Graficando Resultados...")
    
    qrels_files = list(QRELS_ROOT.glob("*.txt")) + list(QRELS_ROOT.glob("*.qrels"))
    if not qrels_files:
        print(f"    No se encontró ningún archivo de Gold Standard en {QRELS_ROOT}.")
        print(f"      Saltando M17. (Para evaluar, mete tu qrels en data/trec/)")
    elif json_submission and json_submission.exists():
        qrels_path = qrels_files[0]
        try:
            from metrics_evaluator import MetricsEvaluator
            from plot_metrics import MetricsPlotter
            
            metrics_output = batch_output_folder / f"Batch{batch_num}_Metrics.json"
            plots_folder = batch_output_folder / "plots"
            
            evaluator = MetricsEvaluator()
            predictions_data = evaluator.load_predictions(str(json_submission))
            qrels_data = evaluator.load_qrels(str(qrels_path))
            
            metrics = evaluator.evaluate(predictions_data, qrels_data)
            
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
                
            evaluator.save_metrics(metrics, str(metrics_output))
            
            if metrics_output.exists():
                print(f"   Rendimiento calculado frente al archivo {qrels_path.name}")
                
                plotter = MetricsPlotter()
                metrics_data = plotter.load_metrics(str(metrics_output))
                plot_file = plots_folder / f"Batch{batch_num}_Metrics_Plot.png"
                plotter.plot_metrics(metrics_data=metrics_data, output_path=str(plot_file))
                print(f"   Gráfico generado exitosamente en 'plots/'.")
                
        except Exception as e:
            print(f"    Fallo en M17 ({e}). Comprueba tus clases MetricsEvaluator y MetricsPlotter.")

    print("\n" + "="*80)
    print(f" FINALIZADO BATCH #{batch_num} ")
    print(f" Pipeline End-to-End Completado. Entregables en: data/output/batch_{batch_num}")
    print("="*80)

if __name__ == "__main__":
    main()