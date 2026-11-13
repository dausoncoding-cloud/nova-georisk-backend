"""2.4 report dependencies: pinned, importable, headless, and writable config inside the image."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_report_dependencies_are_pinned_exactly():
    requirements = (ROOT / "requirements.txt").read_text()
    assert re.search(r"^matplotlib==3\.11\.2$", requirements, re.M)
    assert re.search(r"^python-docx==1\.2\.0$", requirements, re.M)


def test_runtime_image_uses_agg_and_a_config_dir_owned_by_nova():
    dockerfile = (ROOT / "Dockerfile").read_text()
    runtime = dockerfile[dockerfile.index("AS runtime"):dockerfile.index("AS test")]
    assert "MPLBACKEND=Agg" in runtime
    assert "MPLCONFIGDIR=/home/nova/.config/matplotlib" in runtime
    setup = runtime[runtime.index("adduser"):runtime.index("USER nova")]
    assert "mkdir -p /app/outputs /home/nova/.config/matplotlib" in setup
    assert "chown -R nova:nova /app /home/nova" in setup


def test_figures_module_forces_the_headless_backend():
    import matplotlib
    from app.services.reporting import figures  # noqa: F401  (import sets the backend)
    assert matplotlib.get_backend().lower() == "agg"
