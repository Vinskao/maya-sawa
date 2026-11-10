"""TWSE electronic filing catalog and bounded PDF retrieval."""

import re
from urllib.parse import urlencode
from urllib.request import urlopen

HOST = "https://doc.twse.com.tw"
LIMIT = 64 * 1024 * 1024


def catalog_url(code, fiscal_year, kind):
    filing_year = fiscal_year + (kind == "F")
    return HOST + "/server-java/t57sb01?" + urlencode({
        "step": 1, "colorchg": 1, "co_id": code, "year": filing_year - 1911,
        "seamon": "", "mtype": kind,
    })


def listed_files(html, code, fiscal_year, kind):
    prefix = f"{fiscal_year}_{code}_" if kind == "F" else f"{fiscal_year}04_{code}_"
    suffix = r"\d{8}F04" if kind == "F" else r"AI[13]"
    valid = re.compile(re.escape(prefix) + suffix + r"\.pdf")
    return sorted({
        filename for market, issuer, filename in re.findall(
            r'readfile2\("([AF])","(\d+)","([^"]+)"\)', html
        ) if market == kind and issuer == code and valid.fullmatch(filename)
    })


def pdf_path(html):
    match = re.search(r"""href=['"](/pdf/[\w.-]+\.pdf)['"]""", html, re.ASCII)
    if not match:
        raise ValueError("TWSE did not return a PDF download link")
    return match[1]


def read(url, limit):
    with urlopen(url, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("TWSE response exceeded size limit")
    return data


def listing(code, fiscal_year, kind):
    source = catalog_url(code, fiscal_year, kind)
    html = read(source, 512 * 1024).decode("cp950", errors="replace")
    if "function readfile2" not in html:
        raise ValueError("Unexpected TWSE filing catalog response")
    return source, listed_files(html, code, fiscal_year, kind)


def download(code, kind, filename):
    url = HOST + "/server-java/t57sb01?" + urlencode({
        "step": 9, "kind": kind, "co_id": code, "filename": filename,
    })
    page = read(url, 512 * 1024).decode("cp950", errors="replace")
    pdf = read(HOST + pdf_path(page), LIMIT)
    if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-2048:]:
        raise ValueError("TWSE download was not a complete PDF")
    return pdf
