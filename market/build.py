"""Turn both lanes into the five sheets of 01_Hansle_Market_Research.xlsx, then check them with rules (no model).

Claims: two team claims (MKT-01, MKT-02, "role": "parent") judged through Hansle's sub-claims (MKT-01-A ... MKT-02-C).
  Market Conclusions sheet = one row per sub-claim. Market Handoff sheet = one row per team claim.

Evidence row status (Market Evidence sheet):
  UNVERIFIED  drafted by an agent (web quote, or a paper relation still "new"); no person has looked
  PARTIAL     a person looked (relation approved, or review.csv) but it is abstract-level, indirect or only part of the claim
  VERIFIED    only from review.csv: a person opened the original, the quote is there, checked_by and checked_date set,
              and the snapshot is a real page (fetched or manual), not a pilot excerpt

Claim status (Conclusions and Handoff), four levels: VERIFIED > PARTIAL > SYNTHETIC > MISSING
  sub-claim   SYNTHETIC when fixed so (MathBridge's own features are fictional); else from its reviewed supporting
              evidence: none -> MISSING, all VERIFIED -> VERIFIED, otherwise PARTIAL. UNVERIFIED rows do not count.
  team claim  the weakest of its sub-claims; any MISSING sub-claim (or any sub-claim on HOLD) -> HOLD, and the
              limitation names the empty sub-claims.
Evidence marked "EDU related" (market/edu_related.json) counts for MKT like any other row and is also exported to
edu_candidates.csv for Zixuan (shared evidence, one MKT-E id).

Human inputs (never written by an agent):
  market/review.csv        evidence_id, verification_status, checked_by, checked_date, note, stance
                           (NOT APPLICABLE = wrong or irrelevant row: kept in the list, left out of every claim;
                            stance overrides the agent's supports / limits / contradicts)
  market/conclusions.json  {"MKT-01-A": {"conclusion": "...", "proposed_action": "", "review_status": "DRAFT", "cross_refs": ["EDU-E001"]}}
"""
import csv
import json
from pathlib import Path

import mcommon as M
from common import load_dir

STANCE_FROM_REL = {"support": "supports", "motivates": "supports", "narrow": "limits", "conflict": "contradicts",
                   "duplicate": "contradicts"}
HANDOFF_FIELDS = ["claim_id", "owner", "claim_text", "evidence_ids", "assumption_ids", "evidence_status", "materiality",
                  "limitation", "proposed_action", "version", "review_status"]


def academic_rows(data: Path):
    papers, rels, claims = (load_dir(data / d) for d in ("papers", "relations", "claims"))
    rows = []
    for r in rels.values():
        if r.get("layer") != "0-1" or r.get("status") == "rejected" or r["from"] not in papers or r["to"] not in claims:
            continue
        cid = M.short_id(r["to"])
        if not cid.startswith("MKT"):
            continue
        p = papers[r["from"]]
        audit = ((claims[r["to"]].get("audit") or {}).get("papers") or {}).get(p["id"], {})
        verdict = ((audit.get("relations") or {}).get(r["id"]) or {}).get("verdict")
        if verdict == "unsupported":
            continue
        abstract = p.get("abstract", "")
        quote = M.best_sentence(abstract, r.get("reason", "")) or abstract[:300]
        gap = (p.get("summary") or {}).get("gap", "") if isinstance(p.get("summary"), dict) else ""
        rows.append({
            "key": "rel:" + r["id"], "lane": "academic", "claim_id": cid, "url": p.get("url", ""), "title": p.get("title", ""),
            "publisher": p.get("venue", "") or "", "publication_date": str(p.get("published") or p.get("year") or ""),
            "quote": quote, "finding": r.get("reason", ""), "stance": STANCE_FROM_REL.get(r["type"], "supports"), "unit": "",
            "limitation": (r.get("limitation") or "Academic study, abstract-level; not evidence of purchasing by Singapore tuition centres.")
                          + (f" Gap: {gap}" if gap and not r.get("limitation") else ""),
            "source_type": "Academic paper", "tier": "academic", "snapshot": "", "snapshot_kind": "abstract",
            "check_text": abstract, "found_by": f"pipeline:{r.get('model', '')}",
            "verification_status": "PARTIAL" if r.get("status") == "approved" else "UNVERIFIED",
            "relation_status": r.get("status"),
        })
    return rows


def web_rows(data: Path):
    rows = []
    for e in M.read(M.mdir(data) / "evidence.json", {}).values():
        p = data / e["snapshot"] if e.get("snapshot") else None
        rows.append({**e, "check_text": p.read_text() if p and p.exists() else ""})
    return rows


def assign_ids(data: Path, rows):
    path = M.mdir(data) / "ids.json"
    ids = M.read(path, {})
    nxt = max([int(v.split("E")[-1]) for v in ids.values()] + [0]) + 1
    for r in sorted(rows, key=lambda r: (r["claim_id"], r["key"])):
        if r["key"] not in ids:
            ids[r["key"]] = f"MKT-E{nxt:03d}"
            nxt += 1
        r["evidence_id"] = ids[r["key"]]
    M.write(path, ids)
    return rows


def apply_review(data: Path, rows, competitors):
    path = M.mdir(data) / "review.csv"
    if not path.exists():
        return
    rev = {r["evidence_id"].strip(): r for r in csv.DictReader(open(path)) if r.get("evidence_id")}
    for r in rows + competitors:
        x = rev.get(r.get("evidence_id", ""))
        if not x:
            continue
        if x.get("verification_status", "").strip() in M.STATUSES:
            r["verification_status"] = x["verification_status"].strip()
        r["checked_by"] = x.get("checked_by", "").strip()
        r["checked_date"] = x.get("checked_date", "").strip()
        if (x.get("stance") or "").strip() in ("supports", "limits", "contradicts"):
            r["stance_by_agent"] = r.get("stance")
            r["stance"] = x["stance"].strip()
        if x.get("note"):
            r["review_note"] = x["note"].strip()


OVERLAP_STANCE = {"similar": "contradicts", "different": "supports", "unclear": "limits"}


def competitor_rows(data: Path):
    comps = list(M.read(M.mdir(data) / "competitors.json", {}).values())
    for c in comps:
        p = data / c["snapshot"] if c.get("snapshot") else None
        c["check_text"] = p.read_text() if p and p.exists() else ""
    return comps


def competitor_evidence(comps, mc, claim_id=None):
    """One Market Evidence row per competitor page, so the matrix points at a logged source (differentiation claim)."""
    rows = []
    claim_id = claim_id or mc.get("competitor_claim", "MKT-02-A")
    for c in comps:
        t = M.tier(c.get("url", ""), mc, M.competitor_domains(mc))
        t = "company" if t in ("other", "blocked") else t
        quote = (c.get("features") or [""])[0] or (c["price"] if c.get("price") not in ("", "NOT FOUND") else "")
        rows.append({
            "key": c["key"], "lane": "competitor", "claim_id": claim_id, "url": c.get("url", ""),
            "title": f"{c['competitor']}: {c.get('product', '')}".strip(": "), "publisher": c["competitor"],
            "publication_date": "", "quote": quote, "finding": c.get("differentiation", ""),
            "stance": OVERLAP_STANCE.get(c.get("overlap", "unclear"), "limits"), "unit": "",
            "limitation": ("Company self-description on its own website; features and price not independently tested."
                           if t == "company" else "Second-hand description of the competitor; check the provider's own page."),
            "source_type": M.SOURCE_TYPE[t], "tier": t, "snapshot": c.get("snapshot", ""),
            "snapshot_kind": c.get("snapshot_kind", ""), "check_text": c.get("check_text", ""),
            "found_by": c.get("found_by", ""), "verification_status": c.get("verification_status", "UNVERIFIED")})
    return rows


LADDER = ["MISSING", "SYNTHETIC", "PARTIAL", "VERIFIED"]  # weakest first


def counts(r):
    """Evidence that counts toward MKT status: reviewed (PARTIAL/VERIFIED). EDU related rows count too (shared with Zixuan)."""
    return r["verification_status"] in ("PARTIAL", "VERIFIED")


def sub_status(claim, ev):
    if claim.get("fixed_status") in LADDER:
        return claim["fixed_status"]
    sup = [e for e in ev if e["stance"] in ("supports", "limits") and counts(e)]
    if not sup:
        return "MISSING"
    return "VERIFIED" if all(e["verification_status"] == "VERIFIED" for e in sup) else "PARTIAL"


def conclusions(data: Path, config, rows):
    """One row per sub-claim (Market Conclusions)."""
    mc = M.mcfg(config)
    human = M.read(M.mdir(data) / "conclusions.json", {})
    out = []
    for c in sorted(load_dir(data / "claims").values(), key=lambda c: c["id"]):
        cid = M.short_id(c["id"])
        if not cid.startswith("MKT") or c.get("status") == "retired" or c.get("role") == "parent":
            continue
        ev = [r for r in rows if r["claim_id"] == cid and r["verification_status"] != "NOT APPLICABLE"]
        hc = human.get(cid, {})
        st = sub_status(c, ev)
        unreviewed = sum(1 for r in ev if r["verification_status"] == "UNVERIFIED")
        counter = [r for r in ev if r["stance"] == "contradicts" and counts(r)]
        lim = "; ".join(dict.fromkeys(r["limitation"] for r in ev if r.get("limitation") and counts(r)))
        notes = []
        if c.get("fixed_status"):
            notes.append(f"{c['fixed_status']} by design: {c.get('basis', '')}")
        if counter:
            notes.append(f"{len(counter)} reviewed counter-evidence row(s).")
        if unreviewed:
            notes.append(f"{unreviewed} evidence row(s) not reviewed yet (UNVERIFIED, not counted).")
        out.append({
            "claim_id": cid, "parent": c.get("parent", ""), "claim_text": c["text"],
            "market_conclusion": hc.get("conclusion") or f"[DRAFT - write after reading the evidence] {c['text']}",
            "supporting_evidence_ids": sorted(r["evidence_id"] for r in ev if r["stance"] in ("supports", "limits"))
                                       + list(hc.get("cross_refs", [])),
            "counter_evidence_ids": sorted(r["evidence_id"] for r in ev if r["stance"] == "contradicts"),
            "assumption_ids": c.get("assumption_ids", []), "verification_status": st,
            "materiality": c.get("materiality", "HIGH"),
            "limitations": (" ".join(notes) + (" " + lim if lim else ""))[:1500] or "No usable public evidence found yet.",
            "proposed_action": hc.get("proposed_action", ""), "review_status": hc.get("review_status", "DRAFT"),
            "unit": c.get("unit", ""), "owner": mc.get("owner", "Hansle"), "version": mc.get("version", "v0.1"),
        })
    return out


def default_action(c, blocked):
    if c["claim_id"] in blocked or c["verification_status"] == "MISSING":
        return "HOLD"
    return "ACCEPT" if c["verification_status"] == "VERIFIED" else "ACCEPT_WITH_LIMITATION"


def roll_up(data: Path, config, concl):
    """One row per team claim (Market Handoff): weakest sub-claim; any MISSING or HOLD sub-claim -> HOLD."""
    mc = M.mcfg(config)
    human = M.read(M.mdir(data) / "conclusions.json", {})
    out = []
    for c in sorted(load_dir(data / "claims").values(), key=lambda c: c["id"]):
        if c.get("role") != "parent" or c.get("status") == "retired":
            continue
        pid = M.short_id(c["id"])
        subs = [s for s in concl if s.get("parent") == pid]
        if not subs:
            st, action, lim = "MISSING", "HOLD", "No sub-claims defined."
        else:
            st = min((s["verification_status"] for s in subs), key=LADDER.index)
            empty = [s["claim_id"] for s in subs if s["verification_status"] == "MISSING"]
            held = [s["claim_id"] for s in subs if s["proposed_action"] == "HOLD" and s["claim_id"] not in empty]
            action = "HOLD" if empty or held else ("ACCEPT" if st == "VERIFIED" else "ACCEPT_WITH_LIMITATION")
            lim = "Sub-claims: " + ", ".join(f"{s['claim_id']} {s['verification_status']}" for s in subs) + "."
            if empty:
                lim += " Empty (MISSING): " + ", ".join(empty) + "."
            if held:
                lim += " On HOLD by rule or reviewer: " + ", ".join(held) + "."
        hc = human.get(pid, {})
        ids = list(dict.fromkeys(i for s in subs for i in s["supporting_evidence_ids"] + s["counter_evidence_ids"]))
        out.append({"claim_id": pid, "owner": mc.get("owner", "Hansle"), "claim_text": c["text"], "evidence_ids": ids,
                    "assumption_ids": list(dict.fromkeys(a for s in subs for a in s["assumption_ids"])),
                    "evidence_status": st, "materiality": c.get("materiality", "HIGH"), "limitation": lim,
                    "proposed_action": action, "version": mc.get("version", "v0.1"),
                    "review_status": hc.get("review_status", "DRAFT")})
    return out


# ---------- rules ----------
def validate(rows, comps, concl, config):
    issues = []
    mc = M.mcfg(config)
    ev = {r["evidence_id"]: r for r in rows}
    external = tuple(mc.get("cross_file_prefixes", ["EDU-", "FIN-", "INT-"]))
    flag = lambda rule, where, msg: issues.append({"rule": rule, "where": where, "issue": msg})
    for r in rows:
        if r.get("check_text") and not M.contains(r["check_text"], r["quote"], min_len=8):
            flag("R3_quote_not_in_source", r["claim_id"], f"{r['evidence_id']}: quote not found in its saved text")
        if not r.get("check_text"):
            flag("R3_no_saved_text", r["claim_id"], f"{r['evidence_id']}: no saved text to check the quote against")
        if r["verification_status"] == "VERIFIED" and (not r.get("checked_by") or not r.get("checked_date")
                                                     or r.get("snapshot_kind") in ("excerpt", "abstract", "none")):
            flag("R6_verified_without_check", r["claim_id"], f"{r['evidence_id']}: VERIFIED needs checked_by, checked_date and a full saved page")
        if r["verification_status"] not in M.STATUSES:
            flag("R1_bad_status", r["claim_id"], f"{r['evidence_id']}: {r['verification_status']!r}")
    for c in concl:
        for eid in c["supporting_evidence_ids"] + c["counter_evidence_ids"]:
            if eid.startswith(external):
                flag("R9_cross_file_reference", c["claim_id"], f"{eid} is in another member's file: check at integration (T07)")
            elif eid not in ev:
                flag("R2_dangling_evidence_id", c["claim_id"], f"{eid} is not in Market Evidence")
        if c.get("unit"):  # T03: a count of X cannot support a claim counted in Y without an assumption converting it
            conv = mc.get("unit_conversions") or {}
            for eid in c["supporting_evidence_ids"]:
                u = (ev.get(eid) or {}).get("unit", "")
                ok = any(a in conv and M.norm(conv[a].get("from", "")) == M.norm(u) and M.norm(conv[a].get("to", "")) == M.norm(c["unit"])
                         for a in c.get("assumption_ids", []))
                if u and M.norm(u) != M.norm(c["unit"]) and not ok:
                    flag("R4_unit_leap", c["claim_id"], f"claim counts {c['unit']} but {eid} counts {u}; no assumption converts {u} -> {c['unit']}")
        sup = [ev[e] for e in c["supporting_evidence_ids"] if e in ev]
        if c["materiality"] == "HIGH" and sup and all(s.get("tier") == "other" for s in sup):
            flag("R8_weak_sources_only", c["claim_id"], "HIGH claim rests only on 'Other' sources")
    for c in comps:
        txt = c.get("check_text", "")
        for f in c.get("features", []):
            if not M.contains(txt, f, min_len=4):
                flag("R5_competitor_feature_unsourced", c["competitor"], f"not in saved page: {f!r}")
        if c.get("price") not in ("", "NOT FOUND") and not M.contains(txt, c["price"]):
            flag("R5_competitor_price_unsourced", c["competitor"], f"price not in saved page: {c['price']!r}")
    return issues


def build(data: Path, extra_claims=None):
    """Returns rows, competitors, conclusions (sub-claims), handoff (team claims), issues, pending, edu."""
    config = json.loads((data / "config.json").read_text())
    mc = M.mcfg(config)
    comps = competitor_rows(data)
    web = web_rows(data)
    same = {(r["url"], M.norm(r["quote"])): r["key"] for r in web}
    comp_ev = []
    for r in competitor_evidence(comps, mc):  # a competitor quote already logged as web evidence reuses that row
        if (r["url"], M.norm(r["quote"])) in same:
            for c in comps:
                if c["key"] == r["key"]:
                    c["key"] = same[(r["url"], M.norm(r["quote"]))]
        else:
            comp_ev.append(r)
    rows = assign_ids(data, academic_rows(data) + web + comp_ev)
    by_key = {r["key"]: r for r in rows}
    apply_review(data, rows, [])
    edu = (M.read(M.mdir(data) / "edu_related.json", {}).get("items") or {})
    for r in rows:
        if r["evidence_id"] in edu:
            r["edu_related"] = True
            r["edu_id"] = edu[r["evidence_id"]].get("edu_id", "")
    for c in comps:
        r = by_key[c["key"]]
        c["evidence_id"], c["verification_status"] = r["evidence_id"], r["verification_status"]
        c["checked_date"] = r.get("checked_date", "")
    concl = conclusions(data, config, rows)
    for x in extra_claims or []:
        concl.append(x)
    issues = validate(rows, comps, concl, config)
    blocked = {i["where"] for i in issues if i["rule"] in ("R2_dangling_evidence_id", "R4_unit_leap", "R8_weak_sources_only")}
    for c in concl:
        auto = default_action(c, blocked)
        if not c["proposed_action"]:
            c["proposed_action"] = auto
        elif c["proposed_action"] != "HOLD" and auto == "HOLD":
            issues.append({"rule": "R7_human_action_overrides_hold", "where": c["claim_id"],
                           "issue": f"rules say HOLD, conclusions.json says {c['proposed_action']}: needs Kaizhen's adjudication"})
    handoff = roll_up(data, config, concl)
    pending = sum(1 for r in rows if r.get("relation_status") == "new")
    return {"rows": rows, "competitors": comps, "conclusions": concl, "handoff": handoff, "issues": issues,
            "pending": pending, "config": config, "edu": [r for r in rows if r.get("edu_related")]}
