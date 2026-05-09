from pydantic import BaseModel
from LLM.LLM_factory import LLMSize, create_llm

class Biomarker(BaseModel):
    name: str | None = None
    status: str | None = None
    variant: str | None = None


class Location(BaseModel):
    country: str | None = None
    city: str | None = None

# Define el esquema de datos clínicos que Gemini debe extraer del raw_text del paciente. Todos los campos son opcionales y deben ser extraídos solo si están explícitamente mencionados en el texto. No se debe inferir ni inventar información clínica.
class ExtractedPatient(BaseModel):
    condition: str | None = None
    condition_confidence: float | None = None
    subtype: str | None = None
    stage: str | None = None
    age: int | None = None
    sex: str | None = None
    biomarkers: list[Biomarker] | None = None
    prior_treatments: list[str] | None = None
    current_treatments: list[str] | None = None
    treatment_line: str | None = None
    location: Location | None = None

class PatientExtractor:
    def __init__(self):
        self.client = create_llm(LLMSize.SMALL)

    def extract(self, patient):
        result = patient.copy()
        raw_text = patient.get("raw_text")

        if raw_text is None or raw_text.strip() == "":
            result["extraction_status"] = "Failed"
            result["extraction_error"] = "El paciente no tiene raw_text"
            return result

        try:
            extracted = self.client.generate_json(
                prompt=raw_text,
                response_schema=ExtractedPatient,
                system_instruction=(
                    "Use only information explicitly stated in the patient text. "
                    "Do not invent clinical information. "
                    "If a scalar field is missing, return null. "
                    "For biomarkers, extract name, status and variant when available. "
                    "For location, only extract country or city if explicitly mentioned. "
                    "Return data following the provided schema. "
                    "Respond only with valid JSON following the indicated schema."
                ),
                temperature=0.0,
            )

            # Convierte el modelo a un diccionario y lo mezcla con el resultado original del paciente
            result.update(extracted.model_dump())
            result["extraction_status"] = "Ok"

        #Por si Gemini falla
        except Exception as error:
            result["extraction_status"] = "Failed"
            result["extraction_error"] = str(error)

        return result