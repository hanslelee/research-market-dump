"""Market add-on: offline tests (no network, no model)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "market"))
import build as B  # noqa: E402
import export_excel as X  # noqa: E402
import fetch as F  # noqa: E402
import mcommon as M  # noqa: E402
import seeded_tests as T  # noqa: E402


class TestHelpers(unittest.TestCase):
    def test_contains_ignores_case_space_quotes(self):
        self.assertTrue(M.contains("He said “make 10”  first.", 'he said "make 10" first'))
        self.assertFalse(M.contains("S$1.8 billion", "S$2.8 billion"))

    def test_html_to_text_drops_scripts(self):
        t = F.html_to_text("<html><script>var x=1</script><p>Price: SGD 10</p><style>p{}</style></html>")
        self.assertEqual(t, "Price: SGD 10")

    def test_tiers(self):
        mc = json.loads((ROOT / "config.json").read_text())["market"]
        comp = M.competitor_domains(mc)
        self.assertEqual(M.tier("https://www.moe.gov.sg/x", mc, comp), "government")
        self.assertEqual(M.tier("https://geniebook.com/plans", mc, comp), "company")
        self.assertEqual(M.tier("https://s3.amazonaws.com/a/b", mc, comp), "blocked")
        self.assertEqual(M.tier("https://random-blog.example/x", mc, comp), "other")

    def test_snapshot_marks_thin_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "market").mkdir()
            s = F.snapshot(d, "https://x.example/a", "2026-11-03", getter=lambda u: ("text/html", b"<div id=app></div>"))
            self.assertFalse(s["ok"])


class TestSeeded(unittest.TestCase):
    def test_all_component_tests_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "repo"
            shutil.copytree(ROOT, d, ignore=shutil.ignore_patterns(".git", "out", "__pycache__"))
            res = T.run(d, "2026-11-03", log=lambda *a: None)
            failed = [r for r in res if r["pass_fail"] != "PASS"]
            self.assertEqual(failed, [], json.dumps(failed, indent=1))

    def test_export_keeps_template_dropdowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "repo"
            shutil.copytree(ROOT, d, ignore=shutil.ignore_patterns(".git", "out", "__pycache__"))
            res, out = X.export(d, tests=[])
            from openpyxl import load_workbook
            wb = load_workbook(out / "01_Hansle_Market_Research.xlsx")
            ws = wb["Market Evidence"]
            self.assertTrue(str(ws["A5"].value).startswith("MKT-E"))
            self.assertNotIn("EXAMPLE", str(ws["A5"].value))
            self.assertTrue(ws.data_validations.dataValidation)
            self.assertTrue((out / "market_handoff.csv").exists())



class TestAcademicLane(unittest.TestCase):
    def test_judges_adds_and_links(self):
        import academic as AC
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "repo"
            shutil.copytree(ROOT, d, ignore=shutil.ignore_patterns(".git", "out", "__pycache__"))
            hits = [{"id": "doi:10.1/a", "title": "Teachers spend hours on assessment feedback", "abstract": "Teachers report 6 hours a week.", "citations": 50, "year": 2020},
                    {"id": "doi:10.1/b", "title": "Protein folding with transformers", "abstract": "Unrelated.", "citations": 900, "year": 2021}]
            reply = {"results": [{"id": "doi:10.1/a", "type": "narrow", "evidence": "Teachers report 6 hours a week on feedback.", "limitation": "School teachers, not tutors."},
                                 {"id": "doi:10.1/b", "type": "none", "evidence": ""}]}
            chat = lambda *a, **k: {"text": json.dumps(reply), "model": "mock"}
            added = []

            def fake_add(data, title, today, log, chat=None, find=None):
                it = find(title, log)
                added.append(it["id"])
                (data / "papers").mkdir(exist_ok=True)
                (data / "papers" / (it["id"].replace(":", "_").replace("/", "_") + ".json")).write_text(json.dumps({**it, "authors": []}))
                return it["id"], True
            orig = AC.addpaper.add
            AC.addpaper.add = fake_add
            try:
                out = AC.run(d, "2026-11-03", log=lambda *a: None, chat=chat, only={"MKT-01-A"},
                             search_fn=lambda q, log: [dict(h) for h in hits], pause=0)
            finally:
                AC.addpaper.add = orig
            self.assertEqual(added, ["doi:10.1/a"])
            self.assertEqual(out["MKT-01-A"]["relation_drafts"], 1)
            rels = [json.loads(p.read_text()) for p in (d / "relations").glob("*.json")]
            r = next(r for r in rels if r["from"] == "doi:10.1/a")
            self.assertEqual((r["to"], r["type"], r["status"]), ("claim:MKT-01-A", "narrow", "new"))
            res = B.build(d)
            row = next(x for x in res["rows"] if x["key"] == "rel:" + r["id"])
            self.assertEqual((row["stance"], row["verification_status"], row["limitation"]), ("limits", "UNVERIFIED", "School teachers, not tutors."))


if __name__ == "__main__":
    unittest.main()
