"""Provider-independent JSON agent. Mock mode never creates a provider client."""
import json
import random
import time
import threading
import re
from pathlib import Path

# =============================================================================
# SYSTEM PROMPTS — 2 × 2 AGENT VARIANTS (zero-shot/CoT × no-RAG/RAG)
# V2 is the original system prompt, unchanged.
# =============================================================================
PROMPTS = {
    # V1_zeroshot_norag
    'V1_zeroshot_norag': (
        "You are a complaint-triage agent for a medical device manufacturer's quality team. Decide FDA "
        'reportability: REPORTABLE_30DAY, NOT_REPORTABLE, or ESCALATE (when expert judgment is needed). Reply'
        ' with JSON only: '
        '{"action":"final","decision":...,"confidence":...,"needs_expert_review":...,"reasoning":"<max 2 '
        'sentences>"}.'
    ),
    # V2_zeroshot_rag
    'V2_zeroshot_rag': (
        "You are a complaint-triage agent for a medical device manufacturer's quality team. For each "
        'complaint, decide FDA reportability: REPORTABLE_30DAY, NOT_REPORTABLE, or ESCALATE (when expert '
        'judgment is needed). You may look up regulatory guidance first by replying with JSON '
        '{"action":"lookup","topic":"<topic>"}. Topics: mdr_reportability, serious_injury, malfunction, '
        'reportability_pitfalls, not_reportable_examples, escalation. When ready, reply with JSON '
        '{"action":"final","decision":"<one allowed '
        'decision>","confidence":<0-1>,"needs_expert_review":<true|false>,"reasoning":"<max 2 sentences>"}. '
        'Reply with JSON only.'
    ),
    # V3_cot_norag
    'V3_cot_norag': (
        "You are a complaint-triage agent for a medical device manufacturer's quality team. Decide FDA "
        'reportability: REPORTABLE_30DAY, NOT_REPORTABLE, or ESCALATE (when expert judgment is needed). Reply'
        ' with JSON only: '
        '{"action":"final","decision":...,"confidence":...,"needs_expert_review":...,"reasoning":"<max 8 '
        'sentences>"}. Think step by step before deciding. In the reasoning field, work through: 1) Did a '
        'death or serious injury occur, or could one have? 2) Did the device fail to perform as intended? 3) '
        'If the malfunction recurred, would it be likely to cause or contribute to death or serious injury? '
        '4) Is key information missing or disputed? Then give your decision.'
    ),
    # V4_cot_rag
    'V4_cot_rag': (
        "You are a complaint-triage agent for a medical device manufacturer's quality team. For each "
        'complaint, decide FDA reportability: REPORTABLE_30DAY, NOT_REPORTABLE, or ESCALATE (when expert '
        'judgment is needed). You may look up regulatory guidance first by replying with JSON '
        '{"action":"lookup","topic":"<topic>"}. Topics: mdr_reportability, serious_injury, malfunction, '
        'reportability_pitfalls, not_reportable_examples, escalation. When ready, reply with JSON '
        '{"action":"final","decision":"<one allowed '
        'decision>","confidence":<0-1>,"needs_expert_review":<true|false>,"reasoning":"<max 8 sentences>"}. '
        'Reply with JSON only. Think step by step before deciding. In the reasoning field, work through: 1) '
        'Did a death or serious injury occur, or could one have? 2) Did the device fail to perform as '
        'intended? 3) If the malfunction recurred, would it be likely to cause or contribute to death or '
        'serious injury? 4) Is key information missing or disputed? Then give your decision.'
    ),
}
SYSTEM_PROMPT = PROMPTS["V2_zeroshot_rag"]
from variants import DEFAULT_VARIANT, VARIANTS

KNOWLEDGE = json.loads((Path(__file__).parent / 'data/knowledge.json').read_text()) if (Path(__file__).parent / 'data/knowledge.json').exists() else {}
_google_clients = threading.local()
_gates = {}
_gates_lock = threading.Lock()

class ProviderGate:
    """Coordinate request spacing and cooldowns across a model's workers."""
    def __init__(self, interval):
        self.interval = interval
        self.next_request = 0.0
        self.lock = threading.Lock()
        self.daily_error = None

    def acquire(self):
        while True:
            with self.lock:
                if self.daily_error is not None:
                    raise self.daily_error
                wait = self.next_request - time.monotonic()
                if wait <= 0:
                    self.next_request = time.monotonic() + self.interval
                    return
            time.sleep(min(wait, 30))

    def cooldown(self, seconds):
        with self.lock:
            self.next_request = max(self.next_request, time.monotonic() + seconds)

def provider_gate(provider, model):
    with _gates_lock:
        return _gates.setdefault((provider, model), ProviderGate(13.0 if provider == 'google' else 1.0))

def daily_quota_error(exc):
    text = str(exc).lower()
    return any(term in text for term in ['requests per day', 'requestsperday', 'requests_per_day', 'insufficient_quota'])

def retry_delay(exc, attempt):
    """Use provider Retry-After/RetryInfo hints as well as exponential backoff."""
    delays = [2 ** attempt]
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    for header, divisor in [('retry-after', 1), ('retry-after-ms', 1000)]:
        try:
            delays.append(float(headers[header]) / divisor)
        except (KeyError, ValueError, TypeError):
            pass
    text = str(exc)
    for pattern in [r'retryDelay[\"\x27]?\s*:\s*[\"\x27]([\d.]+)s', r'retry in\s+([\d.]+)s']:
        delays.extend(float(value) for value in re.findall(pattern, text, re.I))
    for minutes, seconds in re.findall(r'retry (?:again )?in\s+(\d+)m([\d.]+)s', text, re.I):
        delays.append(int(minutes) * 60 + float(seconds))
    return max(delays) + 1

def safe_error(exc):
    import os
    text = f'{type(exc).__name__}: {exc}'
    for name in ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY']:
        secret = os.getenv(name, '')
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return re.sub(r'AQ\.[A-Za-z0-9_.=-]+', '[REDACTED]', text)

def google_client():
    """Keep a strong client reference for the lifetime of each worker thread."""
    if not hasattr(_google_clients, 'client'):
        import os
        from google import genai
        from google.genai import types
        _google_clients.client = genai.Client(api_key=os.environ['GEMINI_API_KEY'], http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
    return _google_clients.client

def parse_json(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == '{':
            try:
                obj, _ = decoder.raw_decode(text[index:])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                pass
    raise ValueError('No valid JSON object')

def call_model(provider, model, messages):
    if provider == 'mock':
        if 'Topics:' in messages[0]['content'] and random.random() < .4:
            value = {'action':'lookup', 'topic':random.choice(list(KNOWLEDGE))}
        else:
            allowed = messages[1]['content'].split('Allowed decisions: ')[-1].split('|')
            value = {'action':'final','decision':random.choice(allowed),'confidence':round(random.random(), 2), 'needs_expert_review':random.choice([True,False]),'reasoning':'Synthetic random decision for pipeline verification.'}
        return json.dumps(value), 0, 0
    if provider == 'openai':
        from openai import OpenAI
        provider_gate(provider, model).acquire()
        r = OpenAI(max_retries=0).chat.completions.create(model=model, messages=messages)
        return r.choices[0].message.content or '', r.usage.prompt_tokens, r.usage.completion_tokens
    if provider == 'anthropic':
        from anthropic import Anthropic
        provider_gate(provider, model).acquire()
        # Eight-sentence CoT responses need more output room. Preserve V2's budget.
        max_tokens = 4096 if messages[0]['content'] in {PROMPTS['V3_cot_norag'], PROMPTS['V4_cot_rag']} else 1024
        r = Anthropic(max_retries=0).messages.create(model=model, max_tokens=max_tokens, system=messages[0]['content'], messages=messages[1:])
        return ''.join(b.text for b in r.content if hasattr(b,'text')), r.usage.input_tokens, r.usage.output_tokens
    if provider == 'google':
        from google.genai import types
        contents = [types.Content(role='model' if m['role']=='assistant' else 'user', parts=[types.Part(text=m['content'])]) for m in messages[1:]]
        provider_gate(provider, model).acquire()
        r = google_client().models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(system_instruction=messages[0]['content'], tools=[], automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        candidates = getattr(r, 'candidates', None) or []
        content = getattr(candidates[0], 'content', None) if candidates else None
        parts = getattr(content, 'parts', None) or []
        text = ''.join(part.text for part in parts if getattr(part, 'text', None) and not getattr(part, 'thought', False))
        usage = getattr(r, 'usage_metadata', None)
        return text, getattr(usage, 'prompt_token_count', 0) or 0, getattr(usage, 'candidates_token_count', 0) or 0
    raise ValueError(f'Unknown provider: {provider}')

def retryable(exc):
    status = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
    return status in [429,500,502,503,504,529] or any(s in type(exc).__name__.lower() for s in ['ratelimit','servererror','resourceexhausted','serviceunavailable'])

def run_agent(provider, model, case_text, allowed_decisions, model_call=None, knowledge=None, variant=DEFAULT_VARIANT):
    config = VARIANTS[variant]
    max_turns = config['max_turns']
    has_rag = config['rag'] == 'yes'
    call = model_call or call_model
    kb = (KNOWLEDGE if knowledge is None else knowledge) if has_rag else {}
    messages = [{'role':'system','content':PROMPTS[variant]}, {'role':'user','content':case_text + '\nAllowed decisions: ' + '|'.join(allowed_decisions)}]
    result = dict(decision='INVALID', confidence=None, needs_expert_review=False, reasoning='', n_turns=0, tools_used='', input_tokens=0, output_tokens=0, error='')
    used = []
    start = time.monotonic()
    try:
        for turn in range(1,max_turns + 1):
            result['n_turns'] = turn
            for attempt in range(5):
                try:
                    text, inp, out = call(provider, model, messages)
                    break
                except Exception as exc:
                    if daily_quota_error(exc):
                        if model_call is None:
                            gate = provider_gate(provider, model)
                            with gate.lock:
                                gate.daily_error = exc
                        raise
                    if not retryable(exc) or attempt == 4:
                        raise
                    delay = retry_delay(exc, attempt)
                    if model_call is None:
                        provider_gate(provider, model).cooldown(delay)
                    else:
                        time.sleep(delay)
            result['input_tokens'] += inp
            result['output_tokens'] += out
            messages.append({'role':'assistant','content':text})
            try:
                obj = parse_json(text)
            except ValueError:
                if turn == max_turns:
                    result['error'] = 'invalid_json'
                    break
                # Identical recovery message and turn budget for every provider.
                messages.append({'role':'user','content':'Your response did not contain valid JSON. Reply with JSON only, following the system protocol.'})
                continue
            if obj.get('action') == 'lookup':
                if not has_rag:
                    result['error'] = 'lookup_not_allowed'
                    break
                topic = str(obj.get('topic',''))
                used.append(topic)
                messages.append({'role':'user','content':kb.get(topic, 'Unknown topic')})
            elif obj.get('action') == 'final':
                if obj.get('decision') not in allowed_decisions:
                    result['error'] = 'decision_not_allowed'
                elif type(obj.get('needs_expert_review')) is not bool or isinstance(obj.get('confidence'), bool) or not isinstance(obj.get('confidence'), (int,float)) or not 0 <= obj['confidence'] <= 1 or not isinstance(obj.get('reasoning'), str):
                    result['error'] = 'invalid_final_schema'
                else:
                    result.update({k:obj[k] for k in ['decision','confidence','needs_expert_review','reasoning']})
                break
            else:
                result['error'] = 'unknown_action'
                break
        else:
            result['error'] = 'max_turns'
    except Exception as exc:
        result['error'] = safe_error(exc)
    result.update(tools_used='|'.join(used), latency_s=round(time.monotonic()-start,3), transcript=json.dumps(messages))
    return result
