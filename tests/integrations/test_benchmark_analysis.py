from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from maya_sawa.services import benchmark_analysis


def test_model_sees_only_selected_pages_and_keeps_technical_numbers():
    client = Mock()
    client.chat.completions.create.return_value.choices = [SimpleNamespace(
        message=SimpleNamespace(content='''{"claims":[{
            "page":2,"segment":"foundry","dimension":"technology","direction":"neutral",
            "claim":"公司預計下半年量產 2 奈米","evidence":"2 奈米製程預計於下半年量產"
        }]}''')
    )]
    source = ["去年營業收入為新台幣三億元。", "2 奈米製程預計於下半年量產。"]
    pages = benchmark_analysis.select_pages(source)
    claims = benchmark_analysis.propose(client, pages, "2330", "台積電")
    assert claims[0]["codes"] == ["2330"]
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "三億元" not in prompt
    assert "2 奈米製程" in prompt
    client.chat.completions.create.return_value.choices[0].message.content = (
        client.chat.completions.create.return_value.choices[0].message.content.replace(
            "2 奈米製程預計於下半年量產", "已於上半年量產"
        )
    )
    with pytest.raises(ValueError, match="verbatim"):
        benchmark_analysis.propose(client, pages, "2330", "台積電")


def test_retries_do_not_send_a_report_with_an_existing_proposal(monkeypatch):
    conn = Mock()
    conn.scalar.return_value = b"pdf bytes"
    monkeypatch.setattr(benchmark_analysis, "document_pages", lambda _: ["2 奈米製程預計於下半年量產。"])
    reports, inbox = Mock(), Mock()
    reports.save_extracted.return_value = ({"id": "report-1", "status": "claims_pending"}, True)
    inbox.has_proposal.return_value = True
    monkeypatch.setattr(benchmark_analysis, "market_reports_db", reports)
    monkeypatch.setattr(benchmark_analysis, "market_report_claims_inbox_db", inbox)
    client = Mock()
    status = benchmark_analysis.process_filing(conn, {
        "company_name": "台積電", "code": "2330", "filename": "annual.pdf",
        "fiscal_year": 2025, "sha256": "original", "source_url": "https://doc.twse.com.tw/",
    }, client)
    assert status == "submitted"
    client.chat.completions.create.assert_not_called()
    inbox.submit.assert_not_called()
