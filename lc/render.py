"""Render Sideways Wire templates to PNG with headless Chrome.

Usage (library):
    from lc.render import Renderer
    with Renderer() as r:
        result = r.render("news.html", data, "out/news.png")

Each render runs the auto-fit script in the template. If any text still
does not fit after shrinking to its minimum size, the result is marked
not ok so the system can ask Joshua via Telegram instead of posting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
FONTS = ROOT / "fonts"
CHROME = "/usr/bin/google-chrome"


def headline_items(lines, size, styles):
    """Turn a list of headline lines into tape items: (text, size, style)."""
    return [(line, size, styles[i % len(styles)]) for i, line in enumerate(lines)]


@dataclass
class RenderResult:
    path: Path
    ok: bool
    fit: list = field(default_factory=list)

    @property
    def problems(self):
        return [f for f in self.fit if not f["ok"]]


class Renderer:
    def __init__(self, chrome: str | None = CHROME):
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            autoescape=select_autoescape(["html"]),
            extensions=["jinja2.ext.do"],
        )
        self.env.globals["zip"] = zip
        self.env.globals["headline_items"] = headline_items
        self.chrome = chrome

    def __enter__(self):
        self._pw = sync_playwright().start()
        kw = {"executable_path": self.chrome} if self.chrome and Path(self.chrome).exists() else {}
        self._browser = self._pw.chromium.launch(**kw)
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def html(self, template: str, data: dict) -> str:
        ctx = {"fonts": FONTS.as_uri()}
        ctx.update(data)
        return self.env.get_template(template).render(**ctx)

    def render(self, template: str, data: dict, out: str | Path, transparent: bool = False) -> RenderResult:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        w, h = data.get("w", 1080), data.get("h", 1350)
        page = self._browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        # Write to a temp file next to the templates so file:// fonts and images load.
        tmp = TEMPLATES / f".render_{out.stem}.html"
        tmp.write_text(self.html(template, data), encoding="utf-8")
        try:
            page.goto(tmp.as_uri())
            page.evaluate("document.fonts.ready")
            # Re-run fit after fonts load, since metrics change.
            fit = page.evaluate("window.__runFit()")
            page.locator("#frame").screenshot(path=str(out), omit_background=transparent)
        finally:
            page.close()
            tmp.unlink(missing_ok=True)
        ok = all(f["ok"] for f in fit)
        return RenderResult(out, ok, fit)


if __name__ == "__main__":
    import sys

    template, data_file, out = sys.argv[1:4]
    with Renderer() as r:
        res = r.render(template, json.loads(Path(data_file).read_text()), out)
    print(json.dumps({"ok": res.ok, "fit": res.fit}, indent=2))
