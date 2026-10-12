"""Shared variant metadata and backward-compatible result backfill."""
DEFAULT_VARIANT = 'V2_zeroshot_rag'
VARIANTS = {
    'V1_zeroshot_norag': {'prompt_style':'zero_shot', 'rag':'no', 'max_turns':1},
    'V2_zeroshot_rag': {'prompt_style':'zero_shot', 'rag':'yes', 'max_turns':5},
    'V3_cot_norag': {'prompt_style':'cot', 'rag':'no', 'max_turns':1},
    'V4_cot_rag': {'prompt_style':'cot', 'rag':'yes', 'max_turns':5},
}

def backfill_variants(frame):
    """Add metadata only; preserve every pre-existing result value."""
    frame = frame.copy()
    if 'variant' not in frame:
        frame['variant'] = DEFAULT_VARIANT
    else:
        frame['variant'] = frame.variant.fillna('').replace('', DEFAULT_VARIANT)
    unknown = set(frame.variant) - set(VARIANTS)
    if unknown:
        raise ValueError(f'Unknown variants: {sorted(unknown)}')
    for column in ['prompt_style','rag']:
        expected = frame.variant.map(lambda v: VARIANTS[v][column])
        if column not in frame:
            frame[column] = expected
        else:
            missing = frame[column].isna() | frame[column].eq('')
            frame.loc[missing, column] = expected[missing]
            if frame[column].ne(expected).any():
                raise ValueError(f'Inconsistent {column} metadata for variant')
    return frame
