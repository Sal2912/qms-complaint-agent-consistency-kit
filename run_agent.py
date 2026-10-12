"""Concurrent, resumable agent-only experiment runner."""
import argparse
import csv
import os
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from data_utils import ROOT, load_cases, load_wordings
from validate_data import validate
from agent import run_agent
from variants import DEFAULT_VARIANT, VARIANTS, backfill_variants

LEGACY_COLUMNS = 'timestamp provider model case_id device_category wording_id wording_style run decision confidence needs_expert_review reasoning n_turns tools_used input_tokens output_tokens latency_s error transcript'.split()
COLUMNS = LEGACY_COLUMNS + ['variant', 'prompt_style', 'rag']
KEY = ['provider','model','case_id','wording_id','run','variant']
DEFAULT_MODELS = 'anthropic:claude-haiku-5-5'
SIZE_MODELS = 'anthropic:claude-haiku-5-5,anthropic:claude-sonnet-5-5,anthropic:claude-opus-5-5'

def model_pools(models):
    """Give each distinct provider/model its own three-worker pool."""
    return {key: ThreadPoolExecutor(max_workers=3) for key in dict.fromkeys(models)}

def prepare_resume(path):
    """Atomically remove failed attempts before scheduling their replacements."""
    path = Path(path)
    if not path.exists() or not path.stat().st_size:
        return set()
    old = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(old.columns) not in [LEGACY_COLUMNS, COLUMNS]:
        raise ValueError(f'Output schema mismatch: {path}')
    migrated = backfill_variants(old)
    # Preserve historical attempts. Failed keys remain eligible for an appended retry.
    # Analysis selects the latest attempt per key, without deleting stored rows.
    retained = migrated
    if not migrated.equals(old):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, suffix='.csv', delete=False, newline='', encoding='utf-8') as f:
                temporary = Path(f.name)
                retained.to_csv(f, index=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    latest = retained.drop_duplicates(KEY, keep='last')
    completed = latest[latest.error.str.strip().eq('')]
    return {tuple(row[k] for k in KEY) for row in completed.to_dict('records')}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models', default=DEFAULT_MODELS)
    p.add_argument('--variant', choices=list(VARIANTS), default=DEFAULT_VARIANT)
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--limit', type=int, help='Limit number of cases (all five wordings each)')
    p.add_argument('--mock', action='store_true')
    p.add_argument('--out', default='data/results.csv')
    args = p.parse_args()
    cases, wordings = load_cases(), load_wordings()
    if not validate(cases, wordings):
        raise SystemExit(1)
    if args.runs < 1 or (args.limit is not None and args.limit < 1):
        p.error('--runs and --limit must be positive')
    try:
        models = [('mock','random-agent')] if args.mock else [tuple(x.strip().split(':',1)) for x in args.models.split(',')]
        if any(len(x)!=2 or x[0] not in {'openai','anthropic','google','mock'} or not x[1] for x in models):
            raise ValueError()
    except ValueError:
        p.error('--models must contain provider:model entries')
    if not args.mock and any(provider=='mock' for provider, _ in models):
        p.error('Use --mock for synthetic runs')
    load_dotenv(ROOT / '.env', override=True)
    keys = {'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY','google':'GEMINI_API_KEY'}
    for provider, _ in models:
        if provider != 'mock' and not os.getenv(keys[provider], '').strip():
            p.error(f'Missing non-empty {keys[provider]} in .env')
    cases = cases.head(args.limit) if args.limit else cases
    items = wordings[wordings.case_id.isin(cases.case_id)].merge(cases[['case_id','allowed_decisions']], on='case_id').to_dict('records')
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        done = prepare_resume(path)
    except ValueError as exc:
        p.error(str(exc))
    jobs = [(provider,model,row,run) for provider,model in dict.fromkeys(models) for row in items for run in range(1,args.runs+1) if (provider,model,row['case_id'],row['wording_id'],str(run),args.variant) not in done]
    turns = VARIANTS[args.variant]['max_turns']
    print(f'Variant: {args.variant}; planned items: {len(jobs)}; estimated calls: {len(jobs)*(1 if turns == 1 else 2)} (1–{turns} turns each, retries may add calls); resumed rows: {len(done)}', flush=True)
    lock = threading.Lock()
    count = 0
    with path.open('a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if f.tell() == 0:
            writer.writeheader()
            f.flush()
        def work(job):
            nonlocal count
            provider, model, row, run = job
            result = run_agent(provider,model,row['case_text'],row['allowed_decisions'].split('|'),variant=args.variant)
            result.update(timestamp=datetime.now(timezone.utc).isoformat(),provider=provider,model=model,case_id=row['case_id'],device_category=row['device_category'],wording_id=row['wording_id'],wording_style=row['wording_style'],run=run)
            result.update(variant=args.variant,prompt_style=VARIANTS[args.variant]['prompt_style'],rag=VARIANTS[args.variant]['rag'])
            with lock:
                writer.writerow(result)
                f.flush()
                count += 1
                if count % 25 == 0 or count == len(jobs):
                    print(f'Completed {count}/{len(jobs)}', flush=True)
        pools = model_pools(models)
        try:
            futures = [pools[job[:2]].submit(work,job) for job in jobs]
            for future in as_completed(futures):
                future.result()
        finally:
            for pool in pools.values():
                pool.shutdown()
    print(f'Results: {path}')

if __name__ == '__main__':
    main()
