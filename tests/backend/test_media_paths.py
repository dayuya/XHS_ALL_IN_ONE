from urllib.parse import quote

import pytest

from backend.app.services.media_paths import media_preview_url, resolve_media_path


@pytest.mark.parametrize("form", ["absolute", "relative", "url"])
def test_nested_media_paths_preserve_directories_and_special_characters(tmp_path, form):
    root = tmp_path / "media"
    image = root / "示例图" / "封面 #1%.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fixture")
    relative = image.relative_to(root).as_posix()
    url = "/api/files/media/" + quote(relative, safe="/")
    value = {"absolute": str(image), "relative": relative, "url": url}[form]
    assert media_preview_url(value, root) == url
    assert resolve_media_path(value, root) == image


@pytest.mark.parametrize("path", ["../outside.png", "/api/files/media/%2e%2e/outside.png"])
def test_media_paths_reject_directory_escape(tmp_path, path):
    root = tmp_path / "media"
    root.mkdir()
    assert media_preview_url(path, root) is None
    with pytest.raises(ValueError):
        resolve_media_path(path, root)


def test_media_paths_reject_symlink_escape(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private fixture")
    link = root / "link.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks are unavailable on this host")
    assert media_preview_url(str(link), root) is None
    with pytest.raises(ValueError):
        resolve_media_path("link.png", root)
