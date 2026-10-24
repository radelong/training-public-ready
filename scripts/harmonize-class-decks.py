#!/usr/bin/env python3
"""Create consistent Academy-themed copies of the class PowerPoint decks."""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path


PALETTE = {
    "dk1": "0B2440",
    "lt1": "FFFFFF",
    "dk2": "1F2937",
    "lt2": "EEF3F8",
    "accent1": "0B2440",
    "accent2": "1C7293",
    "accent3": "E8A33D",
    "accent4": "13566E",
    "accent5": "56677A",
    "accent6": "D7E0E8",
    "hlink": "1C7293",
    "folHlink": "13566E",
}

LINUX_ACCENTS = {
    "01": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "1C7A48": "0B2440", "2FBF71": "1C7293", "5FE39B": "BCE3EC"},
    "02": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "8F5C15": "0B2440", "D98E2B": "1C7293", "F0C878": "BCE3EC"},
    "03": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "1B5FA8": "0B2440", "2E86DE": "1C7293", "7BB8F5": "BCE3EC"},
    "04": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "5B3894": "0B2440", "8E5CD9": "1C7293", "C4A6F0": "BCE3EC"},
    "05": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "0E6B64": "0B2440", "179E94": "1C7293"},
    "06": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "8A431D": "0B2440", "C1622F": "1C7293", "F0A87C": "BCE3EC"},
    "07": {"23272E": "0B2440", "181B20": "1F2937", "F6F6F3": "EEF3F8",
           "8A2536": "0B2440", "C23B4E": "1C7293", "F08C9B": "BCE3EC"},
}

NETWORK_ACCENTS = {
    "01": {"0B5FA5": "0B2440", "E9F1F7": "EEF3F8", "E7EFF6": "EEF3F8"},
    "02": {"0E7C61": "0B2440", "E9F3F1": "EEF3F8"},
    "03": {"6A3FA0": "0B2440", "F2EEF6": "EEF3F8"},
    "04": {"B3212E": "0B2440", "F8EBEC": "EEF3F8"},
    "05": {"C97A1B": "0B2440", "FAF3EA": "EEF3F8"},
}

SECURITY_ACCENTS = {"1F2937": "0B2440"}
THEME_PART = re.compile(r"^ppt/theme/theme\d+\.xml$")
COLOR_PART = re.compile(
    r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|"
    r"slideMasters/slideMaster\d+|theme/theme\d+)\.xml$"
)


def _replace_theme_colors(xml: bytes) -> bytes:
    for name, color in PALETTE.items():
        tag = name.encode("ascii")
        pattern = re.compile(rb"(<a:" + tag + rb"\b[^>]*>).*?(</a:" + tag + rb">)", re.S)
        xml = pattern.sub(lambda match: match.group(1) + b'<a:srgbClr val="' +
                          color.encode("ascii") + b'"/>' + match.group(2), xml)
    return xml


def harmonize_deck(source: Path, destination: Path, replacements: dict[str, str]) -> int:
    """Copy a PPTX, preserving package entries, while harmonizing explicit theme colors."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    changed = 0
    with zipfile.ZipFile(source, "r") as incoming, zipfile.ZipFile(destination, "w") as outgoing:
        for info in incoming.infolist():
            content = incoming.read(info.filename)
            if COLOR_PART.fullmatch(info.filename):
                if THEME_PART.fullmatch(info.filename):
                    content = _replace_theme_colors(content)
                for old, new in replacements.items():
                    pattern = re.compile(
                        rb'(?i)(<a:srgbClr\b[^>]*\bval=["\'])' + old.encode("ascii") +
                        rb'(["\'])'
                    )
                    content, count = pattern.subn(lambda match: match.group(1) +
                                                  new.encode("ascii") + match.group(2), content)
                    changed += count
            outgoing.writestr(info, content)
    return changed


def _replacement_map(source: Path) -> dict[str, str]:
    folder = source.parent.name.casefold()
    if folder == "linux":
        match = re.search(r"module\s*(\d+)", source.stem, re.I)
        return LINUX_ACCENTS.get(match.group(1).zfill(2), {}) if match else {}
    if folder == "networking":
        match = re.match(r"(\d+)", source.stem)
        return NETWORK_ACCENTS.get(match.group(1).zfill(2), {}) if match else {}
    if folder == "security":
        return SECURITY_ACCENTS
    return {}


def harmonize_directory(source_root: Path, destination_root: Path) -> list[tuple[Path, int]]:
    source_root = source_root.resolve()
    destination_root = destination_root.resolve()
    if destination_root == source_root or source_root in destination_root.parents:
        raise ValueError("Output must be separate from the original class folder")
    if destination_root.exists():
        raise FileExistsError(destination_root)
    results = []
    for source in sorted(source_root.rglob("*.pptx")):
        destination = destination_root / source.relative_to(source_root)
        results.append((destination, harmonize_deck(source, destination, _replacement_map(source))))
    if not results:
        raise ValueError(f"No PowerPoint decks found under {source_root}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    for path, count in harmonize_directory(args.source, args.destination):
        print(f"HARMONIZED {path.name}: {count} explicit color references")
    print(f"Completed {len(list(args.destination.rglob('*.pptx')))} deck copies; originals unchanged")


if __name__ == "__main__":
    main()
