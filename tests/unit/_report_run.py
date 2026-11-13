"""Shared synthetic engine run for the client-report polish tests."""
import json
import re

import pytest
from docx import Document
from pypdf import PdfReader

from tests.unit.test_scientific_report import _pdf_text, _run


def report_run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("polish")
    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _run(directory, monkeypatch)
    finally:
        monkeypatch.undo()
    pdf = directory / result.output_files["scientific_report_pdf"]["path"]
    docx = Document(directory / result.output_files["scientific_report_word"]["path"])
    docx_text = " ".join([p.text for p in docx.paragraphs] + [c.text for t in docx.tables for row in t.rows for c in row.cells])
    return result, directory, pdf, _pdf_text(pdf), docx, docx_text


def section(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))]
