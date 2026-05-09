# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import Literal, Any, List, Optional
from pydantic import BaseModel, Field


AttributeStatus = Literal[
    "found",
    "not_found",
    "ambiguous",
    "contradictory",
    "not_applicable",
    "extraction_error",
]

class EvidenceSpan(BaseModel):
    text: str
    source: str = "raw_text"
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    confidence: Optional[float] = None

class RequiredByCriterion(BaseModel):
    trial_id: str
    criterion_id: str = "unknown" 
    criterion_text: Optional[str] = None

class AttributeImpact(BaseModel):
    affected_trials: int = 0
    affected_criteria: int = 0
    is_ranking_critical: bool = False

class ExtractedPatientAttribute(BaseModel):
    attribute_id: str
    canonical_name: str
    value: Optional[str] = None
    normalized_value: Optional[str] = None
    unit: Optional[str] = None
    status: AttributeStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[EvidenceSpan] = Field(default_factory=list)
    missing_question: Optional[str] = None
    required_by: List[RequiredByCriterion] = Field(default_factory=list)
    impact: Optional[AttributeImpact] = None
    notes: Optional[str] = None
    error: Optional[str] = None

class ExtractionSummary(BaseModel):
    total_attributes: int
    found: int
    not_found: int
    ambiguous: int
    contradictory: int
    not_applicable: int
    extraction_error: int
    coverage: float

class ExtractionFlag(BaseModel):
    type: str
    severity: Literal["low", "medium", "high"]
    message: str

class ExtractorMetadata(BaseModel):
    module: Optional[str] = None
    alex_normalizer_version: Optional[str] = None
    error: Optional[str] = None

class PatientAttributeSet(BaseModel):
    patient_id: str
    registry_id: str
    extraction_status: Literal[
        "completed",
        "completed_with_missing",
        "completed_with_warnings",
        "partial",
        "failed",
    ]
    attributes: List[ExtractedPatientAttribute]
    summary: ExtractionSummary
    flags: List[ExtractionFlag] = Field(default_factory=list)
    metadata: ExtractorMetadata = Field(default_factory=ExtractorMetadata)

SYSTEM_PROMPT = """
Eres el 'Directed Patient Extractor', un agente clínico experto.
Tu objetivo es cruzar el perfil clínico previamente normalizado de un paciente y su texto crudo original, con una lista de atributos médicos requeridos por ensayos clínicos (Attribute Registry).

REGLAS ESTRICTAS:
1. NO INVENTES DATOS: Si un atributo no está en el texto ni en el perfil normalizado, márcalo como "not_found" y genera una "missing_question" clínica y específica.
2. USA EL TRABAJO PREVIO: Revisa primero el 'normalized_profile'. Si el dato ya fue extraído ahí (ej. age, sex), úsalo directamente mapeando la evidencia.
3. ESTADOS: Diferencia bien entre "not_found" y "ambiguous".
4. EVIDENCIA: Todo atributo encontrado debe tener un fragmento exacto en el campo 'evidence'.
5. IMPACTO: Usa la información de 'required_by_trials' para rellenar los campos de requerimiento.
"""

class DirectedPatientExtractor:
    def __init__(self, llm_client, registry_id: str = "default_registry_v1"):
        """
        Inicializa el extractor con el cliente generado por LLM_factory.
        """
        self.llm_client = llm_client
        self.registry_id = registry_id

    def extract(self, normalized_profile: dict, attribute_registry: dict, output_path: Optional[Path] = None) -> PatientAttributeSet:
        
        patient_id = normalized_profile.get("patient_id", "unknown_patient")
        raw_text = normalized_profile.get("raw_text", "")

        user_prompt = f"""
        ID del Paciente: {patient_id}
        
        === TEXTO CLÍNICO ORIGINAL ===
        {raw_text}

        === PERFIL CLÍNICO NORMALIZADO ===
        {json.dumps(normalized_profile.get('normalized_profile', {}), indent=2)}

        === ATRIBUTOS REQUERIDOS ===
        {json.dumps(attribute_registry.get('attributes', []), indent=2)}
        """

        try:
            response_data = self.llm_client.generate_json(
                prompt=user_prompt,
                system_instruction=SYSTEM_PROMPT,
                temperature=0.0, 
                response_schema=PatientAttributeSet
            )

            response_data.patient_id = patient_id
            response_data.registry_id = self.registry_id
            response_data.metadata.module = "DirectedPatientExtractor"
            response_data.metadata.alex_normalizer_version = normalized_profile.get("metadata", {}).get("prompt_version", "unknown")

        except Exception as e:
            response_data = PatientAttributeSet(
                patient_id=patient_id,
                registry_id=self.registry_id,
                extraction_status="failed",
                attributes=[],
                summary=ExtractionSummary(
                    total_attributes=len(attribute_registry.get("attributes", [])),
                    found=0, not_found=0, ambiguous=0, contradictory=0, not_applicable=0,
                    extraction_error=len(attribute_registry.get("attributes", [])), coverage=0.0
                ),
                flags=[ExtractionFlag(type="system_error", severity="high", message=str(e))],
                metadata=ExtractorMetadata(error=str(e)) 
            )
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(response_data.model_dump_json(indent=2))

        return response_data