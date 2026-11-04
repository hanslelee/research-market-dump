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
| Market Evidence | paper lane (Semantic Scholar: maths diagnostics, formative assessment, AI-assisted learning, per sub-claim `academic_queries`) + market agent (statistics, news, competitor pages) |
| Competitor Matrix | market agent (features and price copied from the saved page, else NOT FOUND) |
| Market Conclusions | built from the evidence; **conclusion text is yours** (`market/conclusions.json`) |
| Market Handoff | built from Conclusions (CSV for Kaizhen: `market/out/market_handoff.csv`) |
| Component Tests | `market/seeded_tests.py` (8 seeded-defect tests, expected results frozen in code) |

## Setup (once)

1. Create the public repository `research-market-dump` and push this code.
2. Settings → Secrets → Actions: `GEMINI_API_KEY`, `S2_API_KEY`. Optional web search: `TAVILY_API_KEY`
   (then set `config.json → market.search.provider` to `"tavily"`) or `BRAVE_API_KEY` (`"brave"`, `key_name: "BRAVE_API_KEY"`).
   With provider `"none"` the agent still reads `seed_urls` and each competitor's `urls`.
3. Settings → Pages: deploy from `main`, root (see Web page below).

## Web page

`https://<you>.github.io/research-market-dump/viewer/` (Settings → Pages: main, root).

- **홈**: team claims, sub-claims and evidence as a graph. Evidence shape = source kind (paper, news, government
  statistics, company page, research report, book, other); edge colour = supports / contradicts; dashed = not reviewed.
- **Evidences**: every evidence row with filters; the detail shows the copied quote, the saved snapshot and review buttons.
- **Claims**: MKT-01 / MKT-02 with their sub-claims, status, action, limitation, evidence chips and your conclusion.
- **저장소 연결** (repo, branch, fine-grained token with Contents read/write) enables: review buttons
  (PARTIAL / VERIFIED / NOT APPLICABLE, stance correction) → `market/review.csv`; conclusions → `market/conclusions.json`;
  each save is one commit plus an export request, and Actions rebuilds `viewer.json` and the workbook in 1 to 2 minutes.
- **엑셀 받기 / 엑셀 다시 만들기**: download or rebuild `market/out/01_Hansle_Market_Research.xlsx`.

## Run

Actions → **market** → Run workflow → `all` (or `academic`, `web`, `export`). Then:

1. Web page → Evidences → open each row, check the original, press PARTIAL / VERIFIED / NOT APPLICABLE
   (or edit `market/review.csv` by hand: `MKT-E004,VERIFIED,Hansle,2026-11-04,quote and price on page,contradicts`).
2. Web page → Claims → write a conclusion per sub-claim (or edit `market/conclusions.json`).
3. The workbook rebuilds after each save; 엑셀 받기 downloads it.

Local: `python market/run.py all --data .` (needs the same environment variables).

## Status policy

Two separate axes per evidence row.

| Status (you set it) | Meaning |
|---|---|
| UNVERIFIED | nobody has looked yet (agent draft) |
| PARTIAL | the quote was confirmed, but only part of the source was seen (abstract, excerpt, article summary) |
| VERIFIED | the whole original was opened and checked (needs a full saved page, checked_by, checked_date) |
| NOT APPLICABLE | wrong or irrelevant: kept in the list, left out of every claim |

Stance (the agent sets it; you correct it only when wrong): **supports** or **contradicts**. Indirect or conditional
support is "supports", and why it is indirect is in the limitation. In the workbook, supports → supporting_evidence_ids,
contradicts → counter_evidence_ids. "EDU related" rows (`market/edu_related.json`) are shared with Zixuan's education
check: they count for MKT like any other row and are also exported to `edu_candidates.csv`.

Claims, four levels, weakest first: MISSING < SYNTHETIC < PARTIAL < VERIFIED.
- Sub-claim (Market Conclusions): SYNTHETIC when fixed so (MKT-02-B: MathBridge's features are fictional); otherwise
  none of its reviewed supporting evidence → MISSING, all VERIFIED → VERIFIED, else PARTIAL. UNVERIFIED rows do not count.
- Team claim (Market Handoff): the weakest of its sub-claims. Any MISSING sub-claim → HOLD, and the limitation names it.
- Actions: MISSING or a blocking rule → HOLD; VERIFIED → ACCEPT; otherwise ACCEPT_WITH_LIMITATION.
  A human action in conclusions.json that overrides a rule HOLD is logged as R7 for Kaizhen's adjudication.

## Rules (no model)

R1 status vocabulary · R2 evidence ids resolve · R3 quote found in the saved text · R4 unit leap (a count of X cannot
support a claim counted in Y unless `market.unit_conversions` has an assumption converting X→Y; T03) ·
R5 competitor features and price found in the saved page · R6 no VERIFIED without a person's check and a real page ·
R7 human action overrides a rule HOLD · R8 a HIGH claim may not rest only on "Other" sources ·
R9 ids from other members' files (EDU-, FIN-, INT-) are checked at integration (T07), not here.

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
