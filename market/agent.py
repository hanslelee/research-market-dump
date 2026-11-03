"""Market research agent (web lane). Fills what the paper pipeline cannot: statistics, news, competitor pages.

    python market/run.py web --data .

For each MKT claim and each competitor in config.json -> market:
  1. plan     queries: the claim's market_queries, else the model writes them      (model, Rung 0)
  2. search   provider in market.search (none = seed and competitor urls only)      (no model)
  3. filter   source tier by domain; blocked and "other" domains are dropped        (rule)
  4. fetch    save raw page + text under market/snapshots/                          (no model)
  5. extract  the model copies quotes ONLY from the saved text                      (model, Rung 1)
  6. verify   every quote, feature and price must be found in the saved text;       (rule)
              anything not found is dropped and logged, never repaired
The agent never sets a status above UNVERIFIED. A person marks VERIFIED / PARTIAL in market/review.csv.
It never estimates market size, market share or a missing price.
"""
import json
from pathlib import Path

import fetch as F
import llm
import mcommon as M
import search as S

PLAN_SYSTEM = """You plan web searches for a market-research claim about {country}.
Write {n} short search queries (4 to 9 words) that would find PUBLIC evidence for or against the claim:
government statistics, reputable news, official company pages. Include at least one query that could find counter-evidence.
Reply with JSON only: {{"queries": ["..."]}}"""

EVIDENCE_SYSTEM = """You extract evidence for ONE market claim from ONE saved web page.
Rules:
- "quote" must be copied EXACTLY from the page text, character for character (at most 300 characters). Never paraphrase, translate, round or merge sentences in a quote.
- "finding": one sentence in your own words: what the quote shows for the claim.
- "stance": "supports", "limits" (true but narrower or indirect) or "contradicts".
- "unit": what a number in the quote counts (students, households, schools, centres, customers, SGD per household, ...), or "" if no count.
- "limitation": one sentence on what this quote does NOT establish for the claim (e.g. counts students not paying centres; company self-report; old date; other country).
- Indirect evidence still counts as "limits": e.g. general teacher workload or marking time when the claim is about
  diagnosing maths gaps, school teachers when the claim is about tutors, another country, an older year. Include it and
  say in "limitation" exactly why it is indirect. Only return "items": [] when the page has nothing that bears on the claim at all.
- At most 3 items.
- "publisher", "publication_date" (as written on the page, else ""), "title": from the page.
Reply with JSON only:
{"publisher": "", "publication_date": "", "title": "", "items": [{"quote": "", "finding": "", "stance": "", "unit": "", "limitation": ""}]}"""

COMPETITOR_SYSTEM = """You extract facts about a competitor from ONE saved page of its website.
The product we compare against: {product}
Rules:
- "features": up to 6 phrases copied EXACTLY from the page (at most 120 characters each) about diagnosis, learning gaps, reports, analytics, personalisation, or use by teachers, tutors or centres.
- "target_customer": a phrase copied EXACTLY from the page naming who it is for (parents, students, schools, centres), or "".
- "price": the price text copied EXACTLY from the page with currency and period, or "NOT FOUND". Never compute or guess a price.
- "product": the product or plan name as written on the page.
- "differentiation": one sentence in your own words on how it differs from the product above (or "unclear").
- "overlap": "similar" if the copied features show it already offers what the product above offers (diagnosis of learning gaps with reports),
  "different" if the page clearly shows it does not, "unclear" otherwise.
Reply with JSON only: {{"product": "", "target_customer": "", "features": [""], "price": "", "differentiation": "", "overlap": ""}}"""


def agent_cfg(config):
    l = config.get("llm") or {}
    a = l.get("market") or l.get("summary") or l.get("compare")
    if not a:
        raise llm.LLMUnavailable("config.json needs llm.market or llm.summary")
    return a


class Store:
    """market/evidence.json, market/competitors.json, market/agent_log.jsonl. Human fields are never overwritten."""

    def __init__(self, data: Path):
        self.data = data
        self.md = M.mdir(data)
        self.evidence = M.read(self.md / "evidence.json", {})
        self.competitors = M.read(self.md / "competitors.json", {})
        self.urls = M.read(self.md / "visited.json", {})

    def log(self, **row):
        self.md.mkdir(parents=True, exist_ok=True)
        with open(self.md / "agent_log.jsonl", "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def save(self):
        M.write(self.md / "evidence.json", self.evidence)
        M.write(self.md / "competitors.json", self.competitors)
        M.write(self.md / "visited.json", self.urls)


def plan_queries(claim, mc, chat, agent, log):
    if claim.get("market_queries"):
        return claim["market_queries"]
    sc = mc.get("search", {})
    r = chat(agent, PLAN_SYSTEM.format(country=sc.get("country", "Singapore"), n=sc.get("queries_per_claim", 3)),
             json.dumps({"claim": claim["text"], "basis": claim.get("basis", "")}, ensure_ascii=False), json_mode=True)
    return [q for q in (llm.parse_json(r["text"]) or {}).get("queries", []) if isinstance(q, str)][:5]


def candidate_urls(claim_id, queries, mc, store, log, search_fn):
    """Seed urls first, then search results, filtered by source tier."""
    comp = M.competitor_domains(mc)
    urls = [s["url"] for s in mc.get("seed_urls", []) if s.get("claim_id") == claim_id]
    for q in queries:
        for hit in search_fn(q, mc.get("search", {}), log):
            urls.append(hit["url"])
    out = []
    for u in dict.fromkeys(urls):
        t = M.tier(u, mc, comp)
        if t == "blocked" or (t == "other" and not mc.get("allow_other_tier")):
            store.log(step="filter", claim=claim_id, url=u, tier=t, action="dropped")
            continue
        out.append((u, t))
    return out[: mc.get("max_pages_per_claim", 6)]


def extract_evidence(data, claim, url, tier, snap, text, chat, agent, store, today):
    cid = M.short_id(claim["id"])
    user = json.dumps({"claim": claim["text"], "url": url, "page_text": text[:60000]}, ensure_ascii=False)
    r = chat(agent, EVIDENCE_SYSTEM, user, json_mode=True, timeout=240)
    got = llm.parse_json(r["text"]) or {}
    kept = 0
    for it in got.get("items", []) or []:
        q = (it.get("quote") or "").strip()
        if not M.contains(text, q, min_len=8):
            store.log(step="verify", claim=cid, url=url, action="dropped", rule="quote_not_in_snapshot", quote=q[:200])
            continue
        nq = M.norm(q)
        dup = next((k for k, e in store.evidence.items() if e.get("url") == url and e.get("claim_id") == cid
                    and (nq in M.norm(e["quote"]) or M.norm(e["quote"]) in nq)), None)
        if dup:  # same page, same claim, overlapping quote: keep the existing row (its id and any review stay)
            store.log(step="verify", claim=cid, url=url, action="merged", rule="overlapping_quote", into=dup)
            continue
        key = "web:" + M.h(url, nq, cid)
        old = store.evidence.get(key, {})
        store.evidence[key] = {
            **old, "key": key, "lane": "web", "claim_id": cid, "url": url, "title": got.get("title", "") or old.get("title", ""),
            "publisher": got.get("publisher", "") or M.domain(url), "publication_date": got.get("publication_date", ""),
            "quote": q, "finding": it.get("finding", ""), "stance": it.get("stance", "supports"), "unit": it.get("unit", ""),
            "limitation": it.get("limitation", ""), "tier": tier, "source_type": M.SOURCE_TYPE[tier],
            "snapshot": snap["path"], "snapshot_kind": snap["kind"], "found_by": f"agent:{r['model']}",
            "created_at": old.get("created_at", today), "verification_status": old.get("verification_status", "UNVERIFIED"),
        }
        kept += 1
    return kept


def extract_competitor(comp, url, snap, text, mc, chat, agent, store, today):
    r = chat(agent, COMPETITOR_SYSTEM.format(product=mc.get("product", "")),
             json.dumps({"competitor": comp["name"], "url": url, "page_text": text[:60000]}, ensure_ascii=False),
             json_mode=True, timeout=240)
    got = llm.parse_json(r["text"]) or {}
    feats = []
    for f in got.get("features", []) or []:
        if M.contains(text, f, min_len=4):
            feats.append(f.strip())
        elif f:
            store.log(step="verify", competitor=comp["name"], url=url, action="dropped", rule="feature_not_in_snapshot", text=f[:200])
    price = (got.get("price") or "").strip()
    if price and price != "NOT FOUND" and not M.contains(text, price):
        store.log(step="verify", competitor=comp["name"], url=url, action="dropped", rule="price_not_in_snapshot", text=price[:200])
        price = "NOT FOUND"
    target = got.get("target_customer", "")
    if target and not M.contains(text, target):
        target = ""
    key = "comp:" + M.h(comp["name"], url)
    old = store.competitors.get(key, {})
    store.competitors[key] = {
        **old, "key": key, "competitor": comp["name"], "product": got.get("product", "") or old.get("product", ""),
        "target_customer": target, "features": feats, "price": price or "NOT FOUND",
        "pricing_status": "FOUND" if price and price != "NOT FOUND" else "NOT FOUND",
        "differentiation": got.get("differentiation", ""), "overlap": got.get("overlap", "unclear"), "url": url, "snapshot": snap["path"], "snapshot_kind": snap["kind"],
        "found_by": f"agent:{r['model']}", "checked_date": old.get("checked_date", ""), "created_at": old.get("created_at", today),
        "verification_status": old.get("verification_status", "UNVERIFIED"),
    }
    return len(feats)


def run(data: Path, today: str, log=print, chat=None, search_fn=S.search, getter=F.http_fetch, only=None, refresh=False):
    chat = chat or llm.chat
    config = json.loads((data / "config.json").read_text())
    mc = M.mcfg(config)
    agent = agent_cfg(config)
    store = Store(data)
    from common import load_dir  # pipeline/common.py
    claims = [c for c in load_dir(data / "claims").values() if M.short_id(c["id"]).startswith("MKT") and c.get("status") != "retired"
              and c.get("role") != "parent" and not c.get("fixed_status")]
    summary = {"pages": 0, "evidence": 0, "competitor_features": 0, "skipped_pages": 0}

    for claim in claims:
        cid = M.short_id(claim["id"])
        if only and cid not in only:
            continue
        queries = plan_queries(claim, mc, chat, agent, log)
        store.log(step="plan", claim=cid, queries=queries)
        for url, t in candidate_urls(cid, queries, mc, store, log, search_fn):
            done = store.urls.get(url, {}).get("extracted_for", [])
            if cid in done and not refresh:
                continue  # this page was already read for this claim; --refresh reads it again
            snap = F.snapshot(data, url, today, getter=getter, log=log)
            store.urls[url] = {**snap, "extracted_for": done}
            if not snap["ok"]:
                store.log(step="fetch", claim=cid, url=url, action="skipped", reason=snap["reason"])
                summary["skipped_pages"] += 1
                continue
            summary["pages"] += 1
            try:
                summary["evidence"] += extract_evidence(data, claim, url, t, snap, F.text_of(data, snap), chat, agent, store, today)
                store.urls[url]["extracted_for"] = sorted(set(done) | {cid})
            except llm.LLMUnavailable:
                store.save()
                raise
            except llm.LLMError as e:
                store.log(step="extract", claim=cid, url=url, action="skipped", reason=str(e)[:200])

    for comp in mc.get("competitors", []):
        if only and "competitors" not in only:
            continue
        urls = list(comp.get("urls", []))
        for q in (f"{comp['name']} pricing plans", f"{comp['name']} features for teachers reports"):
            urls += [x["url"] for x in search_fn(q, mc.get("search", {}), log)
                     if M._match(M.domain(x["url"]), comp.get("domains", []))]
        for url in list(dict.fromkeys(urls))[:3]:
            snap = F.snapshot(data, url, today, getter=getter, log=log)
            store.urls[url] = snap
            if not snap["ok"]:
                store.log(step="fetch", competitor=comp["name"], url=url, action="skipped", reason=snap["reason"])
                summary["skipped_pages"] += 1
                continue
            summary["pages"] += 1
            try:
                summary["competitor_features"] += extract_competitor(comp, url, snap, F.text_of(data, snap), mc, chat, agent, store, today)
            except llm.LLMUnavailable:
                store.save()
                raise
            except llm.LLMError as e:
                store.log(step="extract", competitor=comp["name"], url=url, action="skipped", reason=str(e)[:200])
    store.save()
    store.log(step="done", date=today, **summary)
    log(f"market agent: {summary}")
    return summary
