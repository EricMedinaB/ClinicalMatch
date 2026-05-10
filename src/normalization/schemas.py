from typing import Any
from pydantic import BaseModel

#Normalizar conceptos medicos grandes
class NormalizedConcept(BaseModel):
    raw: str
    normalized: str
    concept_type: str
    method: str
    confidence: float
    ontology: str | None = None
    ontology_id: str | None = None

#Normalizar atributos medicos concretos
class NormalizedAttribute(BaseModel):
    raw: str
    attribute_id: str
    canonical_name: str
    value_type: str
    method: str
    confidence: float

#Normalizar valores medicos concretos
class NormalizedValue(BaseModel):
    raw: Any
    normalized: Any
    value_type: str
    method: str
    confidence: float

#Normalizar biomarcadores y su valor
class NormalizedBiomarker(BaseModel):
    raw: str
    biomarker: str
    attribute_id: str
    normalized_value: str
    method: str
    confidence: float