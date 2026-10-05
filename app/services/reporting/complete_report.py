"""One evidence document rendered consistently as PDF, Excel, CSV and DOCX."""
from __future__ import annotations

import json
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.services.reporting.report_builder import export_csv, generate_excel_report

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("w", W)


def flatten(value, prefix=""):
    if isinstance(value, dict):
        return [record for key, item in value.items() for record in flatten(item, f"{prefix}.{key}".strip("."))]
    if isinstance(value, list):
        # Arrays in provenance are inventories, not new scientific observations.
        return [record for index, item in enumerate(value) for record in flatten(item, f"{prefix}[{index}]")]
    return [{"field": prefix, "value": value if value is not None else "not supplied / undefined"}]


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) if isinstance(value, (dict, list)) else str(value)


def _spreadsheet_safe(frame):
    return frame.map(lambda value: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value)


def _write_docx(sections, path):
    """Minimal ECMA-376 package with plain escaped WordprocessingML content."""
    document = ET.Element(f"{{{W}}}document")
    body = ET.SubElement(document, f"{{{W}}}body")
    for title, lines in sections:
        for index, text in enumerate([title, *lines]):
            paragraph = ET.SubElement(body, f"{{{W}}}p")
            run = ET.SubElement(paragraph, f"{{{W}}}r")
            if index == 0:
                ET.SubElement(ET.SubElement(run, f"{{{W}}}rPr"), f"{{{W}}}b")
            ET.SubElement(run, f"{{{W}}}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = text
    section = ET.SubElement(body, f"{{{W}}}sectPr")
    ET.SubElement(section, f"{{{W}}}pgSz", {f"{{{W}}}w": "11906", f"{{{W}}}h": "16838"})
    ET.SubElement(section, f"{{{W}}}pgMar", {f"{{{W}}}top": "1134", f"{{{W}}}right": "1134", f"{{{W}}}bottom": "1134", f"{{{W}}}left": "1134"})
    types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    relationships = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", relationships)
        document_xml = ET.tostring(document, encoding="utf-8", xml_declaration=True)
        ET.fromstring(document_xml)
        archive.writestr("word/document.xml", document_xml)


def complete_report(directory, common, metadata, summary, provenance, analytics, interpretation):
    overview = [{"field": key, "value": value} for key, value in common.items()]
    class_areas = analytics["class_areas"]
    metrics = flatten({key: value for key, value in summary.items() if key not in {"delivery", "interpretation"}})
    sources = flatten(provenance)
    gis = flatten(metadata)
    validation = flatten(summary.get("validation") or {"independent_validation": "not supplied; approval is not independent scientific validation"})
    sections = [
        ("FIRRIS evidence report", [f"{row['field']}: {_serialize(row['value'])}" for row in overview]),
        ("Methodology, source identity, QA, licensing and uncertainty", [f"{row['field']}: {_serialize(row['value'])}" for row in sources] or ["Source metadata not supplied; none is inferred."]),
        ("Units, CRS, grid and temporal semantics", [f"{row['field']}: {_serialize(row['value'])}" for row in gis] or ["GIS metadata not supplied."]),
        ("Computed result summary", [f"{row['field']}: {_serialize(row['value'])}" for row in metrics]),
        ("Class areas and explicit denominators", [_serialize(row) for row in class_areas] or ["No delivered categorical raster area evidence; sample values do not imply spatial area."]),
        ("Quantitative series", [_serialize(item) for item in analytics["series"]] or ["No observed time series is supplied; no trend is inferred."]),
        ("Validation and its scope", [f"{row['field']}: {_serialize(row['value'])}" for row in validation]),
        ("Evidence-linked interpretation", [item["text"] + " Evidence: " + ", ".join(item["evidence_refs"]) for item in interpretation["findings"]]),
        ("Review recommendations", [item["text"] + " Evidence: " + ", ".join(item["evidence_refs"]) for item in interpretation["recommendations"]]),
        ("External data and scientific limitations", interpretation["limitations"]),
    ]
    styles = getSampleStyleSheet()
    story = []
    for title, lines in sections:
        story.append(Paragraph(escape(title), styles["Heading2"]))
        for line in lines:
            story.append(Paragraph(escape(line), styles["BodyText"]))
        story.append(Spacer(1, 8))
    pdf = directory / "complete-evidence-report.pdf"
    SimpleDocTemplate(str(pdf), pagesize=A4).build(story)
    docx = directory / "complete-evidence-report.docx"
    _write_docx(sections, docx)
    excel = directory / "complete-evidence-report.xlsx"
    narrative = [{"section": title, "text": line} for title, lines in sections for line in lines]
    sheets = {"Overview": pd.DataFrame(overview), "Class areas": pd.DataFrame(class_areas),
        "Quantitative series": pd.DataFrame([{"product_key": item["product_key"], "kind": item["kind"], "units": item["units"], "basis": item["basis"], "points": _serialize(item["points"]), "evidence_refs": _serialize(item["evidence_refs"])} for item in analytics["series"]]),
        "Results": pd.DataFrame(metrics), "Validation": pd.DataFrame(validation),
        "Provenance": pd.DataFrame([{**row, "value": _serialize(row["value"])} for row in sources]),
        "Interpretation": pd.DataFrame(narrative)}
    # Excel's fixed cell-width limit must not silently discard long evidence.
    for sheet, frame in sheets.items():
        if any(len(str(value)) > 32767 for value in frame.to_numpy().reshape(-1)):
            raise ValueError(f"Report evidence exceeds Excel cell capacity in {sheet}")
    generate_excel_report({name: _spreadsheet_safe(frame) for name, frame in sheets.items()}, str(excel))
    csv = directory / "complete-evidence-report.csv"
    export_csv(_spreadsheet_safe(pd.DataFrame(narrative)), str(csv))
    return {"complete_report_pdf": (pdf, "application/pdf"),
            "complete_report_excel": (excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "complete_report_csv": (csv, "text/csv"),
            "complete_report_word": (docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
