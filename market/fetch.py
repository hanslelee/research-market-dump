"""Fetch a web page or PDF and save a snapshot (raw bytes + plain text). No model involved.

Snapshots live in market/snapshots/<hash>.txt (+ .html / .pdf). A person can add a snapshot by hand for pages
that need JavaScript or a login: save the visible text as market/snapshots/manual/<hash>.txt where
<hash> = mcommon.h(url) (python market/run.py snapshot-name <url> prints it). Manual snapshots win.
"""
import io
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import mcommon as M

USER_AGENT = "Mozilla/5.0 (compatible; research-market-dump/0.1; +https://github.com/hanslelee/research-market-dump)"
MAX_BYTES = 8_000_000
MIN_CHARS = 300


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "td", "th", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    lines = [" ".join(l.split()) for l in "".join(p.out).splitlines()]
    return "\n".join(l for l in lines if l)


def pdf_to_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        return ""


def http_fetch(url: str, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.headers.get("Content-Type", ""), r.read(MAX_BYTES)


def snapshot(data: Path, url: str, today: str, getter=http_fetch, log=print) -> dict:
    """Return {"url","hash","kind","path","chars","ok","reason","fetched_at"}; text saved next to it."""
    sdir = M.mdir(data) / "snapshots"
    key = M.h(url)
    manual = sdir / "manual" / f"{key}.txt"
    rec = {"url": url, "hash": key, "fetched_at": today}
    if manual.exists():
        text = manual.read_text()
        kind = "excerpt" if text.startswith("EXCERPT") else "manual"
        return {**rec, "kind": kind, "path": str(manual.relative_to(data)), "chars": len(text), "ok": True, "reason": ""}
    txt = sdir / f"{key}.txt"
    if txt.exists():
        text = txt.read_text()
        return {**rec, "kind": "fetched", "path": str(txt.relative_to(data)), "chars": len(text),
                "ok": len(text) >= MIN_CHARS, "reason": "" if len(text) >= MIN_CHARS else "too little text"}
    try:
        ctype, raw = getter(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        log(f"fetch: {url} failed ({e})")
        return {**rec, "kind": "none", "path": "", "chars": 0, "ok": False, "reason": f"fetch failed: {e}"[:200]}
    is_pdf = "pdf" in ctype.lower() or raw[:5] == b"%PDF-"
    text = pdf_to_text(raw) if is_pdf else html_to_text(raw.decode("utf-8", "replace"))
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{key}.{'pdf' if is_pdf else 'html'}").write_bytes(raw)
    txt.write_text(text)
    ok = len(text) >= MIN_CHARS
    reason = "" if ok else "too little text (page may need JavaScript or a login): add a manual snapshot"
    log(f"fetch: {url} -> {len(text)} chars{'' if ok else ' (too little)'}")
    return {**rec, "kind": "fetched", "path": str(txt.relative_to(data)), "chars": len(text), "ok": ok, "reason": reason}


def text_of(data: Path, snap: dict) -> str:
    p = data / snap.get("path", "") if snap.get("path") else None
    return p.read_text() if p and p.exists() else ""
