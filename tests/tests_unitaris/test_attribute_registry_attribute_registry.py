# Executar amb:
# python -m pytest tests/tests_unitaris/test_attribute_registry.py -v

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"

sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from normalization.normalizer import ClinicalNormalizer
from attribute_registry import AttributeRegistryBuilder

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "parsed_trial_criteria"
    / "trial_candidates_with_criteria_real.json"
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "attribute_registry"
OUTPUT_PATH = OUTPUT_DIR / "attribute_registry_real.json"


@pytest.fixture
def candidate_json() -> dict:
    assert INPUT_PATH.exists(), f"Input file not found: {INPUT_PATH}"

    with INPUT_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict), "Input JSON must be a dict"
    return data


def test_attribute_registry_builder_creates_valid_registry(candidate_json: dict) -> None:
    normalizer = ClinicalNormalizer()

    builder = AttributeRegistryBuilder(
        normalizer=normalizer,
        include_soft_criteria=True,
        include_administrative_criteria=False,
    )

    registry = builder.build_from_candidate_json(
        candidate_json=candidate_json,
        output_path=OUTPUT_PATH,
    )

    assert isinstance(registry, dict)

    assert registry["schema_version"] == "attribute_registry_v1"
    assert registry["registry_status"] in {
        "built",
        "built_with_warnings",
        "empty",
        "failed",
    }

    assert "registry_id" in registry
    assert "source_trials" in registry
    assert "source_criteria" in registry
    assert "attributes" in registry
    assert "summary" in registry
    assert "flags" in registry

    assert isinstance(registry["source_trials"], list)
    assert isinstance(registry["source_criteria"], list)
    assert isinstance(registry["attributes"], list)
    assert isinstance(registry["flags"], list)

    assert registry["registry_status"] != "failed", registry.get("flags")

    assert registry["summary"]["total_source_criteria"] == len(
        registry["source_criteria"]
    )
    assert registry["summary"]["total_attributes"] == len(registry["attributes"])

    assert OUTPUT_PATH.exists(), f"Output file was not created: {OUTPUT_PATH}"

    with OUTPUT_PATH.open("r", encoding="utf-8") as f:
        written_registry = json.load(f)

    assert written_registry == registry


def test_attribute_registry_attributes_have_required_fields(candidate_json: dict) -> None:
    normalizer = ClinicalNormalizer()

    builder = AttributeRegistryBuilder(
        normalizer=normalizer,
        include_soft_criteria=True,
        include_administrative_criteria=False,
    )

    registry = builder.build_from_candidate_json(
        candidate_json=candidate_json,
        output_path=OUTPUT_PATH,
    )

    if registry["registry_status"] == "empty":
        pytest.skip("Registry is empty because no extractable criteria were found.")

    assert registry["attributes"], "Registry should contain at least one attribute"

    for attribute in registry["attributes"]:
        assert attribute["attribute_id"]
        assert attribute["canonical_name"]
        assert attribute["normalized_attribute"]

        assert attribute["type"]
        assert attribute["value_type"]

        assert attribute["criticality"] in {"low", "medium", "high"}

        assert isinstance(attribute["aliases"], list)
        assert isinstance(attribute["source_attribute_names"], list)
        assert isinstance(attribute["required_by"], list)

        assert attribute["normalization_method"] is not None
        assert attribute["normalization_confidence"] is not None

        for required_by in attribute["required_by"]:
            assert required_by["trial_id"]
            assert required_by["criterion_id"]
            assert required_by["criterion_text"]
            assert required_by["criterion_type"]


def test_attribute_registry_output_directory_is_created(candidate_json: dict) -> None:
    normalizer = ClinicalNormalizer()

    builder = AttributeRegistryBuilder(
        normalizer=normalizer,
        include_soft_criteria=True,
        include_administrative_criteria=False,
    )

    nested_output_path = (
        PROJECT_ROOT
        / "data"
        / "attribute_registry"
        / "nested"
        / "attribute_registry_real_nested.json"
    )

    if nested_output_path.exists():
        nested_output_path.unlink()

    registry = builder.build_from_candidate_json(
        candidate_json=candidate_json,
        output_path=nested_output_path,
    )

    assert registry["registry_status"] != "failed", registry.get("flags")
    assert nested_output_path.exists()

    with nested_output_path.open("r", encoding="utf-8") as f:
        written_registry = json.load(f)

    assert written_registry == registry