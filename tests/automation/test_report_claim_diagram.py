from xml.etree import ElementTree

from maya_sawa.public_scripts.report_claim_diagram import render_claim_diagram


def test_render_claim_diagram_contains_every_claim_as_svg_text():
    claims = [
        {"direction": "tailwind", "page": 7, "claim": "已建立 HBM4 量產體制"},
        {"direction": "headwind", "page": 3, "claim": "基板供應與成本 <壓力>"},
        {"direction": "neutral", "page": 6, "claim": "評估替代方案 & 成本"},
    ]
    svg = ElementTree.fromstring(render_claim_diagram("SK 海力士", claims))
    text = list(svg.itertext())
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert all(f"p.{claim['page']}  {claim['claim']}" in text for claim in claims)
    assert all(label in text for label in ("待審提案", "順風  1", "逆風  1", "中性  1"))
