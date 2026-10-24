#!/usr/bin/env python3
"""Build the Academy's offline lab walkthrough video using local Windows speech."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_VIDEO = ROOT / "frontend" / "lab-guide.mp4"
OUT_VTT = ROOT / "frontend" / "lab-guide.vtt"
OUT_POSTER = ROOT / "frontend" / "lab-guide-poster.png"
OUT_TRANSCRIPT = ROOT / "docs" / "Lab_Use_Tutorial_Transcript.md"
WIDTH, HEIGHT = 1280, 720
NAVY = "#142c3e"
NAVY2 = "#203d52"
CYAN = "#20a7b4"
PALE = "#e9f5f6"
INK = "#193447"
MUTED = "#617788"
WHITE = "#ffffff"

SCENES = [
    {
        "title": "A place to practice",
        "kicker": "WELCOME TO THE TRAINING ACADEMY",
        "focus": "Your own training space",
        "detail": "Practice safely in a private lab session.",
        "narration": "Welcome to the Training Academy. Labs give you a private environment to practice technical tasks without making changes to production systems. This guide covers the full workflow, from choosing a lab to reviewing your results.",
        "screen": "catalog",
    },
    {
        "title": "Choose a lab and start",
        "kicker": "STEP 1 · OPEN YOUR ENVIRONMENT",
        "focus": "Start lab",
        "detail": "Wait for a seat, then follow the setup estimate.",
        "narration": "Open the Lab catalog and review the description, topics, exercise count, and expected completion time. Select Start lab once. If the service is busy, the request may wait for an available seat. During VM setup, the Academy shows a best guess based on typical launch times. The bar is an estimate, not a measured completion percentage, and the lab is ready only when its status says Ready.",
        "screen": "startup",
    },
    {
        "title": "Read the guide first",
        "kicker": "STEP 2 · PREPARE THE EXERCISE",
        "focus": "Start exercise",
        "detail": "Keep the task and diagram visible while you work.",
        "narration": "In the workspace, choose an exercise from the list. Read the task and goal, and review any diagram before starting. Select Start exercise to prepare its lesson files and baseline. The exercise guide stays on the page while you use the terminal, so you can keep the instructions and diagram in view.",
        "screen": "exercise",
    },
    {
        "title": "Work in the embedded terminal",
        "kicker": "STEP 3 · USE YOUR LAB CONSOLE",
        "focus": "Connect terminal",
        "detail": "Paired labs provide separate Sender and Listener consoles.",
        "narration": "Select Connect terminal to open the console inside the Academy. Click inside the terminal before typing commands. In a paired lab, the Sender and Listener have separate consoles and different hostnames. If a console disconnects, use Reconnect for that role and continue in the same session.",
        "screen": "terminal",
    },
    {
        "title": "Use hints without losing your place",
        "kicker": "STEP 4 · GET HELP WHEN NEEDED",
        "focus": "Hint · Solution",
        "detail": "The guide and session stay open as you review help.",
        "narration": "If you get stuck, use Hint for a smaller nudge. Use Solution when you need the full walkthrough. These actions keep the exercise guide and lab session on the page, so you can return to your work without starting a new session.",
        "screen": "help",
    },
    {
        "title": "Check your work",
        "kicker": "STEP 5 · VERIFY AND LEARN",
        "focus": "Check my work",
        "detail": "Review feedback, make corrections and try again.",
        "narration": "Select Check my work when you are ready. The Academy returns verification feedback and records the result in your account. If the exercise is not complete, read the feedback, make the needed changes and check again. Your lab progress is separate from results already recorded.",
        "screen": "check",
    },
    {
        "title": "Reset, end and review results",
        "kicker": "STEP 6 · CLOSE OUT",
        "focus": "My results",
        "detail": "Reset clears VM files. End releases the lab seat.",
        "narration": "Restore a clean VM when you want to restart the environment. This deletes files in the assigned VM but keeps recorded results. Select End lab when you are finished; the Academy deletes the assigned VM and releases its seat. Visit My results to review your recorded lab work.",
        "screen": "results",
    },
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
             r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
             "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrapped(draw: ImageDraw.ImageDraw, text: str, typeface, width: int, max_lines: int = 3):
    words = text.split()
    lines, current = [], ""
    for word in words:
        proposal = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), proposal, font=typeface)[2] > width:
            lines.append(current)
            current = word
        else:
            current = proposal
    if current:
        lines.append(current)
    return lines[:max_lines]


def render_scene(scene: dict, index: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f3f7f9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 82), fill=NAVY)
    draw.ellipse((1050, -270, 1520, 195), fill=NAVY2)
    draw.text((58, 24), "TRAINING ACADEMY", font=font(23, True), fill=WHITE)
    draw.text((1010, 31), "LAB PLAYBOOK", font=font(14, True), fill="#b8d4df")

    draw.text((68, 132), scene["kicker"], font=font(15, True), fill=CYAN)
    title_font = font(43, True)
    title_lines = wrapped(draw, scene["title"], title_font, 500, 2)
    if len(title_lines) > 1:
        title_font = font(38, True)
        title_lines = wrapped(draw, scene["title"], title_font, 500, 2)
    if len(title_lines) > 2 or " ".join(title_lines) != scene["title"]:
        raise ValueError(f"Scene title does not fit in the Academy heading area: {scene['title']}")
    title_line_height = 47 if len(title_lines) > 1 else 52
    for line_no, line in enumerate(title_lines):
        draw.text((66, 174 + title_line_height * line_no), line, font=title_font, fill=INK)
    accent_y = 174 + title_line_height * len(title_lines) + 5
    draw.rectangle((68, accent_y, 150, accent_y + 6), fill=CYAN)
    detail_y = accent_y + 24
    for line_no, line in enumerate(wrapped(draw, scene["detail"], font(20), 485, 3)):
        draw.text((68, detail_y + 33 * line_no), line, font=font(20), fill=MUTED)

    # Academy-style interface illustration on the right.
    rounded(draw, (600, 125, 1214, 608), 18, WHITE, "#d4e0e6", 2)
    draw.rounded_rectangle((600, 125, 790, 608), radius=18, fill=NAVY)
    draw.rectangle((770, 125, 790, 608), fill=NAVY)
    draw.text((625, 151), "ACADEMY", font=font(17, True), fill=WHITE)
    nav_items = [("Class catalog", "classes"), ("Lab catalog", "catalog"),
                 ("My lab sessions", "startup"), ("My results", "results")]
    selected = scene["screen"]
    for i, (label, key) in enumerate(nav_items):
        y = 205 + i * 48
        if key == selected or (selected in ("exercise", "terminal", "help", "check") and key == "catalog"):
            rounded(draw, (615, y - 5, 772, y + 30), 8, "#2d5269")
        draw.ellipse((627, y + 3, 639, y + 15), fill=CYAN if key == selected else "#88a8b9")
        draw.text((649, y), label, font=font(13), fill="#e1edf3")

    panel_x = 820
    draw.text((panel_x, 155), "Lab workspace", font=font(17, True), fill=INK)
    draw.text((panel_x, 184), "Private environment · Practice at your pace", font=font(11), fill=MUTED)
    rounded(draw, (panel_x, 219, 1183, 438), 12, "#f7fafb", "#e1e9ed")
    draw.text((panel_x + 18, 237), scene["focus"], font=font(17, True), fill=INK)
    draw.text((panel_x + 18, 269), "Work through the task and verify your progress.", font=font(11), fill=MUTED)
    if selected == "terminal":
        rounded(draw, (panel_x + 16, 303, 1165, 415), 8, "#102332")
        draw.text((panel_x + 31, 320), "Sender terminal  ·  Private Ubuntu VM", font=font(11, True), fill="#b8d4df")
        draw.text((panel_x + 31, 360), "learner@sender:~$ _", font=font(16), fill="#c0f1d2")
    elif selected == "help":
        rounded(draw, (panel_x + 18, 306, panel_x + 112, 342), 7, PALE)
        draw.text((panel_x + 36, 315), "Hint", font=font(12, True), fill=CYAN)
        rounded(draw, (panel_x + 124, 306, panel_x + 226, 342), 7, CYAN)
        draw.text((panel_x + 143, 315), "Solution", font=font(12, True), fill=WHITE)
        draw.text((panel_x + 18, 365), "Your exercise guide remains in view.", font=font(12), fill=MUTED)
    elif selected == "startup":
        draw.text((panel_x + 18, 315), "Preparing your private VM", font=font(13, True), fill=INK)
        rounded(draw, (panel_x + 18, 350, 1158, 365), 8, "#dce7eb")
        rounded(draw, (panel_x + 18, 350, panel_x + 255, 365), 8, CYAN)
        draw.text((panel_x + 18, 381), "Best guess only · Actual setup time varies", font=font(11), fill=MUTED)
    elif selected == "results":
        draw.text((panel_x + 18, 310), "✓   Exercise result saved", font=font(13, True), fill="#287751")
        draw.text((panel_x + 18, 346), "Reset clears VM files but preserves results.", font=font(12), fill=MUTED)
        draw.text((panel_x + 18, 374), "End lab releases the VM seat.", font=font(12), fill=MUTED)
    else:
        draw.text((panel_x + 18, 310), "Exercise guide and goal", font=font(13, True), fill=INK)
        draw.text((panel_x + 18, 341), "1. Read the task   2. Start exercise", font=font(12), fill=MUTED)
        draw.text((panel_x + 18, 372), "3. Work in the terminal   4. Check your work", font=font(12), fill=MUTED)

    if selected == "check":
        rounded(draw, (panel_x, 454, 1183, 523), 10, "#eef7f2", "#c7e3d1")
        draw.text((panel_x + 17, 468), "Verification feedback", font=font(13, True), fill="#287751")
        draw.text((panel_x + 17, 493), "Review feedback, correct the task and check again.", font=font(11), fill=MUTED)
    else:
        rounded(draw, (panel_x, 454, 1183, 523), 10, "#f3f7f9", "#e0e8ec")
        draw.text((panel_x + 17, 477), "Your session and results are tied to your account.", font=font(12), fill=MUTED)

    draw.text((68, 633), f"ACADEMY QUICK START     {index + 1:02d} / {len(SCENES):02d}", font=font(13, True), fill=MUTED)
    draw.rounded_rectangle((68, 664, 1214, 671), radius=4, fill="#dce7eb")
    draw.rounded_rectangle((68, 664, 68 + int(1146 * (index + 1) / len(SCENES)), 671), radius=4, fill=CYAN)
    return image


def seconds(path: Path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                            check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def make_audio(text_path: Path, wav_path: Path) -> None:
    script_path = text_path.with_suffix(".ps1")
    script_path.write_text(r"""param([string]$TextPath, [string]$OutputPath)
Add-Type -AssemblyName System.Speech
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$synth.Rate = -1
$synth.Volume = 100
$text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
$synth.SetOutputToWaveFile($OutputPath)
$synth.Speak($text)
$synth.Dispose()
""", encoding="utf-8")
    subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script_path),
                    "-TextPath", str(text_path), "-OutputPath", str(wav_path)], check=True)


def stamp(value: float) -> str:
    ms = round(value * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def main() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required to build the tutorial video")
    OUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    OUT_TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
    render_scene(SCENES[0], 0).save(OUT_POSTER, optimize=True)
    timeline, vtt = [], ["WEBVTT", ""]
    cursor = 0.0
    with tempfile.TemporaryDirectory(prefix="academy-lab-guide-") as temporary:
        temp = Path(temporary)
        concat = temp / "clips.txt"
        clips = []
        for index, scene in enumerate(SCENES):
            frame = temp / f"scene-{index:02d}.png"
            text_path = temp / f"scene-{index:02d}.txt"
            wav = temp / f"scene-{index:02d}.wav"
            clip = temp / f"scene-{index:02d}.mp4"
            render_scene(scene, index).save(frame, optimize=True)
            text_path.write_text(scene["narration"], encoding="utf-8")
            make_audio(text_path, wav)
            duration = seconds(wav)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30",
                            "-i", str(frame), "-i", str(wav), "-t", f"{duration:.3f}", "-shortest",
                            "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium",
                            "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                            "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(clip)], check=True)
            clips.append(clip)
            timeline.append((cursor, cursor + duration, scene))
            cursor += duration
        concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in clips), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                        str(concat), "-c", "copy", "-movflags", "+faststart", str(OUT_VIDEO)], check=True)

    for start, end, scene in timeline:
        sentences = [part.strip() for part in scene["narration"].replace("?", ".").split(".") if part.strip()]
        weights = [max(1, len(sentence.split())) for sentence in sentences]
        total = sum(weights)
        at = start
        for sentence, weight in zip(sentences, weights):
            finish = at + (end - start) * weight / total
            vtt.extend([f"{stamp(at)} --> {stamp(finish)}", sentence + ".", ""])
            at = finish
    OUT_VTT.write_text("\ufeff" + "\n".join(vtt), encoding="utf-8")
    OUT_TRANSCRIPT.write_text(
        "# Training Academy lab-use tutorial transcript\n\n"
        + "\n\n".join(f"## {scene['title']}\n\n{scene['narration']}" for scene in SCENES)
        + "\n", encoding="utf-8")
    print(f"Video: {OUT_VIDEO} ({OUT_VIDEO.stat().st_size:,} bytes; {seconds(OUT_VIDEO):.1f} seconds)")
    print(f"Captions: {OUT_VTT}")
    print(f"Poster: {OUT_POSTER}")
    print(f"Transcript: {OUT_TRANSCRIPT}")


if __name__ == "__main__":
    main()
