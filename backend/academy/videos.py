"""Read-only video catalogue backed by author/topic folders."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class Video:
    id: str
    author: str
    topic: str
    title: str
    path: Path
    size_bytes: int
    mtime_ns: int
    relative_path: str
    order: int | None = None

    def public(self):
        return {"id": self.id, "author": self.author, "topic": self.topic,
                "title": self.title, "size_bytes": self.size_bytes}

    def duration(self) -> float | None:
        return _duration(str(self.path), self.size_bytes, self.mtime_ns)


def _boxes(stream, start: int, end: int):
    position = start
    while position + 8 <= end:
        stream.seek(position)
        header = stream.read(8)
        size = int.from_bytes(header[:4], "big")
        offset = 8
        if size == 1:
            extra = stream.read(8)
            if len(extra) != 8:
                return
            size = int.from_bytes(extra, "big")
            offset = 16
        elif size == 0:
            size = end - position
        if size < offset or position + size > end:
            return
        yield header[4:8], position + offset, position + size
        position += size


@lru_cache(maxsize=256)
def _duration(path: str, size: int, mtime_ns: int) -> float | None:
    """Read the MP4 movie header without scanning or copying media payloads."""
    try:
        with open(path, "rb") as stream:
            for kind, start, end in _boxes(stream, 0, size):
                if kind != b"moov":
                    continue
                for child, payload, limit in _boxes(stream, start, end):
                    if child != b"mvhd":
                        continue
                    stream.seek(payload)
                    header = stream.read(min(32, limit - payload))
                    if len(header) < 20:
                        return None
                    if header[0] == 0:
                        timescale = int.from_bytes(header[12:16], "big")
                        ticks = int.from_bytes(header[16:20], "big")
                    elif header[0] == 1 and len(header) >= 32:
                        timescale = int.from_bytes(header[20:24], "big")
                        ticks = int.from_bytes(header[24:32], "big")
                    else:
                        return None
                    duration = ticks / timescale if timescale else 0
                    return duration if 1 <= duration <= 12 * 3600 else None
    except OSError:
        pass
    return None


def add_watched_range(ranges: list[list[float]], start: float, end: float) -> list[list[float]]:
    merged = []
    for first, last in sorted([*ranges, [start, end]]):
        if merged and first <= merged[-1][1] + 0.05:
            merged[-1][1] = max(last, merged[-1][1])
        else:
            merged.append([first, last])
    return merged


def watched_seconds(ranges: list[list[float]]) -> float:
    return sum(last - first for first, last in ranges)


def catalogue(root_path: str, order_by_path: dict[str, int] | None = None) -> list[Video] | None:
    """Return None while the configured media share is unavailable."""
    root = Path(root_path)
    try:
        if not root.is_dir():
            return None
        videos = []
        for author in root.iterdir():
            if not author.is_dir() or author.is_symlink() or author.name.startswith("."):
                continue
            for topic in author.iterdir():
                if not topic.is_dir() or topic.is_symlink() or topic.name.startswith("."):
                    continue
                for file in topic.iterdir():
                    if not file.is_file() or file.is_symlink() or file.suffix.lower() != ".mp4":
                        continue
                    relative = file.relative_to(root).as_posix()
                    details = file.stat()
                    creator, subject = author.name, topic.name
                    # This directory names the subject, not its creator. All 15 files
                    # in the series carry Eli the Computer Guy as their MP4 artist.
                    if creator.casefold() == "cloud computing":
                        creator, subject = "Eli the Computer Guy", "Cloud Computing"
                    videos.append(Video(
                        id=sha256(f"{relative}\0{details.st_size}\0{details.st_mtime_ns}".encode("utf-8")).hexdigest(),
                        author=creator, topic=subject, title=file.stem,
                        path=file, size_bytes=details.st_size, mtime_ns=details.st_mtime_ns,
                        relative_path=relative, order=(order_by_path or {}).get(relative)))
        return sorted(videos, key=lambda v: (
            v.author.casefold(), v.topic.casefold(), v.order is None,
            v.order if v.order is not None else 0, v.title.casefold()))
    except OSError:
        return None
