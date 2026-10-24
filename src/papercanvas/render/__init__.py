"""Renderers. Every renderer consumes laid-out IR + TextLayout and is strictly read-only."""

from papercanvas.render.svg import render_svg

__all__ = ["render_svg"]
