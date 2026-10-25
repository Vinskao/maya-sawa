"""Content regressions, not an automated assertion that investment research is true."""
import json
import re
from pathlib import Path

from maya_sawa.services.market_research import load_seed_records, validate_research_content, SEED_MODEL

ROOT = Path(__file__).resolve().parents[1]
CURRENT = {'TXF', '2330', '6857-JP', '3008', '3081', '3017', 'LITE-US', 'META-US', '3105',
           '3324', '6524-JP', '8996', '3711', '6187', '6442', '6213', '3443', '3167', '2408', '009811'}


def test_all_current_targets_and_retained_research_are_reviewed():
    seeds = load_seed_records()
    assert CURRENT | {'000660-KR'} <= seeds.keys()
    assert 'Codex' in SEED_MODEL  # do not attribute this review to the former seed model
    for code in CURRENT | {'000660-KR'}:
        data = seeds[code]
        assert data['asOf'] == '2026-10-25', code
        assert len(json.dumps(data, ensure_ascii=False)) <= 20000
        validate_research_content(json.dumps(data, ensure_ascii=False))
        # General ETFs now use the explicitly requested allocation-only contract.
        if data.get('kind') == 'etf':
            assert code == '009811'
            assert data['allocations']
            assert 'lean' not in data and 'assessment' not in data
            assert 'supplyChain' not in data and 'technology' not in data
            continue
        assert '反方' in data['leanReason'], code
        assert '因果橋' in data['leanReason'], code
        assert '研究草稿' in data['basis'] or '六項' in data['basis'], code
        assert len(data['watch']) >= 3
        assert all('—' in item for item in data['watch']), code
        ids = {m.group(0) for item in data['sources'] for m in [re.match(r'S\d+', item['label'])] if m}
        assert len(ids) >= 3, code
        for graph in ('supplyChain', 'technology'):
            assert re.search(r'\|[^|\n]+\|', data[graph]), (code, graph)
            assert set(re.findall(r'\bS\d+\b', data[graph])) <= ids, (code, graph)
            assert re.search(r'\bS\d+\b', data[graph]), (code, graph)


def test_removes_false_linear_roadmaps_and_obsolete_claims():
    seeds = load_seed_records()
    assert 'subgraph' in seeds['3017']['technology']
    assert 'subgraph' in seeds['3105']['technology']
    assert 'subgraph' in seeds['6524-JP']['technology']
    assert 'ETF' in seeds['009811']['summary']
    assert '2026Q3' in seeds['2330']['assessment']['delivery']['note']
    assert '2026Q3' in seeds['META-US']['assessment']['delivery']['note']
    assert '2026Q3' in seeds['2408']['assessment']['delivery']['note']
    for data in seeds.values():
        assert '模型知識截至' not in data.get('basis', '')
        assert '需 EDINET key' not in json.dumps(data, ensure_ascii=False)


def test_companion_evidence_ledger_covers_the_published_records():
    ledger = json.loads((ROOT / 'maya_sawa/data/market_research_review_20261025.json').read_text(encoding='utf-8'))
    assert CURRENT | {'000660-KR'} <= ledger['records'].keys()
    for code, item in ledger['records'].items():
        if item.get('kind') == 'etf':
            assert item['publicationStatus'] == 'allocation-only'
            assert item['allocations'] == load_seed_records()[code]['allocations']
            assert item['sourceLimitations']
            continue
        assert item['claims'] and item['comparison'] and item['counterargument'], code
        assert set(item['scenarios']) == {'bull', 'base', 'bear'}
        assert len(item['qualityGates']) == 6
        assert item['sourceLimitations']


def test_operational_direction_follows_existing_rule_and_discloses_valuation_gap():
    for code, data in load_seed_records().items():
        if data.get('kind') == 'etf':
            assert 'lean' not in data
            continue
        views = [item['view'] for item in data['assessment'].values()]
        expected = '買' if views.count('順風') >= 2 and '逆風' not in views else '賣' if views.count('逆風') >= 2 else '中立'
        assert data['lean'] == expected, code
        assert '未估市場隱含預期' in data['leanReason'], code


def test_real_snapshot_distinguishes_inventory_risk_and_quarter_lag():
    fixture = json.loads((ROOT / 'tests/fixtures/research_review_20261025.json').read_text(encoding='utf-8'))
    seeds = load_seed_records()
    # The captured aggregate is Q2 even though the reviewed official disclosure is Q3.
    assert fixture['financials']['2330']['quarterly'][0]['period'] == '2026Q2'
    assert '2026Q3' in seeds['2330']['assessment']['delivery']['note']
    assert '66.4%' in seeds['2330']['assessment']['delivery']['note']
    assert fixture['financials']['3105']['monthly'][0]['period'] == '2026-09'
    assert round(fixture['financials']['3105']['monthly'][0]['yoyPercent'], 2) == 29.97
    assert '183.44' in seeds['3105']['assessment']['delivery']['note']
    assert '出貨反而' in seeds['2408']['assessment']['cycle']['note']
    assert 'FCF −21.2' in seeds['META-US']['assessment']['delivery']['note']
    assert fixture['semanticSearchStatus'] == 503


def test_actual_review_seeds_upgrade_previous_public_record_without_overwriting_human_edits(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.market_ai_analysis_db import MarketAiAnalysisDatabase
    from maya_sawa.services.market_research import seed_research

    fixture = json.loads((ROOT / 'tests/fixtures/research_review_20261025.json').read_text(encoding='utf-8'))
    database = MarketAiAnalysisDatabase(create_engine(f"sqlite:///{tmp_path / 'review.db'}"))
    previous = fixture['previousResearch2330']
    assert previous['asOf'] == '2026-10-18'
    database.save('research', '2330', 'previous seed', json.dumps(previous, ensure_ascii=False), 0, 'seed')
    # A human-edited research record must survive this deployment, even if it is older.
    database.save('research', '3167', 'Analyst', json.dumps(previous, ensure_ascii=False), 0, 'owner')
    seeds = load_seed_records()
    assert seed_research(database, seeds) == {'inserted': 19, 'updated': 1, 'kept': 1}
    current = database.read('research', '2330')['analysis']
    assert current['revision'] == 2
    assert current['model'] == SEED_MODEL
    assert json.loads(current['content']) == seeds['2330']
    assert json.loads(database.read('research', '3167')['analysis']['content']) == previous
    assert json.loads(database.read('research', '009811')['analysis']['content']) == seeds['009811']
    assert seed_research(database, seeds) == {'inserted': 0, 'updated': 0, 'kept': 21}
