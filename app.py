"""A story and an investigation workspace for complaint-triage reliability."""
import os
import json
import inspect
import time
import html
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from data_utils import ROOT, load_cases, load_wordings
from metrics import report_card, danger_tables, lookup_frequency
from viz_data import (COLORS, METRICS, PALETTE, DECISIONS, TOPICS, VARIANT_LABELS, model_name,
                      scored_view, cards, consistency_distribution, wording_accuracy,
                      matched_variants, kpis, flows, config_label, filter_story, comparison_cards, outcomes, worst_cases, mistake_distribution, missing_reasons)

st.set_page_config(page_title='Can you trust an AI complaint agent?',layout='wide',initial_sidebar_state='collapsed')
# Detach filter values from widget cleanup while their page is not rendered.
for _key in list(st.session_state):
    if _key.startswith(('story_', 'filter_', 'previous_story_', 'previous_filter_')):
        st.session_state[_key]=st.session_state[_key]


def navigate_room():
    st.session_state['page']='Story'


GREY=COLORS['outcomes']['invalid']
INK=COLORS['text']
GREEN=COLORS['outcomes']['correct']
AMBER=COLORS['outcomes']['acceptable']
RED=COLORS['outcomes']['wrong']
st.html('''<style>
.block-container {padding:.6rem 1rem .5rem; max-width:100%;}
h1 {letter-spacing:-.035em;} h2 {letter-spacing:-.02em; padding-top:.4rem;}
[data-testid="stMetric"] {background:#111A2E; border:1px solid #1F2A44; border-radius:12px; padding:10px;}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {color:#94A3B8; font-size:.9rem;}
[data-testid="stMetricValue"] {color:#E2E8F0; font-size:2.25rem; font-weight:700;}
[data-testid="stVerticalBlock"] {gap:.65rem;}
.explain {background:#111A2E;border:1px solid #1F2A44;border-radius:10px;padding:12px;font-size:13px;line-height:1.6;}
.takeaway {display:inline-block;border-radius:20px;padding:3px 9px;margin-top:6px;color:#E2E8F0;}
.stApp{background:#0B1220;color:#E2E8F0}
h1,h2,h3{color:#F1F5F9}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p{color:#94A3B8}
[data-testid="stHeader"]{height:0;background:transparent}
[data-testid="stToolbar"], #MainMenu, footer{display:none}
[data-testid="stSidebarCollapsedControl"]{position:fixed;right:16px;left:auto;top:8px}
[data-testid="stButtonGroup"] button{background:#1A2540;color:#E2E8F0;border-color:#1F2A44}
[data-testid="stButtonGroup"] button[aria-pressed="true"],button[data-testid="stBaseButton-segmented_controlActive"],button[data-testid="stBaseButton-pillsActive"]{background:#38BDF8;color:#0B1220}
</style>''')


def percent(value):
    return 'n/a' if pd.isna(value) else f'{value:.1f}%'


def chart(fig,height=360,interactive_key=None,autoplay=False):
    fig.update_layout(template='plotly_dark',height=height,margin=fig.layout.margin.to_plotly_json() or dict(l=55,r=45,t=25,b=55),
                      font=dict(family='Arial',color=INK,size=13),showlegend=bool(fig.layout.showlegend),
                      paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
    fig.update_xaxes(showgrid=False,zeroline=False,tickfont=dict(color=INK,size=13),title_font=dict(color=INK,size=13))
    fig.update_yaxes(showgrid=False,zeroline=False,tickfont=dict(color=INK,size=13),title_font=dict(color=INK,size=13))
    fig.for_each_xaxis(lambda axis: axis.update(tickformat='.1f') if axis.ticksuffix=='%' else None)
    fig.for_each_yaxis(lambda axis: axis.update(tickformat='.1f') if axis.ticksuffix=='%' else None)
    # Preserve deliberate contrasting text colors inside stacked bars.
    fig.update_annotations(font=dict(color=INK,size=13))
    if fig.frames:
        # Streamlit's native Plotly renderer does not play frames. Embed Plotly's
        # self-contained responsive player, with no CDN or external requests.
        st.components.v1.html(fig.to_html(full_html=False,include_plotlyjs=True,auto_play=autoplay,
            config={'responsive':True,'displayModeBar':False},
            animation_opts={'frame':{'duration':600,'redraw':True},'transition':{'duration':600}}),height=height+12,scrolling=False)
        return None
    options=dict(use_container_width=True,theme=None,config={'displayModeBar':False})
    if interactive_key and 'on_select' in inspect.signature(st.plotly_chart).parameters:
        return st.plotly_chart(fig,key=interactive_key,on_select='rerun',selection_mode='points',**options)
    return st.plotly_chart(fig,**options)


def details(text):
    with st.expander('Details'):
        st.write(text)


def metrics_row(frame):
    values=kpis(frame)
    labels=['Tests scored','Best accuracy','Best consistency','Under-reporting rate']
    placeholders=[column.empty() for column in st.columns(4)]
    animate=not st.session_state.get('kpis_animated',False)
    steps=[.25,.5,.75,1] if animate else [1]
    for fraction in steps:
        displayed=[f"{int(values['tests']*fraction):,}",percent(values['accuracy']*fraction),
                   percent(values['consistency']*fraction),percent(values['under_reporting']*fraction)]
        for placeholder,label,value in zip(placeholders,labels,displayed):
            placeholder.metric(label,value)
        if animate: time.sleep(.08)
    st.session_state['kpis_animated']=True


def explain(question,shows,matters,takeaway,good=False):
    color='#064E3B' if good else '#713F12'
    st.markdown(f'<div class="explain"><b>{html.escape(question)}</b><br>'
        f'📊 What it shows: {html.escape(shows)}<br>💡 Why it matters: {html.escape(matters)}<br>'
        f'<span class="takeaway" style="background:{color}">{html.escape(takeaway)}</span></div>',unsafe_allow_html=True)


def playback(fig,names,autoplay=False):
    duration=600
    fig.update_layout(transition=dict(duration=duration),
        updatemenus=[dict(type='buttons',direction='left',x=0,y=-.36,xanchor='left',yanchor='top',
            buttons=[dict(label='▶ Play',method='animate',args=[None,dict(frame=dict(duration=duration,redraw=True),transition=dict(duration=duration),fromcurrent=True)]),
                     dict(label='Ⅱ Pause',method='animate',args=[[None],dict(mode='immediate',frame=dict(duration=0,redraw=False),transition=dict(duration=0))])])],
        sliders=[] if autoplay else [dict(x=.35,len=.65,y=-.36,active=0,currentvalue=dict(prefix='',font=dict(size=13)),
            steps=[dict(label=name,method='animate',args=[[name],dict(mode='immediate',frame=dict(duration=duration,redraw=True),transition=dict(duration=duration))]) for name in names])])
    fig.update_layout(margin=dict(l=55,r=40,t=20,b=120))
    return fig


def single_pill(container,label,options,key):
    if callable(getattr(st,'segmented_control',None)):
        return container.segmented_control(label,options,default=options[0],key=key) or options[0]
    return container.radio(label,options,index=0,horizontal=True,key=key)


def multi_pills(container,label,options,default,key,format_func=None,on_change=None):
    kwargs=dict(default=default,key=key)
    if format_func:
        kwargs['format_func']=format_func
    if on_change:
        kwargs['on_change']=on_change
    if callable(getattr(st,'pills',None)):
        return container.pills(label,options,selection_mode='multi',**kwargs) or []
    return container.multiselect(label,options,**kwargs)


def normalize_wordings():
    value=st.session_state.get('story_wordings',[])
    previous=st.session_state.get('previous_story_wordings',['All'])
    if 'All' in value and len(value)>1:
        value=['All'] if 'All' not in previous else [v for v in value if v!='All']
        st.session_state['story_wordings']=value
    st.session_state['previous_story_wordings']=value


def story_filters(frame):
    device,difficulty,source,wording=st.columns([1.2,1,1.2,1.5],gap='small')
    d=single_pill(device,'Device',['All','Pulse oximetry','Glucose meter'],'story_device')
    level=single_pill(difficulty,'Case difficulty',['All','Clear','Borderline'],'story_difficulty')
    origin=single_pill(source,'Source',['All','FDA reports','Consumer reviews'],'story_source')
    words=multi_pills(wording,'Wording',['All','W1','W2','W3','W4','W5'],['All'],'story_wordings',on_change=normalize_wordings)
    selected=filter_story(frame,d,level,origin,None if 'All' in words else words)
    return selected


FILTERS=[('Model','model'),('Variant','variant'),('Device category','device_category'),('Difficulty','difficulty'),('Wording style','wording_style'),('Source type','source_type')]
PLAIN={'pulse_oximetry':'Pulse oximeters','glucose_meter':'Glucose meters','clear':'Clear-cut','borderline':'Needs judgment',
       'formal_record':'Neutral record','manufacturer_mdr':'Manufacturer reports','online_review':'Consumer reviews',
       'voluntary_report_consumer':'Consumer reports','voluntary_report_clinician':'Clinician reports','distributor_report':'Distributor reports'}

def reset_filters():
    for _,column in FILTERS:
        st.session_state.pop('filter_'+column,None)
        st.session_state.pop('previous_filter_'+column,None)


def normalize_explore(column):
    key='filter_'+column
    previous=st.session_state.get('previous_'+key,['All'])
    value=st.session_state.get(key,[])
    if 'All' in value and len(value)>1:
        value=['All'] if 'All' not in previous else [v for v in value if v!='All']
        st.session_state[key]=value
    st.session_state['previous_'+key]=value


def explore(frame):
    st.button('← Back to Report Room',key='back_to_room',on_click=navigate_room)
    st.title('Explore the decisions')
    st.sidebar.button('Reset',on_click=reset_filters,width='stretch')
    filtered=frame.copy()
    for label,column in FILTERS:
        options=['All']+sorted(frame[column].dropna().unique())
        def format_value(value,column=column):
            if value=='All':
                return 'All'
            if column=='model':
                return model_name(value)
            if column=='variant':
                return VARIANT_LABELS.get(value,value)
            return PLAIN.get(value,str(value).replace('_',' ').capitalize())
        selected=multi_pills(st.sidebar,label,options,default=['All'],key='filter_'+column,format_func=format_value,on_change=lambda column=column:normalize_explore(column))
        if 'All' not in selected:
            filtered=filtered[filtered[column].isin(selected)]
    if filtered.empty:
        st.info('No tests match these filters. Reset to see all decisions.')
        return
    metrics_row(filtered)
    unavailable=missing_reasons(filtered)
    if unavailable:
        st.caption('n/a: '+ '; '.join(unavailable)+'.')
    danger,case_tab,full=st.tabs(['Danger Zone','Case Explorer','Full metrics'])
    with danger:
        wrong,_=danger_tables(filtered)
        st.subheader(f'{len(wrong):,} confident decisions are wrong')
        if wrong.empty:
            st.info('No confident-but-wrong decisions match these filters.')
        else:
            shown=wrong[['configuration','case_id','wording_id','run','decision','expected_decision','confidence','reasoning','source_url']].copy()
            shown['decision']=shown.decision.map(DECISIONS).fillna('Invalid response')
            shown['expected_decision']=shown.expected_decision.map(DECISIONS)
            shown['confidence']=shown.confidence.map(lambda v:f'{v:.1%}')
            shown=shown.rename(columns={'configuration':'Agent','case_id':'Case','wording_id':'Wording','run':'Repeat','decision':'Decision','expected_decision':'Expected','confidence':'Confidence','reasoning':'Reason','source_url':'Source'})
            st.dataframe(shown,hide_index=True,width='stretch',column_config={'Source':st.column_config.LinkColumn('Source',display_text='Open source')})
        st.caption('Confident = at least 80% confidence; wrong uses the current answer key.')
    with case_tab:
        case_options=sorted(filtered.case_id.unique())
        jump=st.session_state.pop('focus_case',None)
        if jump in case_options:
            st.session_state['case_pick']=jump
        if st.session_state.get('case_pick') not in case_options:
            st.session_state['case_pick']=case_options[0]
        case_id=st.selectbox('Complaint',case_options,key='case_pick')
        selected=filtered[filtered.case_id.eq(case_id)]
        first=selected.iloc[0]
        st.subheader(first.title)
        wording=st.selectbox('Read a wording',sorted(selected.wording_id.unique()))
        with st.container(border=True):
            st.write(selected[selected.wording_id.eq(wording)].iloc[0].case_text)
        st.write('**Expected:** '+DECISIONS.get(first.expected_decision,first.expected_decision))
        st.write(first.rationale)
        if first.get('label_status')=='EXPERT_REVIEWED':
            st.caption('Expert reviewed by '+str(first.get('reviewed_by','')))
        st.link_button('Read the source',first.source_url)
        grid=selected.pivot_table(index='configuration',columns=['wording_id','run'],values='decision',aggfunc='last')
        status=selected.assign(cell=selected.apply(lambda r:COLORS['outcomes'][outcomes(selected).loc[r.name]],axis=1)).pivot_table(index='configuration',columns=['wording_id','run'],values='cell',aggfunc='last')
        display=grid.map(lambda x:DECISIONS.get(x,'n/a'))
        display.columns=[f'{w} · repeat {r}' for w,r in display.columns]
        status.columns=display.columns
        def cell_styles(_):
            return status.map(lambda color:f'background-color: {color}26; color: {COLORS["dark"]}; border-left: 3px solid {color};' if pd.notna(color) else '')
        st.dataframe(display.style.apply(cell_styles,axis=None),width='stretch')
        st.caption('Green = correct; amber = acceptable alternative; red = wrong; slate = invalid.')
        with st.expander('Transcripts'):
            rows=list(selected.index)
            row_index=st.selectbox('Test',rows,format_func=lambda i:f'{selected.loc[i,"configuration"]} · {selected.loc[i,"wording_id"]} · repeat {selected.loc[i,"run"]}')
            row=selected.loc[row_index]
            st.write(row.reasoning)
            if row.error:
                st.write(row.error)
            try:
                st.json(json.loads(row.transcript))
            except (ValueError,TypeError):
                st.code(str(row.transcript))
    with full:
        table=cards(filtered)
        label_map={'rows':'Tests','accuracy %':'Accuracy','acceptable %':'Acceptable decisions','consistency %':'Consistency',
                   'consistency excluded rows':'Errors excluded','consistency excluded cases':'Cases excluded',
                   'borderline escalation %':'Expert review on judgment cases','under-reporting %':'Under-reporting',
                   'over-reporting %':'Over-calling','invalid/error %':'Errors','cave-in (pp)':'Leading-wording shift',
                   'average turns':'Average turns','actual filing agreement %':'Agreement with observed filing',
                   'actual filing rows':'Tests with filing data','average input tokens':'Average input tokens',
                   'average output tokens':'Average output tokens','average total tokens':'Average total tokens',
                   'total tokens':'Total tokens','average latency (s)':'Average seconds'}
        keep=['configuration']+list(label_map)
        table=table[keep]
        for column in table:
            if column.endswith(' %'):
                table[column]=table[column].map(percent)
            elif column=='cave-in (pp)':
                table[column]=table[column].map(lambda x:'n/a' if pd.isna(x) else f'{x:+.1f} points')
        table=table.rename(columns={'configuration':'Agent',**label_map})
        st.dataframe(table.fillna('n/a'),hide_index=True,width='stretch')
        st.caption('n/a = no eligible observations: the filter may omit an expected answer, wording pair, borderline case, valid decision or recorded filing.')
        with st.expander('Details'):
            st.write('Metrics come from the unchanged report-card calculations. Latest attempts only. Consistency excludes errors; other rates include them. Under-reporting and over-reporting use the corresponding expected-answer groups as their denominators. Filters change coverage.')



page=st.sidebar.radio('Page',['Story','Explore'],index=0,key='page',format_func=lambda value:'Report Room' if value=='Story' else value)
try:
    raw=pd.read_csv(os.getenv('QMS_RESULTS_PATH',str(ROOT/'data/results.csv')),keep_default_na=False)
    frame=scored_view(raw,load_cases(),load_wordings())
except Exception as exc:
    st.info(f'No results are available to display. {exc}')
    st.stop()
if frame.empty:
    st.info('No tests are available yet.')
    st.stop()
if page=='Story':
    from report_room import room
    heading,navigation=st.columns([8,1],gap='small')
    heading.markdown('<h3 style="margin:0;padding:0;font-size:22px">Can you trust an AI agent with FDA reportability?</h3>',unsafe_allow_html=True)
    def navigate_explore():
        st.session_state['page']='Explore'
    navigation.button('Explore ↗',key='room_explore',on_click=navigate_explore,use_container_width=True)
    frame=story_filters(frame)
    if frame.empty:
        st.info('No tests match these filters. Choose All or add a wording to continue.')
        st.stop()
    if len(frame)<300:
        st.warning(f'Small sample (n = {len(frame)}): results may not be representative')
    room(frame)
else:
    explore(frame)
