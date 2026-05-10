from normalization.dictionaries import (
    ATTRIBUTE_SYNONYMS,
    CONDITION_SYNONYMS,
    DRUG_SYNONYMS,
)

from normalization.schemas import (
    NormalizedAttribute,
    NormalizedBiomarker,
    NormalizedConcept,
    NormalizedValue,
)

class ClinicalNormalizer:
    #Funcion para quitar espacios al principio y final y pasar a minusculas
    def clean_text(self, text):
        return text.strip().lower()

    def normalize_condition(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        if cleaned in CONDITION_SYNONYMS:
            return NormalizedConcept(
                raw=text,
                normalized=CONDITION_SYNONYMS[cleaned],
                concept_type="condition",
                method="dictionary",
                confidence=1.0
            )

        return NormalizedConcept(
            raw=text,
            normalized=cleaned,
            concept_type="condition",
            method="not_normalized",
            confidence=0.3
        )
    
    def normalize_drug(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        if cleaned in DRUG_SYNONYMS:
            return NormalizedConcept(
                raw=text,
                normalized=DRUG_SYNONYMS[cleaned],
                concept_type="drug",
                method="alias_match",
                confidence=1.0
            )

        return NormalizedConcept(
            raw=text,
            normalized=cleaned,
            concept_type="drug",
            method="not_normalized",
            confidence=0.3
        )
    
    def normalize_sex(self, value):
        if value is None:
            return None

        cleaned = self.clean_text(value)

        male_values = {"m", "male", "man", "gentleman", "boy"}
        female_values = {"f", "female", "woman", "lady", "girl"}

        if cleaned in male_values:
            return NormalizedValue(
                raw=value,
                normalized="male",
                value_type="categorical",
                method="dictionary",
                confidence=1.0
            )

        if cleaned in female_values:
            return NormalizedValue(
                raw=value,
                normalized="female",
                value_type="categorical",
                method="dictionary",
                confidence=1.0
            )

        return NormalizedValue(
            raw=value,
            normalized="unknown",
            value_type="categorical",
            method="not_normalized",
            confidence=0.2
        )
    def normalize_biomarker_text(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        biomarkers = ["EGFR", "ALK", "BRAF", "KRAS", "HER2", "ROS1", "PD-L1"]

        biomarker = None

        for item in biomarkers:
            if item.lower() in cleaned:
                biomarker = item
                break

        if biomarker is None:
            return NormalizedBiomarker(
                raw=text,
                biomarker="unknown",
                attribute_id="unknown_biomarker_status",
                normalized_value="unknown",
                method="not_detected",
                confidence=0.2
            )

        if "-" in cleaned or "negative" in cleaned or "wild-type" in cleaned or "wild type" in cleaned or "not detected" in cleaned:
            status = "negative"
            method = "simple_negative_match"
            confidence = 0.9
        elif "+" in cleaned or "positive" in cleaned or "mutation" in cleaned or "detected" in cleaned:
            status = "positive"
            method = "simple_positive_match"
            confidence = 0.9
        else:
            status = "unknown"
            method = "status_unknown"
            confidence = 0.6

        return NormalizedBiomarker(
            raw=text,
            biomarker=biomarker,
            attribute_id=f"{biomarker}_status",
            normalized_value=status,
            method=method,
            confidence=confidence
        )

    def normalize_attribute(self, text):
        if text is None:
            return None

        cleaned = self.clean_text(text)

        if cleaned in ATTRIBUTE_SYNONYMS:
            attribute_id, canonical_name, value_type = ATTRIBUTE_SYNONYMS[cleaned]

            return NormalizedAttribute(
                raw=text,
                attribute_id=attribute_id,
                canonical_name=canonical_name,
                value_type=value_type,
                method="dictionary",
                confidence=1.0
            )

        return NormalizedAttribute(
            raw=text,
            attribute_id=cleaned,
            canonical_name=text.strip(),
            value_type="unknown",
            method="not_normalized",
            confidence=0.3
        )