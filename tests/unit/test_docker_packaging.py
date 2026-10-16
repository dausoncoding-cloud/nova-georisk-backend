"""Synthetic packaging attacks; no actual credentials or private data."""
import io
import json
import tarfile

import pytest

from scripts.check_image_packaging import inspect_bytes, load_exceptions, path_rules, scan_tar


@pytest.mark.parametrize('path', [
    'app/.env', 'app/app/.env.production', 'opt/deploy/.env.local',
    'app/secrets/innocent.py', 'app/app/private-data/innocent.py',
    'app/data/sample.csv', 'app/datasets/sample.csv', 'app/raw-data/sample.csv',
    'app/artifacts/sample.json', 'app/docx-files/sample.docx',
    'app/docker-data/db.bin', 'app/deploy/certbot/conf/cert.pem',
    'app/cookies.txt', 'app/app/provider_service_account.json',
    'app/app/my_credential.json', 'app/app/secret.json',
    'opt/leak.pem', 'opt/leak.key', 'opt/leak.p12', 'opt/leak.pfx',
    'app/tests/test_any.py', 'app/docs/readme.md', 'app/app/__pycache__/code.pyc',
    'app/outputs/anything.json', 'app/scripts/seed_pre_phase0_fixture.py',
])
def test_prohibited_payload_paths(path):
    assert path_rules(path)


@pytest.mark.parametrize('path', [
    'app/app/main.py', 'app/requirements.txt', 'app/alembic.ini',
    'app/app/db/migrations/env.py', 'app/app/db/migrations/script.py.mako',
    'app/app/services/source_data/firris_catalogue.json',
    'app/scripts/admin_identity.py', 'app/scripts/admin_entitlements.py',
    'app/scripts/reconcile_legacy_projects.py', 'app/scripts/validate_production_environment.py',
])
def test_required_payload_paths(path):
    assert not path_rules(path)


def test_empty_output_mount_is_allowed_but_contents_are_not():
    assert not path_rules('app/outputs', is_file=False)
    assert path_rules('app/outputs/nested/file.bin')


def test_markers_and_service_account_are_detected_across_chunks():
    marker = b'-----BEGIN ' + b'PRIVATE KEY-----'  # harmless, incomplete marker
    for value, rule in [(marker, 'private-key-marker'),
                        (b'{"type": "service_account", "synthetic": true}', 'service-account-json')]:
        data = b'x' * (1024 * 1024 - 8) + value
        rules, _ = inspect_bytes(io.BytesIO(data))
        assert rule in rules


def _archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for path, value in files.items():
            member = tarfile.TarInfo(path)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    stream.seek(0)
    return tarfile.open(fileobj=stream)


def test_filesystem_content_not_git_state_drives_scan_and_values_are_redacted():
    value = b'{"type":"service_account","synthetic":"DO_NOT_LOG_THIS_VALUE"}'
    with _archive({'app/app/normal.json': value}) as archive:
        findings, count, _ = scan_tar(archive)
    assert count == 1
    assert findings[0]['rules'] == ['service-account-json']
    assert 'DO_NOT_LOG_THIS_VALUE' not in json.dumps(findings)


def test_reviewed_system_exception_is_bound_to_exact_path_bytes_and_rules():
    value = b'-----BEGIN ' + b'PRIVATE KEY-----'  # simulated parser constant
    rules, digest = inspect_bytes(io.BytesIO(value))
    path = 'usr/lib/synthetic_parser.py'
    policy = {(path, digest): rules}
    with _archive({path: value}) as archive:
        assert scan_tar(archive, policy)[0] == []
    with _archive({path: value + b'changed'}) as archive:
        assert scan_tar(archive, policy)[0]
    with _archive({'app/app/normal.py': value}) as archive:
        assert scan_tar(archive, policy)[0]


def test_policy_cannot_exempt_application_or_unknown_digest(tmp_path):
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps([{'path': 'app/app/leak.py', 'sha256': '0' * 64,
                                   'rules': ['private-key-marker'], 'reason': 'synthetic'}]))
    with pytest.raises(ValueError):
        load_exceptions(policy)


def test_symbolic_link_to_prohibited_location_fails():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        member = tarfile.TarInfo('app/app/link')
        member.type = tarfile.SYMTYPE
        member.linkname = '/run/secrets/key.json'
        archive.addfile(member)
    stream.seek(0)
    with tarfile.open(fileobj=stream) as archive:
        assert scan_tar(archive)[0]


def test_hidden_secret_in_earlier_image_layer_is_still_rejected(monkeypatch):
    from scripts.check_image_packaging import scan_image
    marker = b'-----BEGIN ' + b'PRIVATE KEY-----'
    layers = {}
    for layer, files in [('old/layer.tar', {'app/app/normal.py': marker}),
                         ('new/layer.tar', {'app/app/.wh.normal.py': b''})]:
        with _archive(files) as archive:
            archive.fileobj.seek(0)
            layers[layer] = archive.fileobj.read()
    manifest = [{'Config': 'config.json', 'Layers': list(layers)}]
    files = {**layers, 'manifest.json': json.dumps(manifest).encode(), 'config.json': b'{}'}
    with _archive(files) as archive:
        archive.fileobj.seek(0)
        saved = archive.fileobj.read()
    monkeypatch.setattr('scripts.check_image_packaging.subprocess.check_output', lambda *a, **k: 'sha256:synthetic\n')
    monkeypatch.setattr('scripts.check_image_packaging.subprocess.run', lambda *a, **k: k['stdout'].write(saved))
    result = scan_image('synthetic:never-pulled')
    assert result['layers'] == 2
    assert result['findings'][0]['layer'] == 0
    assert result['findings'][0]['rules'] == ['private-key-marker']


def test_sentinels_are_synthetic_and_cleaned_without_overwriting_existing_files(tmp_path):
    from scripts.verify_docker_packaging import sentinels
    existing = tmp_path / 'secrets' / 'existing.json'
    existing.parent.mkdir()
    existing.write_text('synthetic existing file')
    with pytest.raises(RuntimeError):
        with sentinels(tmp_path) as paths:
            assert len(paths) == 30
            assert all((tmp_path / name).exists() for name in paths)
            assert all('NO CREDENTIALS' in (tmp_path / name).read_text() for name in paths)
            raise RuntimeError('synthetic failure exercises cleanup')
    assert existing.read_text() == 'synthetic existing file'
    assert list(tmp_path.rglob('*')) == [existing.parent, existing]


def test_json_unicode_escaping_cannot_hide_service_account_or_key_marker():
    value = b'{"ty\\u0070e":"service_account","private_key":"\\u002d----BEGIN PRIVATE KEY-----"}'
    with _archive({'app/app/normal.json': value}) as archive:
        findings, _, _ = scan_tar(archive)
    assert set(findings[0]['rules']) == {'private-key-marker', 'service-account-json'}


def test_unparseable_json_cannot_be_silently_certified_safe():
    with _archive({'app/app/normal.json': b'{broken'}) as archive:
        assert 'uninspectable-json' in scan_tar(archive)[0][0]['rules']


def test_dependency_pyc_fingerprint_ignores_only_timestamp_header():
    value = b'x' * 16 + b'synthetic-code-body'
    rules, digest = inspect_bytes(io.BytesIO(value), pyc=True)
    _, same = inspect_bytes(io.BytesIO(b'y' * 16 + value[16:]), pyc=True)
    _, changed = inspect_bytes(io.BytesIO(value + b'changed'), pyc=True)
    assert not rules
    assert digest == same
    assert digest != changed
