"""One entry point for the market add-on.

    python market/run.py academic --data .          # paper lane (needs GEMINI_API_KEY, S2_API_KEY)
    python market/run.py web --data .               # market research agent (needs GEMINI_API_KEY; search key optional)
    python market/run.py tests --data .             # seeded component tests -> market/test_results.json
    python market/run.py export --data .            # fill the workbook + CSVs in market/out/
    python market/run.py all --data .               # academic, web, tests, export
    python market/run.py snapshot-name <url>        # file name for a hand-made snapshot of a page

--only MKT-01,MKT-03,competitors limits which claims (and whether competitors) are processed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcommon as M  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["academic", "web", "tests", "export", "all", "snapshot-name"])
    ap.add_argument("url", nargs="?")
    ap.add_argument("--data", default=".")
    ap.add_argument("--today", default=M.today())
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    data = Path(a.data)
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    if a.cmd == "snapshot-name":
        print(f"market/snapshots/manual/{M.h(a.url)}.txt")
        return
    if a.cmd in ("academic", "all"):
        import academic
        academic.run(data, a.today, only=only)
    if a.cmd in ("web", "all"):
        import agent
        agent.run(data, a.today, only=only)
    if a.cmd in ("tests", "all"):
        import seeded_tests
        seeded_tests.run(data, a.today)
    if a.cmd in ("export", "all"):
        import export_excel
        res, out = export_excel.export(data)
        print(f"wrote {out}: {len(res['rows'])} evidence, {len(res['competitors'])} competitors, "
              f"{len(res['conclusions'])} conclusions, {len(res['issues'])} issue(s), "
              f"{res['pending']} paper relation draft(s) awaiting your approval")
        for i in res["issues"]:
            print(f"  [{i['rule']}] {i['where']}: {i['issue']}")


if __name__ == "__main__":
    main()
