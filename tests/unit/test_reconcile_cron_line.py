"""Fix round r5, item 5: the documented reconcile cron line is the one tested for this server (R13 record §14 step 5),
the payments checklist repeats it verbatim, and it has none of the earlier line's faults."""
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R13 = ROOT / "docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R13.md"
CHECKLIST = ROOT / "docs/ABLINER_PAYMENTS_RELEASE_RECORD.md"
LIVE = "/home/deploy/nova-releases/firris-2f1b2dc"
LIVE_COMPOSE = (f"docker compose --project-name firris-release-2f1b2dc --env-file {LIVE}/deployment-inputs.env "
                f"-f {LIVE}/compose.active.json --profile workers-after-quiet-point exec -T firris-2f1b2dc-api ")


def _cron_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines()
            if "abliner.cli reconcile" in line and re.match(r"^\s*(?:\d+|\*)(?:/\d+)? \S+ \S+ \S+ \S+ ", line)]


def test_the_r13_record_and_the_checklist_carry_the_same_single_tested_line():
    r13, checklist = _cron_lines(R13), _cron_lines(CHECKLIST)
    assert len(r13) == 1 and checklist == r13


def test_the_line_uses_the_live_compose_file_a_real_log_path_and_a_lock():
    (line,) = _cron_lines(R13)
    fields = line.split(" ", 5)
    assert fields[:5] == ["*/10", "*", "*", "*", "*"]
    words = shlex.split(fields[5])
    assert words[:4] == ["flock", "-n", "/tmp/abliner-reconcile.lock", "sh"] and words[4] == "-c"
    assert words[5] == "date -u -Iseconds; " + LIVE_COMPOSE + "python -m app.services.abliner.cli reconcile --apply"
    assert words[6:] == [">>", "/home/deploy/nova-ops/logs/abliner-reconcile.log", "2>&1"]
    assert "%" not in line  # cron turns % into a newline
    assert "/var/log/nova" not in line


def test_the_dry_run_command_is_the_same_invocation_without_apply():
    text = R13.read_text()
    assert ("     " + LIVE_COMPOSE + "python -m app.services.abliner.cli reconcile\n") in text
    assert "/var/log/nova/abliner-reconcile.log" not in text + CHECKLIST.read_text()
