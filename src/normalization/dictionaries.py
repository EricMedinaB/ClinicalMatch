CONDITION_SYNONYMS = {
    "nsclc": "non-small cell lung cancer",
    "non small cell lung cancer": "non-small cell lung cancer",
    "non-small cell lung cancer": "non-small cell lung cancer",
    "non-small cell lung carcinoma": "non-small cell lung cancer",
    "nonsmall cell lung cancer": "non-small cell lung cancer",
    "carcinoma, non-small-cell lung": "non-small cell lung cancer",
    "lung adenocarcinoma": "non-small cell lung cancer",

    "lung cancer": "lung cancer",
    "cancer, lung": "lung cancer",
    "lung carcinoma": "lung cancer",
    "pulmonary cancer": "lung cancer",

    "sclc": "small cell lung cancer",
    "small cell lung cancer": "small cell lung cancer",
    "small-cell lung cancer": "small cell lung cancer",
    "small cell lung carcinoma": "small cell lung cancer",

    "gbm": "glioblastoma",
    "glioblastoma": "glioblastoma",
    "glioblastoma multiforme": "glioblastoma",

    "breast cancer": "breast cancer",
    "breast carcinoma": "breast cancer",
    "mammary cancer": "breast cancer",
    "metastatic breast cancer": "metastatic breast cancer",
}


CONDITION_MESH = {
    "non-small cell lung cancer": {
        "mesh_id": "D002289",
        "mesh_term": "Carcinoma, Non-Small-Cell Lung",
        "aliases": [
            "NSCLC",
            "non small cell lung cancer",
            "non-small cell lung carcinoma",
            "nonsmall cell lung cancer",
            "carcinoma, non-small-cell lung",
            "lung adenocarcinoma",
        ],
        "parents": [
            {
                "mesh_id": "D008175",
                "mesh_term": "Lung Neoplasms",
            },
            {
                "mesh_id": "D009369",
                "mesh_term": "Neoplasms",
            },
        ],
    },

    "lung cancer": {
        "mesh_id": "D008175",
        "mesh_term": "Lung Neoplasms",
        "aliases": [
            "lung carcinoma",
            "pulmonary cancer",
            "cancer, lung",
            "lung neoplasms",
        ],
        "parents": [
            {
                "mesh_id": "D009369",
                "mesh_term": "Neoplasms",
            }
        ],
    },

    "small cell lung cancer": {
        "mesh_id": "D055752",
        "mesh_term": "Small Cell Lung Carcinoma",
        "aliases": [
            "SCLC",
            "small-cell lung cancer",
            "small cell lung carcinoma",
        ],
        "parents": [
            {
                "mesh_id": "D008175",
                "mesh_term": "Lung Neoplasms",
            },
            {
                "mesh_id": "D009369",
                "mesh_term": "Neoplasms",
            },
        ],
    },

    "glioblastoma": {
        "mesh_id": "D005909",
        "mesh_term": "Glioblastoma",
        "aliases": [
            "GBM",
            "glioblastoma multiforme",
        ],
        "parents": [
            {
                "mesh_id": "D001932",
                "mesh_term": "Brain Neoplasms",
            },
            {
                "mesh_id": "D009369",
                "mesh_term": "Neoplasms",
            },
        ],
    },

    "breast cancer": {
        "mesh_id": "D001943",
        "mesh_term": "Breast Neoplasms",
        "aliases": [
            "breast carcinoma",
            "mammary cancer",
            "breast tumor",
        ],
        "parents": [
            {
                "mesh_id": "D009369",
                "mesh_term": "Neoplasms",
            }
        ],
    },

    "metastatic breast cancer": {
        "mesh_id": "D001943",
        "mesh_term": "Breast Neoplasms",
        "aliases": [
            "metastatic breast carcinoma",
            "stage iv breast cancer",
            "advanced breast cancer",
        ],
        "parents": [
            {
                "mesh_id": "D009369",
                "mesh_term": "Neoplasms",
            },
            {
                "mesh_id": "D009362",
                "mesh_term": "Neoplasm Metastasis",
            },
        ],
    },
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

    "unknown": "unknown",
    "not stated": "unknown",
    "not mentioned": "unknown",
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
    "fusion": "positive",

    "-": "negative",
    "negative": "negative",
    "not detected": "negative",
    "absent": "negative",
    "wild type": "negative",
    "wild-type": "negative",
    "wt": "negative",
    "no mutation": "negative",

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
    "pdl1": ("PDL1_status", "PD-L1 expression status", "categorical"),
}


BIOMARKER_ATTRIBUTE_IDS = {
    "EGFR": "EGFR_status",
    "ALK": "ALK_status",
    "BRAF": "BRAF_status",
    "KRAS": "KRAS_status",
    "HER2": "HER2_status",
    "ROS1": "ROS1_status",
    "PD-L1": "PDL1_status",
}
