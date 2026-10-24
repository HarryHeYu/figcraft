"""Renderers. Every renderer consumes laid-out IR + TextLayout and is strictly read-only."""

from papercanvas.render.pdf import render_pdf
from papercanvas.render.pptx import render_pptx
from papercanvas.render.svg import render_svg

#: canonical output extensions per render format
RENDER_SUFFIXES = {"svg": ".svg", "pdf": ".pdf", "pptx": ".pptx"}

__all__ = ["RENDER_SUFFIXES", "render_pdf", "render_pptx", "render_svg"]
