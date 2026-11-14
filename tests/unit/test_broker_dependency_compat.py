"""The Celery worker must be able to open its Redis broker channel with the pinned packages.

kombu is not a direct dependency; an unpinned rebuild pulled kombu 5.7.0, whose Redis transport
refuses redis-py < 6.1.0 at runtime (VersionMismatch), so the production worker could not start.
pip does not flag this because the constraint lives in kombu's optional "redis" extra.
"""
from importlib.metadata import requires, version

from packaging.requirements import Requirement


def test_installed_redis_satisfies_kombu_redis_extra():
    redis_version = version("redis")
    specs = [Requirement(r) for r in requires("kombu") or [] if r.startswith("redis") and 'extra == "redis"' in r]
    assert specs, "kombu declares no redis extra"
    for spec in specs:
        assert spec.specifier.contains(redis_version, prereleases=True), (version("kombu"), str(spec), redis_version)


def test_kombu_redis_channel_accepts_installed_redis_client():
    from kombu.transport import redis as transport

    channel = object.__new__(transport.Channel)  # the version gate runs before any connection is opened
    assert channel._get_client() is not None


def test_requirements_pin_the_broker_stack():
    pins = {line.split("==")[0].strip().lower(): line.split("==")[1].strip()
            for line in open("requirements.txt") if "==" in line and not line.lstrip().startswith("#")}
    for package in ("celery", "kombu", "redis"):
        assert package in pins, f"{package} must be pinned in requirements.txt"
