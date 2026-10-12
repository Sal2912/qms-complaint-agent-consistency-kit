"""Read source CSVs without modifying them."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent

def read_clean(path):
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str, keep_default_na=False)
    df.columns = df.columns.str.strip()
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    df = df.loc[~df.eq('').all(axis=1)]
    df = df.loc[~df.eq(pd.Series(df.columns, index=df.columns)).all(axis=1)]
    df['device_category'] = df.case_id.map(lambda x: 'pulse_oximetry' if x.startswith('P') else 'glucose_meter' if x.startswith('G') else 'unknown')
    return df.reset_index(drop=True)

def load_cases(path=None):
    return read_clean(path or ROOT / 'data/test_cases.csv')

def load_wordings(path=None):
    return read_clean(path or ROOT / 'data/wordings_cases.csv')
