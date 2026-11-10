import unittest
from maya_sawa.tw_benchmark_filings import listed_files, pdf_path

class FilingsTest(unittest.TestCase):
    def test_selects_shareholder_annual_report_by_fiscal_year(self):
        html = 'readfile2("F","2330","2025_2330_20260604F04.pdf"); readfile2("F","2330","2026_2330_20260604F01.pdf");'
        self.assertEqual(listed_files(html, "2330", 2025, "F"), ["2025_2330_20260604F04.pdf"])

    def test_selects_full_annual_statements_only(self):
        html = ' '.join(f'readfile2("A","6488","{name}.pdf");' for name in
                        ["202503_6488_AI1", "202504_6488_AI1", "202504_6488_AI3", "202504_6488_AIA", "202504_6488_AIC"])
        self.assertEqual(listed_files(html, "6488", 2025, "A"), ["202504_6488_AI1.pdf", "202504_6488_AI3.pdf"])

    def test_download_must_be_local_pdf(self):
        self.assertEqual(pdf_path("<a href='/pdf/file_20261110.pdf'>"), "/pdf/file_20261110.pdf")
        with self.assertRaises(ValueError):
            pdf_path("<a href='https://another.example/pdf/file.pdf'>")
