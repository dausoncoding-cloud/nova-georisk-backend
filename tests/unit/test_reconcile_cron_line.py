"""Fix round r5, item 5, updated in r14: the documented reconcile cron line is the one tested on this server (R13 record
§14 step 5), the payments checklist repeats it verbatim, it finds the live api container at run time (no release
folder or compose file in the line), and every failure leaves a RECONCILE-FAILED line in the log."""
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R13 = ROOT / "docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R13.md"
CHECKLIST = ROOT / "docs/ABLINER_PAYMENTS_RELEASE_RECORD.md"
RELEASE_CHECKLIST = ROOT / "docs/FIRRIS_DEPLOYMENT_CHECKLIST.md"
LOG = "/home/deploy/nova-ops/logs/abliner-reconcile.log"
FIND_LIVE_API = (
    "c=$(docker ps -q --filter label=com.docker.compose.project=firris-release-2f1b2dc "
    "--filter label=com.docker.compose.service=firris-2f1b2dc-api --filter health=healthy); n=$(echo $c | wc -w); "
    'if [ "$n" -ne 1 ]; then echo "RECONCILE-FAILED: $n healthy api containers"; exit 1; fi; '
)
RUN = 'docker exec "$c" python -m app.services.abliner.cli reconcile'
ON_ERROR = ' || { r=$?; echo "RECONCILE-FAILED: exit $r"; exit $r; }'


def _cron_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines()
            if "abliner.cli reconcile" in line and re.match(r"^\s*(?:\d+|\*)(?:/\d+)? \S+ \S+ \S+ \S+ ", line)]


def test_the_r13_record_and_the_checklist_carry_the_same_single_tested_line():
    r13, checklist = _cron_lines(R13), _cron_lines(CHECKLIST)
    assert len(r13) == 1 and checklist == r13


def test_the_line_finds_the_live_container_logs_failures_and_uses_a_lock():
    (line,) = _cron_lines(R13)
    fields = line.split(" ", 5)
    assert fields[:5] == ["*/10", "*", "*", "*", "*"]
    words = shlex.split(fields[5])
    assert words[:4] == ["flock", "-n", "/tmp/abliner-reconcile.lock", "sh"] and words[4] == "-c"
    assert words[5] == "date -u -Iseconds; " + FIND_LIVE_API + RUN + " --apply" + ON_ERROR
    assert words[6:] == [">>", LOG, "2>&1"]
    assert "%" not in line  # cron turns % into a newline
    assert "/var/log/nova" not in line
    # nothing release-specific: no release folder, compose file or env file that a later release would leave stale
    for stale in ("nova-releases", "compose.active.json", "compose.candidate.json", "deployment-inputs.env", "docker compose"):
        assert stale not in line


def test_the_dry_run_command_is_the_same_invocation_without_apply_run_as_cron_runs_it():
    text = R13.read_text()
    dry = "env -i PATH=/usr/bin:/bin /bin/sh -c '" + "date -u -Iseconds; " + FIND_LIVE_API + RUN + ON_ERROR + "'"
    assert ("     " + dry + "\n") in text
    assert "/var/log/nova/abliner-reconcile.log" not in text + CHECKLIST.read_text()


def test_the_failure_signal_and_the_release_checklist_item_are_documented():
    text = R13.read_text()
    assert "RECONCILE-STALE-OR-FAILED" in text and "RECONCILE-OK" in text
    assert "Check that the reconcile cron path still points at the live release" in RELEASE_CHECKLIST.read_text()
