from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "20261023-startup-tutorial-1"


def test_guide_route_and_cache_version_are_connected():
    index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend/academy.js").read_text(encoding="utf-8")
    assert 'data-page="lab-guide"' not in index
    assert 'labGuideMarkup()+heading("Your next step starts here"' in app
    assert f"/static/lab-startup.js?v={VERSION}" in index
    assert "/static/academy.js?v=20261023-catalog-guide-1" in index


def test_video_captions_transcript_and_poster_are_available():
    app = (ROOT / "frontend/academy.js").read_text(encoding="utf-8")
    assert f"/static/lab-guide.mp4?v={VERSION}" in app
    assert f"/static/lab-guide.vtt?v={VERSION}" in app
    assert f"/static/lab-guide-poster.png?v={VERSION}" in app
    assert 'fetch("/static/lab-guide.vtt"' in app
    assert "cues.join(\" \")" in app
    assert (ROOT / "frontend/lab-guide.vtt").read_text(encoding="utf-8-sig").startswith("WEBVTT")
    assert (ROOT / "frontend/lab-guide.mp4").stat().st_size > 1_000_000
    assert (ROOT / "frontend/lab-guide-poster.png").is_file()


def test_startup_progress_hooks_and_accessible_visual_styles_are_present():
    index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend/academy.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend/academy.css").read_text(encoding="utf-8")
    assert "data-page=\"lab-guide\"" not in index
    assert "startupMarkup(d)" in app
    assert "setInterval(updateStartupProgress,1000)" in app
    assert "aria-live=\"polite\"" in app
    assert '.lab-startup-meter[data-indeterminate="true"]' in css
    assert "prefers-reduced-motion:reduce" in css
