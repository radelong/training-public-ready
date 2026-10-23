import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("class_pretest_importer", ROOT / "scripts" / "import-class-pretests.py")
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


def test_pretest_merge_preserves_each_non_pretest_snapshot():
    published = {
        "title": "Example class",
        "category": "Networking",
        "exam": {"questions": [{"id": "published-exam-question"}]},
        "modules": [
            {"id": "module-a", "title": "A", "topics": ["published topic"], "quiz": []},
            {"id": "module-b", "title": "B", "quiz": []},
        ],
    }
    draft = {
        "title": "Example class",
        "category": "Draft category",
        "exam": {"questions": [{"id": "draft-exam-question"}]},
        "modules": [
            {"id": "module-b", "title": "B draft", "estimated_minutes": 17},
            {"id": "module-a", "title": "A", "topics": ["draft topic"]},
        ],
    }
    proposed = {
        "progress_test_enabled": True,
        "modules": [
            {"id": "module-a", "quiz": [{"id": "question-a"}]},
            {"id": "module-b", "quiz": [{"id": "question-b"}]},
        ],
    }

    published_result = IMPORTER.merge_pretests(published, proposed, "Example class")
    draft_result = IMPORTER.merge_pretests(draft, proposed, "Example class")

    assert published_result["category"] == "Networking"
    assert published_result["exam"] == published["exam"]
    assert published_result["modules"][0]["topics"] == ["published topic"]
    assert draft_result["category"] == "Draft category"
    assert draft_result["exam"] == draft["exam"]
    assert draft_result["modules"][0]["title"] == "B draft"
    assert draft_result["modules"][0]["estimated_minutes"] == 17
    assert draft_result["modules"][1]["topics"] == ["draft topic"]
    assert draft_result["modules"][0]["quiz"] == [{"id": "question-b"}]
    assert draft_result["progress_test_enabled"] is True
    assert "progress_test_enabled" not in draft
    assert "quiz" not in draft["modules"][0]


def test_pretest_merge_refuses_changed_module_ids():
    with pytest.raises(ValueError, match="Pretest module IDs do not match"):
        IMPORTER.merge_pretests(
            {"modules": [{"id": "module-a"}]},
            {"modules": [{"id": "module-b", "quiz": []}]},
            "Example class",
        )
