"""Turn both lanes into the five sheets of 01_Hansle_Market_Research.xlsx, then check them with rules (no model).

Claims: two team claims (MKT-01, MKT-02, "role": "parent") judged through Hansle's sub-claims (MKT-01-A ... MKT-02-C).
  Market Conclusions sheet = one row per sub-claim. Market Handoff sheet = one row per team claim.

Two separate axes per evidence row:
  status = a person's check of the row (review.csv)
    UNVERIFIED      nobody has looked yet (agent draft)
    PARTIAL         checked: the evidence backs only part of the claim (indirect, conditional, another setting)
    VERIFIED        checked: the evidence backs the claim fully (checked_by and checked_date required)
    NOT APPLICABLE  wrong or irrelevant: kept in the list, left out of every claim
  stance = what it says about its claim: supports or contradicts (set by the agent; a person corrects it only when wrong).
    Indirect or conditional support is "supports"; why it is indirect is written in the limitation.

Claim status (Conclusions and Handoff), four levels: VERIFIED > PARTIAL > SYNTHETIC > MISSING
  sub-claim   SYNTHETIC when fixed so (MathBridge's own features are fictional); else from its reviewed supporting
              evidence: none -> MISSING, all VERIFIED -> VERIFIED, otherwise PARTIAL. UNVERIFIED rows do not count.
  team claim  the weakest of its sub-claims.
Actions follow the case packet v1.0 section 12 ("a missing fact triggers HOLD only when it is necessary for the
preliminary decision"):
  missing evidence (MISSING)       -> an open question for deeper diligence, not a HOLD
                                      (unless conclusions.json marks the sub-claim "material_blocker": true)
  inflated or false evidence       -> HOLD (R4 unit leap, R2 dangling id, R8 weak sources only)
  unresolved contradiction         -> HOLD (R10: reviewed counter-evidence on the sub-claim)
  team claim                       -> HOLD if any sub-claim is on HOLD; open questions are listed in the limitation
Evidence marked "EDU related" (market/edu_related.json) counts for MKT like any other row and is also exported to
edu_candidates.csv for Zixuan (shared evidence, one MKT-E id).

Human inputs (never written by an agent):
  market/review.csv        evidence_id, verification_status, checked_by, checked_date, note, stance
                           (stance, optional: supports or contradicts, overrides the agent)
  market/conclusions.json  {"MKT-01-A": {"conclusion": "...", "proposed_action": "", "review_status": "DRAFT", "cross_refs": ["EDU-E001"]}}
"""
import csv
import json
from pathlib import Path

import mcommon as M
from common import load_dir

STANCE_FROM_REL = {"support": "supports", "motivates": "supports", "narrow": "supports", "conflict": "contradicts",
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
        st = STANCE_ALIAS.get((x.get("stance") or "").strip())
        if st and st != r.get("stance"):
            r["stance_by_agent"] = r.get("stance")
            r["stance"] = st
        if x.get("note"):
            r["review_note"] = x["note"].strip()


OVERLAP_STANCE = {"similar": "contradicts", "different": "supports", "unclear": "supports"}
STANCE_ALIAS = {"supports": "supports", "limits": "supports", "contradicts": "contradicts"}  # "limits" was the old middle value


def competitor_rows(data: Path):
    comps = list(M.read(M.mdir(data) / "competitors.json", {}).values())
    for c in comps:
        p = data / c["snapshot"] if c.get("snapshot") else None
        c["check_text"] = p.read_text() if p and p.exists() else ""
    return comps


def canonical_competitor(c, mc):
    """One name per competitor: the config name whose domain or first word matches."""
    host = M.domain(c.get("url", ""))
    name = (c.get("competitor") or "").lower()
    for comp in mc.get("competitors", []):
        first = comp["name"].split()[0].lower()
        if M._match(host, comp.get("domains", [])) or name.startswith(first):
            return comp["name"]
    return c.get("competitor", "")


def page_label(url):
    path = url.split("://", 1)[-1].split("?", 1)[0].rstrip("/")
    return path.split("/", 1)[1] if "/" in path else "home page"


def merged_competitors(comps, mc):
    """Competitor Matrix: one row per competitor; every page stays a separate Market Evidence row."""
    groups = {}
    for c in comps:
        groups.setdefault(canonical_competitor(c, mc), []).append(c)
    out = []
    for name, cs in groups.items():
        uniq = lambda xs: list(dict.fromkeys(x for x in xs if x))
        prices = []
        for c in cs:
            if c.get("price") not in ("", "NOT FOUND"):
                note = " (international plan, not the Singapore price)" if "intl" in c.get("url", "") else ""
                prices.append(f"{c['price']} [{c['evidence_id']}, {page_label(c.get('url', ''))}]{note}")
        overlaps = {c.get("overlap", "unclear") for c in cs}
        out.append({
            "competitor": name, "product": "; ".join(uniq(c.get("product", "") for c in cs)),
            "target_customer": "; ".join(uniq(c.get("target_customer", "") for c in cs)),
            "features": uniq(f for c in cs for f in c.get("features", [])),
            "price": "; ".join(prices) or "NOT FOUND", "pricing_status": "FOUND" if prices else "NOT FOUND",
            "differentiation": " ".join(uniq(c.get("differentiation", "") for c in cs)),
            "evidence_ids": sorted({c["evidence_id"] for c in cs}, key=lambda i: int(i.split("E")[-1])),
            "checked_date": max((c.get("checked_date", "") for c in cs), default=""),
            "overlap": "similar" if "similar" in overlaps else ("different" if overlaps == {"different"} else "unclear"),
            "pages": len(cs),
            "limitations": "Company self-description; features and prices not independently tested."
                           + ("" if prices else " No price found on any saved page."),
        })
    return sorted(out, key=lambda r: r["competitor"])


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
            "title": f"{canonical_competitor(c, mc)}: {c.get('product', '')}".strip(": "), "publisher": canonical_competitor(c, mc),
            "publication_date": "", "quote": quote, "finding": c.get("differentiation", ""),
            "stance": OVERLAP_STANCE.get(c.get("overlap", "unclear"), "supports"), "unit": "",
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
    sup = [e for e in ev if e["stance"] == "supports" and counts(e)]
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
        if hc.get("proposed_action") and hc.get("action_reason"):
            notes.append(f"Action {hc['proposed_action']} by reviewer: {hc['action_reason']}")
        if c.get("fixed_status"):
            notes.append(f"{c['fixed_status']} by design: {c.get('basis', '')}")
        if counter:
            notes.append(f"Unresolved contradiction: {len(counter)} reviewed counter-evidence row(s) ({', '.join(r['evidence_id'] for r in counter)}).")
        if st == "MISSING" and not c.get("fixed_status"):
            notes.append("Open question for deeper diligence: no public evidence found."
                         + (" Marked as a material blocker by the reviewer." if hc.get("material_blocker") else ""))
        if unreviewed:
            notes.append(f"{unreviewed} evidence row(s) not reviewed yet (UNVERIFIED, not counted).")
        out.append({
            "claim_id": cid, "parent": c.get("parent", ""), "claim_text": c["text"],
            "market_conclusion": hc.get("conclusion") or f"[DRAFT - write after reading the evidence] {c['text']}",
            "supporting_evidence_ids": sorted(r["evidence_id"] for r in ev if r["stance"] == "supports")
                                       + list(hc.get("cross_refs", [])),
            "counter_evidence_ids": sorted(r["evidence_id"] for r in ev if r["stance"] == "contradicts"),
            "assumption_ids": c.get("assumption_ids", []), "verification_status": st,
            "materiality": c.get("materiality", "HIGH"),
            "limitations": (" ".join(notes) + (" " + lim if lim else ""))[:1500] or "No usable public evidence found yet.",
            "proposed_action": ACTION_ALIAS.get(hc.get("proposed_action", ""), ""), "review_status": hc.get("review_status", "DRAFT"),
            "unit": c.get("unit", ""), "owner": mc.get("owner", "Hansle"), "version": mc.get("version", "v0.1"),
            "contradicted": bool(counter), "material_blocker": bool(hc.get("material_blocker")),
        })
    return out


ACTIONS = ("Accept", "Investigate", "Correct", "HOLD")  # Kaizhen's handoff vocabulary (4 Nov)
ACTION_ALIAS = {"ACCEPT": "Accept", "ACCEPT_WITH_LIMITATION": "Investigate", "INVESTIGATE": "Investigate",
                "CORRECT": "Correct", "HOLD": "HOLD", "Accept": "Accept", "Investigate": "Investigate", "Correct": "Correct"}
TRACTION_NOTE = ("Market evidence, not MathBridge traction: MathBridge is fictional and pre-revenue with no customers (SYN-05).")


def default_action(c, blocked):
    """HOLD for inflated evidence or an unresolved contradiction; Accept only when fully verified; otherwise Investigate
    (partial or missing evidence is a question for deeper diligence, packet v1.0 section 12)."""
    if c["claim_id"] in blocked or c.get("contradicted"):
        return "HOLD"
    if c["verification_status"] == "MISSING" and c.get("material_blocker"):
        return "HOLD"
    return "Accept" if c["verification_status"] == "VERIFIED" else "Investigate"


def roll_up(data: Path, config, concl):
    """One row per team claim (Market Handoff): weakest sub-claim; any sub-claim on HOLD -> HOLD; MISSING sub-claims are open questions."""
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
            held = [s["claim_id"] for s in subs if s["proposed_action"] == "HOLD"]
            action = "HOLD" if held else ("Accept" if all(s["proposed_action"] == "Accept" for s in subs) else "Investigate")
            lim = "Sub-claims: " + ", ".join(f"{s['claim_id']} {s['verification_status']}" for s in subs) + "."
            if held:
                lim += " On HOLD: " + "; ".join(
                    f"{s['claim_id']} ({'unresolved contradiction' if s.get('contradicted') else 'rule or reviewer'})" for s in subs
                    if s["claim_id"] in held) + "."
            if empty:
                lim += " Open questions for deeper diligence (no public evidence): " + ", ".join(empty) + "."
        hc = human.get(pid, {})
        ids = list(dict.fromkeys(i for s in subs for i in s["supporting_evidence_ids"] + s["counter_evidence_ids"]))
        out.append({"claim_id": pid, "owner": mc.get("owner", "Hansle"), "claim_text": c["text"], "evidence_ids": ids,
                    "assumption_ids": list(dict.fromkeys(a for s in subs for a in s["assumption_ids"])),
                    "evidence_status": st, "materiality": c.get("materiality", "HIGH"), "limitation": lim,
                    "proposed_action": action, "version": mc.get("version", "v0.1"),
                    "review_status": hc.get("review_status", "DRAFT")})
    return out


def key_findings(concl, mc):
    """Kaizhen's handoff tab (4 Nov): 5-6 key findings per person. One row per evidence-based sub-claim; the synthetic
    sub-claim (MKT-02-B) is folded into the limitation of its sibling. claim_text = the reviewer's conclusion."""
    synth = {c.get("parent"): c for c in concl if c.get("verification_status") == "SYNTHETIC"}
    out = []
    for c in concl:
        if c.get("verification_status") == "SYNTHETIC" or c["claim_id"].startswith("MKT-99"):
            continue
        lim = TRACTION_NOTE + " " + c["limitations"]
        s = synth.get(c.get("parent"))
        if s and c["claim_id"].endswith("-A"):
            lim += f" {s['claim_id']} (synthetic by design): {s['market_conclusion']}"
        concl_text = c["market_conclusion"]
        if concl_text.startswith("[DRAFT"):
            concl_text = c["claim_text"]
        out.append({"claim_id": c["claim_id"], "owner": c["owner"], "claim_text": concl_text,
                    "evidence_ids": c["supporting_evidence_ids"] + c["counter_evidence_ids"], "assumption_ids": c["assumption_ids"],
                    "evidence_status": c["verification_status"], "materiality": c["materiality"], "limitation": lim[:2000],
                    "proposed_action": c["proposed_action"], "version": c["version"], "review_status": c["review_status"],
                    "parent": c.get("parent", "")})
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
        if r["verification_status"] == "VERIFIED" and (not r.get("checked_by") or not r.get("checked_date")):
            flag("R6_verified_without_check", r["claim_id"], f"{r['evidence_id']}: VERIFIED needs checked_by and checked_date")
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
    for r in rows:
        r["stance"] = STANCE_ALIAS.get(r.get("stance"), "supports")
        r["evidence_class"] = "EXT-PUB"  # packet v1.0 section 1: external public source (all market evidence is public)
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
        if c.get("contradicted"):
            issues.append({"rule": "R10_unresolved_contradiction", "where": c["claim_id"],
                           "issue": "reviewed counter-evidence on this sub-claim; HOLD until adjudicated (packet 12: contradiction unresolved)"})
    for c in concl:
        auto = default_action(c, blocked)
        if not c["proposed_action"]:
            c["proposed_action"] = auto
        elif c["proposed_action"] != "HOLD" and auto == "HOLD":
            issues.append({"rule": "R7_human_action_overrides_hold", "where": c["claim_id"],
                           "issue": f"rules say HOLD, conclusions.json says {c['proposed_action']}: needs Kaizhen's adjudication"})
    handoff = roll_up(data, config, concl)
    handoff_rows = key_findings(concl, mc)
    matrix = merged_competitors(comps, mc)
    pending = sum(1 for r in rows if r.get("relation_status") == "new")
    return {"rows": rows, "competitors": comps, "matrix": matrix, "conclusions": concl, "handoff": handoff,
            "handoff_rows": handoff_rows, "issues": issues,
            "pending": pending, "config": config, "edu": [r for r in rows if r.get("edu_related")]}
