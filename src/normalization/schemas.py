from typing import Any
from pydantic import BaseModel, Field


# Normalizar conceptos medicos grandes:
# enfermedades, tratamientos, conceptos clinicos generales.
class NormalizedConcept(BaseModel):
    raw: str
    normalized: str
    concept_type: str
    method: str
    confidence: float
    status: str = "normalized"

    ontology: str | None = None
    ontology_id: str | None = None
    ontology_term: str | None = None

    aliases: list[str] = Field(default_factory=list)
    parents: list[dict] = Field(default_factory=list)


# Normalizar atributos medicos concretos:
# ECOG, edad, sexo, biomarcador, etc.
class NormalizedAttribute(BaseModel):
    raw: str
    attribute_id: str
    canonical_name: str
    value_type: str
    method: str
    confidence: float


# Normalizar valores medicos concretos:
# male/female, positive/negative, numero, booleano, etc.
class NormalizedValue(BaseModel):
    raw: Any
    normalized: Any
    value_type: str
    method: str
    confidence: float


# Normalizar biomarcadores y su valor:
# EGFR+ -> EGFR_status = positive
class NormalizedBiomarker(BaseModel):
    raw: str
    biomarker: str
    attribute_id: str
    normalized_value: str
    method: str
    confidence: float
