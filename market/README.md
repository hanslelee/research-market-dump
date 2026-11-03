# research-market-dump · market add-on

Market research for the MSI5002 Gate 3 case (MathBridge AI, fictional). Fills the team workbook
`01_Hansle_Market_Research.xlsx` from two lanes. Code and data share this **public** repository:
only public sources and the fictional case go here, never API keys or personal research.

```
                     ┌─ paper lane (research-dump agents) ─┐
claims/MKT-*.json ──►│  Semantic Scholar → add → relation   │──► papers/, relations/  ──┐
                     └──────────────────────────────────────┘   (you approve on the web) │
                     ┌─ market agent (market/agent.py) ─────┐                            ├─► build + rules ─► market/out/*.xlsx, *.csv
config.json:market ─►│  search → tier filter → snapshot →   │──► market/evidence.json   │
                     │  extract quotes → verify in snapshot │    market/competitors.json ─┘
                     └──────────────────────────────────────┘
human:  market/review.csv (VERIFIED / PARTIAL)   market/conclusions.json (conclusion text, action)
```

## Who fills which sheet

| Sheet | Filled by |
|---|---|
| Market Evidence | paper lane (academic rows) + market agent (statistics, news, competitor pages) |
| Competitor Matrix | market agent (features and price copied from the saved page, else NOT FOUND) |
| Market Conclusions | built from the evidence; **conclusion text is yours** (`market/conclusions.json`) |
| Market Handoff | built from Conclusions (CSV for Kaizhen: `market/out/market_handoff.csv`) |
| Component Tests | `market/seeded_tests.py` (8 seeded-defect tests, expected results frozen in code) |

## Setup (once)

1. Create the public repository `research-market-dump` and push this code.
2. Settings → Secrets → Actions: `GEMINI_API_KEY`, `S2_API_KEY`. Optional web search: `TAVILY_API_KEY`
   (then set `config.json → market.search.provider` to `"tavily"`) or `BRAVE_API_KEY` (`"brave"`, `key_name: "BRAVE_API_KEY"`).
   With provider `"none"` the agent still reads `seed_urls` and each competitor's `urls`.
3. Settings → Pages: deploy from `main`, root. The web page is `https://<you>.github.io/research-market-dump/viewer/`;
   connect it to this same repository (owner/name, branch main, a fine-grained token with contents write).

## Run

Actions → **market** → Run workflow → `all` (or `academic`, `web`, `export`). Then:

1. Web page → 연구 주제 tab → approve or reject the paper relation drafts (new → approved = PARTIAL).
2. Open the workbook (`market/out/`, or the run's `market-workbook` artifact). For rows you checked against the
   original page, add a line to `market/review.csv`: `MKT-E004,VERIFIED,Hansle,2026-11-04,quote and price on page`.
3. Write your conclusions in `market/conclusions.json`, then run `export` again.

Local: `python market/run.py all --data .` (needs the same environment variables).

## Status policy

| Status | Meaning |
|---|---|
| UNVERIFIED | drafted by an agent; nobody has looked |
| PARTIAL | a person looked (relation approved or review.csv), but abstract-level, indirect or only part of the claim |
| VERIFIED | only via review.csv, with checked_by + checked_date, and a real saved page (not a pilot excerpt) |
| MISSING | claim level: no usable evidence |

Claim action (rule default; you can override in conclusions.json, which is logged as R7 when it overrides a HOLD):
HIGH + MISSING/UNVERIFIED → HOLD; any blocking rule → HOLD; PARTIAL → ACCEPT_WITH_LIMITATION; VERIFIED → ACCEPT.

## Rules (no model)

R1 status vocabulary · R2 evidence ids resolve · R3 quote found in the saved text · R4 unit leap (a count of X cannot
support a claim counted in Y unless `market.unit_conversions` has an assumption converting X→Y; T03) ·
R5 competitor features and price found in the saved page · R6 no VERIFIED without a person's check and a real page ·
R7 human action overrides a rule HOLD · R8 a HIGH claim may not rest only on "Other" sources.

## The agent may not

Estimate market size or share, guess a missing price, paraphrase inside a quote, or set any status above UNVERIFIED.
Everything it drops is in `market/agent_log.jsonl`.

## Known limits

- Pages that need JavaScript or a login give little text; save the visible text as
  `market/snapshots/manual/<name>.txt` (`python market/run.py snapshot-name <url>` prints the name).
- The audit button reads full text only from arXiv PDFs; education journals are usually abstract-only (PARTIAL at best).
- The pilot rows (`found_by: manual-pilot`) use fetch-tool excerpts, not raw pages, so they can never be VERIFIED; rerun
  the agent on the same URLs to replace them.
- The seeded tests were written by the same person as the rules: not an independent test.
