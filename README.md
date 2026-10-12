# QMS Complaint Agent Consistency Kit

Can you trust an AI agent with FDA reportability? Same complaint, 5 wordings, 3,600 scored decisions.

[Demo video](<LOOM_LINK>) | [Project doc](<DOC_LINK>)

![Agent Report Room: six complaint-triage agents compared](screenshots/01_report_room.png)

## The problem

Medical device manufacturers must assess complaints for FDA reportability: qualifying deaths, serious injuries, and malfunctions must be reported within 30 calendar days of awareness under [21 CFR 803.50](https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-803/subpart-E/section-803.50). AI agents are being proposed for complaint triage. A decision that changes when the same complaint is reworded is not acceptable in a regulated quality management system (QMS). This kit measures **accuracy and consistency** together.

## What it tests

The dataset contains **40 real-world complaints**: 20 pulse oximetry cases and 20 glucose meter cases. Sources are FDA MAUDE reports accessed through openFDA and public consumer reviews; complaints are de-branded and paraphrased, preserving intake facts only.

| Wording | Style |
| --- | --- |
| W1 | Neutral record |
| W2 | Informal |
| W3 | Shorthand |
| W4 | Reordered |
| W5 | Leading question |

Each wording is asked **3 times**: 40 complaints × 5 wordings × 3 repeats × 6 agents = **3,600 scored tests**. Each agent chooses `REPORTABLE_30DAY`, `NOT_REPORTABLE`, or `ESCALATE` when expert judgment is needed.

All answer labels are `EXPERT_REVIEWED` by **Sal (ISO 13485 Lead Auditor, SaMD compliance)**. The answer key records the reviewer, rationale, source, and acceptable alternatives for borderline cases.

## Experiment design

Four Haiku configurations form a **2×2 design**: simple versus step-by-step prompting (CoT), with versus without a rulebook. The rulebook is a retrieval (RAG) lookup tool backed by `data/knowledge.json`. Sonnet and Opus use the same simple + rulebook setup for the model-size comparison.

| Agent | Model identifier | Variant | Prompt | Rulebook | Turn limit |
| --- | --- | --- | --- | --- | --- |
| Haiku · simple prompt | `claude-haiku-5-5` | `V1_zeroshot_norag` | Simple | No | 1 |
| Haiku · simple + rulebook | `claude-haiku-5-5` | `V2_zeroshot_rag` | Simple | Yes | 5 |
| Haiku · step-by-step | `claude-haiku-5-5` | `V3_cot_norag` | Step-by-step | No | 1 |
| Haiku · step-by-step + rulebook | `claude-haiku-5-5` | `V4_cot_rag` | Step-by-step | Yes | 5 |
| Sonnet · simple + rulebook | `claude-sonnet-5-5` | `V2_zeroshot_rag` | Simple | Yes | 5 |
| Opus · simple + rulebook | `claude-opus-5-5` | `V2_zeroshot_rag` | Simple | Yes | 5 |

The agent loop is provider-independent:

- The agent replies with JSON: a `lookup` action requests a rulebook topic; a `final` action supplies the decision, confidence, expert-review flag, and reasoning. Lookup text is returned as the next user message.
- Rulebook agents have at most **5 turns**. Agents without the rulebook must finish in **1 turn** and cannot request lookups. All four system prompts are collected at the top of `agent.py`.
- Malformed responses, disallowed decisions, forbidden lookups, exhausted turns, and terminal API errors are recorded as invalid/error results. Full transcripts are retained for inspection.

## Results

The table below was generated from the current `data/results.csv` using `metrics.load_scored()` and `metrics.report_card()`. Each agent has **600 scored tests**. For duplicate test keys, scoring keeps the latest stored attempt; historical attempts are not added to the denominator. The current answer key is applied at analysis time, so changing labels changes scores without rerunning agents.

| Agent | Accuracy | Consistency | Under-reporting | Over-reporting | Invalid/error rate | Seconds per decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sonnet · simple + rulebook | 80.7% | 52.5% | 0.0% | 0.0% | 0.8% | 8.7 s |
| Opus · simple + rulebook | 78.7% | 77.5% | 0.0% | 0.0% | 0.0% | 10.5 s |
| Haiku · step-by-step + rulebook | 64.2% | 20.0% | 0.0% | 0.0% | 0.0% | 5.2 s |
| Haiku · simple + rulebook | 61.7% | 22.5% | 0.0% | 0.0% | 0.0% | 3.6 s |
| Haiku · simple prompt | 53.7% | 20.0% | 0.0% | 0.0% | 4.3% | 3.4 s |
| Haiku · step-by-step | 52.0% | 25.0% | 0.0% | 0.0% | 3.3% | 5.2 s |

Consistency excludes invalid/error attempts. Excluded rows: **26** for Haiku · simple prompt, **20** for Haiku · step-by-step, and **5** for Sonnet; none for the other setups. No complaint was excluded entirely. A consistent answer can still be wrong.

### Reference values

These values describe the included results snapshot; new API runs can vary.

- **3,600 tests scored**, with 600 per agent.
- **Sonnet:** 80.7% accuracy / 52.5% consistency.
- **Opus:** 78.7% accuracy / 77.5% consistency.
- **Haiku · step-by-step + rulebook:** 64.2% accuracy.
- **Haiku · simple prompt:** 53.7% accuracy.
- **Under-reporting:** 0.0% for every agent, on reportable cases in this dataset.

Recompute the complete report card locally:

```bash
python metrics.py data/results.csv
```

## Key findings

- **Model size mattered more than agent design in this experiment.** Sonnet reached 80.7% accuracy and Opus 78.7%, compared with 64.2% for the strongest Haiku setup.
- **The rulebook-enabled prompt helped Haiku, despite almost no retrieval.** Accuracy rose 8.0 percentage points with the simple prompt and 12.2 points with step-by-step prompting. Haiku made just **2 lookup calls** across its two rulebook setups, both in the simple + rulebook setup. This is an observed configuration effect; it does not establish that retrieved knowledge caused the gain.
- **Step-by-step reasoning had no consistent effect.** It changed Haiku accuracy by -1.7 points without the rulebook and +2.5 points with it.
- **No agent under-reported in the scored sample.** The measured rate was 0.0% for all six agents. Escalations and invalid responses are separate outcomes; zero under-reporting does not mean every reportable case was correctly classified.
- **Consistency is the gap.** Even Opus, the most consistent agent at 77.5%, changed its answer on **22.5% of complaints**—about one in four—among valid attempts.

**Business takeaway: use AI-assisted triage with mandatory human review, not autonomous reportability decisions.**

## Dashboard

The **Agent Report Room** compares all six agents, with live device, difficulty, source, and wording filters. Tiles autoplay independently; Pause reveals their final view, and Expand opens a larger chart with explanations and underlying data. **Explore** provides confident-but-wrong cases, source links, decision grids, transcripts, and full metrics. Filters persist when switching pages.

<table>
  <tr>
    <td width="50%"><img src="screenshots/02_change_its_mind.png" alt="Decision matrix for one complaint across agents and attempts" width="100%"/><br/>Same complaint, 15 attempts: answers change.</td>
    <td width="50%"><img src="screenshots/03_wording_bubbles.png" alt="Agent accuracy and consistency across wording styles" width="100%"/><br/>How wording moves each agent.</td>
  </tr>
  <tr>
    <td width="50%"><img src="screenshots/04_out_of_100.png" alt="Outcome distribution represented as 100 squares" width="100%"/><br/>What happens out of 100 decisions.</td>
    <td width="50%"><img src="screenshots/05_stable_answers.png" alt="Stable and changing answers for each complaint and agent" width="100%"/><br/>How many complaints get a stable answer.</td>
  </tr>
  <tr>
    <td width="50%"><img src="screenshots/06_fingerprint_2x2.png" alt="Wording fingerprint and Haiku prompt and rulebook comparison" width="100%"/><br/>Wording fingerprint and prompt/rulebook gains.</td>
    <td width="50%"></td>
  </tr>
</table>

## How to run

### Set up

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add `ANTHROPIC_API_KEY` to your local `.env`. Keep keys private; `.env` is ignored. If `.env` already exists, retain it instead of copying over it.

```bash
python validate_data.py
```

### Run the four Haiku variants

These commands make real API calls and resume completed test keys, including the variant identifier.

```bash
python run_agent.py --models "anthropic:claude-haiku-5-5" --variant V1_zeroshot_norag --runs 3
python run_agent.py --models "anthropic:claude-haiku-5-5" --variant V2_zeroshot_rag --runs 3
python run_agent.py --models "anthropic:claude-haiku-5-5" --variant V3_cot_norag --runs 3
python run_agent.py --models "anthropic:claude-haiku-5-5" --variant V4_cot_rag --runs 3
```

Model-size comparison:

```bash
python run_agent.py --models "anthropic:claude-sonnet-5-5,anthropic:claude-opus-5-5" --variant V2_zeroshot_rag --runs 3
```

For a small smoke test, add `--limit 5 --runs 1` in place of `--runs 3`. Each model has its own three-worker pool; rate-limit and server errors use backoff. Model identifiers are recorded explicitly and may depend on account availability.

### Test without API calls

Mock mode uses a synthetic random agent, needs no keys, and writes to a separate file:

```bash
python run_agent.py --mock --variant V4_cot_rag --runs 2 --out data/mock_results.csv
```

### Open the dashboard and run tests

```bash
streamlit run app.py
pytest
```

By default, the dashboard reads `data/results.csv`. To inspect mock results:

```bash
QMS_RESULTS_PATH=data/mock_results.csv streamlit run app.py
```

## Metric definitions

| Measure | Definition |
| --- | --- |
| Accuracy | Percentage of scored tests whose valid decision matches the expert answer. |
| Acceptable rate | Correct answers plus permitted alternatives on borderline cases, only when `needs_expert_review` is true and the result is valid. |
| Consistency | Percentage of complaints with exactly one distinct decision across available valid wordings and repeats; invalid/error rows and complaints with no valid attempt are excluded. Full coverage means 15 attempts per complaint. |
| Under-reporting | Percentage of expected `REPORTABLE_30DAY` tests answered `NOT_REPORTABLE`. |
| Over-reporting | Percentage of expected `NOT_REPORTABLE` tests answered `REPORTABLE_30DAY`. |
| Borderline escalation | Percentage of borderline tests answered `ESCALATE`. |
| Cave-in | W1 accuracy minus W5 accuracy, in percentage points. Positive means leading wording reduced accuracy; negative means it increased accuracy. |
| Invalid rate | Percentage of tests with an unrecognized/invalid decision or a non-empty error field. |

Metrics are computed per provider, model, and variant, with device-level breakdowns available. A filtered or incomplete run measures only observed tests. Empty eligible groups have no computable rate. Latency is the recorded mean seconds per decision; it can reflect provider conditions and retries as well as model behavior.

## Data quality checks

`data_utils.py` handles UTF-8 BOMs, trims cell whitespace, and drops fully empty rows and repeated header rows in memory. `validate_data.py` enforces:

- Exactly **40 rows with 40 unique case IDs**, with duplicate IDs identified.
- Exactly **five wordings per case**, containing W1–W5 once each; every wording refers to an existing case.
- The expected answer and every acceptable alternative are included in that case's allowed decisions.
- Every borderline case has `expect_uncertainty=Y`.
- Required `label_status` and `reviewed_by` columns; status must be `EXPERT_REVIEWED` and reviewer attribution must be non-empty.

Validation prints counts by device category, difficulty, expected decision, and source type. Failures identify the offending rows/cases and exit non-zero.

## Repo structure

```text
.
├── README.md                 # Project, findings, and reproduction guide
├── PROMPTS.md                # Main project-building prompts from the conversation
├── agent.py                  # System prompts, provider adapters, and JSON agent loop
├── variants.py               # Four agent variants and legacy-row backfill
├── run_agent.py              # Concurrent runner, retries, transcripts, and resume
├── data_utils.py             # Source CSV cleanup and loading
├── validate_data.py          # Dataset and expert-review metadata checks
├── metrics.py                # Current-answer-key scoring and report-card metrics
├── app.py                    # Dashboard entry point, filters, and Explore page
├── report_room.py            # Report Room tiles and independent autoplay
├── room_viz.py               # Report Room Plotly visualizations
├── viz_data.py               # Display labels, colors, and visualization aggregates
├── requirements.txt          # Python dependencies
├── .env.example              # Empty provider-key template
├── .gitignore                # Local secrets, environment, caches, and mock outputs
├── .streamlit/config.toml    # Dark dashboard theme
├── data/
│   ├── test_cases.csv         # Expert-reviewed answer key and source references
│   ├── wordings_cases.csv     # Five paraphrases per complaint
│   ├── knowledge.json        # Six regulatory lookup topics
│   └── results.csv           # Recorded attempts; scored when analyzed
├── screenshots/              # Dashboard captures for this README
└── tests/                    # Scoring, protocol, validation, and dashboard checks
```

## Limitations

- **40 cases and two device types:** results do not establish performance across medical devices or complaint populations.
- **One expert reviewer:** labels reflect a single ISO 13485 Lead Auditor's judgment, not independent multi-reviewer consensus or FDA determinations.
- **Claude-only reported experiment:** OpenAI and Gemini adapters exist, but quota constraints kept those providers out of the reported six-agent comparison.
- **Paraphrased real complaints:** inputs preserve intake facts, not full MAUDE narratives, investigations, or complete clinical records. Observed filing status is not an answer key by itself.
- **Supplied guidance and changing APIs:** prompt design, available rulebook topics, account conditions, and model versions affect the results. New runs may differ, and zero observed under-reporting does not demonstrate absence of risk.

## Built with

**Codex in VS Code · Python · Anthropic API · Streamlit · Plotly · pandas · pytest**

Data: **openFDA MAUDE + public consumer reviews**. No employer or confidential data.

See [PROMPTS.md](PROMPTS.md) for the main prompts used to build and refine the kit.
