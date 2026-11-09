"""Write the team's workbook (market/templates/01_Hansle_Market_Research.xlsx) and one CSV per sheet.

    python market/run.py export --data .

Keeps the template's styles and drop-down lists, removes the EXAMPLE row, and writes market/out/:
  01_Hansle_Market_Research.xlsx, market_evidence.csv, competitor_matrix.csv, market_conclusions.csv,
  market_handoff.csv and market_handoff.json (packet v1.0 section 13, for Kaizhen), component_tests.csv,
  validation_issues.json; the Test Status v2 row for T03 is filled from the actual component run
"""
import copy
import csv
import json
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

import build as B
import mcommon as M

FIRST_ROW = 5
def topic(r):
    if r.get("edu_related"):
        return f"EDU related ({r['claim_id']}, {r['stance']})" + (f" = {r['edu_id']}" if r.get("edu_id") else "")
    return f"{r['claim_id']} ({r['stance']})"


def j(xs):
    return "; ".join(x for x in xs if x)


def sheet_rows(res, tests):
    ev = [[r["evidence_id"], topic(r), r["title"],
           r["publisher"], r["publication_date"], r["url"], r["quote"], r["finding"], r["source_type"],
           r["verification_status"], r["limitation"], r.get("checked_by", ""), r.get("checked_date", ""),
           r.get("evidence_class", "EXT-PUB")]
          for r in sorted(res["rows"], key=lambda r: r["evidence_id"])]
    comp = [[c["competitor"], c["product"], c["target_customer"], j(c["features"]), c["price"], c["pricing_status"],
             c["differentiation"], j(c["evidence_ids"]), c["checked_date"], c["limitations"]] for c in res["matrix"]]
    concl = [[c["claim_id"], c["market_conclusion"], j(c["supporting_evidence_ids"]), j(c["counter_evidence_ids"]),
              j(c["assumption_ids"]), c["verification_status"], c["materiality"], B.TRACTION_NOTE + " " + c["limitations"],
              c["proposed_action"]] for c in res["conclusions"]]
    def by_sub(pid, field):  # one line per sub-claim, ids joined with "; "
        return "\n".join(j(c[field]) for c in res["conclusions"] if c.get("parent") == pid and c[field])
    concl += [[h["claim_id"] + " (team claim)", h.get("conclusion", "") or "[DRAFT - team-claim conclusion not written yet]",
               by_sub(h["claim_id"], "supporting_evidence_ids"), by_sub(h["claim_id"], "counter_evidence_ids"), j(h["assumption_ids"]), h.get("status_label") or h["evidence_status"], h["materiality"], B.TRACTION_NOTE + " " + h["limitation"],
               h["proposed_action"]] for h in res["handoff"]]
    hand = [[h["claim_id"], h["owner"], h["claim_text"], j(h["evidence_ids"]), j(h["assumption_ids"]), h["evidence_status"],
             h["materiality"], h["limitation"], h["proposed_action"], artifact_version(res), h["review_status"]]
            for h in res["handoff_rows"]]
    tst = [[t["test_id"] + (f" ({t['team_test_id']})" if t.get("team_test_id") else ""), t["description"], t["input_version"], t["expected"], t["observed"], t["pass_fail"],
            t.get("issue_id", ""), t["run_date"], t["evidence_file"]] for t in tests]
    return {"Market Evidence": ev, "Competitor Matrix": comp, "Market Conclusions": concl, "Market Handoff": hand,
            "Component Tests": tst}


def viewer_data(data: Path, res, tests):
    """Everything the web page shows, in one file (market/out/viewer.json)."""
    import datetime as dt
    from common import load_dir
    claims = load_dir(data / "claims")
    concl = {c["claim_id"]: c for c in res["conclusions"]}
    human = M.read(M.mdir(data) / "conclusions.json", {})
    out_claims = []
    for h in res["handoff"]:
        c = claims.get("claim:" + h["claim_id"], {})
        out_claims.append({"id": h["claim_id"], "role": "parent", "text": h["claim_text"], "status": h["evidence_status"],
                           "status_label": h.get("status_label", ""),
                           "action": h["proposed_action"], "limitation": h["limitation"], "review_status": h["review_status"],
                           "conclusion": h.get("conclusion", ""),
                           "evidence_ids": h["evidence_ids"], "basis": c.get("basis", "")})
    for cid, c in concl.items():
        cl = claims.get("claim:" + cid, {})
        out_claims.append({"id": cid, "role": "sub", "parent": c.get("parent", ""), "text": c["claim_text"],
                           "status": c["verification_status"], "action": c["proposed_action"], "limitation": c["limitations"],
                           "conclusion": (human.get(cid) or {}).get("conclusion", ""), "review_status": c["review_status"],
                           "supporting": c["supporting_evidence_ids"], "counter": c["counter_evidence_ids"],
                           "assumptions": c["assumption_ids"], "fixed_status": cl.get("fixed_status", ""), "unit": c.get("unit", ""),
                           "basis": cl.get("basis", "")})
    ev = [{"id": r["evidence_id"], "kind": M.KIND.get(r["source_type"], "other"), "source_type": r["source_type"],
           "title": r["title"], "publisher": r["publisher"], "date": r["publication_date"], "url": r["url"],
           "quote": r["quote"], "finding": r["finding"], "claim": r["claim_id"], "stance": r["stance"],
           "stance_by_agent": r.get("stance_by_agent", ""), "edited_by": r.get("edited_by", ""), "edited_date": r.get("edited_date", ""), "status": r["verification_status"], "limitation": r["limitation"],
           "checked_by": r.get("checked_by", ""), "checked_date": r.get("checked_date", ""), "edu_related": bool(r.get("edu_related")),
           "edu_id": r.get("edu_id", ""), "snapshot": r.get("snapshot", ""), "snapshot_kind": r.get("snapshot_kind", ""),
           "found_by": r.get("found_by", ""), "lane": r.get("lane", ""), "unit": r.get("unit", "")} for r in res["rows"]]
    comps = res["matrix"]
    return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "case_id": M.mcfg(res["config"]).get("case_id", ""), "version": M.mcfg(res["config"]).get("version", ""),
            "claims": out_claims, "evidence": ev, "competitors": comps, "issues": res["issues"],
            "tests": [{"id": t["test_id"], "pass": t["pass_fail"], "description": t["description"]} for t in tests]}


def artifact_version(res):
    """Exact version of the supporting file: config version + the git commit the data was built from."""
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = ""
    v = M.mcfg(res["config"]).get("version", "")
    return f"01_Hansle_Market_Research.xlsx {v} @ {sha}" if sha else f"01_Hansle_Market_Research.xlsx {v}"


def handoff_json(res):
    """Handoff fields (packet v1.0 section 13): one object per team claim (MKT-01, MKT-02), each with its sub-claims."""
    mc = M.mcfg(res["config"])
    ver = artifact_version(res)
    return {"case_id": mc.get("case_id", ""), "owner": mc.get("owner", "Hansle"), "artifact": "market_handoff",
            "artifact_version": ver,
            "claims": [{"claim_id": h["claim_id"], "owner": h["owner"], "claim_text": h["claim_text"],
                        "evidence_ids": h["evidence_ids"], "assumption_ids": h["assumption_ids"],
                        "evidence_status": h["evidence_status"], "materiality": h["materiality"], "limitation": h["limitation"],
                        "recommended_action": h["proposed_action"], "artifact_version": ver, "review_status": h["review_status"],
                        "sub_claims": h["sub_claims"]}
                       for h in res["handoff_rows"]]}


def fill_change_log(wb, data):
    """v2 Change Log: append the dated changes recorded in market/change_log.json (template rows are kept)."""
    rows = M.read(M.mdir(data) / "change_log.json", [])
    if "v2 Change Log" not in wb.sheetnames or not rows:
        return
    ws = wb["v2 Change Log"]
    last = max(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value)
    for i, r in enumerate(rows):
        for k, key in enumerate(("date", "change", "reason", "original_preserved")):
            cell = ws.cell(last + 1 + i, k + 1, r.get(key, ""))
            cell._style = copy.copy(ws.cell(last, k + 1)._style)


def fill_test_status(wb, tests, human=None):
    """Test Status v2 (template v2): record the component run of T03 from the actual test result. Fields that only a
    person or the integrated run can supply (human_review_min, integration_status) are left as they are."""
    if "Test Status v2" not in wb.sheetnames:
        return
    ws = wb["Test Status v2"]
    head = {ws.cell(4, c).value: c for c in range(1, ws.max_column + 1) if ws.cell(4, c).value}
    for t in tests:
        if not t.get("team_test_id"):
            continue
        row = next((r for r in range(5, ws.max_row + 1) if ws.cell(r, 1).value == t["team_test_id"]), None)
        if not row:
            continue
        put = lambda k, v: ws.cell(row, head[k]).__setattr__("value", v) if k in head else None
        put("actual_detection", t["observed"])
        put("actual_route", "HOLD" if t["pass_fail"] == "PASS" else "NOT HOLD")
        put("component_status", t["pass_fail"])
        put("input_version", t["input_version"])
        put("run_date", t["run_date"])
        put("runtime_min", t.get("runtime_min"))
        put("cost_SGD", t.get("cost_sgd", 0))
        put("issue_id", "R4_unit_leap" if t["pass_fail"] == "PASS" else t.get("issue_id", ""))
        put("evidence_file", f"{t['evidence_file']} ({t['test_id']})")
        for k, v in (human or {}).get(t["team_test_id"], {}).items():  # values only a person can supply
            put(k, v)


def _fill(ws, rows):
    style_row = [copy.copy(ws.cell(FIRST_ROW, c)._style) for c in range(1, ws.max_column + 1)]
    for r in range(FIRST_ROW, max(ws.max_row, FIRST_ROW + len(rows)) + 1):
        for c in range(1, ws.max_column + 1):
            ws.cell(r, c).value = None
    for i, row in enumerate(rows):
        for k, v in enumerate(row, start=1):
            cell = ws.cell(FIRST_ROW + i, k, v)
            if k <= len(style_row):
                cell._style = copy.copy(style_row[k - 1])
    last = FIRST_ROW + len(rows) - 1
    for dv in ws.data_validations.dataValidation:  # stretch drop-downs if there are more rows than the template has
        for rng in list(dv.sqref.ranges):
            if rng.max_row < last:
                dv.sqref.add(f"{get_column_letter(rng.min_col)}{rng.max_row + 1}:{get_column_letter(rng.max_col)}{last}")


def export(data: Path, tests=None):
    res = B.build(data)
    tests = tests if tests is not None else M.read(M.mdir(data) / "test_results.json", [])
    out = M.mdir(data) / "out"
    out.mkdir(parents=True, exist_ok=True)
    wb = load_workbook(M.mdir(data) / "templates" / "01_Hansle_Market_Research.xlsx")
    ev_ws = wb["Market Evidence"]
    if ev_ws.cell(4, 14).value != "evidence_class":  # packet v1.0 evidence classes (G2-OBS / SYN / EXT-PUB / TEST / UNK)
        ev_ws.cell(4, 14).value = "evidence_class"
        ev_ws.cell(4, 14)._style = copy.copy(ev_ws.cell(4, 13)._style)
    sheets = sheet_rows(res, tests)
    for name, rows in sheets.items():
        ws = wb[name]
        _fill(ws, rows)
        header = [ws.cell(4, c).value for c in range(1, ws.max_column + 1)]
        fname = name.lower().replace(" ", "_") + ".csv"
        with open(out / fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    fill_test_status(wb, tests, M.mcfg(res["config"]).get("test_status_human", {}))
    fill_change_log(wb, data)
    wb.save(out / "01_Hansle_Market_Research.xlsx")
    M.write(out / "market_handoff.json", handoff_json(res))
    visited = M.read(M.mdir(data) / "visited.json", {})
    manual = [f"{u}\n    -> save the visible page text as {('market/snapshots/manual/' + M.h(u) + '.txt')}  ({v.get('reason', '')})"
              for u, v in visited.items() if not v.get("ok")]
    (out / "needs_manual_snapshot.txt").write_text(
        "Pages the agent could not read (JavaScript, bot protection or login). Open each in a browser, copy the visible\n"
        "text into the file named below, commit, and run the market workflow with step=web again.\n\n" + "\n".join(manual) + "\n")
    M.write(out / "validation_issues.json", res["issues"])
    M.write(out / "viewer.json", viewer_data(data, res, tests))
    with open(out / "edu_candidates.csv", "w", newline="") as f:  # for Zixuan: evidence that belongs to the education check
        w = csv.writer(f)
        w.writerow(["market_evidence_id", "edu_id", "title", "url", "exact_quote_or_excerpt", "finding", "verification_status", "limitations"])
        for r in res["edu"]:
            w.writerow([r["evidence_id"], r.get("edu_id", ""), r["title"], r["url"], r["quote"], r["finding"], r["verification_status"], r["limitation"]])
    return res, out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".")
    a = ap.parse_args()
    res, out = export(Path(a.data))
    print(f"wrote {out}: {len(res['rows'])} evidence, {len(res['competitors'])} competitors, "
          f"{len(res['conclusions'])} conclusions, {len(res['issues'])} issue(s), {res['pending']} relation draft(s) awaiting approval")


if __name__ == "__main__":
    main()
