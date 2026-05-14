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
Asignar una puntuación final a cada ensayo clínico a partir de la evaluación de sus criterios de inclusión y exclusión.

El `Ranking Engine` recibe la salida del `Criterion Evaluator`, donde cada criterio ya ha sido clasificado como:

- `met`: el criterio se cumple.
- `not_met`: el criterio no se cumple.
- `unknown`: no hay información suficiente.
- `not_applicable`: el criterio no aplica.
- `evaluation_error`: no se ha podido evaluar correctamente.

A partir de esto, el módulo calcula un score entre `0` y `100` para cada ensayo.

---

#### Idea general de la fórmula

La puntuación se calcula criterio a criterio. Cada criterio aporta una cantidad positiva o negativa al resultado final según tres factores principales:

```text
valor del criterio × peso por dureza × peso por categoría × factor de confianza
```

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

Se ejecutó una primera evaluación del sistema sobre un batch inicial formado por 3 pacientes/topics.  
La ejecución generó correctamente las predicciones finales en formato JSON y en formato TREC Run.

### Resumen de la ejecución

| Métrica | Valor |
|---|---:|
| Total de topics procesados | 3 |
| Total de predicciones generadas | 140 |
| Archivos de ranking válidos | 3 |
| Archivos de ranking inválidos | 0 |
| Topics sin predicciones | 0 |
| Trials duplicados eliminados | 0 |
| Trials inválidos eliminados | 0 |

La exportación finalizó correctamente con estado `completed`, generando predicciones para los tres topics evaluados.

---

### Métricas globales

| Métrica | Valor |
|---|---:|
| Recall@20 | 0.060 |
| NDCG@10 | 0.482 |
| Micro-F1 | No disponible |

El valor de **Recall@20 = 0.060** indica que el sistema recupera aproximadamente un 6% de los ensayos relevantes dentro de los primeros 20 resultados. Este valor es bajo, por lo que la principal limitación detectada está en la fase de recuperación inicial de candidatos.

El valor de **NDCG@10 = 0.482** es moderado. Esto indica que, cuando el sistema consigue recuperar ensayos potencialmente relevantes, el ranking tiene cierta capacidad para ordenar los resultados útiles en posiciones altas.

La métrica **Micro-F1** no se ha calculado porque todavía no se dispone de etiquetas gold a nivel de criterio de inclusión/exclusión. Por tanto, en esta fase solo se evalúa recuperación y ranking, no la evaluación criterio a criterio.

---

### Consideraciones sobre el tamaño de la evaluación

Los resultados deben interpretarse como una evaluación preliminar, ya que el batch inicial solo incluye 3 pacientes/topics. Debido al tamaño reducido de la muestra, las métricas pueden variar mucho entre pacientes y no representan todavía el rendimiento general del sistema.

Aunque el **Recall@20 global es bajo**, este resultado no debe interpretarse como una conclusión definitiva, sino como una primera baseline sobre la que comparar futuras mejoras. Además, el **NDCG@10 de 0.482** muestra que el sistema tiene cierta capacidad para ordenar ensayos relevantes cuando estos han sido recuperados previamente.

Por tanto, esta primera ejecución demuestra principalmente que el pipeline completo funciona de extremo a extremo y que genera salidas evaluables. La prioridad en futuras iteraciones será ejecutar el sistema sobre un número mayor de pacientes y mejorar la recuperación inicial de candidatos para aumentar el Recall@20.

---

### Métricas por paciente

| Patient ID | Ensayos predichos | Ensayos relevantes | Recall@20 | NDCG@10 |
|---|---:|---:|---:|---:|
| 1 | 58 | 169 | 0.071 | 0.467 |
| 2 | 43 | 270 | 0.048 | 0.716 |
| 3 | 39 | 84 | 0.060 | 0.263 |

El paciente 2 obtiene el mejor resultado de ranking, con un **NDCG@10 de 0.716**, lo que indica que los ensayos relevantes recuperados aparecen relativamente bien posicionados en el Top 10.

El paciente 3 presenta el peor resultado de ranking, con un **NDCG@10 de 0.263**, lo que sugiere que, aunque se recuperan algunos ensayos relevantes, estos no quedan tan bien ordenados.

---

### Interpretación de resultados

Los resultados muestran que el sistema es capaz de ejecutar el pipeline completo y generar una salida evaluable. Sin embargo, el bajo Recall@20 indica que todavía se están perdiendo muchos ensayos relevantes en la fase de recuperación.

Esto apunta a que el principal cuello de botella está en los módulos de:

- `Patient Extractor`
- `Normalization`
- `Query Planner`
- `ClinicalTrials Client`
- `Query Refinement`

Es decir, antes de mejorar mucho más el ranking, es necesario mejorar la recuperación de candidatos. Si un ensayo relevante no entra en la lista inicial, el `Ranking Engine` ya no puede colocarlo en una buena posición.

---

### Análisis cualitativo

El sistema funciona correctamente como pipeline batch:

1. Lee los pacientes de entrada.
2. Extrae información clínica.
3. Genera queries.
4. Recupera ensayos candidatos.
5. Calcula scores.
6. Ordena resultados.
7. Exporta predicciones en JSON y formato TREC.

Sin embargo, las métricas indican que el sistema todavía necesita mejorar la cobertura de búsqueda. Las queries generadas pueden ser demasiado restrictivas o no estar capturando suficientes sinónimos clínicos. También puede ocurrir que algunos perfiles de paciente no estén suficientemente enriquecidos con biomarcadores, subtipo de enfermedad o tratamientos previos.

---

### Análisis de errores

Durante la ejecución del batch inicial se analizaron las salidas intermedias generadas por el pipeline para identificar en qué módulos se producen las principales limitaciones del sistema.

El sistema consiguió completar la ejecución para los 3 pacientes/topics y generó rankings válidos para todos ellos. Sin embargo, el análisis de los archivos intermedios muestra varios puntos de mejora relevantes.

#### 1. Fallo de extracción dirigida en el Topic 1

En el Topic 1 se detectó un fallo importante en el módulo `Directed Patient Extractor`. El sistema generó un `Attribute Registry` con 771 atributos necesarios para evaluar los ensayos recuperados, pero la extracción dirigida falló para todos ellos.

| Elemento | Valor |
|---|---:|
| Ensayos recuperados | 58 |
| Criterios fuente | 2479 |
| Atributos requeridos | 771 |
| Atributos encontrados | 0 |
| Errores de extracción | 771 |
| Cobertura de extracción | 0.0% |

El error registrado indica que Gemini no devolvió un JSON parseable para el esquema esperado:

```text
Directed extraction failed after 2 attempt(s): Gemini no devolvió JSON parseable para el schema LLMExtractionResponse
```

Esto provocó que muchas evaluaciones de criterios quedaran como `evaluation_error` o `unknown`, afectando directamente al ranking final.

**Impacto:**  
El ranking del Topic 1 se genera, pero con baja fiabilidad, porque el sistema no dispone de atributos clínicos extraídos para comparar correctamente paciente y criterios.

**Mejora propuesta:**  
Reducir el tamaño del `Attribute Registry`, dividir la extracción en bloques más pequeños, reforzar el esquema JSON esperado y añadir un mecanismo de recuperación cuando el LLM devuelva una salida inválida.

---

#### 2. Baja cobertura de extracción en Topics 2 y 3

En los Topics 2 y 3 la extracción dirigida sí funcionó, pero la cobertura fue baja.

| Topic | Atributos requeridos | Atributos encontrados | Cobertura |
|---|---:|---:|---:|
| 2 | 440 | 56 | 15.91% |
| 3 | 295 | 28 | 10.51% |

Esto significa que la mayoría de atributos necesarios para evaluar los criterios de los ensayos no estaban presentes en el expediente o no pudieron extraerse correctamente.

**Impacto:**  
Muchos criterios quedan como `unknown`, lo que reduce la confianza del ranking y provoca que el sistema no pueda confirmar si el paciente cumple o no ciertos criterios críticos.

**Mejora propuesta:**  
Mejorar la extracción clínica dirigida, priorizando primero atributos de alto impacto como edad, sexo, diagnóstico, subtipo, tratamientos previos, estado funcional, biomarcadores y criterios de exclusión frecuentes.

---

#### 3. Demasiados criterios críticos desconocidos

El `Ranking Engine` completó la ejecución, pero generó warnings porque muchos ensayos contienen criterios hard desconocidos.

| Topic | Ensayos rankeados | Ensayos con criterios críticos desconocidos |
|---|---:|---:|
| 1 | 58 | 50 |
| 2 | 43 | 39 |
| 3 | 39 | 37 |

Esto indica que el sistema está recuperando y rankeando ensayos, pero en muchos casos no tiene suficiente información para evaluar criterios importantes.

**Impacto:**  
El ranking puede ordenar ensayos de forma aproximada, pero no puede asegurar con suficiente confianza la elegibilidad del paciente.

**Mejora propuesta:**  
Diferenciar mejor entre:

- criterio realmente incumplido;
- criterio desconocido por falta de información;
- criterio administrativo no evaluable;
- criterio clínico crítico que debería generar una pregunta prioritaria.

---

#### 4. Ruido en el `Attribute Registry`

El análisis muestra que algunos atributos generados por el sistema son demasiado largos o poco limpios, por ejemplo atributos derivados de criterios completos en vez de conceptos clínicos concretos.

Esto sugiere que el `Trial Criteria Parser` y el `Attribute Registry` todavía pueden generar atributos demasiado específicos o mal segmentados.

**Impacto:**  
Si el atributo está mal definido, el `Directed Patient Extractor` no puede encontrarlo correctamente en el expediente. Esto aumenta los `not_found`, `unknown` y errores de evaluación.

**Mejora propuesta:**  
Mejorar la normalización de atributos para que criterios largos como:

```text
Age >= 18 years and severe aortic stenosis with bicuspid anatomy...
```

se dividan en atributos simples como:

```text
age
aortic_stenosis
bicuspid_aortic_valve
surgical_candidate
informed_consent
```

---

#### 5. Criterios duplicados detectados

Durante la construcción del `Attribute Registry`, el sistema detectó criterios duplicados y los omitió correctamente.

Ejemplo de warning:

```text
Duplicate criterion skipped
```

**Impacto:**  
Este error es de baja severidad y no bloquea la ejecución. De hecho, indica que el sistema tiene mecanismos de limpieza y deduplicación.

**Mejora propuesta:**  
Mantener la deduplicación y registrar estos casos solo como warnings de baja prioridad.

---

#### 6. Predominio de resultados `unknown`

El análisis de las evaluaciones muestra que muchos criterios quedan en estado `unknown`.

| Topic | Criterios evaluados | `unknown` | `evaluation_error` |
|---|---:|---:|---:|
| 1 | 3058 | 946 | 2112 |
| 2 | 1064 | 860 | 0 |
| 3 | 744 | 602 | 0 |

En el Topic 1 el problema principal son errores de extracción. En los Topics 2 y 3 el problema principal es la falta de información suficiente para evaluar muchos criterios.

**Impacto:**  
El sistema tiende a producir rankings conservadores, con muchos ensayos clasificados como baja coincidencia o con incertidumbre.

**Mejora propuesta:**  
Generar preguntas clínicas priorizadas para resolver los criterios desconocidos más importantes y mejorar el score de los ensayos que dependen de esa información.

---

### Principales limitaciones detectadas

| Limitación | Impacto | Mejora propuesta |
|---|---|---|
| Recall@20 bajo | Se pierden muchos ensayos relevantes | Mejorar generación de queries |
| Uso limitado de sinónimos clínicos | Puede no encontrar ensayos con terminología distinta | Ampliar normalización clínica |
| Ranking dependiente de pocos candidatos | Aunque el ranking funcione, no puede ordenar ensayos no recuperados | Aumentar recall antes del ranking |
| Micro-F1 no disponible | No se puede evaluar todavía criterio a criterio | Añadir gold labels de criterios |
| Evaluación con solo 3 pacientes | Muestra pequeña | Ejecutar sobre más topics TREC |
| Fallo de extracción dirigida en Topic 1 | Muchos criterios quedan como `evaluation_error` | Dividir la extracción en bloques y reforzar validación JSON |
| Baja cobertura de atributos extraídos | Muchos criterios quedan como `unknown` | Priorizar atributos clínicos críticos |
| Attribute Registry demasiado grande o ruidoso | Dificulta la extracción correcta | Simplificar y normalizar atributos |
| Muchos criterios hard desconocidos | Reduce la confianza del ranking | Generar preguntas clínicas priorizadas |

---

### Conclusión de la evaluación

Esta primera ejecución se considera una **baseline inicial** del sistema. La evaluación se ha realizado únicamente sobre 3 pacientes/topics, por lo que los resultados deben interpretarse con cautela y no como una medida definitiva del rendimiento general del sistema.

Aun así, la ejecución permite comprobar que el pipeline funciona de extremo a extremo: procesa los pacientes, genera rankings, exporta predicciones en formato JSON y produce una salida compatible con evaluación tipo TREC.

El **Recall@20 = 0.060** es bajo, lo que indica que el sistema todavía recupera pocos ensayos relevantes dentro de los primeros 20 resultados. Este resultado puede estar influido por el tamaño reducido de la muestra, pero el análisis de errores también muestra limitaciones reales en fases intermedias del pipeline, especialmente en la extracción dirigida de atributos y en la evaluación de criterios.

Por otro lado, el **NDCG@10 = 0.482** muestra un comportamiento más positivo: cuando el sistema consigue recuperar ensayos relevantes, tiene cierta capacidad para ordenarlos en posiciones razonables dentro del Top 10.

Por tanto, esta primera evaluación no debe interpretarse como un resultado final, sino como una primera medición funcional del sistema. La prioridad de mejora no está solo en aumentar el número de pacientes evaluados, sino también en reforzar los módulos de extracción, normalización, parseo de criterios y recuperación inicial de candidatos.

Las siguientes iteraciones deberían enfocarse en:

- ejecutar la evaluación sobre más pacientes/topics;
- mejorar el `Query Planner`;
- añadir más sinónimos clínicos;
- usar biomarcadores, subtipo de enfermedad y tratamientos previos en las queries;
- ajustar el `Query Refinement`;
- dividir la extracción dirigida en bloques más pequeños;
- mejorar la validación de JSON devuelto por el LLM;
- simplificar el `Attribute Registry`;
- generar preguntas clínicas priorizadas para resolver criterios `unknown`;
- comparar futuras ejecuciones contra esta baseline inicial.

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
