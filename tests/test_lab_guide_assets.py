import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def narration_scenes():
    tree = ast.parse((ROOT / "scripts/create-lab-guide-video.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCENES" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Video narration scenes not found")


def caption_cues():
    lines = (ROOT / "frontend/lab-guide.vtt").read_text(encoding="utf-8").splitlines()
    cues = []
    collecting = False
    for line in lines:
        if "-->" in line:
            collecting = True
        elif not line.strip():
            collecting = False
        elif collecting:
            cues.append(line.strip())
    return cues


def test_video_captions_match_the_spoken_narration():
    spoken = " ".join(scene["narration"] for scene in narration_scenes())
    captions = " ".join(caption_cues())
    assert captions == spoken


def test_in_page_transcript_uses_the_same_caption_file():
    app = (ROOT / "frontend/academy.js").read_text(encoding="utf-8")
    assert 'fetch("/static/lab-guide.vtt"' in app
    assert 'src="/static/lab-guide.vtt?v=20261022-lab-guide-2"' in app
    assert 'src="/static/lab-guide.mp4?v=20261022-lab-guide-2"' in app
    assert "cues.join(\" \")" in app


def test_startup_assets_load_and_reduced_motion_remains_indeterminate():
    index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend/academy.css").read_text(encoding="utf-8")
    app = (ROOT / "frontend/academy.js").read_text(encoding="utf-8")
    video = ROOT / "frontend/lab-guide.mp4"
    assert "/static/lab-startup.js?v=20261022-lab-guide-2" in index
    assert "/static/academy.js?v=20261024-admin-exam-resets-1" in index
    assert 'data-page="lab-guide"' not in index
    assert '$("content").innerHTML=labGuideMarkup()+heading("Your next step starts here"' in app
    assert 'else if(state.page==="lab-guide")' not in app
    assert 'loadLabGuideTranscript();}' in app
    assert 'return "catalog"' in app
    assert video.is_file() and video.stat().st_size > 1_000_000
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert '.lab-startup-meter[data-indeterminate="true"] i{width:100%!important' in css
