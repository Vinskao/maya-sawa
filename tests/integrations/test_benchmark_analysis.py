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


def test_profile_change_reprocesses_existing_filings_and_records_the_version(monkeypatch):
    conn = Mock()
    key = dict(code='2330', filename='annual.pdf', sha256='original')
    conn.execute.return_value.mappings.return_value.all.return_value = [key]
    monkeypatch.setattr(benchmark_analysis.Config, 'OPENAI_API_KEY', 'fixture-key')
    monkeypatch.setattr(benchmark_analysis, 'OpenAI', Mock())
    monkeypatch.setattr(benchmark_analysis, 'process_filing', Mock(return_value='submitted'))
    benchmark_analysis.process_annual_filings(conn)
    query, parameters = conn.execute.call_args_list[0].args
    assert 'analysis_profile IS DISTINCT FROM :profile' in str(query)
    assert parameters['profile'] == 'benchmark-evidence-v2'
    updates = [call.args for call in conn.execute.call_args_list if 'analysis_status=:status' in str(call.args[0])]
    assert updates[0][1]['profile'] == 'benchmark-evidence-v2'


@pytest.mark.parametrize('error_code', ['insufficient_quota', 'credit_balance_exhausted'])
def test_exhausted_quota_stops_the_batch_instead_of_retrying_every_company(monkeypatch, error_code):
    class Exhausted(Exception):
        code = error_code
    conn = Mock()
    conn.execute.return_value.mappings.return_value.all.return_value = [
        dict(code=code, filename=f'{code}.pdf', sha256=code) for code in ('2330', 'NVDA-US')]
    monkeypatch.setattr(benchmark_analysis.Config, 'OPENAI_API_KEY', 'fixture-key')
    monkeypatch.setattr(benchmark_analysis, 'OpenAI', Mock())
    process = Mock(side_effect=Exhausted())
    monkeypatch.setattr(benchmark_analysis, 'process_filing', process)
    benchmark_analysis.process_annual_filings(conn)
    assert process.call_count == 1
