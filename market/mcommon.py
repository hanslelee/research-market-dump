"""Shared helpers for the market add-on (paths, ids, text matching, source tiers)."""
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent / "pipeline"
sys.path.insert(0, str(PIPELINE))

STATUSES = ("VERIFIED", "PARTIAL", "SYNTHETIC", "MISSING", "UNVERIFIED", "NOT APPLICABLE")
SOURCE_TYPE = {"government": "Government statistics", "academic": "Academic paper", "news": "News",
               "company": "Company website", "other": "Other"}


def today():
    return dt.date.today().isoformat()


def mdir(data: Path) -> Path:
    return data / "market"


def mcfg(config: dict) -> dict:
    return config.get("market") or {}


def read(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def short_id(cid: str) -> str:
    return cid.split(":", 1)[1] if ":" in cid else cid


def h(*parts) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


# ---------- verbatim matching ----------
_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "−": "-", " ": " ", " ": " ", " ": " "})


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_TRANS)
    return re.sub(r"\s+", " ", s).strip().casefold()


def contains(text: str, quote: str, min_len: int = 3) -> bool:
    """True when quote appears in text, ignoring case, whitespace and quote/dash styles."""
    q = norm(quote)
    return len(q) >= min_len and q in norm(text)


def sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) > 20]


def best_sentence(text: str, hint: str) -> str:
    """The sentence of text sharing the most words with hint (used to pick a verbatim quote from an abstract)."""
    words = set(re.findall(r"[a-z]{4,}", norm(hint)))
    best, score = "", -1
    for s in sentences(text):
        sc = len(words & set(re.findall(r"[a-z]{4,}", norm(s))))
        if sc > score:
            best, score = s, sc
    return best


# ---------- source tiers ----------
def domain(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _match(host: str, patterns) -> bool:
    return any(host == p or host.endswith("." + p) for p in patterns)


def tier(url: str, mc: dict, competitor_domains=()) -> str:
    host = domain(url)
    if _match(host, mc.get("blocked_domains", [])):
        return "blocked"
    tiers = mc.get("source_tiers", {})
    if _match(host, tiers.get("government", [])):
        return "government"
    if _match(host, competitor_domains):
        return "company"
    for name in ("academic", "news"):
        if _match(host, tiers.get(name, [])):
            return name
    return "other"


def competitor_domains(mc: dict):
    return [d for c in mc.get("competitors", []) for d in c.get("domains", [])]
