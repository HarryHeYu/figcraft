"""Service layer security and path-policy regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from papercanvas.core.errors import PaperCanvasError
from papercanvas.service import ServiceContext, text_layout_for


def test_relative_paths_resolve_inside_root(tmp_path: Path) -> None:
    ctx = ServiceContext(root=tmp_path)
    assert ctx.resolve("fig.json") == (tmp_path / "fig.json").resolve()
    assert ctx.resolve("sub/dir/fig.json") == (tmp_path / "sub/dir/fig.json").resolve()
    assert ctx.resolve(".") == tmp_path.resolve()  # the root itself is allowed


def test_absolute_paths_inside_root_resolve(tmp_path: Path) -> None:
    ctx = ServiceContext(root=tmp_path)
    target = tmp_path / "fig.json"
    assert ctx.resolve(target) == target.resolve()


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    ctx = ServiceContext(root=tmp_path / "project")
    (tmp_path / "project").mkdir()
    for candidate in ("../evil.json", "sub/../../evil.json"):
        with pytest.raises(PaperCanvasError, match="escapes the project root"):
            ctx.resolve(candidate)


def test_absolute_path_outside_root_is_rejected(tmp_path: Path) -> None:
    ctx = ServiceContext(root=tmp_path)
    with pytest.raises(PaperCanvasError, match="escapes the project root"):
        ctx.resolve(tmp_path.parent / "elsewhere.json")


@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="drive-relative check is Windows-specific"
)
def test_absolute_path_on_another_drive_is_rejected(tmp_path: Path) -> None:
    """Another drive is outside the root even though no parent chain exists."""
    ctx = ServiceContext(root=tmp_path)
    with pytest.raises(PaperCanvasError, match="escapes the project root"):
        ctx.resolve("Q:/somewhere/fig.json")


def test_symlink_escaping_the_root_is_rejected(tmp_path: Path) -> None:
    """A symlink inside the root that points outside must not be usable."""
    import os
    import sys

    if sys.platform == "win32":
        # file symlinks need developer mode / privilege on Windows
        try:
            probe = tmp_path / "probe_link"
            os.symlink(tmp_path / "probe_target", probe)
            probe.unlink()
        except OSError:
            pytest.skip("symlink creation requires privileges on this Windows host")

    outside = tmp_path.parent / "outside_rc"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.json"
    secret.write_text("{}", encoding="utf-8")

    link = tmp_path / "link.json"
    os.symlink(secret, link)

    ctx = ServiceContext(root=tmp_path)
    with pytest.raises(PaperCanvasError, match="escapes the project root"):
        ctx.resolve(link)

    import shutil

    shutil.rmtree(outside, ignore_errors=True)


def test_enforce_root_false_allows_any_path(tmp_path: Path) -> None:
    """The CLI posture (enforce_root=False) keeps absolute-path freedom."""
    ctx = ServiceContext(root=tmp_path, enforce_root=False)
    anywhere = tmp_path.parent / "anywhere.json"
    assert ctx.resolve(anywhere) == anywhere.resolve()


def test_text_layout_for_uses_one_font_for_the_whole_figure(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["label"] = "Alpha"
    figure_dict["nodes"][1]["label"] = "Beta"
    fig = __import__("papercanvas").core.models.Figure.model_validate(figure_dict)
    layout = text_layout_for(fig)
    assert layout.metrics.resolved_family  # one font resolved for all labels
