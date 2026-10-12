"""Validate the answer key and five paraphrases per case."""
from data_utils import load_cases, load_wordings

ACCEPTED_LABEL_STATUSES = {"EXPERT_REVIEWED"}

def validate(cases=None, wordings=None, verbose=True):
    c = load_cases() if cases is None else cases
    w = load_wordings() if wordings is None else wordings
    errors = []
    if len(c) != 40 or c.case_id.nunique() != 40:
        errors.append(f'Expected 40 unique cases; rows={len(c)}, unique={c.case_id.nunique()}')
    for column in ['label_status', 'reviewed_by']:
        if column not in c.columns:
            errors.append(f'Test cases: missing required column {column}')
    for i, row in c.iterrows():
        if 'label_status' in c.columns and row.label_status not in ACCEPTED_LABEL_STATUSES:
            errors.append(f'Test cases row {i + 2} ({row.case_id}): unsupported label_status {row.label_status!r}; expected EXPERT_REVIEWED')
        if 'reviewed_by' in c.columns and (not isinstance(row.reviewed_by, str) or not row.reviewed_by.strip()):
            errors.append(f'Test cases row {i + 2} ({row.case_id}): reviewed_by must name the reviewer')
        allowed = row.allowed_decisions.split('|')
        for value in [row.expected_decision] + [a for a in row.acceptable_alternatives.split('|') if a]:
            if value not in allowed:
                errors.append(f'Test cases row {i + 2} ({row.case_id}): decision {value!r} not allowed')
        if row.difficulty.lower() == 'borderline' and row.expect_uncertainty.upper() != 'Y':
            errors.append(f'Test cases row {i + 2} ({row.case_id}): borderline requires expect_uncertainty Y')
    for i, row in c[c.case_id.duplicated(False)].iterrows():
        errors.append(f'Test cases row {i + 2}: duplicate case_id {row.case_id}')
    for case_id in c.case_id:
        group = w[w.case_id == case_id]
        if len(group) != 5 or set(group.wording_id) != {'W1','W2','W3','W4','W5'}:
            errors.append(f'Wordings {case_id}: expected W1-W5 exactly once; rows={(group.index + 2).tolist()}, ids={group.wording_id.tolist()}')
    for i, row in w[~w.case_id.isin(c.case_id)].iterrows():
        errors.append(f'Wordings row {i + 2}: unknown case_id {row.case_id}')
    if verbose:
        for column in ['device_category','difficulty','expected_decision','source_type']:
            print(f'{column}:\n{c[column].value_counts().to_string()}')
        for error in errors:
            print('FAIL:', error)
        print(f'{"FAIL" if errors else "PASS"}: {len(c)} cases, {len(w)} wordings')
    return not errors

if __name__ == '__main__':
    raise SystemExit(0 if validate() else 1)
