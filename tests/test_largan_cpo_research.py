"""Regressions for the user-requested Largan CPO evidence review."""
import json
from pathlib import Path

from maya_sawa.services.market_research import load_seed_records, validate_research_content

DATA = Path(__file__).parents[1] / 'maya_sawa/data'


def test_largan_cpo_is_a_separate_optical_coupling_branch_with_direct_sources():
    record = load_seed_records()['3008']
    assert record['asOf'] == '2026-10-26'
    validate_research_content(json.dumps(record, ensure_ascii=False))
    assert '稜鏡微透鏡陣列' in record['technology']
    assert '光纖陣列' in record['technology']
    assert 'subgraph' in record['technology']
    assert 'ELS' in record['supplyChain']
    assert '電光調變' in record['supplyChain']
    assert '被動光學' in record['assessment']['technology']['note']
    assert '未確認' in record['assessment']['delivery']['note']
    assert record['lean'] == '中立'
    sources = {s['label'].split()[0]: s for s in record['sources']}
    assert 'sinotrade.com.tw/richclub/' in sources['S4']['url']
    assert '2026-04-28' in sources['S4']['label']
    assert 'developer.nvidia.com' in sources['S5']['url']
    assert any('插入損耗' in item for item in record['watch'])
    assert any('營收' in item and '量產' in item for item in record['watch'])


def test_largan_ledger_separates_company_catalogue_from_article_claims_and_unknown_commercials():
    ledger = json.loads((DATA / 'market_research_review_20261025.json').read_text(encoding='utf-8'))['records']['3008']
    assert ledger['reviewedAt'] == '2026-10-26'
    claims = {c['id']: c for c in ledger['claims']}
    assert claims['C4']['kind'] == 'company-disclosure'
    assert claims['C5']['kind'] == 'secondary-commentary'
    assert claims['C6']['kind'] == 'architecture-reference'
    assert claims['C5']['sourceIds'] == ['S4']
    assert '未確認' in ledger['sourceLimitations'][0]
    assert 'partial' in {g['status'] for g in ledger['qualityGates']}
    fixture = json.loads((Path(__file__).parent / 'fixtures/largan_cpo_sources_20261026.json').read_text(encoding='utf-8'))
    assert fixture['article']['contentUpdatedAt'] == '2026-04-28'
    assert fixture['article']['independentlyVerifiedSupplierRelationships'] is False
    assert '五節正文' in claims['C5']['statement']
