"""test_docs_governance — active docs must not present LEGACY frt-v1 results as current (audit G).

This is REGION-AWARE (audit round-4 G.7): a STRONG active conclusion (主结果 / 10/10 PASS / ✅ valid /
superiority) is only allowed inside a section whose heading marks it legacy/INVALIDATED/Historical.
An inline 'PENDING' on the same line does NOT exempt a strong conclusion in an active region. Softer
items (a bare legacy score, +37.8pp) still pass with a same-line invalidation marker.
"""
import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ['README.md', 'docs/PROJECT_OVERVIEW.md', 'docs/CONTROL_MODES.md',
        'src/hpt_frt/network/report.md']

# a heading (possibly blockquoted, e.g. "> #### Historical ...") that opens a LEGACY region
HEADING = re.compile(r'^\s*>?\s*#{1,6}\s')
LEGACY_HEADING = re.compile(r'INVALIDATED|Historical|失效|legacy|PENDING frt-v2', re.I)

# STRONG active conclusions — must live in a legacy region (inline marker does NOT exempt them)
STRONG = [
    re.compile(r'主结果'),
    re.compile(r'10\s*/\s*10\s*PASS', re.I),
    re.compile(r'✅\s*valid', re.I),
    re.compile(r'valid[-\s]*hardgate', re.I),
    re.compile(r'系统层不需要协调学习'),
    re.compile(r'(国标|GB/?T)[^。\n]{0,6}合规率'),
    re.compile(r'代表性抽查[^。\n]{0,8}通过'),
]
# softer items — allowed if the SAME line carries an invalidation marker
SOFT = [re.compile(r'\+?\s*37\.8\s*pp', re.I), re.compile(r'主方法.*82\.2')]
INLINE_MARKER = re.compile(r'INVALIDATED|失效|已停用|弃用|deprecated|PENDING|historical|历史', re.I)


def _regions(path):
    legacy = False
    for i, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
        if HEADING.match(line):
            legacy = bool(LEGACY_HEADING.search(line))
        yield i, line, legacy


@pytest.mark.parametrize('doc', DOCS)
def test_strong_conclusions_only_in_legacy_regions(doc):
    path = ROOT / doc
    if not path.exists():
        pytest.skip(f'{doc} absent')
    bad = []
    for i, line, in_legacy in _regions(path):
        if in_legacy:
            continue
        # a same-line invalidation framing (e.g. 〔legacy frt-v1 INVALIDATED〕…) also neutralises it
        if INLINE_MARKER.search(line):
            continue
        if any(p.search(line) for p in STRONG):
            bad.append((i, line.strip()[:90]))
    assert not bad, f'{doc}: STRONG active conclusion outside a legacy region:\n' + \
        '\n'.join(f'  L{n}: {t}' for n, t in bad)


@pytest.mark.parametrize('doc', DOCS)
def test_soft_legacy_items_have_inline_marker(doc):
    path = ROOT / doc
    if not path.exists():
        pytest.skip(f'{doc} absent')
    bad = []
    for i, line, in_legacy in _regions(path):
        if in_legacy or INLINE_MARKER.search(line):
            continue
        if any(p.search(line) for p in SOFT):
            bad.append((i, line.strip()[:90]))
    assert not bad, f'{doc}: legacy score/claim without an invalidation marker:\n' + \
        '\n'.join(f'  L{n}: {t}' for n, t in bad)


def test_readme_frtv2_honest_framing():
    """frt-v2 full-320 switching results are now reported (2026-06-23), so the README head must (a)
    present the three DISTINCT metrics (strict_pass / no-fail / NOT_EVALUATED) and (b) never assert a
    bare '国标认证通过率' — that phrase may appear ONLY when explicitly negated. Replaces the old
    'must say PENDING / no valid pass rate' rule, which the frt-v2 results have superseded."""
    head = (ROOT / 'README.md').read_text(encoding='utf-8')[:3000]
    assert 'strict_pass' in head, 'README head must report the frt-v2 strict_pass metric'
    assert ('no-fail' in head or 'effective_pass' in head), 'README head must report the no-fail/effective metric'
    assert ('NOT_EVALUATED' in head or 'NE' in head), 'README head must explain NOT_EVALUATED'
    # the forbidden claim may appear ONLY as a negation (不得称为 / 非 / 不是 / 不可 ... 国标认证通过率)
    for m in re.finditer(r'国标认证通过率', head):
        ctx = head[max(0, m.start() - 14):m.start()]
        assert any(neg in ctx for neg in ('不得', '不是', '非', '不可')), \
            'README must not assert a bare 国标认证通过率 (only negated mentions allowed)'
