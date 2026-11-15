"""Client decision (2026-11-15): the product is called FRRIS. "FIRRIS" must not reach users.

Internal identifiers keep the old spelling on purpose (module/file names, Python/TS symbols, engine_key
"firris", science_version "firris-science-*", DB names, env vars, Redis keys, git tags, Docker image
names, API paths, machine codes such as FIRRIS_ACQUISITION_QA_FAILED). Only the exceptions listed in
KEPT below may still contain the word "FIRRIS" in a string.
"""
import ast
import json
import re
import zipfile
from pathlib import Path

import pytest

from tests.unit._report_run import report_run

ROOT = Path(__file__).resolve().parents[2]
WORD = re.compile(r"\bFIRRIS\b")
# Client style (2026-11-15): no article before the name; write "the/this FRRIS analysis".
ARTICLE = re.compile(r"\b(?:a|an)\s+FRRIS\b", re.IGNORECASE)
# (file, string) pairs kept on purpose; each is stored data, not text written for users.
KEPT = {
    ("app/models/project.py", "FIRRIS"),        # projects.analysis_module default: stored value (5 production rows)
    ("app/platform/registry.py", "FIRRIS"),     # engines.name seed: mirrors the stored engine row
}


def _strings(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_no_user_visible_string_or_docstring_in_the_app_says_firris():
    offenders = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        if "migrations" in path.parts:  # historical migrations are never edited
            continue
        rel = str(path.relative_to(ROOT))
        for line, value in _strings(path):
            if (WORD.search(value) and (rel, value) not in KEPT) or ARTICLE.search(value):
                offenders.append(f"{rel}:{line}: {value[:80]!r}")
    assert not offenders, "\n".join(offenders)


def test_kept_exceptions_still_exist():
    # Remove an entry from KEPT when its source no longer needs it.
    for rel, value in KEPT:
        assert any(v == value for _, v in _strings(ROOT / rel)), (rel, value)


@pytest.mark.parametrize("name", ["nova-browser-api.json", "nova-internal-api.json"])
def test_openapi_exports_say_frris(name):
    text = (ROOT / "openapi" / name).read_text()
    assert not WORD.search(text), WORD.search(text) and text[max(0, WORD.search(text).start() - 80):WORD.search(text).end() + 20]
    assert "FRRIS" in text
    assert not ARTICLE.search(text), ARTICLE.search(text) and ARTICLE.search(text).group(0)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_client_outputs_say_frris(run):
    result, directory, _, text, _, docx_text = run
    for body in (text, docx_text):
        assert not WORD.search(body) and "FRRIS" in body and not ARTICLE.search(body)
    for key, entry in result.output_files.items():
        assert not WORD.search(str(entry.get("label", ""))), (key, entry.get("label"))
        assert not Path(entry["path"]).name.startswith("firris-"), entry["path"]  # download file names
        cartography = (entry.get("gis_metadata") or {}).get("cartography") or {}
        assert not WORD.search(json.dumps(cartography)), key
    with zipfile.ZipFile(directory / result.output_files["report_package"]["path"]) as archive:
        readme = archive.read("README.txt").decode()
        names = archive.namelist()
    assert not WORD.search(readme) and "FRRIS" in readme and not ARTICLE.search(readme)
    assert not any(Path(name).name.startswith("firris-") for name in names)
    assert result.output_files["report_package"]["path"].endswith("frris-result-package.zip")


def test_engine_display_name_is_frris_but_identifiers_are_unchanged():
    from app.platform.engines.firris import FIRRISEngineAdapter
    from app.platform.registry import display_name

    adapter = FIRRISEngineAdapter()
    assert adapter.key == "firris" and adapter.name == "FRRIS"
    assert display_name("firris", "FIRRIS") == "FRRIS" and display_name("wras", "WRAS") == "WRAS"


@pytest.mark.parametrize("text, bad", [("Submit a FRRIS analysis", True), ("an FRRIS project", True),
                                       ("A  FRRIS run", True), ("the FRRIS analysis", False), ("data FRRIS", False)])
def test_article_rule_catches_a_and_an(text, bad):
    assert bool(ARTICLE.search(text)) is bad
