"""Paper lane: academic evidence for the market sub-claims, reusing research-dump's search and paper agents.

    python market/run.py academic --data .

Brief 5.1: "Reuse your existing research workflow to search for relevant academic work on mathematics diagnostics,
formative assessment and AI-assisted learning." For each sub-claim with "academic_queries":
  1. search   Semantic Scholar relevance search for each query (pipeline/websearch.s2_search)          (no model)
  2. judge    the model reads title + abstract and says how the paper bears on THIS market sub-claim:
              support / narrow (indirect or partial: becomes "limits") / conflict, with one evidence sentence;
              "none" when it does not bear on it at all                                                (model, Rung 0)
  3. add      the top papers are added to papers/ (tagged and summarized by the existing agents)       (pipeline/addpaper.py)
  4. link     a relation draft paper -> sub-claim, status "new" (= UNVERIFIED in the workbook)
Papers already in the repository are judged too, so earlier additions get linked.
You confirm each paper on the web page (Evidences tab: PARTIAL / VERIFIED / NOT APPLICABLE), like web evidence.
"""
import datetime as dt
import json
import time
from pathlib import Path

import mcommon as M  # noqa: F401  (puts pipeline/ on sys.path)
import addpaper
import claimrel
import collect
import llm
import websearch
from common import clean_text, file_for, load_dir, write_json

JUDGE_SYSTEM = """You check academic papers as evidence for ONE claim in a market screening of an education-technology startup
(a primary-mathematics learning-gap diagnostic tool sold to tuition centres in Singapore).
For each paper, from its title and abstract, decide how it bears on the CLAIM:
- "support": its findings directly back the claim.
- "narrow": it backs the claim only indirectly or partly (other country, school teachers instead of tutors,
  general assessment instead of maths diagnosis, a related but different tool). Most useful academic evidence is here.
- "conflict": its findings go against the claim.
- "none": it does not bear on the claim.
For every answer other than "none" give "evidence": one sentence naming the paper's specific finding and how it bears
on the claim, and "limitation": one sentence on what it does NOT show for this market claim.
Reply with JSON only: {"results": [{"id": "...", "type": "...", "evidence": "...", "limitation": ""}]}"""


def judge(claim, papers, chat, agent, log):
    out = {}
    for i in range(0, len(papers), 10):
        chunk = papers[i:i + 10]
        user = json.dumps({"claim": claim["text"], "papers": [
            {"id": p["id"], "title": clean_text(p["title"]), "year": p.get("year"), "abstract": clean_text(p.get("abstract") or "")[:2500]}
            for p in chunk]}, ensure_ascii=False)
        try:
            r = chat(agent, JUDGE_SYSTEM, user, json_mode=True)
            rows = (llm.parse_json(r["text"]) or {}).get("results", [])
        except llm.LLMUnavailable:
            raise
        except llm.LLMError as e:
            log(f"academic: skipped a batch ({e})")
            continue
        ids = {p["id"] for p in chunk}
        for x in rows:
            if isinstance(x, dict) and x.get("id") in ids and x.get("type") in ("support", "narrow", "conflict") and (x.get("evidence") or "").strip():
                out[x["id"]] = {**x, "model": r["model"]}
    return out


def run(data: Path, today: str, log=print, chat=None, only=None, search_fn=None, find=None, pause=3.5):
    chat = chat or llm.chat
    search_fn = search_fn or websearch.s2_search
    config = json.loads((data / "config.json").read_text())
    n = (M.mcfg(config).get("academic") or {}).get("add_per_claim", 4)
    agent = (config.get("llm") or {}).get("summary") or (config.get("llm") or {}).get("compare")
    if not agent:
        raise llm.LLMUnavailable("config.json needs llm.summary")
    claims = [c for c in load_dir(data / "claims").values() if M.short_id(c["id"]).startswith("MKT")
              and c.get("status") != "retired" and c.get("role") != "parent" and c.get("academic_queries")]
    out = {}
    for c in claims:
        cid = M.short_id(c["id"])
        if only and cid not in only:
            continue
        papers = load_dir(data / "papers")
        rels = load_dir(data / "relations")
        linked = {r["from"] for r in rels.values() if r.get("to") == c["id"]}
        have_titles = {collect.norm_title(p.get("title")): pid for pid, p in papers.items()}
        cands = {}
        for q in c["academic_queries"]:
            for it in search_fn(q, log):
                if it.get("abstract") and collect.norm_title(it["title"]) not in have_titles:
                    cands.setdefault(it["id"], it)
            time.sleep(pause)
        existing = [p for pid, p in papers.items() if pid not in linked and p.get("abstract")]
        verdicts = judge(c, list(cands.values()) + existing, chat, agent, log)
        # papers already in the repository first, then new ones by citation count
        new_hits = sorted((cands[i] for i in verdicts if i in cands), key=lambda x: -(x.get("citations") or 0))[:n]
        targets = [(p["id"], verdicts[p["id"]]) for p in existing if p["id"] in verdicts]
        for it in new_hits:
            try:
                pid, _ = addpaper.add(data, it["title"], today, log, chat=chat, find=find or (lambda q, lg, it=it: dict(it)))
                targets.append((pid, verdicts[it["id"]]))
            except llm.LLMUnavailable:
                raise
            except Exception as e:
                log(f"academic {cid}: could not add {it.get('title', '')[:60]} ({e})")
        written = 0
        for pid, v in targets:
            rel = {"id": claimrel.rel_id(pid, c["id"]), "from": pid, "to": c["id"], "layer": "0-1", "type": v["type"],
                   "reason": clean_text(v["evidence"]), "limitation": clean_text(v.get("limitation", "")), "status": "new",
                   "model": v["model"], "created_at": today, "source": "market-academic"}
            path = data / file_for("relations", rel["id"])
            if path.exists():
                continue
            write_json(path, rel)
            written += 1
        out[cid] = {"searched": len(cands), "judged_relevant": len(verdicts), "added": len(new_hits), "relation_drafts": written}
        log(f"academic {cid}: {out[cid]}")
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    a = ap.parse_args()
    run(Path(a.data), a.today)


if __name__ == "__main__":
    main()
