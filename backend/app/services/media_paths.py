from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote


MEDIA_URL_PREFIX = "/api/files/media/"


def resolve_media_path(value: str, media_dir: Path) -> Path:
    """Resolve stored paths or media URLs while staying inside media storage."""
    root = media_dir.resolve()
    if value.startswith(MEDIA_URL_PREFIX):
        value = unquote(value[len(MEDIA_URL_PREFIX):])
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    relative = resolved.relative_to(root)
    if not relative.parts:
        raise ValueError("A media file path is required")
    return resolved


def media_preview_url(value: str, media_dir: Path) -> str | None:
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    try:
        path = resolve_media_path(value, media_dir)
        relative = path.relative_to(media_dir.resolve())
    except (ValueError, OSError, RuntimeError):
        return None
    return MEDIA_URL_PREFIX + quote(relative.as_posix(), safe="/")
