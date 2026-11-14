"""Client PDFs embed a TrueType font (DejaVu Sans from matplotlib) so ², ≤, ≥, κ, – and · always render."""
import pytest
from pypdf import PdfReader

from tests.unit._report_run import report_run

SPECIAL = ["²", "≤", "≥", "κ", "–", "·"]


def pdf_fonts(path) -> set[tuple[str, bool]]:
    """(BaseFont, embedded) for every font used on any page."""
    found = set()
    for page in PdfReader(path).pages:
        for ref in ((page.get("/Resources") or {}).get("/Font") or {}).values():
            font = ref.get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None and font.get("/DescendantFonts"):
                descriptor = font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor is not None else {}
            found.add((str(font.get("/BaseFont")), any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3"))))
    return found


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_scientific_report_embeds_every_font(run):
    _, _, pdf, text, _, _ = run
    fonts = pdf_fonts(pdf)
    assert fonts and all(embedded for _, embedded in fonts), fonts
    assert all("DejaVuSans" in name for name, _ in fonts), fonts
    assert "km²" in text and "≤" in text and "≥" in text and "·" in text


def test_every_special_character_renders_and_extracts(tmp_path):
    from app.services.reporting.scientific_report import _Writer, write_pdf
    writer = _Writer()
    writer.heading("Heading " + " ".join(SPECIAL), 1)
    writer.para("Body " + " ".join(SPECIAL))
    writer.table(["Column"], [[" ".join(SPECIAL)]])
    path = tmp_path / "glyphs.pdf"
    write_pdf(writer, path)
    text = " ".join(page.extract_text() for page in PdfReader(path).pages)
    for char in SPECIAL:
        assert text.count(char) >= 3, char
    assert all(embedded for _, embedded in pdf_fonts(path))
