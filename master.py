# -*- coding: utf-8 -*-

import sys
import json
import shutil
import concurrent.futures
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
DATA_PATH = PROJECT_ROOT / "data"

INPUT_ROOT = DATA_PATH / "input"
OUTPUT_ROOT = DATA_PATH / "output"
QRELS_ROOT = DATA_PATH / "trec"

for folder in [INPUT_ROOT, OUTPUT_ROOT, DATA_PATH, QRELS_ROOT]:
    folder.mkdir(parents=True, exist_ok=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

METRICS_PATH = SRC_PATH / "metrics"
if str(METRICS_PATH) not in sys.path:
    sys.path.insert(0, str(METRICS_PATH))


# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------

load_dotenv(PROJECT_ROOT / ".env")


# -----------------------------------------------------------------------------
# Imports internos
# -----------------------------------------------------------------------------

from src.LLM.LLM_factory import LLMSize, create_llm

from InputAdapter import InputAdapter
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
    PredictionExporter = None

try:
    from patient_extractor import PatientExtractor
except ImportError:
    PatientExtractor = None


# -----------------------------------------------------------------------------
# Compatibilidad Question Generator
# -----------------------------------------------------------------------------

class MissingQuestion(BaseModel):
    attribute: str
    question: str
    expected_answer_type: Literal[
        "integer",
        "float",
        "boolean",
        "string",
        "date",
    ]
    valid_answers: Optional[list[Any]] = None
    resolves_criteria: list[str] = Field(default_factory=list)
    status: str = "generated"


question_generator.MissingQuestion = MissingQuestion


class InternalRunnerGen:
    def __init__(self, cli):
        self.client = cli
        self.temperature = 0.0
        self.system_instruction = "Oncólogo experto. Redacta preguntas breves en ESPAÑOL."

    def generate_question(self, d):
        return question_generator.generate_question(self, d)

    def _safe_expected_answer_type(self, v):
        return question_generator._safe_expected_answer_type(self, v)


# -----------------------------------------------------------------------------
# Master
# -----------------------------------------------------------------------------

class ClinicalMatchMaster:
    def __init__(
        self,
        generate_dossiers: bool = False,
        trec_year: int | None = None,
    ) -> None:
        """
        Args:
            generate_dossiers:
                Si True, genera los dossiers PDF finales por paciente.

            trec_year:
                None -> modo normal/live ClinicalTrials.gov
                2021 o 21 -> modo TREC 2021
                2022 o 22 -> modo TREC 2022
        """
        self.generate_dossiers = generate_dossiers
        self.trec_year = self._normalize_trec_year(trec_year)

        self.project_root = PROJECT_ROOT
        self.src_path = SRC_PATH
        self.data_path = DATA_PATH

        self.input_root = INPUT_ROOT
        self.output_root = OUTPUT_ROOT
        self.qrels_root = QRELS_ROOT

        self.llm_client = None

    # ------------------------------------------------------------------
    # Helpers básicos
    # ------------------------------------------------------------------

    def get_and_increment_batch(self) -> int:
        counter_file = self.data_path / "batch_counter.txt"

        if not counter_file.exists():
            counter_file.write_text("0")

        current_batch = int(counter_file.read_text().strip())
        new_batch = current_batch + 1
        counter_file.write_text(str(new_batch))

        return new_batch

    def safe_folder_name(self, value: str) -> str:
        return "".join(
            char if char.isalnum() or char in {"_", "-", "."} else "_"
            for char in str(value)
        )

    def _normalize_trec_year(
        self,
        trec_year: int | None,
    ) -> int | None:
        if trec_year is None:
            return None

        if trec_year in {21, 2021}:
            return 2021

        if trec_year in {22, 2022}:
            return 2022

        raise ValueError("trec_year debe ser None, 21, 22, 2021 o 2022")

    def build_clinical_trials_client(self) -> ClinicalTrialsClient:
        """
        Crea el cliente de ClinicalTrials según el modo de ejecución.

        - trec_year=None -> API live
        - trec_year=2021/2022 -> snapshot TREC local
        """
        if self.trec_year is None:
            return ClinicalTrialsClient(
                mode="live",
            )

        return ClinicalTrialsClient(
            mode="trec",
            trec_year=self.trec_year,
        )

    # ------------------------------------------------------------------
    # Dossier opcional
    # ------------------------------------------------------------------

    def generate_patient_dossier(
        self,
        ranking_output: dict[str, Any],
        output_path: str | Path,
    ) -> Path | None:
        """
        Genera el dossier PDF de un paciente.

        Este método solo se llama si self.generate_dossiers=True.
        """
        output_path = Path(output_path)

        try:
            DossierGenerator().generate_pdf(
                ranking_output=ranking_output,
                output_path=output_path,
            )

            if output_path.exists():
                return output_path

            return None

        except Exception as e:
            print(f"       Aviso: no se pudo generar el dossier ({e})")
            return None

    # ------------------------------------------------------------------
    # Ejecución principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        print("\n" + "=" * 80)
        print(" SISTEMA BATCH MULTI-PACIENTE - CLINICALMATCH ")
        print("=" * 80)

        xml_files = sorted(self.input_root.glob("*.xml"))

        if not xml_files:
            print(f" No hay archivos XML en {self.input_root}.")
            return

        batch_num = self.get_and_increment_batch()

        batch_folder = self.data_path / f"batch_{batch_num}"
        batch_output_folder = self.output_root / f"batch_{batch_num}"
        m16_inputs_folder = batch_folder / "m16_inputs"
        input_archived = batch_folder / "input_archived"

        for folder in [
            batch_folder,
            batch_output_folder,
            m16_inputs_folder,
            input_archived,
        ]:
            folder.mkdir(parents=True, exist_ok=True)

        print(f" BATCH #{batch_num} | Archivos XML detectados: {len(xml_files)}")

        if self.trec_year is None:
            print(" Modo ClinicalTrials: live")
        else:
            print(f" Modo ClinicalTrials: TREC {self.trec_year}")

        # ------------------------------------------------------------------
        # [M1] InputAdapter
        # ------------------------------------------------------------------
        print("\n" + "─" * 80)
        print("[M1] Adaptando archivos XML de entrada con InputAdapter...")

        try:
            input_adapter = InputAdapter(
                output_path=batch_folder / "adapted_patients.json"
            )

            adapted_path, adapted_data = input_adapter.adapt_files()
            patients_to_process = adapted_data.get("patients", [])

            if not isinstance(patients_to_process, list) or not patients_to_process:
                print(" No se han encontrado pacientes tras ejecutar InputAdapter.")
                return

            print(f"    JSON adaptado generado en: {adapted_path}")
            print(f"    Pacientes detectados: {len(patients_to_process)}")

        except Exception as e:
            print(f" Fallo en M1 InputAdapter: {e}")
            return

        self.llm_client = create_llm(LLMSize.SMALL)

        # ------------------------------------------------------------------
        # Procesamiento paciente a paciente
        # ------------------------------------------------------------------
        for p_idx, p_data in enumerate(patients_to_process, start=1):
            internal_patient_id = str(p_data.get("patient_id") or f"patient_{p_idx}")
            source_patient_id = str(
                p_data.get("source_patient_id")
                or p_data.get("patient_id")
                or p_idx
            )
            p_text = p_data.get("raw_text", "")

            source_file = p_data.get("source_file")
            source_stem = (
                Path(source_file).stem
                if isinstance(source_file, str) and source_file.strip()
                else "input"
            )

            patient_folder_name = self.safe_folder_name(
                f"{source_stem}_topic_{source_patient_id}"
            )

            patient_folder = batch_folder / patient_folder_name
            patient_output = batch_output_folder / patient_folder_name

            patient_folder.mkdir(parents=True, exist_ok=True)
            patient_output.mkdir(parents=True, exist_ok=True)

            print(f"\n   ─────────────────────────────────────────────────────────────")
            print(f"    [{p_idx}/{len(patients_to_process)}] PACIENTE ID: {internal_patient_id}")
            print(f"    Topic original: {source_patient_id}")
            print(f"   ─────────────────────────────────────────────────────────────")

            # ------------------------------------------------------------------
            # [M2] Patient Extractor
            # ------------------------------------------------------------------
            print(f"    [M2] Extrayendo perfil médico de Topic {source_patient_id}...")

            try:
                if PatientExtractor is None:
                    raise ImportError("No se ha podido importar PatientExtractor")

                extractor = PatientExtractor()

                profile_data = extractor.extract(
                    {
                        "patient_id": internal_patient_id,
                        "source_patient_id": source_patient_id,
                        "source": p_data.get("source"),
                        "source_file": p_data.get("source_file"),
                        "input_format": p_data.get("input_format"),
                        "raw_text": p_text,
                    }
                )

                if hasattr(profile_data, "model_dump"):
                    profile_data = profile_data.model_dump()

                profile_data["patient_id"] = internal_patient_id
                profile_data["source_patient_id"] = source_patient_id
                profile_data["source"] = p_data.get("source")
                profile_data["source_file"] = p_data.get("source_file")
                profile_data["input_format"] = p_data.get("input_format")
                profile_data["raw_text"] = p_text

                with open(patient_folder / "patient_profile.json", "w", encoding="utf-8") as f:
                    json.dump(profile_data, f, ensure_ascii=False, indent=2)

            except Exception as e:
                print(f"       Fallo en M2 PatientExtractor ({e}).")

                profile_data = {
                    "patient_id": internal_patient_id,
                    "source_patient_id": source_patient_id,
                    "source": p_data.get("source"),
                    "source_file": p_data.get("source_file"),
                    "input_format": p_data.get("input_format"),
                    "raw_text": p_text,
                    "patient_profile": {
                        "condition": "Unknown"
                    },
                    "extraction_status": "failed",
                    "extraction_error": str(e),
                }

            # ------------------------------------------------------------------
            # [M3] Query Planner
            # ------------------------------------------------------------------
            q_plan = QueryPlanner().build_plan(
                profile_data,
                output_path=patient_folder / "query_plan.json",
            )

            # ------------------------------------------------------------------
            # [M4-M5] ClinicalTrials Client
            # ------------------------------------------------------------------
            print(f"    [M4-M5] Descargando ensayos médicos...")

            raw_api = patient_folder / "raw_api_data.json"

            self.build_clinical_trials_client().search_from_plan(
                q_plan,
                output_path=raw_api,
            )

            # ------------------------------------------------------------------
            # [M6-M7] Query Refinement + Candidate Store
            # ------------------------------------------------------------------
            refined = patient_folder / "refined_trials.json"

            with open(raw_api, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            QueryRefinementLoop().refine_from_api_result(
                raw_data,
                output_path=refined,
            )

            store_path = patient_folder / "candidate_store.json"

            TrialCandidateStore().build_store_from_file(
                refined,
                output_path=store_path,
            )

            # ------------------------------------------------------------------
            # [M8] Trial Criteria Parser
            # ------------------------------------------------------------------
            parsed_criteria_path = patient_folder / "parsed_criteria_with_ai.json"

            try:
                from trial_criteria_parser import TrialCriteriaParser

                parser = TrialCriteriaParser(
                    inclusion_llm=self.llm_client,
                    exclusion_llm=self.llm_client,
                    hardness_llm=self.llm_client,
                )

                with open(store_path, "r", encoding="utf-8") as f:
                    store_data = json.load(f)

                unique_studies = store_data.get("unique_studies", [])

                print(
                    f"    [M8] MODO TURBO: Procesando {len(unique_studies)} "
                    "ensayos en paralelo..."
                )

                def procesar_un_ensayo(study):
                    nct_id = (
                        study.get("nct_id")
                        or study.get("trial", {}).get("nct_id")
                        or "Desconocido"
                    )
                    print(f"       [Hilo] Enviando a Gemini: {nct_id}...")
                    return parser.parse_trial(study)

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    store_data["unique_studies"] = list(
                        executor.map(procesar_un_ensayo, unique_studies)
                    )

                with open(parsed_criteria_path, "w", encoding="utf-8") as f:
                    json.dump(store_data, f, ensure_ascii=False, indent=2)

                store_para_m9 = parsed_criteria_path

                print("   Parseo semántico en paralelo finalizado con éxito.")

            except Exception as e:
                print(f"       Aviso: Fallo en M8 ({e})")
                store_para_m9 = store_path

            # ------------------------------------------------------------------
            # [M9] Attribute Registry
            # ------------------------------------------------------------------
            with open(store_para_m9, "r", encoding="utf-8") as f:
                c_data = json.load(f)

            registry = AttributeRegistryBuilder().build_from_candidate_json(
                c_data,
                output_path=patient_folder / "registry.json",
            )

            # ------------------------------------------------------------------
            # [M10] Directed Patient Extractor
            # ------------------------------------------------------------------
            try:
                ext_obj = DirectedPatientExtractor(
                    self.llm_client,
                    registry_id=internal_patient_id,
                ).extract(
                    profile_data,
                    registry,
                    output_path=patient_folder / "extraction.json",
                )

                res_ext = ext_obj.model_dump() if hasattr(ext_obj, "model_dump") else ext_obj

            except Exception as e:
                print(f"       Aviso: Fallo en M10 ({e})")

                res_ext = {
                    "patient_id": internal_patient_id,
                    "registry_id": internal_patient_id,
                    "extraction_status": "failed",
                    "attributes": [],
                    "flags": [
                        {
                            "type": "directed_extraction_failed",
                            "severity": "high",
                            "message": str(e),
                        }
                    ],
                }

            # ------------------------------------------------------------------
            # [M11] Criterion Evaluator
            # ------------------------------------------------------------------
            eval_path = patient_folder / "eligibility_matrix.json"

            CriterionEvaluator().evaluate_patient_candidate_file(
                c_data,
                res_ext,
                output_path=eval_path,
            )

            # ------------------------------------------------------------------
            # [M12] Question Generator
            # ------------------------------------------------------------------
            print(f"   [M12] Localizando incógnitas y redactando preguntas con IA...")

            with open(eval_path, "r", encoding="utf-8") as f:
                eval_data = json.load(f)

            missing_attrs = []
            seen = set()

            for study in eval_data.get("unique_studies", []):
                criterion_evaluation = study.get("criterion_evaluation", {})
                all_crit = (
                    criterion_evaluation.get("all", [])
                    or criterion_evaluation.get("all_criteria", [])
                )

                for c in all_crit:
                    attribute_id = c.get("attribute_id")

                    if (
                        (
                            c.get("evaluation_status") == "unknown"
                            or c.get("requires_missing_info")
                        )
                        and attribute_id
                        and attribute_id not in seen
                    ):
                        seen.add(attribute_id)

                        missing_attrs.append(
                            {
                                "attribute_id": attribute_id,
                                "canonical_name": c.get("attribute", attribute_id),
                                "required_by": [
                                    {
                                        "trial_id": c.get("trial_id"),
                                        "criterion_text": c.get("raw_text"),
                                    }
                                ],
                            }
                        )

            runner_q = InternalRunnerGen(cli=self.llm_client)
            preguntas_finales = []

            if missing_attrs:
                print(f"      Redactando {len(missing_attrs)} preguntas en paralelo...")

                def generar_pregunta(item):
                    try:
                        res_q = runner_q.generate_question(item)
                        return res_q.model_dump() if hasattr(res_q, "model_dump") else res_q

                    except Exception:
                        return {
                            "attribute": item["attribute_id"],
                            "question": f"¿Estado actual para {item['attribute_id']}?",
                            "expected_answer_type": "string",
                            "resolves_criteria": [
                                item["required_by"][0]["trial_id"]
                            ],
                            "status": "generated",
                        }

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    preguntas_finales = list(executor.map(generar_pregunta, missing_attrs))

            with open(patient_folder / "ai_questions.json", "w", encoding="utf-8") as f:
                json.dump(preguntas_finales, f, ensure_ascii=False, indent=2)

            print(f"       Se han redactado {len(preguntas_finales)} preguntas clínicas.")

            # ------------------------------------------------------------------
            # [M13-M15] Question PDF + Ranking + Dossier opcional
            # ------------------------------------------------------------------
            print(f"    [M13-M15] Generando reportes finales...")

            q_manager = QuestionManager()

            unified_json = q_manager.unify_patient_questions(
                internal_patient_id,
                preguntas_finales,
                res_ext.get("attributes", []),
            )

            local_cuestionario_pdf = patient_folder / "Cuestionario_Faltante.pdf"

            q_manager.export_to_pdf(
                unified_json,
                str(local_cuestionario_pdf),
            )

            ranking_path = patient_folder / "ranking_resultados.json"

            with open(eval_path, "r", encoding="utf-8") as f:
                ev_data = json.load(f)

            ranking_output = RankingEngine().rank_patient_candidate_file(
                ev_data,
                output_path=ranking_path,
            )

            ranking_output["patient_id"] = source_patient_id
            ranking_output["topic_id"] = source_patient_id
            ranking_output["internal_patient_id"] = internal_patient_id
            ranking_output["source_file"] = p_data.get("source_file")
            ranking_output["source"] = p_data.get("source")

            with open(ranking_path, "w", encoding="utf-8") as f:
                json.dump(ranking_output, f, ensure_ascii=False, indent=2)

            shutil.copy(
                str(ranking_path),
                str(m16_inputs_folder / f"topic_{source_patient_id}_ranking.json"),
            )

            local_dossier_pdf = patient_folder / "Dossier_Ejecutivo.pdf"

            if self.generate_dossiers:
                self.generate_patient_dossier(
                    ranking_output=ranking_output,
                    output_path=local_dossier_pdf,
                )

            shutil.copy(
                str(local_cuestionario_pdf),
                str(patient_output / f"1_Topic_{source_patient_id}_Cuestionario.pdf"),
            )

            shutil.copy(
                str(ranking_path),
                str(patient_output / f"3_Topic_{source_patient_id}_Ranking.json"),
            )

            if self.generate_dossiers and local_dossier_pdf.exists():
                shutil.copy(
                    str(local_dossier_pdf),
                    str(patient_output / f"2_Topic_{source_patient_id}_Dossier.pdf"),
                )

        # ------------------------------------------------------------------
        # Archivar XMLs originales
        # ------------------------------------------------------------------
        for xml_path in xml_files:
            try:
                shutil.move(
                    str(xml_path),
                    str(input_archived / xml_path.name),
                )
            except Exception as e:
                print(f"    Aviso: no se pudo archivar {xml_path.name}: {e}")

        # ------------------------------------------------------------------
        # [M16] Prediction Exporter
        # ------------------------------------------------------------------
        json_submission = None

        print("\n" + "─" * 80)
        print(
            f" [M16] Consolidando resultados globales del Batch #{batch_num} "
            "(Prediction Exporter)..."
        )

        try:
            if PredictionExporter is None:
                raise ImportError("No se ha podido importar PredictionExporter")

            exporter = PredictionExporter(run_name=f"BATCH{batch_num}")

            json_submission = batch_output_folder / f"Batch{batch_num}_Predictions.json"
            trec_submission = batch_output_folder / f"Batch{batch_num}_TREC_Run.txt"

            export_result = exporter.export_from_directory(
                input_dir=m16_inputs_folder,
                output_json_path=json_submission,
                output_trec_path=trec_submission,
            )

            total_topics = export_result.get("summary", {}).get("total_topics", 0)
            total_preds = export_result.get("summary", {}).get("total_predictions", 0)

            print(
                f"    Exportación completada: {total_topics} pacientes, "
                f"{total_preds} predicciones."
            )
            print(f"    JSON consolidado: {json_submission.name}")
            print(f"    Archivo TREC: {trec_submission.name}")

        except Exception as e:
            print(f"    Fallo en M16 ({e}).")

        # ------------------------------------------------------------------
        # [M17] Metrics
        # ------------------------------------------------------------------
        print("\n" + "─" * 80)
        print(f"[M17] Evaluando Métricas de Rendimiento y Graficando Resultados...")

        qrels_files = list(self.qrels_root.glob("*.txt")) + list(self.qrels_root.glob("*.qrels"))

        if not qrels_files:
            print(f"    No se encontró ningún archivo de Gold Standard en {self.qrels_root}.")
            print(f"      Saltando M17. Para evaluar, mete tu qrels en data/trec/.")

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

                    plotter.plot_metrics(
                        metrics_data=metrics_data,
                        output_path=str(plot_file),
                    )

                    print(f"   Gráfico generado exitosamente en 'plots/'.")

            except Exception as e:
                print(
                    f"    Fallo en M17 ({e}). "
                    "Comprueba tus clases MetricsEvaluator y MetricsPlotter."
                )

        print("\n" + "=" * 80)
        print(f" FINALIZADO BATCH #{batch_num} ")
        print(f" Pipeline End-to-End Completado. Entregables en: data/output/batch_{batch_num}")
        print("=" * 80)


if __name__ == "__main__":
    master = ClinicalMatchMaster(
        generate_dossiers=False,
        trec_year=None,  # None = live | 2021/21 = TREC 2021 | 2022/22 = TREC 2022
    )
    master.run()