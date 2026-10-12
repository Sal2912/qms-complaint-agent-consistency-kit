"""Report Room visuals; uses the existing scoring functions without changing them."""
import math
import pandas as pd
import plotly.graph_objects as go
from viz_data import COLORS, cards, mistake_distribution, matched_variants

DECISION_COLORS={'REPORTABLE_30DAY':'#A78BFA','NOT_REPORTABLE':'#2DD4BF','ESCALATE':'#FBBF24','INVALID':'#94A3B8'}
WORDINGS={'W1':'Neutral','W2':'Informal','W3':'Shorthand','W4':'Reordered','W5':'Leading'}


def short_name(agent):
    if not agent.startswith('Haiku'): return agent.split(' · ')[0]
    return agent.replace('simple prompt','simple').replace('step-by-step','steps').replace('rulebook','rules')


def bubble_label_position(agent):
    # Haiku positions cluster together: place labels on opposite sides of them.
    if agent.startswith('Haiku'):
        if 'step-by-step' in agent:
            return 'bottom right' if 'rulebook' in agent else 'top left'
        return 'top right' if 'rulebook' in agent else 'bottom left'
    return 'top right'


def style(fig,left=35,bottom=30):
    fig.update_layout(template='plotly_dark',height=150,margin=dict(l=left,r=12,t=10,b=bottom),
        font=dict(size=12,color=COLORS['text']),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',showlegend=False)
    fig.update_xaxes(tickfont=dict(color='#E2E8F0'),title_font=dict(color='#E2E8F0'),showgrid=False,gridcolor='#1F2A44',zeroline=False,automargin=True)
    fig.update_yaxes(tickfont=dict(color='#E2E8F0'),title_font=dict(color='#E2E8F0'),showgrid=False,gridcolor='#1F2A44',zeroline=False,automargin=True)
    return fig


def animate(fig,duration,slider=False,autoplay=False):
    # Frames are advanced by independent Streamlit fragments, never Plotly controls.
    fig.update_layout(transition=dict(duration=duration),updatemenus=[],sliders=[])
    return fig


def rings(row,first):
    fig=go.Figure(); values=[row['accuracy %'],row['consistency %']]
    for index,(value,label) in enumerate(zip(values,['Accuracy','Consistency'])):
        value=float(value) if pd.notna(value) else 0
        domain=dict(x=[index*.5,index*.5+.48],y=[0,1])
        fig.add_trace(go.Pie(values=[value,100-value],hole=.82,sort=False,direction='clockwise',rotation=90,
            marker=dict(colors=[row.color,'#1F2A44']),domain=domain,textinfo='none',hoverinfo='skip'))
        fig.add_trace(go.Indicator(mode='number',value=value,number=dict(suffix='%',valueformat='.1f',font=dict(size=16,color='#E2E8F0')),
            domain=domain,title=dict(text=label,font=dict(size=11,color=COLORS['text']))))
    style(fig);fig.update_layout(height=65,margin=dict(l=0,r=0,t=0,b=0))
    if first:
        final=list(fig.data)
        fig.frames=[]
        growth=[]
        for step in range(1,9):
            data=[]
            for trace in final:
                record=trace.to_plotly_json()
                if trace.type=='pie':
                    value=float(trace.values[0])*step/8
                    record['values']=[value,100-value]
                else: record['value']=float(trace.value)*step/8
                data.append(record)
            growth.append(go.Frame(name=str(step),data=data))
        fig.frames=growth
        for trace in fig.data:
            if trace.type=='pie': trace.values=[0,100]
            else: trace.value=0
        animate(fig,800,autoplay=True);fig.update_layout(margin=dict(l=0,r=0,t=0,b=0))
    return fig


def case_matrix(frame,case_id,order):
    selected=frame[frame.case_id.eq(case_id)]
    indexed=selected.set_index(['configuration','wording_id','run'])
    rows=[]
    for agent in order:
        for column in range(15):
            wording=f'W{column//3+1}'; run=column%3+1; key=(agent,wording,run)
            if key in indexed.index:
                r=indexed.loc[key];decision='INVALID' if r.invalid else r.decision
                rows.append(dict(Agent=agent,Attempt=column+1,Wording=wording,Repeat=run,Decision=decision,Correct=bool(r.is_correct and not r.invalid),Available=True))
            else: rows.append(dict(Agent=agent,Attempt=column+1,Wording=wording,Repeat=run,Decision='Missing',Correct=False,Available=False))
    table=pd.DataFrame(rows)
    def traces(visible):
        d=table[table.Attempt.le(visible)];correct=d[d.Correct]
        return [go.Scatter(x=list(d.Attempt),y=list(d.Agent),mode='markers',marker=dict(size=16,
                    color=['#1F2A44' if not r.Available else COLORS['outcomes']['invalid'] if r.Decision=='INVALID' else COLORS['outcomes']['acceptable'] if r.Decision=='ESCALATE' else COLORS['outcomes']['correct'] if r.Correct else COLORS['outcomes']['wrong'] for r in d.itertuples()]),customdata=d[['Wording','Repeat','Decision']].values.tolist(),
                    hovertemplate='%{y}<br>%{customdata[0]} · run %{customdata[1]}<br>%{customdata[2]}<extra></extra>'),
                go.Scatter(x=list(correct.Attempt),y=list(correct.Agent),mode='markers+text',text=['✓']*len(correct),textfont=dict(size=9,color='#E2E8F0'),
                    marker=dict(size=21,symbol='circle-open',color='#34D399',line=dict(width=1.5)),hoverinfo='skip')]
    fig=go.Figure(data=traces(15));fig.frames=[go.Frame(name=str(i),data=traces(i)) for i in range(1,16)]
    style(fig,left=185);fig.update_xaxes(range=[.3,15.7],tickvals=[2,5,8,11,14],ticktext=list(WORDINGS));fig.update_yaxes(categoryorder='array',categoryarray=list(reversed(order)),range=[-.6,len(order)-.4],tickmode='array',tickvals=list(range(len(order))),ticktext=list(reversed(order)))
    animate(fig,300)
    return fig,table


def bubbles(frame,order):
    snapshots=[]; tables=[]
    for wording in WORDINGS:
        subset=frame[frame.wording_id.eq(wording)]
        if subset.empty: continue
        c=cards(subset).set_index('configuration').reindex(order)
        c['Wording']=wording;tables.append(c.reset_index())
    table=pd.concat(tables,ignore_index=True) if tables else pd.DataFrame()
    def traces(index):
        result=[]
        for agent in order:
            history=table[table.configuration.eq(agent)].iloc[:index+1]
            if history.empty:continue
            r=history.iloc[-1]
            result.append(go.Scatter(x=list(history['accuracy %']),y=list(history['consistency %']),mode='lines',line=dict(color=r.color if isinstance(r.color,str) else '#94A3B8',width=1),opacity=.3,hoverinfo='skip'))
            result.append(go.Scatter(x=[r['accuracy %']],y=[r['consistency %']],mode='markers+text',text=[short_name(agent)],textposition=bubble_label_position(agent),cliponaxis=False,textfont=dict(size=12),
                marker=dict(size=18,color=r.color if isinstance(r.color,str) else '#94A3B8'),name=agent,hovertemplate=agent+'<br>%{x:.1f}% accurate<br>%{y:.1f}% consistent<extra></extra>'))
        return result
    fig=go.Figure(data=traces(0))
    fig.frames=[go.Frame(name=t.Wording.iloc[0],data=traces(i)) for i,t in enumerate(tables)]
    style(fig)
    fig.update_xaxes(range=[40,100],ticksuffix='%',title='Accuracy')
    fig.update_yaxes(range=[0,100],ticksuffix='%',title='Consistency',tickvals=[0,25,50,75,100])
    animate(fig,600)
    return fig,table


def pictogram(frame,agent,first):
    d=mistake_distribution(frame[frame.configuration.eq(agent)])
    counts=d.groupby('mistake').tests.sum().reindex(COLORS['mistakes'],fill_value=0)
    shares=counts/counts.sum()*100
    # Largest-remainder allocation preserves exactly 100 squares without fabricating tests.
    units=shares.map(math.floor); remaining=100-int(units.sum())
    for kind in (shares-units).sort_values(ascending=False).index[:remaining]: units[kind]+=1
    kinds=[kind for kind,n in units.items() for _ in range(int(n))]
    fig=go.Figure(go.Scatter(x=[i%10 for i in range(100)],y=[9-i//10 for i in range(100)],mode='markers',
        marker=dict(size=20,symbol='square',color=[COLORS['mistakes'][k] for k in kinds]),text=kinds,hovertemplate='%{text}<extra></extra>'))
    style(fig,left=5,bottom=5);fig.update_layout(margin=dict(l=5,r=5,t=5,b=5));fig.update_xaxes(visible=False,range=[-1,10]);fig.update_yaxes(visible=False,range=[-1,10],scaleanchor='x')
    if first:
        final=fig.data[0].to_plotly_json()
        fig.frames=[go.Frame(name=str(n),data=[go.Scatter(dict(final,marker=dict(size=20,symbol='square',color=[COLORS['mistakes'][k] if i<n else '#1F2A44' for i,k in enumerate(kinds)])))]) for n in range(0,101,20)]
        fig.data[0].marker.color=['#1F2A44']*100
        animate(fig,100,autoplay=True);fig.update_layout(margin=dict(l=5,r=5,t=5,b=5))
    table=pd.DataFrame({'Outcome':counts.index,'Tests':counts.values,'Per 100':shares.values,'Squares':units.values})
    return fig,table


def waffles(frame,order):
    valid=frame[~frame.invalid];table=valid.groupby(['configuration','case_id']).decision.nunique().reset_index(name='Distinct answers')
    fig=go.Figure()
    for agent in order:
        g=table[table.configuration.eq(agent)].sort_values('case_id')
        complaints=sorted(table.case_id.unique())
        fig.add_trace(go.Scatter(x=[complaints.index(case)+1 for case in g.case_id],y=[order.index(agent)]*len(g),mode='markers',
            marker=dict(size=9,symbol='square',color=[COLORS['outcomes']['correct'] if v==1 else COLORS['outcomes']['acceptable'] for v in g['Distinct answers']]),
            customdata=g[['case_id','Distinct answers']].values.tolist(),hovertemplate=agent+'<br>%{customdata[0]}: %{customdata[1]} answers<extra></extra>'))
    style(fig,left=190,bottom=35)
    fig.update_xaxes(range=[0,len(complaints)+1],title='Complaints',tickvals=list(range(1,len(complaints)+1,5)))
    fig.update_yaxes(tickvals=list(range(len(order))),ticktext=order,autorange='reversed')
    return fig,table


def radar(frame,order):
    table=frame.groupby(['configuration','wording_id']).is_correct.mean().mul(100).unstack().reindex(index=order,columns=WORDINGS)
    fig=go.Figure()
    axes=list(WORDINGS.values())
    for agent in order:
        color=frame.loc[frame.configuration.eq(agent),'color'].iloc[0];values=list(table.loc[agent])
        fig.add_trace(go.Scatterpolar(r=values+values[:1],theta=axes+axes[:1],name=agent,mode='lines',line=dict(color=color,width=2),connectgaps=False))
    style(fig);fig.update_layout(showlegend=True,margin=dict(l=55,r=10,t=10,b=10),polar=dict(domain=dict(x=[.08,.92],y=[.15,1]),radialaxis=dict(range=[0,100],tickvals=[50,100],showticklabels=False,ticksuffix='%',tickfont=dict(size=10,color='#E2E8F0'),gridcolor='#1F2A44',linecolor='#1F2A44'),angularaxis=dict(tickfont=dict(size=11,color='#E2E8F0'),gridcolor='#1F2A44',linecolor='#1F2A44'),bgcolor='rgba(0,0,0,0)'),
        legend=dict(x=0,y=-.08,orientation='h',font=dict(size=12),itemwidth=30))
    return fig,table.reset_index()


def design_matrix(frame):
    matched=matched_variants(frame);c=cards(matched)
    values={r.variant:r['accuracy %'] for _,r in c.iterrows()}
    keys=[['V1_zeroshot_norag','V2_zeroshot_rag'],['V3_cot_norag','V4_cot_rag']]
    z=[[values.get(k,float('nan')) for k in row] for row in keys]
    fig=go.Figure(go.Heatmap(z=z,x=['No rulebook','Rulebook'],y=['Simple','Step-by-step'],zmin=0,zmax=100,colorscale=[[0,'#111A2E'],[1,'#047857']],showscale=False,
        text=[['n/a' if pd.isna(v) else f'{v:.1f}%' for v in row] for row in z],texttemplate='%{text}',textfont=dict(size=23,color='#E2E8F0'),hovertemplate='%{y}, %{x}: %{z:.1f}%<extra></extra>',xgap=32,ygap=30))
    style(fig,left=80);fig.update_xaxes(side='top');fig.update_yaxes(autorange='reversed')
    for x,y,a,b,symbol in [(.5,0,z[0][0],z[0][1],'→'),(.5,1,z[1][0],z[1][1],'→'),(0,.5,z[0][0],z[1][0],'↓'),(1,.5,z[0][1],z[1][1],'↓')]:
        if pd.notna(a) and pd.notna(b):
            fig.add_annotation(x=x,y=y,text=f'{b-a:+.1f} {symbol}',showarrow=False,font=dict(size=11,color='#E2E8F0'),bgcolor='#111A2E')
    table=pd.DataFrame(z,index=['Simple','Step-by-step'],columns=['No rulebook','Rulebook'])
    return fig,table,len(matched)//4
