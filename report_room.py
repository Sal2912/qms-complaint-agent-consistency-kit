"""Compact Story page. Explore and regulatory scoring remain in their existing modules."""
import html
import inspect
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from viz_data import COLORS, cards, kpis, DECISIONS, wording_accuracy
from room_viz import short_name, bubble_label_position, rings, case_matrix, bubbles, pictogram, waffles, radar, design_matrix


EXPLANATIONS = {
    'matrix': ('the same complaint worded 5 ways, 3 attempts each; each dot is one decision (green = correct, red = wrong, amber = escalated).', 'a compliance decision should not change because someone phrased the complaint differently.'),
    'bubbles': ('each bubble is an agent; it moves as we switch wording W1 to W5 (x = accuracy, y = consistency).', 'shows which agents are stable and which drift with wording style.'),
    'outcomes': ('for the selected agent, how 100 decisions break down (correct, escalated, over-called, under-reported, invalid).', 'under-reporting is the costly FDA risk; this shows how often it happens.'),
    'waffle': ('each column is a complaint; green = same answer all 15 times, amber = the answer changed.', 'inconsistency means the outcome depends on luck, which an auditor will not accept.'),
    'radar': ('accuracy per wording style for each agent; a round, full shape = not affected by wording.', 'reveals which wording styles (shorthand, leading, informal) trick each agent.'),
    'design': ('Haiku accuracy across the 2x2 design (simple vs step-by-step prompt, with vs without rulebook); arrows show the gain.', 'shows whether agent design improves a small model, separate from model size.'),
}

def pct(value):
    return 'n/a' if pd.isna(value) else f'{value:.1f}%'


def draw(fig,height=450,autoplay=False,expanded=False,key=None):
    fig.update_layout(height=height,template='plotly_dark',paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',font=dict(color='#E2E8F0'),updatemenus=[],sliders=[],
        margin=dict(l=8,r=8,t=28,b=8) if height>100 else dict(l=0,r=0,t=0,b=0))
    fig.update_xaxes(gridcolor='#1F2A44');fig.update_yaxes(gridcolor='#1F2A44')
    if expanded:
        fig.update_layout(height=460,font=dict(size=13),margin=dict(l=190,r=30,t=75,b=45))
        if fig.frames and fig.layout.updatemenus:
            fig.layout.updatemenus[0].y=1.1
    if fig.frames:
        duration=fig.layout.transition.duration or 600
        # Indicators redraw in small increments: eight 100ms frames total 800ms.
        frame_ms=duration/len(fig.frames) if fig.data[0].type=='pie' else duration
        markup=fig.to_html(full_html=False,include_plotlyjs=True,auto_play=autoplay,
            config={'responsive':True,'displayModeBar':False},
            animation_opts={'frame':{'duration':frame_ms,'redraw':True},'transition':{'duration':frame_ms}})
        markup='<style>html,body{margin:0;width:100%;overflow:hidden;background:#111A2E;color:#E2E8F0}</style>'+markup
        st.components.v1.html(markup,height=(460 if expanded else height),scrolling=False)
    else:
        st.plotly_chart(fig,key=key,use_container_width=True,theme=None,config={'displayModeBar':False})


def pill(text,good=False):
    color='#064E3B' if good else '#0E3A4A'
    st.html(f'<div class="room-pill" title="{html.escape(text,quote=True)}" style="background:{color}">{html.escape(text)}</div>',)


def expand(title,figure,table,shows,matters):
    def content():
        st.write('**What it shows:** '+shows)
        st.write('**Why it matters:** '+matters)
        draw(figure,expanded=True)
        shown=table.copy()
        if 'configuration' in shown: shown=shown.rename(columns={'configuration':'Agent'})
        # Keep all viewer-facing names plain; implementation identifiers stay off the dashboard.
        if 'Decision' in shown:
            shown['Decision']=shown.Decision.map(lambda v:DECISIONS.get(v,'No attempt' if v=='Missing' else v))
        shown=shown.drop(columns=['model','variant','provider','prompt_style','rag','color'],errors='ignore')
        st.dataframe(shown,use_container_width=True,hide_index=True)
    if callable(getattr(st,'dialog',None)):
        kwargs={'width':'large'} if 'width' in inspect.signature(st.dialog).parameters else {}
        st.dialog(title,**kwargs)(content)()
    else:
        with st.expander(title,expanded=True): content()


def tile_title(title,key,figure,table,shows,matters,loop_key=None):
    shows,matters=EXPLANATIONS[key]
    if loop_key:
        heading,pause,button=st.columns([3.5,1.3,1],gap='small')
        paused=st.session_state.get(loop_key+'_paused',False)
        pause.button('▶ Resume' if paused else '⏸ Pause',key='pause_'+key,
            on_click=toggle_pause,args=(loop_key,),use_container_width=True)
    else:
        heading,button=st.columns([5,1],gap='small')
    heading.html(f'<div class="room-title">{html.escape(title)}</div>',)
    if button.button('⤢ Expand',key='expand_'+key,use_container_width=True):
        expand(title,figure,table,shows,matters)
    st.html(f'<div class="room-explanation"><div><b>What it shows:</b> {html.escape(shows)}</div><div><b>Why it matters:</b> {html.escape(matters)}</div></div>')


def toggle_pause(key):
    st.session_state[key+'_paused']=not st.session_state.get(key+'_paused',False)


def next_frame(key,total,context):
    if st.session_state.get(key+'_context')!=context:
        st.session_state[key+'_context']=context
        st.session_state[key+'_index']=-1
        st.session_state[key+'_paused']=False
    if not st.session_state[key+'_paused']:
        st.session_state[key+'_index']=(st.session_state[key+'_index']+1)%total
    return st.session_state[key+'_index'],st.session_state[key+'_paused']


def context_id(frame):
    return int(pd.util.hash_pandas_object(frame[['configuration','case_id','wording_id','run','decision']],index=False).sum())


def frame_view(fig,index=None):
    data=fig.frames[index].data if index is not None else fig.data
    result=go.Figure(data=list(data),layout=fig.layout)
    result.update_layout(updatemenus=[],sliders=[],margin=dict(l=8,r=8,t=28,b=8))
    return result


def matrix_verdict(table,order):
    agent=next((a for a in order if a.startswith('Opus')),order[0])
    observed=table[table.Agent.eq(agent)&table.Available]
    counts=observed.Decision.value_counts();total=len(observed)
    words={'REPORTABLE_30DAY':'Report','NOT_REPORTABLE':'No report','ESCALATE':'Expert','INVALID':'Invalid'}
    distribution=', '.join(f'{words.get(decision,decision)} {count}/{total}' for decision,count in counts.items())
    return f"Final: {agent} · {distribution or 'no attempts'} → "+('inconsistent' if len(counts)>1 else 'stable' if total else 'n/a')


def bubble_verdict(frame):
    paired=wording_accuracy(frame).dropna()
    if paired.empty:return 'Final: n/a · both W1 and W5 are needed'
    change=paired.W5-paired.W1;agent=change.abs().idxmax()
    return f'Final: wording moves {agent} most ({change.loc[agent]:+.1f} pts W1→W5)'


@st.fragment(run_every=1.2)
def matrix_tile(frame,order):
    with st.container(border=True,key='room_matrix'):
        diversity=frame[~frame.invalid].groupby('case_id').decision.nunique().sort_values(ascending=False,kind='stable')
        cases=list(diversity.index)+[x for x in sorted(frame.case_id.unique()) if x not in diversity.index]
        chosen=st.session_state.get('room_case',cases[0])
        if chosen not in cases:
            chosen=cases[0]
            st.session_state['room_case']=chosen
        fig,table=case_matrix(frame,chosen,order)
        index,paused=next_frame('matrix_loop',len(fig.frames),(context_id(frame),chosen))
        tile_title('Watch it change its mind', 'matrix',frame_view(fig),table,
            'Five wordings, three repeats: indigo = report, teal = no report, amber = expert, grey = invalid. A ✓ ring matches the expert.',
            'The same complaint should not receive conflicting decisions.',loop_key='matrix_loop')
        chosen=st.selectbox('Case',cases,key='room_case',label_visibility='collapsed',format_func=lambda x:x+' · '+str(frame.loc[frame.case_id.eq(x),'title'].iloc[0]))
        if paused:
            pill(matrix_verdict(table,order))
        else:
            expected=frame.loc[frame.case_id.eq(chosen),'expected_decision'].iloc[0]
            pill('Expert: '+DECISIONS.get(expected,expected)+' · '+str(int(diversity.get(chosen,0)))+' different answers')
            st.html(f'<div class="room-label">Attempt {index+1} of 15</div>')
        draw(frame_view(fig,None if paused else index),key='matrix_chart')


@st.fragment(run_every=1.2)
def bubble_tile(frame,order):
    with st.container(border=True,key='room_bubbles'):
        fig,table=bubbles(frame,order)
        index,paused=next_frame('bubble_loop',len(fig.frames),context_id(frame))
        tile_title('Does wording move the agents?', 'bubbles',frame_view(fig),table,
            'Accuracy and consistency for each wording; trails show earlier positions. Pausing shows all-wording scores.',
            'A reliable assistant stays correct and consistent as facts are rephrased.',loop_key='bubble_loop')
        shift=table.groupby('configuration')['accuracy %'].agg(lambda v:v.max()-v.min()).max()
        if paused:
            pill(bubble_verdict(frame))
            overall=cards(frame).set_index('configuration').reindex(order)
            final=frame_view(fig)
            final.data=()
            for agent,r in overall.iterrows():
                final.add_trace(go.Scatter(x=[r['accuracy %']],y=[r['consistency %']],mode='markers+text',text=[short_name(agent)],textposition=bubble_label_position(agent),cliponaxis=False,
                    textfont=dict(size=12),marker=dict(size=18,color=r.color),name=agent,hovertemplate=agent+'<br>%{x:.1f}% accurate<br>%{y:.1f}% consistent<extra></extra>'))
            draw(final,key='bubble_chart')
        else:
            pill(f'Largest wording swing: {shift:.1f} points',pd.notna(shift) and shift<=5)
            st.html(f'<div class="room-label">Wording {fig.frames[index].name} of {len(fig.frames)}</div>')
            draw(frame_view(fig,index),key='bubble_chart')


@st.fragment(run_every=1.2)
def outcome_tile(frame,order):
    with st.container(border=True,key='room_outcomes'):
        agent=st.session_state.get('room_outcome_agent',order[0])
        if agent not in order:
            agent=order[0]
            st.session_state['room_outcome_agent']=agent
        fig,table=pictogram(frame,agent,True)
        index,paused=next_frame('outcome_loop',len(fig.frames),(context_id(frame),agent))
        tile_title('What happens out of 100 decisions?', 'outcomes',frame_view(fig,-1),table,
            'One hundred squares show outcome shares; the table retains exact counts and percentages.',
            'Escalation adds work, while under-reporting can miss a reportable event.',loop_key='outcome_loop')
        agent=st.selectbox('Agent',order,key='room_outcome_agent',label_visibility='collapsed')
        correct=table.loc[table.Outcome.eq('Correct'),'Per 100'].iloc[0]
        pill(('Final: ' if paused else '')+f'{correct:.1f} out of 100 match the expert',correct>=95)
        if not paused:st.html(f'<div class="room-label">Filled {fig.frames[index].name} of 100 decisions</div>')
        chart_col,counts_col=st.columns([1,1],gap='small')
        with chart_col: draw(frame_view(fig,-1 if paused else index),key='outcome_chart')
        with counts_col:
            for _,r in table.iterrows():
                if r.Outcome!='Invalid response' or r.Tests:
                    short={'Asked an expert instead of deciding':'Escalated (correct)','Decided when expert was needed':'Missed escalation','Invalid response':'Invalid'}.get(r.Outcome,r.Outcome)
                    st.html(f'<div style="font-size:13px;line-height:1.4;margin:10px 0;color:{COLORS["mistakes"][r.Outcome]}"><b style="font-size:24px">{r["Per 100"]:.1f}</b> {short}</div>')


def room(frame):
    st.html('''<style>
    .block-container{padding:.6rem 1rem .5rem;max-width:100%}
    [data-testid="stHeader"],[data-testid="stToolbar"],#MainMenu,footer{display:none}
    [data-testid="stVerticalBlock"]{gap:2px}
    .block-container>[data-testid="stVerticalBlock"]{gap:8px}
    [data-testid="stMetric"]{height:78px!important;min-height:78px;padding:4px 10px;gap:1px!important;background:#111A2E;border:1px solid #1F2A44}
    [data-testid="stMetricValue"],[data-testid="stMetricValue"]>div{line-height:1.1!important}
    [data-testid="stMetricValue"]{font-size:1.3rem;color:#F1F5F9}
    [data-testid="stMetricLabel"] p{font-size:12px;line-height:1.1;color:#94A3B8}
    [data-testid="stMetricDelta"]{font-size:11px;line-height:1.1;color:#94A3B8}
    [data-testid="stMetricDelta"] svg{display:none}
    .st-key-room_matrix,.st-key-room_bubbles,.st-key-room_outcomes,.st-key-room_waffle,.st-key-room_radar,.st-key-room_design,[class*="st-key-room_card_"]{
        background:#111A2E;border:1px solid #1F2A44!important;border-radius:12px!important;padding:10px!important;box-shadow:0 2px 8px #0003}
    [data-testid="stAlert"]>div{padding:3px 7px!important}
    [data-testid="stAlert"] p{font-size:11px}
    .room-label{font-size:11px;line-height:14px;color:#94A3B8;margin:0}
    .room-title{font-size:16px;font-weight:650;line-height:1.2;padding-top:3px;color:#F1F5F9;margin:0}
    .room-explanation{font-size:13px;line-height:1.45;color:#94A3B8;margin:6px 0;min-height:100px}
    .st-key-room_matrix,.st-key-room_bubbles,.st-key-room_outcomes,.st-key-room_waffle,.st-key-room_radar,.st-key-room_design{min-height:700px}
    .room-agent{font-size:12px;font-weight:650;line-height:1.2;min-height:30px;color:#F1F5F9;margin:0}
    .room-pill{font-size:11px;color:#E2E8F0;border-radius:12px;padding:2px 7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}
    [data-testid="stButton"] button{min-height:23px;padding:0 4px;font-size:11px}
    [data-testid="stButton"] button p{font-size:11px;white-space:nowrap}
    [data-testid="stCaptionContainer"] p{font-size:11px;margin:0;color:#94A3B8}
    [data-testid="stSelectbox"] [data-baseweb="select"]>div{min-height:28px;font-size:12px;background:#1A2540;color:#E2E8F0}
    [data-testid="stSelectbox"] label{display:none}
    </style>''')
    c=cards(frame).sort_values('accuracy %',ascending=False).reset_index(drop=True)
    order=list(c.configuration)
    best=c.iloc[0];repeat=c.loc[c['consistency %'].idxmax()] if c['consistency %'].notna().any() else None
    rates=c['under-reporting %'];lowest=rates.min()
    under_agent=c.loc[rates.idxmin(),'configuration'] if rates.notna().any() else 'No reportable cases'
    if rates.notna().all() and rates.nunique()==1: under_agent=f'All {len(c)} agents'
    labels=['Tests scored','Best accuracy','Best consistency','Lowest under-reporting']
    values=[f'{len(frame):,} · All agents',f"{pct(best['accuracy %'])} · {best.configuration}",
            f"{pct(repeat['consistency %'])} · {repeat.configuration}" if repeat is not None else 'n/a · No valid decisions',
            f'{pct(lowest)} · {under_agent}']
    for col,label,value in zip(st.columns(4,gap='small'),labels,values):
        number,agent=value.split(' · ',1)
        col.metric(label,number,delta=agent,delta_color='off')
    first=not st.session_state.get('room_rings_animated',False)
    for col,(_,r) in zip(st.columns(len(c),gap='small'),c.iterrows()):
        with col.container(border=True,key=f'room_card_{_}'):
            badges=('🏆 ' if r.configuration==best.configuration else '')+('🔁 ' if repeat is not None and r.configuration==repeat.configuration else '')
            st.html(f'<div class="room-agent">{badges}{html.escape(r.configuration)}</div>',)
            draw(rings(r,first),height=80,autoplay=first)
            latency=f"⏱ {r['average latency (s)']:.1f} s per decision" if pd.notna(r['average latency (s)']) else '⏱ n/a: no latency recorded'
            st.html(f'<div class="room-label">{latency}</div>')
    st.session_state['room_rings_animated']=True

    cols=st.columns(2,gap='small')
    with cols[0]: matrix_tile(frame,order)
    with cols[1]: bubble_tile(frame,order)

    cols=st.columns(2,gap='small')
    with cols[0]: outcome_tile(frame,order)
    with cols[1].container(border=True,key='room_waffle'):
        fig,table=waffles(frame,order)
        tile_title('How many complaints get a stable answer?', 'waffle',fig,table,
            'Each square is an observed complaint: green = one answer, amber = two, red = three. A complete unfiltered agent has 40 squares; invalid-only cases are omitted.',
            'Repeated disagreement signals an unreliable triage assistant.')
        stable=int(table['Distinct answers'].eq(1).sum());total=len(table)
        pill(f'{stable} of {total} agent–complaint pairs stable',total>0 and stable/total>=.95)
        st.html('<div class="room-label">🟢 green = same answer all 15 times, 🟠 amber = changed</div>')
        draw(fig)
    cols=st.columns(2,gap='small')
    with cols[0].container(border=True,key='room_radar'):
        fig,table=radar(frame,order)
        tile_title('What is each agent’s wording fingerprint?', 'radar',fig,table,
            'Each colored shape shows accuracy across the five wording styles. Click an agent in the legend to hide or restore its shape.',
            'A regular shape means wording has little effect; a larger shape also means more correct decisions.')
        averages=frame.groupby('wording_id').is_correct.mean()*100
        pill('Most accurate wording: '+str(averages.idxmax())+f' · {averages.max():.1f}%')
        draw(fig)
        st.html('<div class="room-label">a perfect circle = not affected by wording</div>')
    with cols[1].container(border=True,key='room_design'):
        fig,table,matching=design_matrix(frame)
        tile_title('What do the prompt and rulebook add?', 'design',fig,table,
            'Four Haiku designs on matching tests: simple or step-by-step, with or without a rulebook. Arrows show percentage-point gains.',
            'Prompt changes should earn their extra complexity by improving accuracy.')
        gain=table.loc['Step-by-step','Rulebook']-table.loc['Simple','No rulebook']
        pill(f'Combined gain: {gain:+.1f} points · {matching} matching tests' if pd.notna(gain) else 'n/a: no matching tests',pd.notna(gain) and gain>0)
        draw(fig)
