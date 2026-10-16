"""End-to-end Docker packaging regression (requires a local Docker daemon).

Builds from the actual checkout with harmless untracked sentinels, inspects the
Docker context filesystem, builds the default production image, and scans all
image layers. Cleans only its own sentinel files, probe image and containers.
Run: python scripts/verify_docker_packaging.py --image NAME:TAG
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_image_packaging import load_exceptions, scan_image

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def sentinels(root=ROOT):
    token = 'firris_synthetic_' + uuid.uuid4().hex
    paths = [f'{folder}/{token}.py' for folder in (
        'secrets', 'outputs', 'artifacts', 'data', 'datasets', 'raw-data',
        'private-data', 'docx-files', 'docker-data', 'deploy/certbot/conf',
        'deploy/certbot/www', 'app/secrets', 'app/private-data', 'app/data',
        'app/__pycache__', 'app/.venv', 'app/.git',
    )]
    paths += [f'app/{name}' for name in (
        '.env.' + token, token + '_service_account.json', token + '_credential.json',
        token + '_secret.json', token + '.pem', token + '.key', token + '.p12',
        token + '.pfx', token + '.db', token + '.sqlite', token + '.log',
    )]
    # Avoid overwriting any existing file, including local .env/cookies.txt.
    paths += [f'app/secrets/{token}/.env', f'app/secrets/{token}/cookies.txt']
    created, directories = [], set()
    try:
        for name in paths:
            path = root / name
            parent = path.parent
            while parent != root and not parent.exists():
                directories.add(parent)
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x') as target:
                target.write('# FIRRIS SYNTHETIC PACKAGING SENTINEL; NO CREDENTIALS\n')
            created.append(path)
        yield paths
    finally:
        for path in created:
            path.unlink()
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass  # never remove an existing directory or someone else's files


def context_members(image):
    container = subprocess.check_output(['docker', 'create', image, '/unused'], text=True).strip()
    try:
        process = subprocess.Popen(['docker', 'export', container], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|*') as archive:
                names = {item.name.removeprefix('./') for item in archive}
        finally:
            process.stdout.close()
        if process.wait() != 0:
            raise RuntimeError('Context filesystem export failed')
        return names
    finally:
        subprocess.run(['docker', 'rm', container], check=True, stdout=subprocess.DEVNULL)


def verify_negative_probe():
    """A real built image must fail, even after overwriting its fake key file."""
    image = 'firris-packaging-negative:' + uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix='firris-synthetic-negative-') as folder:
            root = Path(folder)
            marker = '-----BEGIN ' + 'PRIVATE KEY-----'
            (root / 'bad.json').write_text(json.dumps({'type': 'service_account', 'synthetic': True, 'private_key': marker}))
            (root / 'safe.json').write_text(json.dumps({'synthetic': True, 'contains_credentials': False}))
            (root / 'Dockerfile').write_text(
                'FROM scratch\n'
                'COPY bad.json /app/app/innocent.json\n'
                'COPY safe.json /app/app/innocent.json\n'
                'COPY safe.json /app/.env\n'
                'COPY safe.json /opt/credential.json\n'
                'COPY safe.json /opt/synthetic.pfx\n'
                'COPY safe.json /app/private-data/synthetic.json\n'
            )
            subprocess.run(['docker', 'build', '--progress=plain', '-t', image, folder], check=True)
            result = scan_image(image)
            detected = {rule for finding in result['findings'] for rule in finding['rules']}
            required = {'private-key-marker', 'service-account-json', 'dotenv', 'credential-name', 'key-container', 'private-path'}
            if not required <= detected:
                raise RuntimeError('Synthetic negative image was not rejected correctly')
            print('NEGATIVE IMAGE PASS: overwritten synthetic marker and all prohibited payload classes rejected', flush=True)
    finally:
        subprocess.run(['docker', 'image', 'rm', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='nova-georisk-backend:packaging-verified')
    args = parser.parse_args()
    probe = 'firris-packaging-context:' + uuid.uuid4().hex
    try:
        verify_negative_probe()
        with sentinels() as excluded:
            subprocess.run(['docker', 'build', '--progress=plain', '-t', probe, '-f', '-', '.'],
                           input='FROM scratch\nCOPY . /context/\n', text=True, cwd=ROOT, check=True)
            names = context_members(probe)
            if any('context/' + name in names for name in excluded):
                raise RuntimeError('Prohibited synthetic file reached Docker context')
            required = {'app/main.py', 'requirements.txt', 'alembic.ini',
                        'app/db/migrations/env.py', 'app/db/migrations/script.py.mako',
                        'app/services/source_data/firris_catalogue.json'}
            if not {'context/' + name for name in required} <= names:
                raise RuntimeError('Docker context is missing required runtime files')
            forbidden = {'secrets', 'outputs', 'artifacts', 'data', 'datasets', 'raw-data',
                         'private-data', 'docx-files', 'docker-data', '.git', '__pycache__'}
            for name in names:
                path = Path(name)
                if not name.startswith('context/'):
                    continue
                if any(part in forbidden for part in path.parts) or path.name == 'cookies.txt' or path.name.startswith('.env'):
                    raise RuntimeError('Prohibited path reached Docker context')
            print(f'CONTEXT PASS: {len(excluded)} synthetic sentinels excluded; required runtime files present', flush=True)
            subprocess.run(['docker', 'build', '--progress=plain', '-t', args.image, '.'], cwd=ROOT, check=True)
            result = scan_image(args.image, load_exceptions())
            print(json.dumps(result, indent=2, sort_keys=True))
            if result['findings']:
                raise RuntimeError('Production image packaging scan failed')
            print('PACKAGING REGRESSION PASS', flush=True)
    finally:
        subprocess.run(['docker', 'image', 'rm', probe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
