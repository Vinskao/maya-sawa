"""Mermaid flowcharts from the research records, drawn as images for the social posts."""
import json
import shutil
from pathlib import Path

import pytest

from maya_sawa.services.social.diagram import mermaid_sources, parse_flowchart, to_dot

DIAGRAMS = json.loads((Path(__file__).parent / 'fixtures' / 'research_diagrams.json').read_text(encoding='utf-8'))


def test_every_mermaid_diagram_in_a_research_record_is_found_without_naming_fields():
    """Unified lookup (2026-11-02): walk the JSON, take every string that is a flowchart; ETF records may have none."""
    record = {'name': 'x', 'summary': 'flowchart is a word', 'supplyChain': 'flowchart TB\n  A["a"] --> B["b"]',
              'nested': {'deep': [{'technology': 'graph LR\n  A --> B'}]}, 'watch': ['flowchart-ish text']}
    assert [(path, source.split('\n')[0]) for path, source in mermaid_sources(record)] == [
        ('supplyChain', 'flowchart TB'), ('nested.deep.0.technology', 'graph LR')]
    assert mermaid_sources({'kind': 'etf', 'name': 'x'}) == []


def test_parse_handles_nodes_labelled_edges_subgraphs_and_inline_definitions():
    graph = parse_flowchart('''flowchart TB
  N0["封裝廠製程需求｜投資決策"]
  N1["萬潤自動化設備"]
  N0 -->|功能／需求傳導，非訂單證明| N1
  subgraph G0["並行製程能力 S1"]
    T0["精密對位"]
    T1[未加引號的標籤]
  end
  N1 --> T0 --> T1
  N1 -.->|待驗證| X["行內定義"]''')
    assert graph['direction'] == 'TB'
    assert graph['nodes']['N0'] == '封裝廠製程需求｜投資決策' and graph['nodes']['T1'] == '未加引號的標籤'
    assert graph['nodes']['X'] == '行內定義'
    assert graph['clusters'] == [{'id': 'G0', 'title': '並行製程能力 S1', 'nodes': ['T0', 'T1']}]
    assert graph['edges'] == [('N0', 'N1', '功能／需求傳導，非訂單證明', False), ('N1', 'T0', '', False),
                              ('T0', 'T1', '', False), ('N1', 'X', '待驗證', True)]


def test_dot_output_is_escaped_and_keeps_clusters_and_dashed_edges():
    dot = to_dot('flowchart LR\n  A[he said "hi" ok] -.->|x| B\n  subgraph G["組"]\n    B\n  end')
    assert dot.startswith('digraph') and 'rankdir=LR' in dot
    assert 'subgraph cluster_G' in dot and 'style=dashed' in dot
    assert 'he said \\"hi\\" ok' in dot


def test_a_subgraph_without_an_id_uses_the_whole_text_as_its_title():
    graph = parse_flowchart('flowchart TB\n  subgraph 並行製程能力\n    A["a"]\n  end')
    assert graph['clusters'][0]['title'] == '並行製程能力' and graph['clusters'][0]['nodes'] == ['A']


def test_all_fifty_real_research_diagrams_parse_into_connected_nodes_and_dot():
    count = 0
    for code, sources in DIAGRAMS.items():
        for source in sources:
            graph = parse_flowchart(source)
            assert graph['nodes'], code
            assert all(a in graph['nodes'] and b in graph['nodes'] for a, b, _, _ in graph['edges']), code
            assert to_dot(source).count('->') == len(graph['edges'])
            count += 1
    assert count == 50


@pytest.mark.skipif(shutil.which('dot') is None, reason='Graphviz is installed in the Docker image, not on this machine')
def test_rendering_returns_a_portrait_card_png():
    import io
    from PIL import Image
    from maya_sawa.services.social.diagram import render_diagram_card
    image = Image.open(io.BytesIO(render_diagram_card('6187 萬潤 · 供應鏈', DIAGRAMS['6187'][0])))
    assert image.size == (1080, 1350)
