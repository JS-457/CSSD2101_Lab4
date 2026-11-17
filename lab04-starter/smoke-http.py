#!/usr/bin/env python3
"""Exercise an owned packaged server using loopback, temporary storage, and OS ports."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
JAVA = str(Path(os.environ['JAVA_HOME']) / 'bin/java')
parser = argparse.ArgumentParser(description=__doc__)
# The same script is supplied at the collection's lab04 level and inside the
# standalone solution download; neither location requires a publication edit.
PROJECT = ROOT / 'solution' if (ROOT / 'solution/pom.xml').is_file() else ROOT
parser.add_argument('--jar', type=Path, default=PROJECT / 'target/lab04-solution-1.0.0.jar',
                    help='Packaged solution JAR to test')
JAR = parser.parse_args().jar.resolve()

def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

def start(directory, suffix):
    log = directory / ('server-' + suffix + '.log')
    with log.open('w') as output:
        process = subprocess.Popen([JAVA, '-jar', str(JAR), '--server.port=0', '--server.address=127.0.0.1',
                                    '--catalogue.file=' + str(directory / 'books.json')],
                                   stdout=output, stderr=subprocess.STDOUT, cwd=directory)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        text = log.read_text()
        match = re.search(r'Tomcat started on port (\d+)', text)
        if match:
            return process, 'http://127.0.0.1:' + match.group(1)
        if process.poll() is not None:
            raise AssertionError('Packaged server exited: ' + text)
        time.sleep(0.1)
    stop(process)
    raise AssertionError('Packaged server startup timed out: ' + log.read_text())

def call(base, method, route, body=None):
    encoded = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + route, data=encoded, method=method,
                                     headers={'Content-Type': 'application/json'})
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        text = response.read().decode()
        return response.status, dict(response.headers), json.loads(text) if text else None

with tempfile.TemporaryDirectory(prefix='cssd2101-lab04-smoke-') as owned:
    directory = Path(owned)
    process, base = start(directory, 'first')
    try:
        assert call(base, 'GET', '/api/books')[2] == []
        body = {'title': 'Packaged Java', 'priceCents': 1299, 'format': 'PRINT'}
        status, headers, created = call(base, 'POST', '/api/books', body)
        assert status == 201
        route = headers['Location']
        assert route == '/api/books/' + created['id']
        assert call(base, 'GET', route)[2] == created
        invalid = dict(body, priceCents=-1)
        assert call(base, 'PUT', route, invalid)[0] == 400
        assert call(base, 'GET', route)[2] == created
        changed = dict(body, title='Survives restart', format='EBOOK')
        status, _, replacement = call(base, 'PUT', route, changed)
        assert status == 200 and replacement['id'] == created['id']
    finally:
        stop(process)
    process, base = start(directory, 'restart')
    try:
        assert call(base, 'GET', route)[2] == replacement
        assert call(base, 'DELETE', route)[0] == 204
        assert call(base, 'GET', route)[0] == 404
        assert call(base, 'DELETE', route)[0] == 404
    finally:
        stop(process)
    process, base = start(directory, 'deleted')
    try:
        assert call(base, 'GET', '/api/books')[2] == []
    finally:
        stop(process)
print('PASS packaged HTTP: create/read/replace/delete, invalid-write preservation, two restarts')
