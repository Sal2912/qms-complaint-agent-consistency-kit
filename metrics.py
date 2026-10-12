"""Apply the current answer key at analysis time; rates are percentages."""
import argparse
import pandas as pd
from data_utils import load_cases
from variants import backfill_variants

MODEL_KEYS = ['provider','model','variant']

def truth(value):
    return str(value).strip().lower() in {'true','1','yes'}

def score_results(results, cases):
    results = backfill_variants(results)
    attempt_key = ['provider','model','case_id','wording_id','run','variant']
    if all(column in results for column in attempt_key):
        results = results.drop_duplicates(attempt_key, keep='last')
    # Discard any historical scoring/label fields and category from results.
    frame = results.drop(columns=[x for x in cases.columns if x != 'case_id' and x in results.columns] + [x for x in ['is_correct','is_acceptable','invalid'] if x in results.columns])
    frame = frame.merge(cases, on='case_id', how='left', validate='many_to_one')
    if frame.expected_decision.isna().any():
        raise ValueError(f'Unknown case IDs: {frame.loc[frame.expected_decision.isna(), "case_id"].unique().tolist()}')
    frame['needs_expert_review'] = frame.needs_expert_review.map(truth)
    for column in ['confidence','n_turns','input_tokens','output_tokens','latency_s']:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors='coerce')
        else:
            frame[column] = float('nan')
    frame['total_tokens'] = frame.input_tokens + frame.output_tokens
    frame['error'] = frame.get('error', pd.Series('',index=frame.index)).fillna('')
    frame['tools_used'] = frame.get('tools_used',pd.Series('',index=frame.index)).fillna('')
    frame['invalid'] = ~frame.decision.isin(['REPORTABLE_30DAY','NOT_REPORTABLE','ESCALATE']) | frame.error.ne('')
    frame['is_correct'] = frame.decision.eq(frame.expected_decision) & ~frame.invalid
    alternative = frame.apply(lambda r: r.decision in str(r.acceptable_alternatives).split('|'), axis=1)
    frame['is_acceptable'] = frame.is_correct | (frame.difficulty.str.lower().eq('borderline') & alternative & frame.needs_expert_review & ~frame.invalid)
    return frame

def load_scored(results_path, cases_path='data/test_cases.csv'):
    results = pd.read_csv(results_path, keep_default_na=False)
    return score_results(results, load_cases(cases_path))

def pct(series):
    return round(100 * series.mean(), 2) if len(series) else float('nan')

def report_card(frame, by_device=False):
    keys = MODEL_KEYS + (['device_category'] if by_device else [])
    records = []
    for key, g in frame.groupby(keys, dropna=False):
        valid = g[~g.invalid]
        decisions = valid.groupby('case_id').decision.nunique()
        borderline = g[g.difficulty.str.lower().eq('borderline')]
        under = g[g.expected_decision.eq('REPORTABLE_30DAY')]
        over = g[g.expected_decision.eq('NOT_REPORTABLE')]
        w1, w5 = g[g.wording_id.eq('W1')], g[g.wording_id.eq('W5')]
        # Filing is observational: include manufacturer, distributor and voluntary MAUDE reports.
        maude_source = g.source_type.str.lower().str.contains('maude|mdr|voluntary_report|distributor_report', regex=True)
        filed = g.actual_filing.str.lower().str.contains('mdr filed|medwatch report|report.*filed', regex=True)
        maude = g[maude_source & filed]
        row = dict(zip(keys, key if isinstance(key,tuple) else (key,)))
        row.update({'rows':len(g),'accuracy %':pct(g.is_correct),'acceptable %':pct(g.is_acceptable),'consistency %':pct(decisions.eq(1)), 'consistency excluded rows':int(g.invalid.sum()),'consistency excluded cases':g.case_id.nunique()-valid.case_id.nunique(), 'borderline escalation %':pct(borderline.decision.eq('ESCALATE')),'under-reporting %':pct(under.decision.eq('NOT_REPORTABLE')),'over-reporting %':pct(over.decision.eq('REPORTABLE_30DAY')),'invalid/error %':pct(g.invalid),'cave-in (pp)':round(pct(w1.is_correct)-pct(w5.is_correct),2),'average turns':round(g.n_turns.mean(),2),'actual filing agreement %':pct(maude.decision.eq('REPORTABLE_30DAY')), 'actual filing rows':len(maude)})
        row.update(prompt_style=g.prompt_style.iloc[0],rag=g.rag.iloc[0],
                   **{'average input tokens':round(g.input_tokens.mean(),2),
                      'average output tokens':round(g.output_tokens.mean(),2),
                      'average total tokens':round(g.total_tokens.mean(),2),
                      'total tokens':g.total_tokens.sum(min_count=1),
                      'average latency (s)':round(g.latency_s.mean(),2)})
        records.append(row)
    return pd.DataFrame(records)

def lookup_frequency(frame):
    rows = []
    for _, r in frame.iterrows():
        for topic in r.tools_used.split('|'):
            if topic:
                rows.append({'provider':r.provider,'model':r.model,'variant':r.variant,'topic':topic})
    if not rows:
        return pd.DataFrame(columns=MODEL_KEYS + ['topic','lookups'])
    return pd.DataFrame(rows).groupby(MODEL_KEYS + ['topic']).size().reset_index(name='lookups')

def danger_tables(frame):
    wrong = frame[~frame.is_correct & frame.confidence.ge(.8)].copy()
    valid = frame[~frame.invalid]
    stats = valid.groupby(MODEL_KEYS + ['case_id']).agg(distinct_decisions=('decision','nunique'), mean_confidence=('confidence','mean')).reset_index()
    inconsistent = stats[stats.distinct_decisions.gt(1) & stats.mean_confidence.ge(.8)]
    details = frame.merge(inconsistent, on=MODEL_KEYS + ['case_id'])
    return wrong, details

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('results', nargs='?', default='data/results.csv')
    args = parser.parse_args()
    scored = load_scored(args.results)
    print(report_card(scored).to_string(index=False))
    print('\nBy device category:\n' + report_card(scored, by_device=True).to_string(index=False))
