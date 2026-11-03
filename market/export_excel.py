"""Write the team's workbook (market/templates/01_Hansle_Market_Research.xlsx) and one CSV per sheet.

    python market/run.py export --data .

Keeps the template's styles and drop-down lists, removes the EXAMPLE row, and writes market/out/:
  01_Hansle_Market_Research.xlsx, market_evidence.csv, competitor_matrix.csv, market_conclusions.csv,
  market_handoff.csv (the file Kaizhen integrates), component_tests.csv, validation_issues.json
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
TOPIC = {"MKT-01": "Demand", "MKT-02": "Differentiation", "MKT-03": "Market size"}


def j(xs):
    return "; ".join(x for x in xs if x)


def sheet_rows(res, tests):
    claims = {c["claim_id"]: c for c in res["conclusions"]}
    ev = [[r["evidence_id"], f"{TOPIC.get(r['claim_id'], r['claim_id'])} ({r['claim_id']}, {r['stance']})", r["title"],
           r["publisher"], r["publication_date"], r["url"], r["quote"], r["finding"], r["source_type"],
           r["verification_status"], r["limitation"], r.get("checked_by", ""), r.get("checked_date", "")]
          for r in sorted(res["rows"], key=lambda r: r["evidence_id"])]
    comp = [[c["competitor"], c.get("product", ""), c.get("target_customer", ""), j(c.get("features", [])),
             c.get("price", "NOT FOUND"), c.get("pricing_status", "NOT FOUND"), c.get("differentiation", ""),
             c["evidence_id"], c.get("checked_date", ""),
             "Company self-description; " + ("price found on page" if c.get("pricing_status") == "FOUND" else "price NOT FOUND on saved page")]
            for c in res["competitors"]]
    concl = [[c["claim_id"], c["market_conclusion"], j(c["supporting_evidence_ids"]), j(c["counter_evidence_ids"]),
              j(c["assumption_ids"]), c["verification_status"], c["materiality"], c["limitations"], c["proposed_action"]]
             for c in res["conclusions"]]
    hand = [[h["claim_id"], h["owner"], h["claim_text"], j(h["evidence_ids"]), j(h["assumption_ids"]), h["evidence_status"],
             h["materiality"], h["limitation"], h["proposed_action"], h["version"], h["review_status"]] for h in res["handoff"]]
    tst = [[t["test_id"], t["description"], t["input_version"], t["expected"], t["observed"], t["pass_fail"],
            t.get("issue_id", ""), t["run_date"], t["evidence_file"]] for t in tests]
    return {"Market Evidence": ev, "Competitor Matrix": comp, "Market Conclusions": concl, "Market Handoff": hand,
            "Component Tests": tst}


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
    wb.save(out / "01_Hansle_Market_Research.xlsx")
    M.write(out / "validation_issues.json", res["issues"])
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
