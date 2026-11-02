from pathlib import Path

from maya_sawa.services.job_alerts.cake_parser import is_cake_alert, parse_cake_alert
from maya_sawa.services.job_alerts.salary import Verdict

HTML = (Path(__file__).parent / 'fixtures' / 'cake_job_alert.html').read_text(encoding='utf-8')


def test_sender_check_is_exact():
    assert is_cake_alert('notifications@no-reply.cake.me')
    assert is_cake_alert('Cake <notifications@no-reply.cake.me>')
    assert not is_cake_alert('notifications@no-reply.cake.me.evil.com')
    assert not is_cake_alert('someone@gmail.com')


def test_parses_only_job_items_with_section_and_salary():
    jobs = parse_cake_alert(HTML)
    assert [j.title for j in jobs] == [
        'EC (資深)後端工程師 - TL',
        '資深後端工程師（Python）- AY',
        'Cloud Service Staff Backend Engineer - TL',
        'Senior DevOps Engineer - Agnes',
        '神祕職缺',
    ]
    assert jobs[0].section == '後端開發人員'
    assert jobs[3].section == 'DevOps／系統管理員'
    assert jobs[0].salary_text == '1.2M ~ 2.2M TWD/年'
    assert jobs[4].salary_text is None
    assert jobs[0].url.startswith('https://email.no-reply.cake.me/')


def test_verdicts_per_job():
    verdicts = [j.decision.verdict for j in parse_cake_alert(HTML)]
    assert verdicts == [Verdict.NEEDS_REVIEW, Verdict.REJECTED, Verdict.PASSED, Verdict.PASSED, Verdict.NEEDS_REVIEW]
