"""Component tests with seeded defects (Gate 3 brief 5.3, T03, T07). Expected results are frozen in this file.

    python market/run.py tests --data .      -> market/test_results.json (+ the Component Tests sheet on export)

Each test copies the current data to a temporary folder, plants one defect, rebuilds, and compares with the
expected result. Nothing in the real data changes. Note: written by the same person as the rules, so this
is not an independent test; a teammate should add seeds of their own (market/tests_extra.json, same format).
"""
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import agent as A
import build as B
import fetch as F
import mcommon as M


def _copy(data: Path, tmp: Path) -> Path:
    d = tmp / "data"
    shutil.copytree(data, d, ignore=shutil.ignore_patterns(".git", "out", "*.raw", "node_modules"))
    return d


def _ev(d):
    return M.read(M.mdir(d) / "evidence.json", {})


def _put_ev(d, ev):
    M.write(M.mdir(d) / "evidence.json", ev)


def _rules(res, where=None):
    return {i["rule"] for i in res["issues"] if where is None or i["where"] == where}


def _action(res, cid):
    return next((c["proposed_action"] for c in res["conclusions"] if c["claim_id"] == cid), None)


def _first_web(d, claim=None):
    ev = _ev(d)
    for k, e in ev.items():
        if claim is None or e["claim_id"] == claim:
            return ev, k, e
    return ev, None, None


# ---------- tests: each returns (observed, passed) ----------
def t_clean(d, base):
    bad = _rules(base) & {"R2_dangling_evidence_id", "R3_quote_not_in_source", "R5_competitor_feature_unsourced",
                          "R5_competitor_price_unsourced", "R6_verified_without_check", "R1_bad_status"}
    return (f"integrity issues: {sorted(bad) or 'none'}; actions: "
            + ", ".join(f"{c['claim_id']}={c['proposed_action']}" for c in base["conclusions"])), not bad


def t_unit_leap(d, base):
    ev = _ev(d)
    key = "web:seed-t03"
    ev[key] = {"key": key, "lane": "web", "claim_id": "MKT-01-D", "url": "https://example.gov.sg/seed", "title": "seed",
               "publisher": "seed", "publication_date": "", "quote": "Primary enrolment 2024: 237,966 students.",
               "finding": "MathBridge can reach 237,966 paying customers.", "stance": "supports", "unit": "students",
               "limitation": "", "tier": "government", "source_type": "Government statistics", "snapshot": "market/snapshots/manual/seed_t03.txt",
               "snapshot_kind": "manual", "verification_status": "PARTIAL"}
    (M.mdir(d) / "snapshots" / "manual").mkdir(parents=True, exist_ok=True)
    (M.mdir(d) / "snapshots" / "manual" / "seed_t03.txt").write_text("Primary enrolment 2024: 237,966 students.")
    _put_ev(d, ev)
    res = B.build(d)
    ok = "R4_unit_leap" in _rules(res, "MKT-01-D") and _action(res, "MKT-01-D") == "HOLD"
    return f"rules on MKT-01-D: {sorted(_rules(res, 'MKT-01-D'))}; action {_action(res, 'MKT-01-D')}", ok


def t_fake_feature(d, base):
    comps = M.read(M.mdir(d) / "competitors.json", {})
    if not comps:
        return "no competitor rows to seed", False
    k = next(iter(comps))
    comps[k]["features"] = comps[k].get("features", []) + ["tutor-reviewed learning-gap diagnosis for tuition centres"]
    M.write(M.mdir(d) / "competitors.json", comps)
    res = B.build(d)
    ok = any(i["rule"] == "R5_competitor_feature_unsourced" and "tutor-reviewed" in i["issue"] for i in res["issues"])
    return f"R5 raised: {ok}", ok


def t_fake_citation(d, base):
    res = B.build(d, extra_claims=[{
        "claim_id": "MKT-99", "claim_text": "Centres report a 40% time saving from AI diagnosis (Tan et al., 2025).",
        "market_conclusion": "seed", "supporting_evidence_ids": ["MKT-E999"], "counter_evidence_ids": [], "assumption_ids": [],
        "verification_status": "PARTIAL", "materiality": "HIGH", "limitations": "", "proposed_action": "", "review_status": "DRAFT",
        "unit": "", "owner": "Hansle", "version": "seed", "parent": ""}])
    ok = "R2_dangling_evidence_id" in _rules(res, "MKT-99") and _action(res, "MKT-99") == "HOLD"
    return f"rules on MKT-99: {sorted(_rules(res, 'MKT-99'))}; action {_action(res, 'MKT-99')}", ok


def t_altered_quote(d, base):
    ev, k, e = _first_web(d)
    if not k:
        return "no web evidence to seed", False
    e["quote"] = e["quote"].replace("1", "2", 1) if "1" in e["quote"] else e["quote"] + " (doubled)"
    _put_ev(d, ev)
    res = B.build(d)
    ok = "R3_quote_not_in_source" in _rules(res, e["claim_id"])
    return f"R3 raised on {e['claim_id']}: {ok}", ok


def t_verified_unchecked(d, base):
    ev, k, e = _first_web(d)
    if not k:
        return "no web evidence to seed", False
    e["verification_status"] = "VERIFIED"
    _put_ev(d, ev)
    (M.mdir(d) / "review.csv").unlink(missing_ok=True)
    res = B.build(d)
    ok = "R6_verified_without_check" in _rules(res, e["claim_id"])
    return f"R6 raised on {e['claim_id']}: {ok}", ok


def t_agent_invented_quote(d, base):
    """The model returns a quote that is not on the page: the agent must drop it (mock model, mock page)."""
    page = "<html><body><p>" + "KooBits Premium Plan. Proficiency Reports with KooBits Parent App. $148.50 / year. " * 6 + "</p></body></html>"
    reply = {"publisher": "x", "publication_date": "", "title": "x", "items": [
        {"quote": "KooBits reaches 40% of Singapore tuition centres.", "finding": "x", "stance": "supports", "unit": "", "limitation": ""},
        {"quote": "Proficiency Reports with KooBits Parent App.", "finding": "x", "stance": "limits", "unit": "", "limitation": ""}]}
    chat = lambda *a, **k: {"text": json.dumps(reply), "model": "mock"}
    cfg = json.loads((d / "config.json").read_text())
    cfg["market"]["seed_urls"] = [{"url": "https://www.koobits.com/seed-page", "claim_id": "MKT-02-A"}]
    cfg["market"]["search"]["provider"] = "none"
    (d / "config.json").write_text(json.dumps(cfg))
    _put_ev(d, {})
    A.run(d, "2026-11-03", log=lambda *a: None, chat=chat, getter=lambda u: ("text/html", page.encode()), only={"MKT-02-A"})
    quotes = [e["quote"] for e in _ev(d).values()]
    ok = quotes == ["Proficiency Reports with KooBits Parent App."]
    return f"kept quotes: {quotes}", ok


def t_blocked_domain(d, base):
    cfg = json.loads((d / "config.json").read_text())
    mc = cfg["market"]
    store = A.Store(d)
    hits = lambda q, sc, log: [{"url": "https://s3.amazonaws.com/singaporeweb/math-tuition/x.html", "title": "spam"},
                               {"url": "https://www.moe.gov.sg/x", "title": "gov"}]
    mc["seed_urls"] = []
    urls = A.candidate_urls("MKT-01-A", ["q"], mc, store, lambda *a: None, hits)
    ok = [u for u, _ in urls] == ["https://www.moe.gov.sg/x"]
    return f"kept: {urls}", ok


TESTS = [
    ("CT-01", "Clean baseline: current data has no integrity failures (clean case must not be falsely blocked)", "No R1/R2/R3/R5/R6 issue", t_clean),
    ("CT-02", "T03 seed: student enrolment used as paying customers for the centres-based market claim (MKT-01-D)", "R4_unit_leap and MKT-01-D = HOLD", t_unit_leap),
    ("CT-03", "Seed a competitor feature that is not on the saved page", "R5_competitor_feature_unsourced", t_fake_feature),
    ("CT-04", "Seed a conclusion citing an evidence id that does not exist (fake citation, T07-like)", "R2_dangling_evidence_id and HOLD", t_fake_citation),
    ("CT-05", "Seed a changed number inside a logged quote", "R3_quote_not_in_source", t_altered_quote),
    ("CT-06", "Seed VERIFIED with no checked_by / checked_date", "R6_verified_without_check", t_verified_unchecked),
    ("CT-07", "Mock model returns one invented quote and one real quote from the page", "Invented quote dropped, real quote kept", t_agent_invented_quote),
    ("CT-08", "Search returns an SEO-spam domain and a government page", "Spam domain dropped before fetching", t_blocked_domain),
]


def input_version(data: Path):
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=data, capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = ""
    blob = b"".join(p.read_bytes() for p in sorted(M.mdir(data).glob("*.json")) if p.name not in ("test_results.json",))
    return f"{sha or 'nogit'}+data:{hashlib.sha1(blob).hexdigest()[:8]}"


def run(data: Path, today: str, log=print):
    base = B.build(data)
    ver = input_version(data)
    results = []
    for tid, desc, expected, fn in TESTS:
        with tempfile.TemporaryDirectory() as tmp:
            d = _copy(data, Path(tmp))
            try:
                observed, ok = fn(d, base if fn is t_clean else B.build(d))
            except Exception as e:  # a crash is a failed test, not a skipped one
                observed, ok = f"error: {e}", False
        results.append({"test_id": tid, "description": desc, "input_version": ver, "expected": expected,
                        "observed": observed, "pass_fail": "PASS" if ok else "FAIL", "issue_id": "" if ok else f"ISS-{tid}",
                        "run_date": today, "evidence_file": "market/test_results.json"})
        log(f"{tid}: {'PASS' if ok else 'FAIL'} - {observed}")
    M.write(M.mdir(data) / "test_results.json", results)
    return results
