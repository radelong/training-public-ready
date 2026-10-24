import importlib.util
import zipfile
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "harmonize_class_decks", ROOT / "scripts" / "harmonize-class-decks.py"
)
harmonizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harmonizer)


def test_harmonize_deck_preserves_package_and_replaces_only_theme_colors(tmp_path):
    source = tmp_path / "original.pptx"
    target = tmp_path / "copy.pptx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld><a:srgbClr val="2FBF71"/><a:srgbClr val="FFFFFF"/></p:sld>',
        )
        package.writestr(
            "ppt/theme/theme1.xml",
            '<a:theme><a:clrScheme><a:dk1><a:sysClr val="window" lastClr="000000"/>'
            '</a:dk1><a:accent2><a:srgbClr val="old"/></a:accent2></a:clrScheme></a:theme>',
        )
        package.writestr("ppt/notesSlides/notesSlide1.xml", "untouched")

    changed = harmonizer.harmonize_deck(source, target, {"2FBF71": "1C7293"})

    assert changed == 1
    with zipfile.ZipFile(target) as package:
        assert package.namelist() == [
            "ppt/slides/slide1.xml", "ppt/theme/theme1.xml", "ppt/notesSlides/notesSlide1.xml"
        ]
        assert b'val="1C7293"' in package.read("ppt/slides/slide1.xml")
        assert b'val="FFFFFF"' in package.read("ppt/slides/slide1.xml")
        theme = package.read("ppt/theme/theme1.xml")
        assert b'<a:dk1><a:srgbClr val="0B2440"/></a:dk1>' in theme
        assert b'<a:accent2><a:srgbClr val="1C7293"/></a:accent2>' in theme
        assert package.read("ppt/notesSlides/notesSlide1.xml") == b"untouched"


def test_harmonizer_rejects_output_inside_original_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="separate"):
        harmonizer.harmonize_directory(source, source / "styled")
