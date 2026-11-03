"""Paper lane: the existing research-dump agents, run for each MKT claim.

    python market/run.py academic --data .

For each MKT claim:
  1. websearch.search   Semantic Scholar queries written by the model, relevance-filtered     (pipeline/websearch.py)
  2. addpaper.add       the top N suggestions are added, tagged and summarized                 (pipeline/addpaper.py)
  3. claimrel.link      relation drafts paper -> claim (support / narrow / conflict / ...)     (pipeline/claimrel.py)
Drafts stay "new" until you approve or reject them on the web page (연구 주제 tab), as before.
Export: approved -> PARTIAL, new -> UNVERIFIED, rejected -> left out. The audit button still works per claim.
"""
import json
from pathlib import Path

import mcommon as M  # noqa: F401  (puts pipeline/ on sys.path)
import addpaper
import claimrel
import llm
import websearch
from common import load_dir


def run(data: Path, today: str, log=print, chat=None, only=None, ws_kwargs=None, find=None):
    config = json.loads((data / "config.json").read_text())
    n = (M.mcfg(config).get("academic") or {}).get("add_per_claim", 4)
    claims = [c for c in load_dir(data / "claims").values() if M.short_id(c["id"]).startswith("MKT") and c.get("status") != "retired"
              and c.get("role") != "parent" and not c.get("fixed_status")]
    out = {}
    for c in claims:
        cid = M.short_id(c["id"])
        if only and cid not in only:
            continue
        try:
            kept = websearch.search(data, c["id"], today, log, chat=chat, **({"pause": 3.5} | (ws_kwargs or {})))
        except llm.LLMUnavailable:
            raise
        except Exception as e:
            log(f"academic {cid}: web search failed ({e})")
            kept = []
        added = []
        for it in kept[:n]:
            try:
                finder = find or (lambda q, lg, it=it: dict(it))
                pid, _ = addpaper.add(data, it["title"], today, log, chat=chat, find=finder)
                added.append(pid)
            except llm.LLMUnavailable:
                raise
            except Exception as e:
                log(f"academic {cid}: could not add {it.get('title', '')[:60]} ({e})")
        rels = claimrel.link(data, c["id"], today, log, chat=chat, paper_ids=set(added)) if added else []
        out[cid] = {"suggested": len(kept), "added": len(added), "relation_drafts": len(rels)}
        log(f"academic {cid}: {out[cid]}")
    return out
