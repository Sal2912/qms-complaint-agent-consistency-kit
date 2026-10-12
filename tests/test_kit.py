import json
import pandas as pd
import pytest
from agent import parse_json, run_agent
from metrics import score_results, report_card, load_scored, danger_tables
from data_utils import load_cases, load_wordings
from validate_data import validate


def dashboard_run(app):
    # Streamlit 1.50 AppTest treats single-selection button groups as multi-select.
    # Normalize only the test harness serialization; live widgets use native state.
    for group in app.get('button_group'):
        if isinstance(group.value,str):
            group.set_value([group.value])
    return app.run(timeout=30)


def case_frame(expected='REPORTABLE_30DAY', difficulty='clear', alternatives=''):
    return pd.DataFrame([dict(case_id='P01',device_category='pulse_oximetry',expected_decision=expected,difficulty=difficulty,acceptable_alternatives=alternatives,source_type='manufacturer_mdr',actual_filing='Manufacturer MDR filed (Death)')])


def rows(decisions, reviews=None):
    return pd.DataFrame([dict(provider='mock',model='test',case_id='P01',wording_id=f'W{i+1}',decision=d,needs_expert_review=(reviews or [False]*len(decisions))[i],confidence=.9,n_turns=2,error='',tools_used='malfunction') for i,d in enumerate(decisions)])


def test_consistency():
    for decisions, expected in [(['REPORTABLE_30DAY']*5,100),(['REPORTABLE_30DAY','NOT_REPORTABLE','ESCALATE','NOT_REPORTABLE','ESCALATE'],0)]:
        assert report_card(score_results(rows(decisions),case_frame())).iloc[0]['consistency %'] == expected


def test_borderline_acceptable():
    r = rows(['ESCALATE','ESCALATE','NOT_REPORTABLE'],[True,False,True])
    assert score_results(r,case_frame(difficulty='borderline',alternatives='ESCALATE')).is_acceptable.tolist() == [True,False,False]
    assert not score_results(r,case_frame(difficulty='clear',alternatives='ESCALATE')).is_acceptable.any()


def test_under_over_and_cave_in():
    r = rows(['REPORTABLE_30DAY','REPORTABLE_30DAY','REPORTABLE_30DAY','REPORTABLE_30DAY','NOT_REPORTABLE'])
    card = report_card(score_results(r,case_frame())).iloc[0]
    assert card['under-reporting %'] == 20
    assert card['cave-in (pp)'] == 100
    card = report_card(score_results(rows(['REPORTABLE_30DAY']*5),case_frame('NOT_REPORTABLE'))).iloc[0]
    assert card['over-reporting %'] == 100


def test_current_answer_key(tmp_path):
    cases_path, results_path = tmp_path/'cases.csv', tmp_path/'results.csv'
    rows(['REPORTABLE_30DAY']).to_csv(results_path,index=False)
    case_frame().to_csv(cases_path,index=False)
    assert load_scored(results_path,cases_path).is_correct.iloc[0]
    case_frame('NOT_REPORTABLE').to_csv(cases_path,index=False)
    assert not load_scored(results_path,cases_path).is_correct.iloc[0]


def fake_sequence(objects):
    iterator = iter(objects)
    def call(*args):
        return json.dumps(next(iterator)), 10, 5
    return call

FINAL = dict(action='final',decision='ESCALATE',confidence=.8,needs_expert_review=True,reasoning='Expert judgment needed.')

@pytest.mark.parametrize('topic,text',[('malfunction','Known guidance'),('unknown','Unknown topic')])
def test_lookup_final(topic,text):
    result = run_agent('mock','test','Complaint',['ESCALATE'],fake_sequence([dict(action='lookup',topic=topic),FINAL]),knowledge={'malfunction':'Known guidance'})
    assert result['decision'] == 'ESCALATE'
    assert result['n_turns'] == 2
    assert result['input_tokens'] == 20
    assert json.loads(result['transcript'])[3]['content'] == text


def test_max_turns_and_bad_final():
    result = run_agent('mock','test','Complaint',['ESCALATE'],fake_sequence([dict(action='lookup',topic='x')]*5))
    assert result['decision'] == 'INVALID' and result['error'] == 'max_turns'
    result = run_agent('mock','test','Complaint',['NOT_REPORTABLE'],fake_sequence([FINAL]))
    assert result['decision'] == 'INVALID' and result['error'] == 'decision_not_allowed'

@pytest.mark.parametrize('text',['```json\n{"action":"lookup"}\n```','extra text {"action":"lookup"} trailing','junk {bad} then {"action":"lookup"}'])
def test_json_parsing(text):
    assert parse_json(text) == {'action':'lookup'}


def test_invalid_exclusions_and_danger():
    r = rows(['REPORTABLE_30DAY','INVALID','NOT_REPORTABLE'])
    r.loc[1,'error'] = 'max_turns'
    scored = score_results(r,case_frame())
    card = report_card(scored).iloc[0]
    assert card['consistency excluded rows'] == 1
    assert card['consistency %'] == 0
    wrong, inconsistent = danger_tables(scored)
    assert len(wrong) == 2 and inconsistent.case_id.nunique() == 1


def test_source_data():
    assert validate(verbose=False)
    assert len(load_cases()) == 40 and len(load_wordings()) == 200


def test_cleanup(tmp_path):
    path = tmp_path/'cases.csv'
    path.write_text('\ufeffcase_id,title\n P01 , hello \n , \ncase_id,title\n',encoding='utf-8')
    from data_utils import read_clean
    result = read_clean(path)
    assert len(result) == 1 and result.iloc[0].title == 'hello'


def test_dashboard(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QMS_RESULTS_PATH','data/mock_results.csv')
    app = AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    assert app.sidebar.radio[0].value == 'Story'
    assert not app.sidebar.multiselect
    dashboard_run(app.sidebar.radio[0].set_value('Explore').root)
    assert len(app.tabs) == 3
    app.sidebar.get('button_group')[0].set_value([])
    dashboard_run(app)
    assert not app.exception
    assert any('No tests match' in item.value for item in app.info)


def test_retry_without_network(monkeypatch):
    import agent
    class ServerError(Exception):
        status_code = 503
    calls = []
    monkeypatch.setattr(agent.time,'sleep',lambda seconds: None)
    def call(*args):
        calls.append(1)
        if len(calls) < 3:
            raise ServerError('Synthetic transient error')
        return json.dumps(FINAL), 1, 1
    assert run_agent('mock','test','Complaint',['ESCALATE'],call)['decision'] == 'ESCALATE'
    assert len(calls) == 3
    def fail(*args):
        raise ServerError('Synthetic persistent error')
    result = run_agent('mock','test','Complaint',['ESCALATE'],fail)
    assert result['decision'] == 'INVALID' and 'ServerError' in result['error']


def test_filing_agreement():
    c = case_frame()
    c['source_type'] = 'voluntary_report_consumer'
    c['actual_filing'] = 'Voluntary MedWatch report (Injury)'
    card = report_card(score_results(rows(['REPORTABLE_30DAY']),c)).iloc[0]
    assert card['actual filing agreement %'] == 100
    assert card['actual filing rows'] == 1


def test_google_client_lifetime_and_thread_isolation(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from google import genai
    import agent
    created = []
    barrier = threading.Barrier(2)
    class FakeClient:
        def __init__(self, **kwargs):
            self.models = self
            self.calls = 0
            created.append(self)
        def generate_content(self, **kwargs):
            self.calls += 1
            assert kwargs['config'].automatic_function_calling.disable is True
            assert kwargs['config'].tools == []
            parts = [SimpleNamespace(text='private thought',thought=True), SimpleNamespace(text=None,thought=False,function_call='ignored'), SimpleNamespace(text=json.dumps(FINAL),thought=False)]
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],usage_metadata=SimpleNamespace(prompt_token_count=1,candidates_token_count=2))
        def close(self):
            pytest.fail('Client must stay open during the run')
    monkeypatch.setenv('GEMINI_API_KEY','fake-test-key')
    monkeypatch.setattr(genai,'Client',FakeClient)
    monkeypatch.setattr(agent,'_google_clients',threading.local())
    monkeypatch.setattr(agent,'provider_gate',lambda *args: SimpleNamespace(acquire=lambda:None))
    def worker():
        barrier.wait(timeout=5)
        messages = [{'role':'system','content':'test'},{'role':'user','content':'complaint'}]
        first = agent.google_client()
        for _ in range(2):
            assert agent.call_model('google','test',messages)[1:] == (1,2)
            assert agent.google_client() is first
        return first
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        clients = [future.result() for future in futures]
    assert clients[0] is not clients[1]
    assert len(created) == 2 and all(client.calls == 2 for client in created)


def test_resume_replaces_failed_rows(tmp_path, monkeypatch):
    import sys
    import run_agent as runner
    path = tmp_path/'results.csv'
    case_id = load_cases().iloc[0].case_id
    records = []
    for wording, decision, error in [('W1','ESCALATE',''),('W2','INVALID','RuntimeError: client closed'),('W3','NOT_REPORTABLE','API error'),('W4','INVALID','max_turns')]:
        row = dict.fromkeys(runner.COLUMNS,'')
        row.update(provider='mock',model='random-agent',case_id=case_id,wording_id=wording,run='1',decision=decision,error=error)
        records.append(row)
    pd.DataFrame(records,columns=runner.COLUMNS).to_csv(path,index=False)
    done = runner.prepare_resume(path)
    assert done == {('mock','random-agent',case_id,'W1','1','V2_zeroshot_rag')}
    assert pd.read_csv(path).wording_id.tolist() == ['W1','W2','W3','W4']
    def fake(*args, **kwargs):
        return dict(decision='ESCALATE',confidence=.8,needs_expert_review=True,reasoning='Test',n_turns=1,tools_used='',input_tokens=0,output_tokens=0,latency_s=0,error='',transcript='[]')
    monkeypatch.setattr(runner,'run_agent',fake)
    monkeypatch.setattr(sys,'argv',['run_agent.py','--mock','--limit','1','--runs','1','--out',str(path)])
    runner.main()
    result = pd.read_csv(path,keep_default_na=False)
    assert len(result) == 8
    latest = result.drop_duplicates(runner.KEY,keep='last')
    assert len(latest) == 5 and latest.error.eq('').all()
    runner.main()
    assert len(pd.read_csv(path)) == 8


def test_invalid_json_recovery_same_protocol():
    calls = []
    def call(provider, model, messages):
        calls.append([dict(m) for m in messages])
        return ('non-JSON' if len(calls)==1 else json.dumps(FINAL)), 1, 2
    result = run_agent('mock','test','Complaint',['ESCALATE'],call)
    assert result['decision'] == 'ESCALATE' and result['n_turns'] == 2
    assert calls[1][-1]['content'].startswith('Your response did not contain valid JSON')
    assert result['input_tokens'] == 2 and result['output_tokens'] == 4
    result = run_agent('mock','test','Complaint',['ESCALATE'],lambda *args: ('',0,0))
    assert result['decision'] == 'INVALID' and result['error'] == 'invalid_json'


def test_retry_delay_and_daily_quota():
    from agent import retry_delay, daily_quota_error
    from types import SimpleNamespace
    exc = RuntimeError("Please retry in 26.932s. 'retryDelay': '26s'")
    exc.response = SimpleNamespace(headers={'retry-after':'30'})
    assert retry_delay(exc,0) == 31
    assert daily_quota_error(RuntimeError('requests per day (RPD): Limit 50, Used 50'))
    assert not daily_quota_error(RuntimeError('GenerateRequestsPerMinutePerProjectPerModel-FreeTier'))


def test_pacing_and_cooldown(monkeypatch):
    import agent
    now = [0.0]
    monkeypatch.setattr(agent.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(agent.time,'sleep',lambda seconds:now.__setitem__(0,now[0]+seconds))
    gate = agent.ProviderGate(13)
    gate.acquire()
    gate.acquire()
    assert now[0] == 13
    gate.cooldown(31)
    gate.acquire()
    assert now[0] == 44
    gate.daily_error = RuntimeError('daily quota')
    with pytest.raises(RuntimeError,match='daily quota'):
        gate.acquire()


def test_errors_redact_keys(monkeypatch):
    from agent import safe_error
    monkeypatch.setenv('GEMINI_API_KEY','AQ.synthetic-secret')
    message = safe_error(RuntimeError('Rejected AQ.synthetic-secret'))
    assert 'synthetic-secret' not in message and '[REDACTED]' in message


def test_daily_quota_circuit_stops_network_attempts(monkeypatch):
    import agent
    class RateLimitError(Exception):
        status_code = 429
    gate = agent.ProviderGate(0)
    monkeypatch.setattr(agent,'provider_gate',lambda *args:gate)
    attempted = []
    def call(*args):
        gate.acquire()
        attempted.append(1)
        raise RateLimitError('requests per day (RPD): Limit 50, Used 50')
    monkeypatch.setattr(agent,'call_model',call)
    for _ in range(3):
        result = agent.run_agent('openai','test','Complaint',['ESCALATE'])
        assert result['decision'] == 'INVALID'
        assert 'RateLimitError' in result['error']
    assert len(attempted) == 1


def test_three_workers_per_model_run_in_parallel():
    import threading
    from run_agent import model_pools, SIZE_MODELS
    models = [tuple(entry.split(':',1)) for entry in SIZE_MODELS.split(',')]
    pools = model_pools(models + models[:1])
    assert len(pools) == 3
    barrier = threading.Barrier(9)
    def task():
        barrier.wait(timeout=5)
        return threading.get_ident()
    try:
        futures = [pool.submit(task) for pool in pools.values() for _ in range(3)]
        assert len({f.result(timeout=10) for f in futures}) == 9
    finally:
        for pool in pools.values():
            pool.shutdown()


@pytest.mark.parametrize('status',[429,529])
def test_anthropic_backoff_statuses(status):
    from agent import retryable
    error = RuntimeError('Synthetic API error')
    error.status_code = status
    assert retryable(error)


@pytest.mark.parametrize('variant',['V1_zeroshot_norag','V3_cot_norag'])
def test_no_rag_rejects_lookups(variant):
    calls = []
    def call(*args):
        calls.append(1)
        return json.dumps({'action':'lookup','topic':'malfunction'}),1,1
    result = run_agent('mock','test','Complaint',['ESCALATE'],call,knowledge={'malfunction':'SECRET KNOWLEDGE'},variant=variant)
    assert result['decision'] == 'INVALID' and result['error'] == 'lookup_not_allowed'
    assert len(calls) == 1 and result['n_turns'] == 1 and result['tools_used'] == ''
    assert 'SECRET KNOWLEDGE' not in result['transcript']


@pytest.mark.parametrize('variant',['V1_zeroshot_norag','V3_cot_norag'])
def test_no_rag_one_turn_final(variant):
    result = run_agent('mock','test','Complaint',['ESCALATE'],fake_sequence([FINAL]),variant=variant)
    assert result['decision']=='ESCALATE' and result['n_turns']==1


def test_variant_backfill_preserves_existing_values(tmp_path):
    from run_agent import LEGACY_COLUMNS, COLUMNS, prepare_resume
    record = dict.fromkeys(LEGACY_COLUMNS,'')
    record.update(provider='anthropic',model='claude-haiku-5-5',case_id='P01',wording_id='W1',run='1',decision='ESCALATE',reasoning='Original, exact reasoning.',transcript='[{"content":"unaltered"}]')
    before = pd.DataFrame([record],columns=LEGACY_COLUMNS)
    path = tmp_path/'results.csv'
    before.to_csv(path,index=False)
    done = prepare_resume(path)
    after = pd.read_csv(path,dtype=str,keep_default_na=False)
    pd.testing.assert_frame_equal(before,after[LEGACY_COLUMNS])
    assert list(after.columns)==COLUMNS
    assert after.variant.iloc[0]=='V2_zeroshot_rag'
    assert after.prompt_style.iloc[0]=='zero_shot' and after.rag.iloc[0]=='yes'
    assert ('anthropic','claude-haiku-5-5','P01','W1','1','V2_zeroshot_rag') in done
    assert ('anthropic','claude-haiku-5-5','P01','W1','1','V1_zeroshot_norag') not in done
    contents = path.read_bytes()
    prepare_resume(path)
    assert path.read_bytes()==contents


def test_resume_is_independent_per_variant(tmp_path,monkeypatch):
    import sys
    import run_agent as runner
    path=tmp_path/'results.csv'
    calls=[]
    def fake(*args,**kwargs):
        calls.append(kwargs['variant'])
        return dict(decision='ESCALATE',confidence=.8,needs_expert_review=True,reasoning='Test',n_turns=1,tools_used='',input_tokens=1,output_tokens=1,latency_s=0,error='',transcript='[]')
    monkeypatch.setattr(runner,'run_agent',fake)
    def execute(variant):
        monkeypatch.setattr(sys,'argv',['run_agent.py','--mock','--limit','1','--runs','1','--variant',variant,'--out',str(path)])
        runner.main()
    execute('V2_zeroshot_rag')
    before=pd.read_csv(path,dtype=str,keep_default_na=False)
    execute('V1_zeroshot_norag')
    execute('V1_zeroshot_norag')
    after=pd.read_csv(path,dtype=str,keep_default_na=False)
    pd.testing.assert_frame_equal(before,after.iloc[:5].reset_index(drop=True))
    assert len(after)==10 and len(calls)==10
    assert not after.duplicated(runner.KEY).any()


def test_metrics_do_not_mix_variants():
    from metrics import lookup_frequency
    a=rows(['REPORTABLE_30DAY']*5).assign(variant='V1_zeroshot_norag')
    b=rows(['NOT_REPORTABLE']*5).assign(variant='V2_zeroshot_rag')
    scored=score_results(pd.concat([a,b],ignore_index=True),case_frame())
    card=report_card(scored).set_index('variant')
    assert len(card)==2
    assert card.loc['V1_zeroshot_norag','accuracy %']==100
    assert card.loc['V2_zeroshot_rag','accuracy %']==0
    assert card['consistency %'].eq(100).all()
    _, inconsistent=danger_tables(scored)
    assert inconsistent.empty
    assert set(lookup_frequency(scored).variant)==set(card.index)


def test_v2_prompt_unchanged_and_v4_lookup():
    from agent import PROMPTS,SYSTEM_PROMPT
    assert PROMPTS['V2_zeroshot_rag']==SYSTEM_PROMPT
    assert '<max 2 sentences>' in SYSTEM_PROMPT
    assert '<max 8 sentences>' in PROMPTS['V3_cot_norag']
    assert '<max 8 sentences>' in PROMPTS['V4_cot_rag']
    result=run_agent('mock','test','Complaint',['ESCALATE'],fake_sequence([{'action':'lookup','topic':'malfunction'},FINAL]),variant='V4_cot_rag')
    assert result['decision']=='ESCALATE' and result['n_turns']==2


def test_anthropic_cot_output_budget_preserves_v2(monkeypatch):
    import agent
    import anthropic
    from types import SimpleNamespace
    budgets=[]
    def create(**kwargs):
        budgets.append(kwargs['max_tokens'])
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(FINAL))],usage=SimpleNamespace(input_tokens=1,output_tokens=1))
    monkeypatch.setattr(anthropic,'Anthropic',lambda **kwargs:SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(agent,'provider_gate',lambda *args:SimpleNamespace(acquire=lambda:None))
    for variant in ['V1_zeroshot_norag','V2_zeroshot_rag','V3_cot_norag','V4_cot_rag']:
        agent.call_model('anthropic','test',[{'role':'system','content':agent.PROMPTS[variant]},{'role':'user','content':'Complaint'}])
    assert budgets==[1024,1024,4096,4096]


def test_latest_attempt_scored_without_deleting_history():
    from variants import backfill_variants
    from run_agent import KEY
    a=rows(['INVALID']).assign(run=1,error='invalid_json')
    b=rows(['REPORTABLE_30DAY']).assign(run=1)
    stored=backfill_variants(pd.concat([a,b],ignore_index=True))
    scored=score_results(stored,case_frame())
    assert len(stored)==2 and stored.duplicated(KEY).sum()==1
    assert len(scored)==1 and scored.is_correct.iloc[0]


def test_dashboard_all_four_variants_and_filters(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from run_agent import COLUMNS
    from variants import VARIANTS
    case_id=load_cases().iloc[0].case_id
    records=[]
    for variant,cfg in VARIANTS.items():
        for i in range(1,6):
            record=dict.fromkeys(COLUMNS,'')
            record.update(provider='anthropic',model='claude-haiku-5-5',case_id=case_id,wording_id=f'W{i}',wording_style='formal_record',run=1,decision='REPORTABLE_30DAY',confidence=.9,needs_expert_review=False,reasoning='Test',n_turns=1,input_tokens=10,output_tokens=5,latency_s=.1,transcript='[]',variant=variant,prompt_style=cfg['prompt_style'],rag=cfg['rag'])
            records.append(record)
    path=tmp_path/'variants.csv'
    pd.DataFrame(records,columns=COLUMNS).to_csv(path,index=False)
    monkeypatch.setenv('QMS_RESULTS_PATH',str(path))
    app=AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    assert app.metric[0].value=='20'
    dashboard_run(app.sidebar.radio[0].set_value('Explore').root)
    assert [tab.label for tab in app.tabs]==['Danger Zone','Case Explorer','Full metrics']
    app.sidebar.get('button_group')[1].set_value(['V1_zeroshot_norag'])
    dashboard_run(app)
    assert not app.exception
    app.sidebar.button[0].click()
    dashboard_run(app)
    assert not app.exception
    assert app.sidebar.get('button_group')[1].value==['All']


def test_story_aggregations_are_presentation_only():
    from viz_data import scored_view, cards, consistency_distribution, flows
    from run_agent import COLUMNS
    from data_utils import load_cases,load_wordings
    case=load_cases().iloc[0]
    records=[]
    for wording,decision in [('W1','NOT_REPORTABLE'),('W1',case.expected_decision),('W2','ESCALATE')]:
        r=dict.fromkeys(COLUMNS,'')
        r.update(provider='anthropic',model='claude-haiku-5-5',variant='V2_zeroshot_rag',prompt_style='zero_shot',rag='yes',case_id=case.case_id,wording_id=wording,run=1,decision=decision,needs_expert_review=True,confidence=.9,n_turns=1,input_tokens=10,output_tokens=10,latency_s=1)
        records.append(r)
    original=pd.DataFrame(records)
    before=original.copy(deep=True)
    view=scored_view(original,load_cases(),load_wordings())
    pd.testing.assert_frame_equal(before,original)
    assert len(view)==2 and view[view.wording_id.eq('W1')].is_correct.all()
    distribution=consistency_distribution(view)
    assert distribution.loc[distribution.state.eq('Wavering'),'share'].iloc[0]==100
    assert distribution.share.sum()==100
    assert cards(view)['accuracy %'].iloc[0]==50
    assert flows(view)['count'].sum()==2


def test_report_room_filters_and_case_controls(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QMS_RESULTS_PATH','data/results.csv')
    app=AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    assert len([b for b in app.button if b.label=='⤢ Expand'])==6
    all_tests=app.metric[0].value
    app.get('button_group')[0].set_value(['Pulse oximetry'])
    dashboard_run(app)
    assert not app.exception and app.metric[0].value!=all_tests
    assert app.selectbox(key='room_case').value.startswith('P')
    app.get('button_group')[3].set_value([])
    dashboard_run(app)
    assert not app.exception and any('No tests match' in x.value for x in app.info)


def test_report_room_expand_dialog(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QMS_RESULTS_PATH','data/results.csv')
    app=AppTest.from_file('app.py').run(timeout=30)
    app.button(key='expand_matrix').click()
    dashboard_run(app)
    assert not app.exception
    assert any('What it shows:' in m.value for m in app.markdown)
    assert len(app.dataframe)==1


def test_live_presentation_filters_and_colors():
    from viz_data import COLORS,scored_view,filter_story,comparison_cards,outcomes
    from data_utils import load_cases,load_wordings
    frame=scored_view(pd.read_csv('data/results.csv',keep_default_na=False),load_cases(),load_wordings())
    part=filter_story(frame,'Pulse oximetry','Borderline','FDA reports',['W5'])
    assert part.device_category.eq('pulse_oximetry').all()
    assert part.difficulty.eq('borderline').all()
    assert part.wording_id.eq('W5').all()
    assert not part.source_type.eq('online_review').any()
    c=comparison_cards(frame,'Model sizes with a rulebook',by_device=True)
    assert c.variant.eq('V2_zeroshot_rag').all() and len(c)==6
    assert COLORS['outcomes']['wrong']=='#F87171'
    assert COLORS['configurations'][('claude-haiku-5-5','V2_zeroshot_rag')]=='#38BDF8'
    assert set(outcomes(frame)) <= set(COLORS['outcomes'])


def test_report_room_fallback_and_explore(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QMS_RESULTS_PATH','data/results.csv')
    monkeypatch.setattr(st,'segmented_control',None)
    monkeypatch.setattr(st,'pills',None)
    monkeypatch.setattr(st,'dialog',None)
    app=AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    app.button(key='expand_radar').click().run(timeout=30)
    assert not app.exception and app.expander
    app.sidebar.radio[0].set_value('Explore').run(timeout=30)
    assert not app.exception and len(app.sidebar.multiselect)==6
    assert [t.label for t in app.tabs]==['Danger Zone','Case Explorer','Full metrics']


def test_mistake_bars_preserve_all_tests():
    from viz_data import mistake_distribution
    frame=pd.DataFrame({'expected_decision':['REPORTABLE_30DAY']*3+['ESCALATE'],
        'decision':['REPORTABLE_30DAY','NOT_REPORTABLE','ESCALATE','NOT_REPORTABLE'], 'invalid':[False]*4})
    result=mistake_distribution(frame)
    assert result.tests.sum()==4
    assert all(abs(v-100)<1e-8 for v in result.groupby('expected_decision').share.sum())
    assert {'Correct','Under-reported','Asked an expert instead of deciding','Decided when expert was needed'}==set(result.mistake)


def test_room_visuals_and_wording_consistency():
    from room_viz import case_matrix,bubbles,pictogram,waffles,radar,design_matrix,rings
    from viz_data import scored_view,cards
    frame=scored_view(pd.read_csv('data/results.csv',keep_default_na=False),load_cases(),load_wordings())
    c=cards(frame);order=list(c.configuration)
    fig,table=case_matrix(frame,frame.case_id.iloc[0],order)
    assert len(fig.frames)==15 and fig.layout.transition.duration==300
    assert len(table)==6*15
    assert len(fig.frames[-1].data[0].x)==90
    scatter,data=bubbles(frame,order)
    assert [f.name for f in scatter.frames]==['W1','W2','W3','W4','W5']
    assert scatter.layout.transition.duration==600
    for _,row in data.iterrows():
        subset=frame[frame.configuration.eq(row.configuration)&frame.wording_id.eq(row.Wording)&~frame.invalid]
        distinct=subset.groupby('case_id').decision.nunique()
        assert abs(row['consistency %']-100*distinct.eq(1).mean())<.0051
    unit,counts=pictogram(frame,order[0],True)
    assert counts.Squares.sum()==100
    assert counts.Tests.sum()==len(frame[frame.configuration.eq(order[0])])
    assert len(unit.frames[-1].data[0].marker.color)==100
    waffle,cases=waffles(frame,order)
    assert len(cases)==240 and all(len(t.x)==40 for t in waffle.data)
    fingerprint,_=radar(frame,order)
    assert fingerprint.layout.showlegend and len(fingerprint.data)==6
    matrix,_,n=design_matrix(frame)
    assert n==600 and len(matrix.layout.annotations)==4
    gauge=rings(c.iloc[0],True)
    assert gauge.layout.transition.duration==800
    assert len([t for t in gauge.data if t.type=='indicator'])==2
    assert all(t.value==0 for t in gauge.data if t.type=='indicator')


def test_room_rings_skip_animation_on_rerun(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import plotly.graph_objects as go
    monkeypatch.setenv('QMS_RESULTS_PATH','data/results.csv')
    animated=[];original=go.Figure.to_html
    def capture(fig,*args,**kwargs):
        animated.append(go.Figure(fig))
        return original(fig,*args,**kwargs)
    monkeypatch.setattr(go.Figure,'to_html',capture)
    app=AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    assert len([f for f in animated if f.data[0].type=='pie'])==6
    animated.clear();dashboard_run(app)
    assert not app.exception
    assert not any(f.data[0].type=='pie' for f in animated)
    assert app.session_state['room_rings_animated'] is True
    app.button(key='room_explore').click()
    dashboard_run(app)
    assert not app.exception and app.sidebar.radio[0].value=='Explore'


def test_animation_state_is_independent_and_loops(monkeypatch):
    import report_room as room
    state={}
    monkeypatch.setattr(room.st,'session_state',state)
    assert room.next_frame('matrix_loop',3,'case-one')==(0,False)
    assert room.next_frame('bubble_loop',5,'wordings')==(0,False)
    room.toggle_pause('matrix_loop')
    assert room.next_frame('matrix_loop',3,'case-one')==(0,True)
    assert room.next_frame('bubble_loop',5,'wordings')==(1,False)
    assert state['matrix_loop_index']==0
    room.toggle_pause('matrix_loop')
    assert room.next_frame('matrix_loop',3,'case-one')==(1,False)
    assert room.next_frame('matrix_loop',3,'case-one')==(2,False)
    assert room.next_frame('matrix_loop',3,'case-one')==(0,False)
    assert room.next_frame('matrix_loop',3,'new-filter')==(0,False)


def test_pause_shows_complete_matrix_and_overall_bubbles(monkeypatch):
    import streamlit as st
    import plotly.graph_objects as go
    from functools import wraps
    from streamlit.testing.v1 import AppTest
    from viz_data import cards,scored_view
    monkeypatch.setenv('QMS_RESULTS_PATH','data/results.csv')
    rendered={};original=st.plotly_chart
    @wraps(original)
    def capture(fig,*args,**kwargs):
        rendered[kwargs.get('key')]=go.Figure(fig)
        return original(fig,*args,**kwargs)
    monkeypatch.setattr(st,'plotly_chart',capture)
    app=AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    app.button(key='pause_matrix').click()
    dashboard_run(app)
    assert not app.exception
    assert app.button(key='pause_matrix').label=='▶ Resume'
    assert len(rendered['matrix_chart'].data[0].x)==90
    app.button(key='pause_bubbles').click()
    dashboard_run(app)
    assert not app.exception
    assert app.button(key='pause_bubbles').label=='▶ Resume'
    overall=cards(scored_view(pd.read_csv('data/results.csv',keep_default_na=False),load_cases(),load_wordings())).set_index('configuration')
    fig=rendered['bubble_chart']
    assert len(fig.data)==6
    for trace in fig.data:
        assert trace.x[0]==overall.loc[trace.name,'accuracy %']
        assert trace.y[0]==overall.loc[trace.name,'consistency %']
    app.button(key='pause_outcomes').click()
    dashboard_run(app)
    assert not app.exception
    assert len(rendered['outcome_chart'].data[0].marker.color)==100
    for fig in rendered.values():
        assert not fig.layout.updatemenus and not fig.layout.sliders
        assert fig.layout.paper_bgcolor=='rgba(0,0,0,0)'
        assert fig.layout.font.color=='#E2E8F0'
    app.button(key='pause_matrix').click()
    dashboard_run(app)
    assert not app.exception and app.button(key='pause_matrix').label=='⏸ Pause'


def test_report_room_polish_and_filter_navigation(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from report_room import EXPLANATIONS
    monkeypatch.setenv('QMS_RESULTS_PATH','data/results.csv')
    app=AppTest.from_file('app.py').run(timeout=30)
    assert not app.exception
    assert list(EXPLANATIONS)==['matrix','bubbles','outcomes','waffle','radar','design']
    app.get('button_group')[0].set_value(['Pulse oximetry'])
    dashboard_run(app)
    tests=app.metric[0].value
    app.button(key='room_explore').click()
    dashboard_run(app)
    assert not app.exception
    assert app.button(key='back_to_room').label=='← Back to Report Room'
    next(g for g in app.get('button_group') if g.key=='filter_device_category').set_value(['glucose_meter'])
    dashboard_run(app)
    app.button(key='back_to_room').click()
    dashboard_run(app)
    assert not app.exception and app.metric[0].value==tests
    assert app.session_state['story_device']=='Pulse oximetry'
    app.button(key='room_explore').click()
    dashboard_run(app)
    assert not app.exception and app.session_state['filter_device_category']==['glucose_meter']


def test_polished_chart_readability():
    from room_viz import bubbles,waffles,radar,case_matrix
    from viz_data import scored_view,cards,COLORS
    frame=scored_view(pd.read_csv('data/results.csv',keep_default_na=False),load_cases(),load_wordings())
    order=list(cards(frame).configuration)
    fig,_=bubbles(frame,order)
    assert tuple(fig.layout.xaxis.range)==(40,100)
    assert tuple(fig.layout.yaxis.range)==(0,100)
    assert not fig.layout.shapes
    assert all(t.opacity==.3 for t in fig.data if t.mode=='lines')
    assert all(t.text for t in fig.data if t.mode=='markers+text')
    stable,_=waffles(frame,order)
    assert stable.layout.xaxis.title.text=='Complaints'
    assert all(len(set(t.y))==1 for t in stable.data)
    assert all(set(t.marker.color)<=set([COLORS['outcomes']['correct'],COLORS['outcomes']['acceptable']]) for t in stable.data)
    fingerprint,_=radar(frame,order)
    assert fingerprint.layout.polar.radialaxis.showticklabels is False
    matrix,table=case_matrix(frame,frame.case_id.iloc[0],order)
    for record,color in zip(table.itertuples(),matrix.data[0].marker.color):
        if record.Decision=='ESCALATE':assert color==COLORS['outcomes']['acceptable']
        elif record.Correct:assert color==COLORS['outcomes']['correct']


def test_expert_review_metadata_and_unchanged_case_values():
    import csv
    import hashlib
    from pathlib import Path
    with Path('data/test_cases.csv').open(encoding='utf-8-sig',newline='') as source:
        records=list(csv.reader(source))
    header=records[0]
    assert header[-2:]==['label_status','reviewed_by']
    reviewer='Sal (ISO 13485 Lead Auditor, SaMD compliance)'
    assert len(records[1:])==40
    assert all(row[-2:]==['EXPERT_REVIEWED',reviewer] for row in records[1:])
    # Baseline captured before the metadata update, covering all other columns.
    payload=json.dumps([row[:-2] for row in records],ensure_ascii=False,separators=(',',':')).encode()
    assert hashlib.sha256(payload).hexdigest()=='bc9e676b61242086b3f9945dcf643761eb9098c52b7e17bb959e70bd80df05ba'
    assert validate(verbose=False)


@pytest.mark.parametrize('column,value,message',[
    ('label_status','UNREVIEWED','unsupported label_status'),
    ('reviewed_by','','reviewed_by must name the reviewer'),
    ('reviewed_by','   ','reviewed_by must name the reviewer'),
])
def test_review_metadata_validation(column,value,message,capsys):
    cases=load_cases().copy()
    cases.loc[0,column]=value
    assert not validate(cases,load_wordings())
    output=capsys.readouterr().out
    assert 'Test cases row 2 (G01)' in output and message in output


@pytest.mark.parametrize('column',['label_status','reviewed_by'])
def test_review_metadata_required_columns(column,capsys):
    assert not validate(load_cases().drop(columns=[column]),load_wordings())
    assert f'missing required column {column}' in capsys.readouterr().out
