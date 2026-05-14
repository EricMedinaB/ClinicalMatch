# Clinical Match

## UAB THE HACK × Deloitte  
### Agente de IA para matching entre pacientes y ensayos clínicos

---

## Índice

- [Introducción](#introducción)
- [Problema a resolver](#problema-a-resolver)
- [Objetivo del proyecto](#objetivo-del-proyecto)
- [Arquitectura del sistema](#arquitectura-del-sistema)
- [Diseño modular](#diseño-modular)
- [Modelos LLM utilizados](#modelos-llm-utilizados)
- [Trazabilidad y explicabilidad](#trazabilidad-y-explicabilidad)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Instalación](#instalación)
- [Resultados obtenidos](#resultados-obtenidos)
- [Equipo](#equipo)

---

## Introducción

**Clinical Match** es un sistema de inteligencia artificial diseñado para encontrar y priorizar ensayos clínicos potencialmente adecuados para un paciente a partir de su expediente médico.

El proyecto se ha desarrollado en el contexto de **UAB THE HACK × Deloitte**, con el objetivo de construir una solución capaz de procesar información clínica no estructurada, recuperar ensayos clínicos candidatos, analizar sus criterios de elegibilidad y generar una predicción final ordenada y explicable.

La solución se basa en una arquitectura modular, trazable y orientada a pipeline, donde cada fase transforma la información recibida y guarda resultados intermedios en formato JSON.

---

## Problema a resolver

Encontrar ensayos clínicos adecuados para un paciente es un proceso complejo porque combina múltiples dificultades:

- Los expedientes médicos suelen estar escritos en texto libre.
- Los criterios de inclusión y exclusión de los ensayos son largos, variables y difíciles de estructurar.
- La información clínica del paciente puede estar incompleta, negada, ambigua o expresada con sinónimos.
- Un mismo paciente puede tener cientos de ensayos potencialmente relevantes.
- Es necesario priorizar resultados, no solo recuperar candidatos.
- El sistema debe ser explicable: no basta con devolver una lista, también debe poder justificar el matching.

Clinical Match aborda este problema mediante un agente compuesto por módulos especializados que transforman gradualmente los datos hasta obtener un ranking final de ensayos.

---

## Objetivo del proyecto

El objetivo principal es construir un sistema que, dado un expediente clínico de paciente, sea capaz de:

1. Extraer la enfermedad principal y atributos clínicos relevantes.
2. Buscar ensayos clínicos potencialmente relacionados.
3. Parsear criterios de inclusión y exclusión.
4. Identificar qué atributos del paciente son necesarios para evaluar los ensayos.
5. Comparar paciente y criterios de forma estructurada.
6. Calcular una puntuación por ensayo.
7. Exportar la predicción final en el formato requerido.

---

## Arquitectura del sistema

El sistema se organiza como un **pipeline modular controlado por un módulo master**.

```text
┌──────────────────────────────────────────────────────────────┐
│                    Master / Orchestrator                     │
│     Controla el pipeline, rutas, estados, errores y outputs   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────┐
│ 1. Patient Pipeline  │
└──────────────────────┘
        │
        ├── InputAdapter
        ├── Patient Extractor
        ├── Normalization
        └── Directed Patient Extractor

                              │
                              ▼
┌─────────────────────────────┐
│ 2. Trial Retrieval Pipeline │
└─────────────────────────────┘
        │
        ├── Query Planner
        ├── ClinicalTrials Client
        ├── Query Refinement
        └── Trial Candidate Store

                              │
                              ▼
┌──────────────────────────────┐
│ 3. Matching & Evaluation     │
└──────────────────────────────┘
        │
        ├── Trial Criteria Parser
        ├── Attribute Registry
        ├── Criterion Evaluator
        └── Ranking Engine

                              │
                              ▼
┌──────────────────────┐
│ 4. Final Export      │
└──────────────────────┘
        │
        └── Prediction Exporter
````

La arquitectura está pensada para que cada módulo tenga una responsabilidad clara, entradas y salidas definidas, y pueda ser probado de forma independiente.

---

## Diseño modular

### 1. `InputAdapter`

**Responsabilidad:**
Leer los archivos de entrada del benchmark y convertirlos a un formato interno común.

**Entrada:**

```text
/data/input/*.xml
```

**Salida:**

```json
{
  "patients": [
    {
      "id": "2021_1",
      "source": "2021",
      "source_patient_id": 1,
      "raw_text": "Clinical patient description..."
    }
  ]
}
```

**Función dentro del pipeline:**
Unifica la entrada para que los siguientes módulos no dependan del formato original.

---

### 2. `Patient Extractor`

**Responsabilidad:**
Extraer un perfil clínico inicial del paciente a partir del texto bruto.

**Entrada:**

```json
{
  "id": "patient_3",
  "raw_text": "Patient is a 45-year-old man..."
}
```

**Salida:**

```json
{
  "patient_id": "patient_3",
  "patient_profile": {
    "condition": "glioblastoma",
    "age": 45,
    "sex": "male",
    "biomarkers": [],
    "prior_treatments": []
  },
  "extraction_status": "complete"
}
```

**Función dentro del pipeline:**
Obtiene una primera representación estructurada del paciente.

---

### 3. `Normalization`

**Responsabilidad:**
Normalizar conceptos clínicos para reducir inconsistencias.

El módulo incluye:

* Diccionarios de sinónimos.
* Normalización de enfermedades.
* Normalización de fármacos.
* Normalización de sexo.
* Normalización de biomarcadores.
* Normalización de atributos clínicos.
* Integración con MeSH cuando aplica.

**Entrada:**

```text
Texto o concepto clínico sin normalizar
```

Ejemplo:

```text
"NSCLC"
```

**Salida:**

```json
{
  "raw": "NSCLC",
  "normalized": "non-small cell lung cancer",
  "concept_type": "condition",
  "ontology": "MeSH",
  "confidence": 1.0
}
```

**Función dentro del pipeline:**
Asegura que paciente, criterios y atributos utilicen identificadores comparables.

---

### 4. `Query Planner`

**Responsabilidad:**
Generar consultas para recuperar ensayos clínicos candidatos.

**Entrada:**

```json
{
  "condition": "non-small cell lung cancer"
}
```

**Salida:**

```json
{
  "patient_id": "patient_3",
  "queries": [
    {
      "query_id": "q1",
      "query": "non-small cell lung cancer",
      "query_type": "base_queries"
    }
  ]
}
```

**Función dentro del pipeline:**
Transforma la enfermedad principal del paciente en consultas ejecutables.

---

### 5. `ClinicalTrials Client`

**Responsabilidad:**
Conectarse a la fuente de ensayos clínicos y recuperar resultados.

**Entrada:**

```json
{
  "query": "non-small cell lung cancer"
}
```

**Salida:**

```json
{
  "query_id": "q1",
  "studies": [
    {
      "nct_id": "NCT01234567",
      "raw": {}
    }
  ]
}
```

**Función dentro del pipeline:**
Obtiene ensayos candidatos desde la base de datos externa.

---

### 6. `Query Refinement`

**Responsabilidad:**
Consolidar, filtrar y deduplicar los resultados recuperados por distintas consultas.

**Entrada:**

```json
{
  "results": [
    {
      "query_id": "q1",
      "studies": []
    }
  ]
}
```

**Salida:**

```json
{
  "unique_studies": [
    {
      "nct_id": "NCT01234567",
      "retrieved_by": []
    }
  ],
  "total_unique_candidates": 50
}
```

**Función dentro del pipeline:**
Controla el número de candidatos y mejora la calidad del conjunto recuperado.

---

### 7. `Trial Candidate Store`

**Responsabilidad:**
Transformar los ensayos recuperados a un formato interno estable.

**Entrada:**

```json
{
  "unique_studies": [
    {
      "nct_id": "NCT01234567",
      "raw": {}
    }
  ]
}
```

**Salida:**

```json
{
  "unique_studies": [
    {
      "nct_id": "NCT01234567",
      "retrieved_by": [],
      "trial": {
        "nct_id": "NCT01234567",
        "title": "...",
        "criteria": {
          "raw": "Inclusion Criteria..."
        }
      }
    }
  ]
}
```

**Función dentro del pipeline:**
Prepara los ensayos para el análisis posterior de criterios.

---

### 8. `Trial Criteria Parser`

**Responsabilidad:**
Parsear los criterios de inclusión y exclusión de cada ensayo.

**Entrada:**

```json
{
  "trial": {
    "criteria": {
      "raw": "Inclusion Criteria: Age >= 18..."
    }
  }
}
```

**Salida:**

```json
{
  "criteria": {
    "inclusion": [
      {
        "criterion_id": "NCT01234567_inc_001",
        "type": "inclusion",
        "raw_text": "Age >= 18 years",
        "attribute": "age",
        "normalized_attribute": "age",
        "operator": ">=",
        "target_value": 18,
        "unit": "years",
        "hardness": "hard",
        "category": "demographic"
      }
    ],
    "exclusion": [],
    "all": []
  }
}
```

**Función dentro del pipeline:**
Convierte texto libre de elegibilidad en criterios estructurados y evaluables.

---

### 9. `Attribute Registry`

**Responsabilidad:**
Construir una lista única de atributos requeridos para evaluar los ensayos candidatos.

**Entrada:**

```json
{
  "criteria": {
    "all": [
      {
        "normalized_attribute": "age",
        "criterion_id": "NCT01234567_inc_001"
      }
    ]
  }
}
```

**Salida:**

```json
{
  "registry_id": "attribute_registry_v1",
  "attributes": [
    {
      "attribute_id": "age",
      "canonical_name": "age",
      "value_type": "integer",
      "unit": "years",
      "required_by": [
        {
          "trial_id": "NCT01234567",
          "criterion_id": "NCT01234567_inc_001"
        }
      ]
    }
  ]
}
```

**Función dentro del pipeline:**
Evita extraer datos de paciente ensayo por ensayo. En su lugar, genera una única lista consolidada de atributos necesarios.

---

### 10. `Directed Patient Extractor`

**Responsabilidad:**
Extraer del paciente únicamente los atributos requeridos por el `Attribute Registry`.

**Entrada:**

```json
{
  "patient_profile": {},
  "raw_text": "...",
  "attribute_registry": {
    "attributes": []
  }
}
```

**Salida:**

```json
{
  "patient_id": "patient_3",
  "attributes": [
    {
      "attribute_id": "age",
      "value": 45,
      "normalized_value": 45,
      "status": "found",
      "confidence": 0.99,
      "evidence": []
    }
  ]
}
```

**Función dentro del pipeline:**
Genera una tabla de atributos del paciente directamente comparable con los criterios de ensayo.

---

### 11. `Criterion Evaluator`

**Responsabilidad:**
Comparar cada criterio parseado con los atributos extraídos del paciente.

**Entrada:**

```json
{
  "criterion": {
    "type": "inclusion",
    "normalized_attribute": "age",
    "operator": ">=",
    "target_value": 18
  },
  "patient_attribute": {
    "attribute_id": "age",
    "normalized_value": 45
  }
}
```

**Salida:**

```json
{
  "criterion_id": "NCT01234567_inc_001",
  "evaluation_status": "met",
  "eligibility_impact": "supports_eligibility",
  "reason": "Patient age is 45, which satisfies age >= 18."
}
```

**Función dentro del pipeline:**
Determina si cada criterio se cumple, no se cumple, es desconocido, no aplica o produce error.

---

### 12. `Ranking Engine`

**Responsabilidad:**
Asignar una puntuación final a cada ensayo según los criterios evaluados.

**Entrada:**

```json
{
  "criterion_evaluation": {
    "all": [
      {
        "criterion_type": "inclusion",
        "evaluation_status": "met",
        "hardness": "hard",
        "category": "demographic"
      }
    ]
  }
}
```

**Salida:**

```json
{
  "ranked_trials": [
    {
      "rank": 1,
      "nct_id": "NCT01234567",
      "score": 87.4,
      "ranking_bucket": "good_match",
      "reasons": []
    }
  ]
}
```

**Función dentro del pipeline:**
Ordena los ensayos según una fórmula ponderada basada en tipo de criterio, dureza, categoría clínica, estado de evaluación y confianza.

---

### 13. `Prediction Exporter`

**Responsabilidad:**
Unificar los rankings individuales de todos los pacientes y generar la salida final.

**Entrada:**

```text
/data/ranking/*.json
```

**Salida JSON:**

```json
{
  "schema_version": "prediction_export_v1",
  "run_name": "CLINMATCH1",
  "predictions": [
    {
      "topic_id": "3",
      "trials": [
        {
          "rank": 1,
          "nct_id": "NCT01234567",
          "score": 87.4
        }
      ]
    }
  ]
}
```

**Salida TREC opcional:**

```text
3 Q0 NCT01234567 1 87.4000 CLINMATCH1
```

**Función dentro del pipeline:**
Genera el resultado final entregable para la hackathon.

---

## Modelos LLM utilizados

El sistema utiliza modelos Gemini a través de una capa de abstracción propia.

### Modelos usados

* `gemini-3-flash-preview`
* `gemini-3.1-flash-lite-preview`

### Componentes LLM

```text
src/LLM/
├── base.py
├── gemini_client.py
├── LLM_factory.py
└── prompt_loader.py
```

### Diseño

* `Gemini Client`: encapsula las llamadas al proveedor LLM.
* `LLM Factory`: centraliza la creación de modelos según el tamaño o tarea.
* `Prompt Loader`: carga prompts desde ficheros externos.
* Prompts versionados: permiten modificar instrucciones sin alterar lógica de negocio.

Este diseño permite cambiar el modelo o el prompt de un módulo sin reescribir el pipeline completo.

---

## Trazabilidad y explicabilidad

Clinical Match guarda salidas intermedias en JSON para facilitar auditoría y depuración.

Cada módulo puede registrar:

* Estado de ejecución.
* Metadatos del modelo.
* Versión del prompt.
* Warnings.
* Errores.
* Evidencias clínicas.
* Criterios evaluados.
* Desglose de score.
* Razones del ranking.

Esto permite responder preguntas como:

* ¿Qué atributos se extrajeron del paciente?
* ¿Qué criterios requerían esos atributos?
* ¿Qué criterios se cumplieron o no?
* ¿Por qué un ensayo aparece por encima de otro?
* ¿Qué información faltaba?

---

## Estructura del repositorio

```text
ClinicalMatch/
├── src/
│   ├── LLM/
│   │   ├── base.py
│   │   ├── gemini_client.py
│   │   ├── LLM_factory.py
│   │   └── prompt_loader.py
│   │
│   ├── normalization/
│   │   ├── dictionaries.py
│   │   ├── mesh_client.py
│   │   ├── normalizer.py
│   │   └── schemas.py
│   │
│   ├── InputAdapter.py
│   ├── patient_extractor.py
│   ├── query_planner.py
│   ├── clinicaltrials_client.py
│   ├── query_refinement.py
│   ├── trial_candidate_store.py
│   ├── trial_criteria_parser.py
│   ├── attribute_registry.py
│   ├── directed_extractor.py
│   ├── criterion_evaluator.py
│   ├── ranking_engine.py
│   ├── prediction_exporter.py
│   ├── question_generator.py
│   ├── question_manager.py
│   └── dossier_generator.py
│
├── tests/
│   ├── tests_unitaris/
│   └── tests_integració/
│
├── data/
│
├── input/
│
├── output/
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/EricMedinaB/ClinicalMatch.git
cd ClinicalMatch
````

---

### 2. Crear y activar un entorno virtual

#### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

#### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

---

### 3. Configurar el proyecto

Clinical Match incluye un comando de configuración inicial que crea el archivo `.env`, instala dependencias y prepara las carpetas de trabajo.

```bash
python master.py setup --api-key TU_GEMINI_API_KEY
```

Este comando realiza automáticamente las siguientes acciones:

```text
- Crea el archivo .env con la API key de Gemini.
- Configura los modelos Gemini usados por el sistema.
- Instala las dependencias de requirements.txt.
- Crea las carpetas necesarias en /data.
- Vacía la carpeta data/input.
- Vacía la carpeta data/output.
- Elimina carpetas temporales data/batch_N.
- Reinicia data/batch_counter.txt a 0.
```

El archivo `.env` generado tendrá este formato:

```env
GEMINI_API_KEY=TU_GEMINI_API_KEY
GEMINI_FLASH_MODEL=gemini-3-flash-preview
GEMINI_FLASH_LITE_MODEL=gemini-3.1-flash-lite-preview
```

> El archivo `.env` no debe subirse al repositorio.

---

### 4. Instalar dependencias manualmente, si es necesario

Si se prefiere no instalar dependencias durante el setup automático:

```bash
python master.py setup --api-key TU_GEMINI_API_KEY --no-install
```

Después pueden instalarse manualmente con:

```bash
python -m pip install -r requirements.txt
```

---

### 5. Añadir los archivos de entrada

Coloca los archivos XML de pacientes en:

```text
data/input/
```

Ejemplo:

```text
data/input/topics2021.xml
```

---

### 6. Ejecutar el pipeline

#### Modo normal usando ClinicalTrials.gov live

```bash
python master.py run
```

#### Modo TREC 2021

```bash
python master.py run --trec-year 2021
```

#### Modo TREC 2022

```bash
python master.py run --trec-year 2022
```

#### Ejecutar generando dossiers PDF

```bash
python master.py run --generate-dossiers
```

---

### 7. Salidas generadas

Cada ejecución crea una carpeta de batch en:

```text
data/output/batch_N/
```

Dentro se generan los resultados por paciente y la predicción final consolidada.

Ejemplo:

```text
data/output/batch_1/
├── Batch1_Predictions.json
├── Batch1_TREC_Run.txt
├── Topic_1/
│   ├── 1_Topic_1_Cuestionario.pdf
│   └── 3_Topic_1_Ranking.json
└── ...
```

También se guardan resultados intermedios en:

```text
data/batch_N/
```

Estos archivos permiten revisar el estado de cada módulo, depurar errores y consultar la trazabilidad completa del pipeline.

---

### 8. Evaluación con qrels

Para evaluar resultados contra un gold standard TREC, coloca el archivo de qrels en:

```text
data/trec/
```

Ejemplo:

```text
data/trec/qrels2021.txt
```

Después ejecuta el pipeline en el modo correspondiente:

```bash
python master.py run --trec-year 2021
```

Si el archivo qrels existe, el módulo de métricas intentará calcular automáticamente los resultados.

---

### 9. Notas importantes

* Para usar los modos TREC, la primera ejecución puede tardar bastante porque se descarga y prepara el snapshot histórico de ensayos clínicos.
* El corpus TREC se cachea localmente mediante `ir_datasets`.
* Los modelos LLM requieren una API key válida de Gemini.
* La carpeta `data/input/` se vacía al ejecutar `setup`, por lo que los XML deben añadirse después de configurar el proyecto.


---

## Resultados obtenidos

> Pendiente de completar.

En este apartado se incluirán:

* Número de pacientes procesados.
* Número medio de ensayos recuperados.
* Número de ensayos rankeados.
* Ejemplos de predicciones finales.
* Métricas obtenidas en el benchmark, si están disponibles.
* Análisis cualitativo de errores.

---

## Decisiones de diseño

### Modularidad

Cada módulo tiene una responsabilidad concreta y se comunica mediante JSON. Esto facilita el desarrollo paralelo, la depuración y la sustitución de componentes.

### Determinismo en evaluación y ranking

Aunque algunos módulos usan LLM para extracción o parsing, la evaluación de criterios y el ranking final son deterministas. Esto mejora la reproducibilidad.

### Normalización clínica

El sistema incorpora una capa dedicada de normalización para reducir diferencias entre cómo aparece un concepto en el expediente del paciente y cómo aparece en un criterio de ensayo.

### Explicabilidad

El sistema no solo devuelve una lista de ensayos, sino también el razonamiento intermedio: atributos, criterios, evaluaciones y puntuaciones.

### Exportación final

El `Prediction Exporter` permite generar una salida unificada para todos los pacientes, preparada para entrega.

---

## Equipo

```text
Èric Medina Bruch,
Víctor Segura García,
Alex Ruiz Zapater
```

```
```
