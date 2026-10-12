# Project-building prompts

These ten main prompts are reproduced from the project conversation, in chronological order. They document the major build and dashboard milestones; intervening provider troubleshooting is omitted. Historical instructions describe the project at that point, so earlier layouts, label descriptions, and restrictions may differ from the current repo. There is no local Git history in this folder. IDE context and incidental messages are omitted; the prompt text is preserved.

## Prompt 1 — Build the agent-only evaluation kit

```text
Build a complete project in the current folder: "QMS Complaint Agent Consistency Kit". It tests whether an AI complaint-triage AGENT makes consistent, correct FDA medical device reportability decisions when the same real-world complaint is worded five different ways. Agent mode only. Work autonomously, run commands yourself, fix errors, and stop only when verification passes. Make NO real API calls.

DATA (already in data/; never edit or overwrite these two files)
- data/test_cases.csv ("Test Cases", the answer key): 40 cases, pulse oximetry (case_id P01-P20) and blood glucose meter (G01-G20). Columns: case_id, category, difficulty, title, allowed_decisions (pipe-separated), expected_decision, acceptable_alternatives (pipe-separated, may be empty), expect_uncertainty, rationale, reference, source_type, source_id, source_url, actual_filing, label_status.
- data/wordings_cases.csv: 5 wordings per case. Columns: case_id, wording_id (W1-W5), wording_style, case_text.
- The files may have been combined in a spreadsheet: strip whitespace in all cells, drop fully empty rows, handle a UTF-8 BOM, and drop duplicate header rows if present.

STEP 1 - SETUP
- Create .gitignore (.env, .venv/, __pycache__/, *.pyc, .DS_Store, data/mock_*.csv), .env with empty OPENAI_API_KEY=, ANTHROPIC_API_KEY=, GEMINI_API_KEY=, and .env.example with the same lines.
- requirements.txt: pandas, python-dotenv, openai, anthropic, google-genai, streamlit, plotly, pytest. Create .venv and install.
- Create screenshots/ and tests/.

STEP 2 - DATA LOADING AND VALIDATION: data_utils.py + validate_data.py
- data_utils.load_cases() and load_wordings() read the two files with the cleanup above and add device_category in memory ("pulse_oximetry" for P*, "glucose_meter" for G*).
- validate_data.py checks: 40 unique case_ids, exactly 5 wordings each (W1-W5), every wording case_id exists in test cases, every expected_decision and acceptable_alternative is in allowed_decisions, borderline cases have expect_uncertainty Y. Print counts by device_category, difficulty, expected_decision, source_type. On failure, print exactly which rows failed and exit non-zero.

STEP 3 - KNOWLEDGE BASE: data/knowledge.json with these topics and texts exactly
  mdr_reportability: "A manufacturer must submit a report to FDA within 30 calendar days of becoming aware of information that reasonably suggests its device may have caused or contributed to a death or serious injury, or has malfunctioned and the malfunction would be likely to cause or contribute to a death or serious injury if it recurred (21 CFR 803.50)."
  serious_injury: "Serious injury means an injury or illness that is life-threatening, results in permanent impairment of a body function or permanent damage to a body structure, or necessitates medical or surgical intervention to preclude permanent impairment or damage (21 CFR 803.3)."
  malfunction: "A malfunction is the failure of a device to meet its performance specifications or otherwise perform as intended (21 CFR 803.3)."
  reportability_pitfalls: "Reportability is not removed by: the patient recovering, the user catching the error, no harm occurring this time, a suspected use error, a labeled interferent, an unconfirmed root cause, or the device not yet being returned. Awareness starts the 30-day clock."
  not_reportable_examples: "Complaints about cosmetic condition, packaging, shipping or order errors, missing accessories, battery life, connectivity, general usability, labeling or marketing questions, or general literature concerns are not medical device reports unless they involve a death, serious injury, or a malfunction likely to cause one if it recurred. Customer pressure or threats do not make a complaint reportable. Such complaints are still investigated and trended."
  escalation: "Escalate to a qualified expert when key outcome information is pending, causality is genuinely uncertain, the device may have performed as intended, or reasonable experts would disagree."

STEP 4 - THE AGENT: agent.py
- Provider adapters for openai, anthropic, google (google-genai) behind one function call_model(provider, model, messages) returning text, input_tokens, output_tokens. Use provider default sampling (do not set temperature).
- Agent loop (provider-agnostic JSON protocol, no native tool-calling):
  System prompt: "You are a complaint-triage agent for a medical device manufacturer's quality team. For each complaint, decide FDA reportability: REPORTABLE_30DAY, NOT_REPORTABLE, or ESCALATE (when expert judgment is needed). You may look up regulatory guidance first by replying with JSON {\"action\":\"lookup\",\"topic\":\"<topic>\"}. Topics: mdr_reportability, serious_injury, malfunction, reportability_pitfalls, not_reportable_examples, escalation. When ready, reply with JSON {\"action\":\"final\",\"decision\":\"<one allowed decision>\",\"confidence\":<0-1>,\"needs_expert_review\":<true|false>,\"reasoning\":\"<max 2 sentences>\"}. Reply with JSON only."
  User message: the case_text plus the allowed decisions.
  On lookup: append the knowledge text (or "Unknown topic") as the next user message. On final: stop. Max 5 turns; otherwise decision="INVALID", error="max_turns".
- Parse JSON defensively (strip markdown fences, take the first {...}). Decision not allowed -> "INVALID".
- Record the full transcript as JSON text.

STEP 5 - RUNNER: run_agent.py
- Args: --models "openai:MODEL,anthropic:MODEL,google:MODEL", --runs (default 3), --limit N, --mock (fake model: random lookups then random final; no keys needed), --out (default data/results.csv).
- Startup: run validation; for real runs check each needed key in .env is non-empty (name the missing variable; never print values); print planned items and estimated calls.
- Retry rate-limit/server errors with exponential backoff (max 5); on final failure record the error and continue.
- 4 worker threads per provider, providers in parallel. Append each result immediately (thread-safe). Resume: skip rows already done (key: provider, model, case_id, wording_id, run). Progress line every 25 items.
- Output columns: timestamp, provider, model, case_id, device_category, wording_id, wording_style, run, decision, confidence, needs_expert_review, reasoning, n_turns, tools_used (pipe-separated), input_tokens, output_tokens, latency_s, error, transcript.
- Do NOT store expected answers or correctness in results; scoring happens at analysis time.

STEP 6 - METRICS: metrics.py
- load_scored(results_path, cases_path="data/test_cases.csv"): joins results with the CURRENT test cases on case_id, then computes is_correct (decision == expected_decision) and is_acceptable (is_correct OR (difficulty == borderline AND decision in acceptable_alternatives AND needs_expert_review is true)). Editing test_cases.csv later must change scores without re-running.
- Per model (and per device_category): accuracy %, acceptable %, consistency % (share of cases where the model gave exactly one distinct decision across all wordings and runs; exclude INVALID/error rows and report how many were excluded), borderline escalation %, invalid/error %, under-reporting rate (expected REPORTABLE_30DAY but decided NOT_REPORTABLE), over-reporting rate (expected NOT_REPORTABLE but decided REPORTABLE_30DAY), cave-in rate (accuracy W1 minus accuracy W5), average turns, lookup frequency by topic, agreement with actual_filing for MAUDE-sourced cases.
- Lists: confident-but-wrong rows (wrong, confidence >= 0.8) and confident-but-inconsistent cases (more than one decision, mean confidence >= 0.8).

STEP 7 - DASHBOARD: app.py (Streamlit + plotly)
- Loads data/results.csv (file uploader alternative) and data/test_cases.csv. Sidebar filters: model, device_category, difficulty, wording_style, source_type. All views respect filters; clear message on empty data.
- Tabs:
  1 "Report Card": per model accuracy, acceptable, consistency, borderline escalation, under-reporting, over-reporting, invalid %, with units.
  2 "Consistency": heatmap model x case colored by number of distinct decisions; accuracy by wording_style per model.
  3 "Leading Questions": W1 vs W5 accuracy per model, labeled cave-in rate; split by direction (W5 pushing toward under-reporting vs over-reporting, inferred from expected_decision).
  4 "Agent Behavior": lookup topic frequency per model, average turns, whether using lookups correlates with accuracy.
  5 "Danger Zone": confident-but-wrong and confident-but-inconsistent tables with case_text, reasoning, and source_url link.
  6 "Case Explorer": pick a case; show title, source link, actual filing, expected decision, rationale, a grid of decisions per model x wording x run, and an expander to read any transcript.

STEP 8 - README.md
Problem, what it measures, data sources (FDA MAUDE via openFDA and public consumer reviews, de-branded and paraphrased, intake facts only), setup, commands, how scoring works (answer key applied at analysis time), limitations (40 cases, single-expert draft labels, knowledge base gives the agent guidance, models via API).

STEP 9 - VERIFY (do not skip)
1. python validate_data.py (must pass: 40 cases, 200 wordings).
2. python run_agent.py --mock --runs 2 --out data/mock_results.csv
3. pytest tests covering: consistency 100% vs 0%; is_acceptable borderline rule; under/over-reporting; cave-in; scoring changes when test_cases.csv expected_decision changes (use a temp copy, never edit the real file); agent loop lookup->final, unknown topic, max_turns -> INVALID; JSON parsing with fences and extra text.
4. Print the Report Card from data/mock_results.csv.
5. Launch streamlit headless for 10 seconds on the mock results to confirm no errors.

FINAL REPORT: files created, test results, issues fixed, and exact commands for (a) smoke test with real models: --limit 5 --runs 1, (b) full run: --runs 3, (c) dashboard.
```

## Prompt 2 — Compare three Claude model sizes

```text
Switch the experiment to Anthropic models only, comparing three sizes: anthropic:claude-haiku-5-5, anthropic:claude-sonnet-5-5, anthropic:claude-opus-5-5.
1. Make the thread pool per MODEL, not per provider (3 workers per model), so the three Claude models run in parallel. Keep backoff for 429/529 errors.
2. Update README and default commands to these three models. Keep the openai and google adapters in the code but unused.
3. Delete data/results.csv, then run a smoke test with real calls: python run_agent.py --models "anthropic:claude-haiku-5-5,anthropic:claude-sonnet-5-5,anthropic:claude-opus-5-5" --limit 5 --runs 1
4. If a model name is rejected, report the exact error and try the closest valid Claude model name from the Anthropic API models list.
5. Run pytest. Report a table: model, rows, errors, invalid, average turns, average latency.
```

## Prompt 3 — Add the 2×2 agent-variant experiment

```text
Add AGENT VARIANTS as a 2x2 design, all using the SAME model (anthropic:claude-haiku-5-5). Do not delete or modify existing rows in data/results.csv.

Add --variant to run_agent.py and a "variant" column to results, with also "prompt_style" (zero_shot or cot) and "rag" (yes or no) columns. Backfill existing rows as variant=V2_zeroshot_rag, prompt_style=zero_shot, rag=yes. Include variant in the resume key.

The four variants (keep the same output JSON for all: decision, confidence, needs_expert_review, reasoning):
- V1_zeroshot_norag: Zero-shot prompt, no lookup tool, no knowledge. System prompt: "You are a complaint-triage agent for a medical device manufacturer's quality team. Decide FDA reportability: REPORTABLE_30DAY, NOT_REPORTABLE, or ESCALATE (when expert judgment is needed). Reply with JSON only: {\"action\":\"final\",\"decision\":...,\"confidence\":...,\"needs_expert_review\":...,\"reasoning\":\"<max 2 sentences>\"}." Max 1 turn; a lookup reply counts as INVALID.
- V2_zeroshot_rag: the CURRENT agent exactly as it is now (zero-shot prompt + lookup tool + knowledge.json). Do not change it.
- V3_cot_norag: Chain-of-thought prompt, no lookup tool, no knowledge. Same as V1 plus: "Think step by step before deciding. In the reasoning field, work through: 1) Did a death or serious injury occur, or could one have? 2) Did the device fail to perform as intended? 3) If the malfunction recurred, would it be likely to cause or contribute to death or serious injury? 4) Is key information missing or disputed? Then give your decision." Allow reasoning up to 8 sentences. Max 1 turn.
- V4_cot_rag: V2 (current agent with lookup tool + knowledge.json) plus the same chain-of-thought instruction as V3. Max 5 turns.

Also:
1. metrics.py: compute every metric per model AND variant.
2. app.py: new FIRST tab "Agent Variants" showing the 2x2 grid for the selected model: accuracy, consistency, under-reporting, over-reporting, borderline escalation, cave-in rate (W1 vs W5), average turns, tokens, latency. Add charts: prompt effect (zero-shot vs CoT) and RAG effect (no vs yes). Keep a "Model Size" view for haiku/sonnet/opus on V2 with a note that sonnet and opus have partial data.
3. Put all four system prompts in one clearly labeled section at the top of agent.py (PROMPTS dictionary) so they are easy to read and screenshot.
4. Tests for variant backfill, resume with variant, and no-RAG variants rejecting lookups. Run pytest.
5. Real smoke test only: --limit 5 --runs 1 for V1, V3, V4 on claude-haiku-5-5. Report errors and invalids per variant.
6. Do NOT start full runs. Print the three full-run commands (--runs 3) for me.
```

## Prompt 4 — Turn the dashboard into Story and Explore

```text
Redesign app.py as a story-driven, intuitive dashboard with minimal text. Do NOT change metrics.py calculations, data files, or results. You may add a viz_data.py with helper aggregations. Only streamlit, plotly, pandas. Score each test by its latest attempt.

STRUCTURE: two pages via st.sidebar radio: "Story" (default) and "Explore".

DESIGN RULES
- Wide layout. Minimal text: each chapter = a short headline that states the finding (computed from data, not hard-coded), one chart, and at most one caption line. Put any detail in a collapsed st.expander("Details").
- Plain-English labels only (e.g. "Haiku: zero-shot, no retrieval"), percentages to 1 decimal with %.
- One fixed colorblind-safe color per configuration across every chart. Highlight the configuration a chapter is about in color and grey the others.
- Clean charts: no gridline clutter, direct labels on data instead of legends where possible, chart titles that are statements.

STORY PAGE (fixed data, no filters), chapters in this order:
0. Hero: title "Can you trust an AI agent with FDA reportability decisions?", one-line subtitle, and 4 st.metric cards: tests scored, best accuracy, best consistency, under-reporting rate across all tests.
1. "Bigger model beats better prompt": SCATTER of all 6 configurations (Haiku V1-V4, Sonnet V2, Opus V2), x = accuracy %, y = consistency %, bubble size = average tokens per decision, labeled directly. Add a shaded "ready for unsupervised use" target zone (accuracy >= 95%, consistency >= 95%) that no configuration reaches.
2. "What each design choice adds": WATERFALL chart for Haiku: V1 accuracy -> + retrieval instructions (V2 - V1) -> + chain of thought (V4 - V2) -> V4 accuracy. Include a small 2x2 grid of four metric tiles (accuracy per variant) beside it.
3. "Agents rarely give the same answer twice": 100% STACKED HORIZONTAL BAR per configuration showing the share of cases with 1, 2, or 3 distinct decisions across all 15 attempts (stable / wavering / all over the place).
4. "When agents are wrong, they over-call, never under-report": SANKEY diagram from expected decision (left) to agent decision (right) for a configuration chosen with a small selectbox (default Opus V2). Color correct flows green, over-calls amber, under-reporting red.
5. "Leading questions barely move them": SLOPE CHART per configuration from neutral wording (W1) accuracy to leading wording (W5) accuracy.
6. "Reliability costs time and tokens": DOT/LOLLIPOP chart of average latency (s) and tokens per configuration.
7. "What the bigger models looked up": TREEMAP of lookup topics used, by model (only configurations that used lookups).
8. Bottom line: 3 short bullet takeaways computed from data, then a one-sentence recommendation: "Use as AI-assisted triage with human review, not unsupervised."

EXPLORE PAGE (sidebar filters: model, variant, device category, difficulty, wording style, source type, with a Reset button):
- KPI cards row for the filtered data.
- Tabs: "Danger Zone" (confident-but-wrong table, compact, with source links), "Case Explorer" (pick a case: complaint text in a bordered box, expected answer + rationale, and a compact grid of decisions per configuration x wording x run with cells colored green correct / amber acceptable / red wrong; transcripts in an expander), "Full metrics" (the existing report card table).
- Clear message when filters return no data.

Then run pytest and launch streamlit headless for 10 seconds to confirm no errors. Report what you built.
```

## Prompt 5 — Explain the experiment and fix overlapping charts

```text
Make the Story page understandable to someone who knows nothing about this project, and fix every overlap. Do NOT change metrics.py calculations or data. Keep the COLORS dict and light theme.

A. ORIENTATION (top of Story, before any chart)
1. Title + one sentence: "We tested whether AI agents give the same, correct answer when a medical device complaint must be judged for FDA reporting."
2. "How the test works" strip: 3 icon cards in a row: "40 real complaints (FDA reports + consumer reviews)" -> "Each written 5 ways, asked 3 times" -> "6 agent setups compared". Short text only.
3. "Meet the 6 agents" row of small cards with plain names and one line each: "Haiku · simple prompt", "Haiku · simple + rulebook", "Haiku · step-by-step", "Haiku · step-by-step + rulebook", "Sonnet · simple + rulebook", "Opus · simple + rulebook". Use these plain names in EVERY chart, legend and table instead of variant codes. ("Rulebook" = the regulatory lookup tool.)
4. A collapsed "What the measures mean" glossary: Accuracy (matches the expert answer), Consistency (same answer on all 15 tries), Under-reporting (missed a reportable event: the dangerous error), Over-calling (reported something that did not need it), Escalation (asked a human expert).

B. FILTERS
5. Default every filter to "All" on load, with only one option visibly selected per group. When the filtered data has fewer than 300 tests, show a yellow banner "Small sample (n = X): results may not be representative" and phrase headlines neutrally (no "beats"/"leads" claims).
6. Never show "—": if a metric cannot be computed, show "n/a" with a short reason in the caption (e.g. "no reportable cases in this filter").

C. CHART FIXES (no overlapping text anywhere; use hover for long labels)
7. Compare configurations: remove stripe patterns. Plain grouped horizontal bars, legend placed below the chart (orientation horizontal), chart title separate from legend, value labels outside bars, x-axis 0-100% for percentage metrics. Left margin wide enough for full plain names.
8. Scatter: compute axis ranges from the data with 10-point padding so no bubble is clipped; cap bubble size; short labels with leader lines placed to avoid collisions; keep the 95% target zone visible (extend range to 100%) and labeled inside.
9. Waterfall: replace the four truncated tiles with a clean 2x2 table (rows: simple / step-by-step, columns: no rulebook / rulebook, cells = accuracy %) shown under the waterfall, full width, readable.
10. Stability chart: labels only when segment is wide enough; otherwise hover. Use white label text only on dark segments, dark text on light ones.
11. Replace the Sankey with a clear "What kind of mistakes?" view for the selected agent: a horizontal 100% stacked bar per expected answer (Reportable / Not reportable / Needs expert), segments colored by outcome: Correct (green #16A34A), Asked an expert instead of deciding (blue #3B82F6), Over-called (amber #F59E0B), Under-reported (red #DC2626), Decided when expert was needed (purple #8B5CF6). Legend as colored chips above the chart. Headline in plain English, e.g. "When Opus is wrong, it usually asks an expert instead of deciding."
12. Replace the slope chart with a dumbbell chart: one row per agent, dot at neutral-wording accuracy and dot at leading-wording accuracy, connected by a line, labels on the left only.
13. Replace the treemap with a simple horizontal bar chart of rulebook topics looked up, one small chart per model that used lookups, plain topic names.
14. Every chart: height fixed per chart type, margins set so titles, legends and labels never overlap; font 13px for labels.

D. END
15. "What this means for the quality team": 3 plain-English takeaways with icons and one recommendation, computed from the unfiltered data so it never contradicts the main story.

Then run pytest, launch streamlit headless for 10 seconds, and if playwright is available, screenshot the Story page at 1440px width and check for errors. Report what you changed.
```

## Prompt 6 — Compact the Story layout and add animation

```text
Final Story page redesign: compact layout, explanations, and animation. Do not change metrics.py calculations or data.

1. LAYOUT (cut white space)
- Use a 2-column grid: place charts side by side in pairs with st.columns(2, gap="medium"): [Accuracy vs consistency scatter | Answer stability bar], [Prompt & rulebook waterfall + 2x2 table | Mistake types], [Leading questions dumbbell | Time & cost lollipop]. Keep "Compare configurations" full width at the top.
- Put "How the test works" and "Meet the 6 agents" on one row each with compact cards; reduce vertical padding (custom CSS: block-container padding-top 1rem, smaller gaps between elements, chart heights 320-380px). Every chart uses use_container_width=True so nothing is cropped.

2. EXPLAIN EVERY CHART (above each chart, inside a light card)
- Bold one-line title as a question (e.g. "Does the agent give the same answer every time?").
- Two short lines with icons: "📊 What it shows: ..." and "💡 Why it matters: ..." in plain English for a non-expert (e.g. "A complaint team needs the same decision no matter who writes the complaint; wavering answers mean unpredictable compliance").
- A computed one-line takeaway in a colored pill (green if good, amber if concerning) with the actual number from the filtered data.

3. ANIMATION (plotly built-in animation, smooth transitions)
- Scatter "Accuracy vs consistency": animation_frame = wording style (Neutral record -> Informal -> Shorthand -> Reordered -> Leading), so viewers watch each agent move as the complaint wording changes; play/pause button and slider; fixed axis ranges; transition duration 600ms.
- Compare configurations bar chart: animation_frame = repeat run (Run 1 -> Run 2 -> Run 3) showing how accuracy shifts between identical repeats, with a play button; plus a static "All runs" default view.
- Stability bar: animate bars growing in on load (frames from 0 to final values).
- KPI cards: a short count-up animation on first load using st.empty with a quick loop (under 1 second total), skipped on reruns via st.session_state.

4. FIXES
- Leading-questions dumbbell is empty ("trace 0..5"): fix it (circle = neutral W1 accuracy, diamond = leading W5 accuracy, grey connector, values labeled, no legend).
- Remove the Haiku rulebook chart; show text "Haiku never used the rulebook (0 lookups)". Keep Sonnet and Opus lookup bars side by side.
- Scatter: no leader lines; short labels next to bubbles.
- Stability legend: distinct colors per segment (Stable = agent color, Wavering = tint, All over the place = light grey) with matching legend chips.
- Mistake types: percentage labels on segments plus a caption with the share of each mistake type.

Run pytest and launch streamlit headless for 10 seconds; fix errors. Report changes.
```

## Prompt 7 — Build the Agent Report Room

```text
Redesign the Story page into a one-screen "Agent Report Room" (fits a 1440x900 laptop screen without scrolling). Keep metrics.py, data, COLORS, light theme, filters, and the Explore page. Plain agent names everywhere.

TOP BAR (compact): title "Can you trust an AI agent with FDA reportability?", filter pills (device, difficulty, source), 4 KPI cards each showing the value AND the agent that achieved it (e.g. "80.7% · Sonnet · simple + rulebook").

ROW 1 — AGENT REPORT CARDS: 6 cards in one row, sorted by accuracy. Each card: agent name, two plotly Indicator gauges styled as rings (accuracy %, consistency %) that animate from 0 to value on first load (transition 800ms), "⏱ X.X s per decision", and a 🏆 badge on the most accurate and a 🔁 badge on the most consistent.

ROW 2 (3 tiles):
(a) "Watch it change its mind" (signature visual): case selector defaulting to the case with the most distinct decisions. Dot matrix: rows = 6 agents, columns = 15 attempts (W1-W5 x runs 1-3), large dots colored by decision (Report = indigo, Not reportable = teal, Ask an expert = amber, Invalid = grey), with a ✓ ring on dots matching the expert answer. Plotly animation frames reveal dots column by column with a play button (300ms per step). Expert answer shown above the grid.
(b) "Does wording move the agents?": animated bubble chart, x = accuracy, y = consistency... (compute consistency per wording as share of cases with one answer across its 3 runs), animation_frame = wording W1->W5, trails of previous positions, shaded green safe zone (>=95% both), fixed axes, play button, 600ms transitions.
(c) "Out of 100 decisions": agent selector; 10x10 square pictogram (unit chart) filled in order by outcome: correct green, asked an expert instead of deciding blue, over-called amber, decided when expert needed purple, under-reported red; animate filling on change; counts shown as large numbers beside it.

ROW 3 (3 tiles):
(d) "How many complaints get a stable answer?": waffle chart per agent, 40 small squares (one per complaint): green = one answer every time, amber = two answers, red = three answers.
(e) "Wording fingerprint": plotly radar (Scatterpolar), 5 axes = wording styles, value = accuracy, one shape per agent in its color, legend toggles agents; caption "a perfect circle = not affected by wording".
(f) "What do the prompt and rulebook add?": 2x2 tile matrix (rows simple / step-by-step, columns no rulebook / rulebook) colored on a green scale by accuracy, big numbers in tiles, arrows between tiles labeled with the point gain.

EVERY TILE: one-line question title, one takeaway pill computed from data, and an "⤢ Expand" button that opens st.dialog (fallback: st.expander) with a full-size version, two lines "What it shows / Why it matters", and the underlying data table. No other text on the main screen.

STYLE: tile cards with white background, subtle shadow, 12px radius; compact padding; chart heights ~230px in tiles; fonts 12-13px; no overlapping labels; all charts use_container_width.

Run pytest, launch headless for 10 seconds, fix errors, report what you built.
```

## Prompt 8 — Apply the dark theme and independent autoplay

```text
Update the "Agent Report Room" dashboard in app.py (and .streamlit/config.toml). Make only these 3 changes and keep everything else (data, metrics, layout order, tiles, filters, Explore page) exactly as is.

1) DARK THEME (more visible)
- .streamlit/config.toml: base="dark", backgroundColor="#0B1220", secondaryBackgroundColor="#111A2E", textColor="#E2E8F0", primaryColor="#38BDF8".
- In the CSS: page background #0B1220; tiles/cards background #111A2E, border 1px #1F2A44, radius 12px; titles #F1F5F9; captions and labels #94A3B8; filter pills dark (#1A2540) with the active pill in #38BDF8 and dark text.
- All Plotly figures: template "plotly_dark", paper_bgcolor and plot_bgcolor "rgba(0,0,0,0)", gridlines #1F2A44, font color #E2E8F0.
- Re-check the agent colors so they stand out on dark: use bright, distinct colors (for example Haiku #38BDF8, Sonnet #A78BFA, Opus #F472B6, plus their variants as lighter/darker shades). Correct = #34D399, wrong = #F87171, escalate = #FBBF24. Ring gauge tracks #1F2A44.
- Every piece of text must be readable on dark (no dark grey on navy).

2) REMOVE WHITE SPACE
- Set block-container padding-top 0.6rem, padding-bottom 0.5rem, left/right 1rem; max-width 100%.
- Column gap "small"; tile inner padding 10px; reduce the vertical margins between rows to about 8px.
- Hide Streamlit's header/footer/menu chrome.
- Increase chart heights so the 3 rows plus the top bar fill a 1440x900 screen with no empty area at the bottom: about 150px for the agent cards row and about 300px for each chart in rows 2 and 3. Plotly margins: l=8, r=8, t=28, b=8.
- Remove any empty st.write("")/spacer elements and any empty containers.

3) ANIMATIONS: ALWAYS PLAYING, PAUSE ONLY
Apply this to every tile that currently has play/pause controls ("Watch it change its mind" dot matrix and the "Does wording move the agents?" bubble chart, plus any other animated tile):
- Remove the Plotly play/pause buttons, sliders and updatemenus.
- Wrap each animated tile in its own @st.fragment(run_every=1.2) so it moves to the next frame by itself every 1.2s and loops forever. Store the frame index in st.session_state per tile, so other tiles don't rerun.
- Show one small "⏸ Pause" button in the tile header. When it is pressed: stop the animation and jump to the FINAL ANSWER view:
  - dot matrix: show all 15 attempts filled in for the selected case, with a one-line verdict on top, e.g. "Final: Opus said REPORTABLE 11/15, ESCALATE 4/15 → inconsistent".
  - bubble chart: show the overall position of every agent (all wordings combined) and a one-line verdict, e.g. "Final: wording moves Haiku the most (−X pts W1→W5)".
- While paused, the same button shows "▶ Resume" and resuming continues the loop.
- While playing, show a small label with the current frame (for example "Wording W3 of 5" or "Attempt 7 of 15").
- If st.fragment is not available in the installed Streamlit version, upgrade streamlit in requirements.txt to a version that supports it.

When done:
- Run pytest (all tests must pass) and start the app headless to confirm there are no errors.
- Do not touch data/, .env, or the results files.
- Show me a short list of what changed.
```

## Prompt 9 — Enlarge the tiles and preserve navigation filters

```text
Polish app.py (Report Room page and Explore page). Keep data, metrics, filters, KPI cards, agent cards, colors and dark theme unchanged.

1) LAYOUT: 2 CHARTS PER ROW, BIGGER, SCROLLING IS FINE
- Keep the top bar, filters, KPI cards and the 6 agent cards row as they are.
- Below them, place the 6 chart tiles in a 2-column grid (3 rows x 2 charts), in this order:
  Row A: "Watch it change its mind" | "Does wording move the agents?"
  Row B: "What happens out of 100 decisions?" | "How many complaints get a stable answer?"
  Row C: "What is each agent's wording fingerprint?" | "What do the prompt and rulebook add?"
- Each chart height ~450px; tiles in the same row equal height. Page may scroll; no large empty area at the end (bottom padding max 1rem).

2) HEADING + EXPLANATION ABOVE EVERY CHART
At the top of each tile, show: a bold title (16px, #F1F5F9), then one line "What it shows" and one line "Why it matters" (13px, #94A3B8). Use this text:
- Watch it change its mind
  What: the same complaint worded 5 ways, 3 attempts each; each dot is one decision (green = correct, red = wrong, amber = escalated).
  Why: a compliance decision should not change because someone phrased the complaint differently.
- Does wording move the agents?
  What: each bubble is an agent; it moves as we switch wording W1 to W5 (x = accuracy, y = consistency).
  Why: shows which agents are stable and which drift with wording style.
- What happens out of 100 decisions?
  What: for the selected agent, how 100 decisions break down (correct, escalated, over-called, under-reported, invalid).
  Why: under-reporting is the costly FDA risk; this shows how often it happens.
- How many complaints get a stable answer?
  What: each column is a complaint; green = same answer all 15 times, amber = the answer changed.
  Why: inconsistency means the outcome depends on luck, which an auditor will not accept.
- What is each agent's wording fingerprint?
  What: accuracy per wording style for each agent; a round, full shape = not affected by wording.
  Why: reveals which wording styles (shorthand, leading, informal) trick each agent.
- What do the prompt and rulebook add?
  What: Haiku accuracy across the 2x2 design (simple vs step-by-step prompt, with vs without rulebook); arrows show the gain.
  Why: shows whether agent design improves a small model, separate from model size.

3) SMALL CHART FIXES
- Bubble chart: use the full tile; x-axis 40-100%, y-axis 0-100; remove the stray teal bar/shape at top right; trails thin and faint (opacity 0.3); label each bubble with the agent short name.
- Stable-answer tile: add a small legend "green = same answer all 15 times, amber = changed" and x-axis title "Complaints".
- Radar: fill the tile; hide the radial tick labels (50/100).
- Waffle legend: rename "Asked an expert" to "Escalated (correct)" and "Should ask an expert" to "Missed escalation".
- Replace the brown banner background with dark teal (#0E3A4A), text #E2E8F0. Keep the green banner.
- Keep the autoplay + Pause/Resume behavior and the Expand buttons.

4) NAVIGATION BACK FROM EXPLORE
- Add a clear "← Back to Report Room" button at the top of the Explore page that returns to the main dashboard (use st.session_state page switching or st.switch_page / st.navigation, whichever the app already uses). Also keep a sidebar/top nav with both pages so the user can switch either way at any time.
- Make sure the filters keep their values when switching pages.

When done: run pytest (all pass), run a headless check of both pages, and list what changed. Do not touch data/, .env, or results files.
```

## Prompt 10 — Record expert-reviewed answer labels

```text
In data/test_cases.csv, change every label_status value from DRAFT to EXPERT_REVIEWED. Add a column reviewed_by with the value "Sal (ISO 13485 Lead Auditor, SaMD compliance)" for all rows. Update validate_data.py, tests, README.md and any app text so that EXPERT_REVIEWED is an accepted status and nothing says "draft" anymore. Do not change any expected_decision, acceptable_alternatives or other values. Run pytest and validate_data.py.
```
