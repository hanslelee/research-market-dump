"""T03 controlled test (inflated market size). Owner: Hansle; independent reviewer: Kaizhen.

    python market/run.py t03 --data .     (or Actions -> market -> Run workflow -> step: t03)

1. Copies the repository data to a temporary TEST folder (the real data is never changed).
2. Applies controlled_tests/T03/input/T03_injection.json to the TEST copy only:
   - baseline alignment: MKT-01-D assumption_ids = [] (same as baseline v1.2, INT-01)
   - the seeded defect: MOE student count described as paying tuition centres, as MKT-01-D evidence
3. Runs the actual market checker (build.py rules) on the TEST copy, and on the same copy without the seeded row
   (control), and rebuilds the TEST workbook.
4. Writes raw output to controlled_tests/T03/output/ (checker output JSON, run log, TEST workbook).
It records what the checker printed; PASS/FAIL is decided by the people reviewing the output.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import build as B
import mcommon as M

TEST_DIR = Path("controlled_tests/T03")


def _copy(data: Path, tmp: Path) -> Path:
    d = tmp / "data"
    shutil.copytree(data, d, ignore=shutil.ignore_patterns(".git", "node_modules", "controlled_tests"))
    return d


def _align(d: Path, inj: dict):
    for rel, patch in inj.get("baseline_alignment", {}).items():
        if rel == "why":
            continue
        p = d / rel
        c = json.loads(p.read_text())
        c.update(patch)
        p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n")


def _seed(d: Path, inj: dict):
    ev = M.read(M.mdir(d) / "evidence.json", {})
    row = inj["add_evidence"]
    ev[row["key"]] = row
    M.write(M.mdir(d) / "evidence.json", ev)


def _view(res, seed_key=None):
    concl = {c["claim_id"]: c for c in res["conclusions"]}
    team = {h["claim_id"]: h for h in res["handoff"]}
    seed = next((r for r in res["rows"] if r.get("key") == seed_key), None) if seed_key else None
    d = concl.get("MKT-01-D", {})
    return {
        "issues_all": res["issues"],
        "issues_on_MKT-01-D": [i for i in res["issues"] if i["where"] == "MKT-01-D"],
        "MKT-01-D": {k: d.get(k) for k in ("verification_status", "proposed_action", "supporting_evidence_ids",
                                           "assumption_ids", "limitations")},
        "MKT-01": {k: team.get("MKT-01", {}).get(k) for k in ("evidence_status", "proposed_action", "limitation")},
        "seeded_row": None if not seed else {k: seed.get(k) for k in (
            "evidence_id", "claim_id", "quote", "finding", "unit", "source_type", "tier", "evidence_class",
            "verification_status", "url")},
    }


def run(data: Path, today: str, log=print, out_dir: Path = None):
    out = Path(out_dir or data / TEST_DIR / "output")
    out.mkdir(parents=True, exist_ok=True)
    inj = json.loads((data / TEST_DIR / "input" / "T03_injection.json").read_text())
    lines = []

    def say(msg):
        lines.append(msg)
        log(msg)

    sgt = timezone(timedelta(hours=8))
    start = datetime.now(sgt)
    t0 = time.perf_counter()
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=data, capture_output=True, text=True).stdout.strip()
    say(f"T03 start {start.isoformat(timespec='seconds')} | repo commit {sha or 'unknown'} | "
        f"GitHub run {os.environ.get('GITHUB_RUN_ID', 'local')} by {os.environ.get('GITHUB_ACTOR', 'local')}")
    say(f"injected change: {inj['injected_change']}")
    with tempfile.TemporaryDirectory() as tmp:
        d = _copy(data, Path(tmp))
        _align(d, inj)
        say("TEST copy made; baseline alignment applied (MKT-01-D assumption_ids = [])")
        control = B.build(d)
        say("control run (TEST copy without the seeded row): "
            f"MKT-01-D {_view(control)['MKT-01-D']['proposed_action']}, R4 on MKT-01-D: "
            f"{any(i['rule'] == 'R4_unit_leap' and i['where'] == 'MKT-01-D' for i in control['issues'])}")
        _seed(d, inj)
        say("seeded row added to the TEST copy")
        res = B.build(d)
        v = _view(res, inj["add_evidence"]["key"])
        for i in v["issues_on_MKT-01-D"]:
            say(f"checker: [{i['rule']}] {i['where']}: {i['issue']}")
        say(f"route: MKT-01-D {v['MKT-01-D']['proposed_action']} ({v['MKT-01-D']['verification_status']}); "
            f"team claim MKT-01 {v['MKT-01']['proposed_action']} ({v['MKT-01']['evidence_status']})")
        s = v["seeded_row"] or {}
        say(f"seeded row kept as {s.get('evidence_id')}: source_type={s.get('source_type')}, "
            f"evidence_class={s.get('evidence_class')}, unit={s.get('unit')}")
        import export_excel
        export_excel.export(d)
        shutil.copy(M.mdir(d) / "out" / "01_Hansle_Market_Research.xlsx", out / "T03_TEST_output_workbook.xlsx")
        say("TEST workbook rebuilt from the TEST copy")
    secs = time.perf_counter() - t0
    say(f"T03 end, runtime {secs:.1f} s; external cost SGD 0 (no API calls)")
    raw = {"test_id": "T03", "scenario": inj["scenario"], "owner": inj["owner"], "run_started": start.isoformat(timespec="seconds"),
           "runtime_seconds": round(secs, 2), "cost_sgd": 0, "repo_commit": sha,
           "github_run_id": os.environ.get("GITHUB_RUN_ID", "local"), "executor": os.environ.get("GITHUB_ACTOR", "local"),
           "checker": "research-market-dump market/build.py validate() (rules R1-R10)", "injection": inj,
           "control_without_seed": _view(control), "with_seed": v}
    (out / "T03_raw_checker_output.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str) + "\n")
    (out / "T03_run_log.txt").write_text("\n".join(lines) + "\n")
    return raw
