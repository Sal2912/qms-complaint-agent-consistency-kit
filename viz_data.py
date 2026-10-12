"""Presentation-only aggregations; regulatory scoring lives in metrics.py."""
import pandas as pd
from metrics import score_results, report_card

COLORS = {
    'configurations': {
        ('claude-haiku-5-5','V1_zeroshot_norag'):'#0EA5E9',
        ('claude-haiku-5-5','V2_zeroshot_rag'):'#38BDF8',
        ('claude-haiku-5-5','V3_cot_norag'):'#2DD4BF',
        ('claude-haiku-5-5','V4_cot_rag'):'#BAE6FD',
        ('claude-sonnet-5-5','V2_zeroshot_rag'):'#A78BFA',
        ('claude-opus-5-5','V2_zeroshot_rag'):'#F472B6',
    },
    'outcomes': {'correct':'#34D399','acceptable':'#FBBF24','wrong':'#F87171','invalid':'#94A3B8'},
    'devices': {'pulse_oximetry':'#C4B5FD','glucose_meter':'#2DD4BF'},
    'mistakes': {'Correct':'#34D399','Asked an expert instead of deciding':'#38BDF8','Over-called':'#FBBF24','Under-reported':'#F87171','Decided when expert was needed':'#C4B5FD','Invalid response':'#94A3B8'},
    'text':'#E2E8F0', 'dark':'#F1F5F9', 'muted':'#94A3B8', 'border':'#1F2A44',
}
PALETTE = COLORS['configurations']

DECISIONS = {'REPORTABLE_30DAY':'Report within 30 days','NOT_REPORTABLE':'No report needed','ESCALATE':'Ask an expert','INVALID':'Invalid response'}
TOPICS = {'mdr_reportability':'Reporting rules','serious_injury':'Serious injury','malfunction':'Device malfunction','reportability_pitfalls':'Common reporting mistakes','not_reportable_examples':'When no report is needed','escalation':'When to ask an expert'}
VARIANT_LABELS = {'V1_zeroshot_norag':'Simple prompt','V2_zeroshot_rag':'Simple + rulebook','V3_cot_norag':'Step-by-step','V4_cot_rag':'Step-by-step + rulebook'}

def model_name(model):
    for name in ['haiku','sonnet','opus']:
        if name in model.lower():
            return name.title()
    return model

def config_label(model,variant):
    return f'{model_name(model)} · {VARIANT_LABELS.get(variant,variant).lower()}'

def decorate(frame):
    frame=frame.copy()
    frame['configuration']=[config_label(m,v) for m,v in zip(frame.model,frame.variant)]
    frame['color']=[PALETTE.get((m,v),COLORS['outcomes']['invalid']) for m,v in zip(frame.model,frame.variant)]
    return frame

def scored_view(results,cases,wordings):
    frame=score_results(results,cases)  # Also selects the latest stored attempt per test key.
    frame=frame.merge(wordings[['case_id','wording_id','case_text']],on=['case_id','wording_id'],how='left',validate='many_to_one')
    return decorate(frame)

def cards(frame):
    return decorate(report_card(frame)) if not frame.empty else pd.DataFrame()

def consistency_distribution(frame):
    rows=[]
    for label,g in frame.groupby('configuration',sort=False):
        valid=g[~g.invalid]
        distinct=valid.groupby('case_id').decision.nunique()
        for count,name in [(1,'Stable'),(2,'Wavering'),(3,'All over the place')]:
            rows.append(dict(configuration=label,state=name,share=100*distinct.eq(count).mean() if len(distinct) else 0,color=g.color.iloc[0]))
    return pd.DataFrame(rows)

def wording_accuracy(frame):
    return frame[frame.wording_id.isin(['W1','W5'])].groupby(['configuration','wording_id'],sort=False).is_correct.mean().mul(100).unstack().reindex(columns=['W1','W5'])

def matched_variants(frame):
    h=frame[frame.model.eq('claude-haiku-5-5') & frame.provider.eq('anthropic')]
    key=['case_id','wording_id','run']
    common=h.groupby(key).variant.nunique()
    return h.merge(common[common.eq(4)].reset_index()[key],on=key)

def kpis(frame):
    c=cards(frame)
    under=frame.expected_decision.eq('REPORTABLE_30DAY')
    return dict(tests=len(frame),accuracy=c['accuracy %'].max() if len(c) else float('nan'),consistency=c['consistency %'].max() if len(c) else float('nan'),under_reporting=100*frame.loc[under,'decision'].eq('NOT_REPORTABLE').mean() if under.any() else float('nan'))

def flows(frame):
    rows=[]
    for (expected,decision),g in frame.groupby(['expected_decision','decision']):
        if expected==decision:
            kind='Correct'
        elif expected=='REPORTABLE_30DAY' and decision=='NOT_REPORTABLE':
            kind='Under-reporting'
        elif expected=='NOT_REPORTABLE' and decision=='REPORTABLE_30DAY':
            kind='Over-reporting'
        else:
            kind='Other mismatch'
        rows.append(dict(expected=expected,decision=decision,count=len(g),kind=kind))
    return pd.DataFrame(rows)


METRICS = {
    'Accuracy': ('accuracy %','%'), 'Consistency': ('consistency %','%'),
    'Under-reporting': ('under-reporting %','%'), 'Over-calling': ('over-reporting %','%'),
    'Borderline escalation': ('borderline escalation %','%'),
    'Cave-in on leading wording': ('cave-in (pp)','points'),
    'Avg latency': ('average latency (s)','s'), 'Avg tokens': ('average total tokens','tokens'),
}

def filter_story(frame,device='All',difficulty='All',source='All',wordings=None):
    selected=frame.copy()
    if device!='All':
        selected=selected[selected.device_category.eq({'Pulse oximetry':'pulse_oximetry','Glucose meter':'glucose_meter'}[device])]
    if difficulty!='All':
        selected=selected[selected.difficulty.str.lower().eq(difficulty.lower())]
    if source=='FDA reports':
        selected=selected[~selected.source_type.eq('online_review')]
    elif source=='Consumer reviews':
        selected=selected[selected.source_type.eq('online_review')]
    if wordings is not None:
        selected=selected[selected.wording_id.isin(wordings)]
    return selected

def comparison_cards(frame,group='All six',by_device=False):
    if group in ['Haiku prompt designs','Agent design (Haiku V1-V4)']:
        frame=frame[frame.model.eq('claude-haiku-5-5')]
    elif group in ['Model sizes with a rulebook','Model size (Haiku vs Sonnet vs Opus, V2)']:
        frame=frame[frame.variant.eq('V2_zeroshot_rag')]
    return decorate(report_card(frame,by_device=by_device)) if len(frame) else pd.DataFrame()

def outcomes(frame):
    result=pd.Series('wrong',index=frame.index)
    result.loc[frame.is_acceptable & ~frame.is_correct]='acceptable'
    result.loc[frame.is_correct]='correct'
    result.loc[frame.invalid]='invalid'
    return result

def worst_cases(frame):
    table=frame.assign(wrong=~frame.is_correct).groupby('case_id').agg(
        errors=('wrong','sum'),tests=('wrong','size'),accuracy=('is_correct','mean'),title=('title','first'))
    return table.assign(error_share=table.errors/table.tests).sort_values(['error_share','errors'],ascending=False).head(5).reset_index()


def mistake_distribution(frame):
    kind=pd.Series('Invalid response',index=frame.index)
    valid=~frame.invalid
    kind.loc[valid & frame.decision.eq(frame.expected_decision)]='Correct'
    kind.loc[valid & frame.decision.eq('ESCALATE') & ~frame.expected_decision.eq('ESCALATE')]='Asked an expert instead of deciding'
    kind.loc[valid & frame.expected_decision.eq('NOT_REPORTABLE') & frame.decision.eq('REPORTABLE_30DAY')]='Over-called'
    kind.loc[valid & frame.expected_decision.eq('REPORTABLE_30DAY') & frame.decision.eq('NOT_REPORTABLE')]='Under-reported'
    kind.loc[valid & frame.expected_decision.eq('ESCALATE') & ~frame.decision.eq('ESCALATE')]='Decided when expert was needed'
    result=frame.assign(mistake=kind).groupby(['expected_decision','mistake']).size().reset_index(name='tests')
    result['share']=100*result.tests/result.groupby('expected_decision').tests.transform('sum')
    return result

def missing_reasons(frame):
    reasons=[]
    if not frame.expected_decision.eq('REPORTABLE_30DAY').any(): reasons.append('under-reporting: no reportable cases in this filter')
    if not frame.expected_decision.eq('NOT_REPORTABLE').any(): reasons.append('over-calling: no non-reportable cases in this filter')
    if not frame.difficulty.str.lower().eq('borderline').any(): reasons.append('escalation: no borderline cases in this filter')
    if not {'W1','W5'}.issubset(set(frame.wording_id)): reasons.append('leading-wording shift: both neutral and leading wordings are needed')
    if frame.invalid.all(): reasons.append('consistency: no valid decisions in this filter')
    return reasons
