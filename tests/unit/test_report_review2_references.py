"""Client review 2: reference class names in tables, CSV and figures."""
import csv

import pytest

from tests.unit._report_run import report_run, section


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory, organization_name="Example Consulting Ltd", sample_report=True)

INDEPENDENT = ("Reference: new open water (optical)", "Reference: no new open water")
INTERNAL = ("SAR screening label: flood candidate", "SAR screening label: not flood candidate")


# Reference column names, the same in the report, CSV and figures.
def test_reference_columns_per_scope():
    from app.services.validation.accuracy_tables import reference_columns
    assert reference_columns("independent_optical") == INDEPENDENT
    assert reference_columns("internal_screening") == INTERNAL
    assert reference_columns("internal_supplied")[0].startswith("Supplied label")


def test_report_tables_name_the_reference_classes(run):
    _, _, _, text, _, _ = run
    accuracy = section(text, "9. Accuracy assessment", "10. Limitations")
    assert all(name in accuracy for name in INDEPENDENT) and "Reference: flood candidate" not in text
    assert all(name in text for name in INTERNAL)  # internal tables (Appendix A after the move)


def test_csv_and_figures_use_the_same_reference_names(run):
    result, directory, _, _, _, _ = run
    for scope, names in (("independent_optical", INDEPENDENT), ("internal_screening", INTERNAL)):
        with open(directory / result.output_files[f"accuracy_{scope}_confusion"]["path"], newline="") as handle:
            header = next(csv.reader(handle))
        assert list(names) == [h for h in header if h in names], header
        svg = (directory / result.output_files[f"figure_{scope}_confusion_svg"]["path"]).read_text()
        for name in names:
            label, value = name.split(": ")
            assert label in svg and value in svg
