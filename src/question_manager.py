# -*- coding: utf-8 -*-
import json
from pathlib import Path
from fpdf import FPDF

class QuestionManager:
    def __init__(self):
        pass

    def calculate_impact(self, original_attribute_data: dict) -> dict:

        impact_data = original_attribute_data.get("impact", {})
        
        ensayos_afectados = impact_data.get("affected_trials", 0)
        criterios_afectados = impact_data.get("affected_criteria", 0)
        is_critical = impact_data.get("is_ranking_critical", False)

        peso_criticidad = 10 if is_critical else 5
        severidad = criterios_afectados * peso_criticidad

        score = (0.40 * ensayos_afectados) + (0.30 * severidad)

        if score >= 5.0:
            priority = "ALTA"
        elif score >= 2.0:
            priority = "MEDIA"
        else:
            priority = "BAJA"

        return {
            "score": round(score, 2), 
            "priority": priority,
            "affected_trials_count": ensayos_afectados
        }

    def unify_patient_questions(self, patient_id: str, generated_questions: list, original_attributes: list) -> dict:

        unified_list = []

        for i, question_data in enumerate(generated_questions):
            attr_name = question_data.get("attribute")
            
            original_data = next((item for item in original_attributes if item.get("attribute_id") == attr_name or item.get("canonical_name") == attr_name), {})
            
            impact_info = self.calculate_impact(original_data)

            unified_question = {
                "question_id": f"Q_{patient_id}_{i+1:03d}",
                "attribute": attr_name,
                "priority": impact_info["priority"],
                "impact_score": impact_info["score"],
                "question_text": question_data.get("question"),
                "expected_type": question_data.get("expected_answer_type"),
                "valid_answers": question_data.get("valid_answers"),
                "resolves_criteria": question_data.get("resolves_criteria", [])
            }
            unified_list.append(unified_question)

        unified_list.sort(key=lambda x: x["impact_score"], reverse=True)

        return {
            "patient_id": patient_id,
            "total_questions": len(unified_list),
            "questions": unified_list
        }
    def export_to_pdf(self, patient_json: dict, output_path: str):

        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        try:
            pdf.add_font("Montserrat", style="B", fname="Montserrat-VariableFont_wght.ttf")
            pdf.add_font("Inter", style="", fname="Inter-VariableFont_opsz,wght.ttf")
            pdf.add_font("Inter", style="B", fname="Inter-VariableFont_opsz,wght.ttf")
            pdf.add_font("Inter", style="I", fname="Inter-Italic-VariableFont_opsz,wght.ttf")
            font_title = "Montserrat"
            font_body = "Inter"
        except Exception as e:
            print(f" Aviso: No se pudieron cargar las fuentes ({e}). Usando Helvetica.")
            font_title = "Helvetica"
            font_body = "Helvetica"

        verde_deloitte = (134, 188, 37)
        gris_pizarra = (69, 69, 69)

        pdf.set_font(font_title, style="B", size=18)
        pdf.set_text_color(*verde_deloitte)
        pdf.cell(0, 10, text="Cuestionario Clínico Faltante", new_x="LMARGIN", new_y="NEXT", align="C")
        
        pdf.set_font(font_body, style="B", size=12)
        pdf.set_text_color(*gris_pizarra)
        patient_id = patient_json.get("patient_id", "Desconocido")
        pdf.cell(0, 10, text=f"Paciente ID: {patient_id}", new_x="LMARGIN", new_y="NEXT", align="C")

        pdf.set_draw_color(*verde_deloitte)
        pdf.set_line_width(0.5)
        pdf.line(15, 30, 195, 30)
        pdf.ln(10)

        for q in patient_json.get("questions", []):
            priority = q.get('priority')
            
            if priority == "ALTA":
                pdf.set_text_color(220, 50, 50) 
            elif priority == "MEDIA":
                pdf.set_text_color(220, 140, 0)  
            else:
                pdf.set_text_color(*verde_deloitte) 

            pdf.set_font(font_body, style="B", size=12)
            pdf.cell(0, 10, text=f"[{priority}] ID: {q.get('question_id')} - {q.get('attribute')}", new_x="LMARGIN", new_y="NEXT")

            pdf.set_text_color(*gris_pizarra)
            pdf.set_font(font_body, style="", size=11)
            pdf.set_x(15) 
            pdf.write(8, text=f"Pregunta: {q.get('question_text')}")
            pdf.ln(8)
            
            opciones = q.get('valid_answers')
            if opciones:
                pdf.set_font(font_body, style="I", size=10)
                opciones_str = ", ".join([str(o) for o in opciones])
                pdf.set_x(15)
                pdf.write(8, text=f"Opciones válidas: {opciones_str}")
                pdf.ln(8)
            
            pdf.ln(3)
            pdf.set_font(font_body, style="B", size=10)
            pdf.set_text_color(*verde_deloitte)
            pdf.cell(0, 8, text="Respuesta del médico: ____________________________________________________", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(8)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        pdf.output(output_path)