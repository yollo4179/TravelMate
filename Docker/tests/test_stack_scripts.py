"""Bootstrap and shell regression checks; Docker is stubbed for portability cases."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

DOCKER_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', DOCKER_DIR / 'stack-bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_standard_ca_and_jwt_without_host_configuration(self):
        bootstrap.prepare(self.state)
        self.assertIn('BEGIN CERTIFICATE', (self.state / 'ca-bundle.pem').read_text())
        secret = (self.state / 'runtime.env').read_text()
        self.assertTrue(secret.startswith('JWT_SECRET='))
        self.assertGreater(len(secret), 70)
        self.assertEqual((self.state / 'runtime.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((self.state / 'proxy.compose.yml').read_text()), {'services': {}})
        bootstrap.prepare(self.state)
        self.assertEqual((self.state / 'runtime.env').read_text(), secret)

    def test_custom_ca_is_preserved(self):
        os.environ['STACK_CUSTOM_CA'] = '1'
        (self.state / 'ca-bundle.pem').write_text('custom CA')
        bootstrap.prepare(self.state)
        self.assertEqual((self.state / 'ca-bundle.pem').read_text(), 'custom CA')

    def test_proxy_mapping_is_optional_and_host_network_only_when_requested(self):
        os.environ['HTTPS_PROXY'] = 'http://proxy.test:8080'
        with patch.object(bootstrap.socket, 'gethostbyname', return_value='192.0.2.1'):
            bootstrap.prepare(self.state)
            settings = json.loads((self.state / 'proxy.compose.yml').read_text())['services']
            self.assertEqual(settings['embedding']['extra_hosts'], {'proxy.test': '192.0.2.1'})
            self.assertNotIn('network', settings['server']['build'])
            os.environ['STACK_BUILD_NETWORK'] = 'host'
            bootstrap.prepare(self.state)
            settings = json.loads((self.state / 'proxy.compose.yml').read_text())['services']
            self.assertEqual(settings['server']['build']['network'], 'host')
        self.assertIn('systemProp.https.proxyPort=8080', (self.state / 'gradle.properties').read_text())


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='travelmate scripts ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo with spaces'
        self.scripts = self.repo / 'Docker'
        self.scripts.mkdir(parents=True)
        for source in DOCKER_DIR.glob('*.sh'):
            shutil.copyfile(source, self.scripts / source.name)
        (self.scripts / 'init').mkdir()
        (self.scripts / 'init/01-schema.sql').write_text('-- test schema\n')
        (self.scripts / 'migrations').mkdir()
        (self.scripts / 'migrations/20261013_add_planning_context.sql').write_text('-- planning migration\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        self.env = dict(os.environ)
        for name in ['SSL_CERT_FILE', 'HTTP_PROXY', 'HTTPS_PROXY', 'STACK_STATE_DIR',
                     'BUILDX_CONFIG', 'STACK_WAIT_TIMEOUT', 'MSYS_NO_PATHCONV', 'MSYS2_ARG_CONV_EXCL']:
            self.env.pop(name, None)
        self.env.update(PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FAKE_LOG=str(self.log))
        self.executable('docker', f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({{'args': args, 'pathconv': os.environ.get('MSYS_NO_PATHCONV')}}) + '\\n')
if args[0] == 'run':
    mount = next(x for x in args if x.startswith('type=bind,source=') and x.endswith('target=/stack'))
    source = mount.split('source=', 1)[1].rsplit(',target=', 1)[0]
    if source.startswith('C:'):
        source = source[2:]
    state = pathlib.Path(source)
    (state / 'runtime.env').write_text('JWT_SECRET=test-only\\n')
    (state / 'proxy.compose.yml').write_text('{{"services":{{}}}}')
if args[0] == 'inspect':
    if os.environ.get('FAKE_STATE') == 'missing':
        sys.exit(1)
    print(os.environ.get('FAKE_STATE', 'healthy'))
''')
        for command in ('python', 'python3'):
            self.executable(command, '#!/bin/bash\necho "Host Python must not be called" >&2\nexit 93\n')

    def executable(self, name, text):
        file = self.bin / name
        file.write_text(text)
        file.chmod(0o755)

    def run_script(self, name, *args):
        return subprocess.run(['/bin/bash', str(self.scripts / name), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_start_without_host_python_or_linux_ca_path(self):
        result = self.run_script('stack-up.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.scripts / 'build/stack/init/02-planning-context.sql').read_text(),
            '-- planning migration\n',
        )
        calls = self.calls()
        helper = next(x['args'] for x in calls if x['args'][0] == 'run')
        self.assertIn('/bootstrap.py', helper)
        self.assertTrue(any('repo with spaces' in x and 'target=/stack' in x for x in helper))
        self.assertTrue(any(x['args'][-2:] == ['up', '-d'] for x in calls))

    def test_git_bash_native_paths_and_msys_conversion_disabled(self):
        self.executable('cygpath', '#!/bin/bash\nprintf "C:%s\\n" "$2"\n')
        self.executable('uname', '#!/bin/bash\necho MINGW64_NT-10.0\n')
        result = self.run_script('stack-up.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        helper = next(x for x in calls if x['args'][0] == 'run')
        self.assertEqual(helper['pathconv'], '1')
        self.assertTrue(any(x.startswith('type=bind,source=C:/') for x in helper['args']))
        compose = next(x['args'] for x in calls if '--env-file' in x['args'])
        self.assertTrue(compose[compose.index('--env-file') + 1].startswith('C:/'))

    def test_invalid_explicit_ca_stops_before_compose_up(self):
        self.env['SSL_CERT_FILE'] = '/does-not-exist.pem'
        result = self.run_script('stack-up.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Fix or unset it', result.stderr)
        self.assertFalse(any('up' in x['args'] for x in self.calls()))

    def test_wait_needs_no_python_and_succeeds_when_all_healthy(self):
        result = self.run_script('stack-wait.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('All four services', result.stdout)

    def test_wait_rejects_missing_and_unhealthy_services(self):
        for state in ['missing', 'unhealthy', 'starting', 'exited']:
            with self.subTest(state=state):
                self.env.update(FAKE_STATE=state, STACK_WAIT_TIMEOUT='0')
                result = self.run_script('stack-wait.sh')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('All four services passed', result.stdout)

    def test_invalid_timeout_and_uninitialized_status_fail_clearly(self):
        self.env['STACK_WAIT_TIMEOUT'] = 'invalid'
        result = self.run_script('stack-wait.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-negative integer', result.stderr)
        result = self.run_script('stack-status.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stack-up.sh', result.stderr)


if __name__ == '__main__':
    unittest.main()
