CONDITION_SYNONYMS = {
    "nsclc": "non-small cell lung cancer",
    "non small cell lung cancer": "non-small cell lung cancer",
    "non-small cell lung cancer": "non-small cell lung cancer",
    "non-small cell lung carcinoma": "non-small cell lung cancer",
    "lung adenocarcinoma": "non-small cell lung cancer",
    "lung cancer": "lung cancer",

    "sclc": "small cell lung cancer",
    "small cell lung cancer": "small cell lung cancer",

    "gbm": "glioblastoma",
    "glioblastoma": "glioblastoma",
    "glioblastoma multiforme": "glioblastoma",

    "breast cancer": "breast cancer",
    "metastatic breast cancer": "metastatic breast cancer",
}

DRUG_SYNONYMS = {
    "tagrisso": "osimertinib",
    "azd9291": "osimertinib",
    "osimertinib mesylate": "osimertinib",
    "osimertinib": "osimertinib",

    "avastin": "bevacizumab",
    "bevacizumab": "bevacizumab",

    "keytruda": "pembrolizumab",
    "pembrolizumab": "pembrolizumab",

    "opdivo": "nivolumab",
    "nivolumab": "nivolumab",

    "temodar": "temozolomide",
    "temozolomide": "temozolomide",

    "cpt-11": "irinotecan",
    "irinotecan": "irinotecan",
}

SEX_SYNONYMS = {
    "m": "male",
    "male": "male",
    "man": "male",
    "gentleman": "male",
    "boy": "male",

    "f": "female",
    "female": "female",
    "woman": "female",
    "lady": "female",
    "girl": "female",
}

STATUS_SYNONYMS = {
    "+": "positive",
    "positive": "positive",
    "detected": "positive",
    "present": "positive",
    "mutated": "positive",
    "mutation": "positive",
    "activating mutation": "positive",
    "rearranged": "positive",
    "amplified": "positive",

    "-": "negative",
    "negative": "negative",
    "not detected": "negative",
    "absent": "negative",
    "wild type": "negative",
    "wild-type": "negative",
    "wt": "negative",

    "unknown": "unknown",
    "not available": "unknown",
    "n/a": "unknown",
    "na": "unknown",
    "pending": "unknown",
}

ATTRIBUTE_SYNONYMS = {
    "age": ("age", "Age", "number"),

    "sex": ("sex", "Biological sex", "categorical"),
    "gender": ("sex", "Biological sex", "categorical"),

    "ecog": ("ECOG", "ECOG performance status", "integer"),
    "ecog ps": ("ECOG", "ECOG performance status", "integer"),
    "performance status": ("ECOG", "ECOG performance status", "integer"),
    "eastern cooperative oncology group": ("ECOG", "ECOG performance status", "integer"),

    "karnofsky": ("KPS", "Karnofsky performance status", "integer"),
    "kps": ("KPS", "Karnofsky performance status", "integer"),

    "egfr": ("EGFR_status", "EGFR mutation status", "categorical"),
    "egfr mutation": ("EGFR_status", "EGFR mutation status", "categorical"),

    "alk": ("ALK_status", "ALK rearrangement status", "categorical"),
    "alk rearrangement": ("ALK_status", "ALK rearrangement status", "categorical"),

    "braf": ("BRAF_status", "BRAF mutation status", "categorical"),
    "kras": ("KRAS_status", "KRAS mutation status", "categorical"),
    "her2": ("HER2_status", "HER2 status", "categorical"),
    "pd-l1": ("PDL1_status", "PD-L1 expression status", "categorical"),
}