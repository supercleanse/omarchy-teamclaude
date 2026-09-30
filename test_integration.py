"""Opt-in test against installed TeamClaude code, using only synthetic accounts.

TEAMCLAUDE_SOURCE=/path/to/teamclaude/src python3 -m unittest test_integration -v
"""
import json
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from test_bridge import b


@unittest.skipUnless(os.environ.get("TEAMCLAUDE_SOURCE"), "set TEAMCLAUDE_SOURCE for the local server integration test")
class IntegrationTest(unittest.TestCase):
    def test_managed_service_start_log_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            config = directory / 'config.json'
            config.write_text(json.dumps({'proxy': {'port': port}}))
            executable = directory / 'teamclaude-synthetic'
            executable.write_text('''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
port = json.loads(Path(os.environ['TEAMCLAUDE_CONFIG']).read_text())['proxy']['port']
Path(sys.argv[sys.argv.index('--activity-log')+1]).write_text('Synthetic request completed (200, 0.1s)\\n')
class Handler(BaseHTTPRequestHandler):
 def log_message(self, *args): pass
 def do_GET(self):
  self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
  self.wfile.write(json.dumps({'server': {'version': 'synthetic'}, 'accounts': []}).encode())
HTTPServer(('127.0.0.1', port), Handler).serve_forever()
''')
            executable.chmod(0o700)
            env = {'TEAMCLAUDE_CONFIG': str(config), 'XDG_STATE_HOME': str(directory / 'state')}
            unit = 'omarchy-teamclaude-test-' + str(os.getpid()) + '.service'
            with patch.dict(os.environ, env), patch.object(b, 'UNIT', unit), patch.object(b, 'cli', return_value=str(executable)):
                try:
                    self.assertIn('Starting', b.action('start'))
                    for _ in range(30):
                        try:
                            result = b.snapshot()
                            if result['online']:
                                break
                        except Exception:
                            pass
                        time.sleep(.1)
                    self.assertTrue(result['online'])
                    self.assertTrue(result['managed'])
                    self.assertIn('Synthetic request', '\n'.join(result['lines']))
                    self.assertIn('stopped', b.action('stop'))
                    self.assertFalse(b.managed())
                finally:
                    subprocess.run(['systemctl', '--user', 'stop', unit], capture_output=True)

    def test_real_server_status_quota_switch_and_removal(self):
        source = Path(os.environ["TEAMCLAUDE_SOURCE"])
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "server.mjs"
            script.write_text('''
import { AccountManager } from SOURCE_ACCOUNT;
import { createProxyServer } from SOURCE_SERVER;
const accounts = [{id: 'test-only', name: 'Synthetic test', type: 'oauth',
  accessToken: 'not-a-real-token', expiresAt: Date.now() + 3600000,
  rateLimitTier: 'default_claude_ai', accountUuid: 'fake-test-account'}];
const config = {accounts, proxy: {apiKey: 'synthetic-test-key', trustLoopback: false, mcp: 'full'}};
const manager = new AccountManager(accounts);
manager.accounts[0].quota.unified5h = 0.35;
manager.accounts[0].quota.unified5hReset = Date.now() + 3600000;
const server = createProxyServer(manager, config, {
  getStatusExtra: () => ({server: {version: 'integration-test'}}),
  persistAccounts: async () => {}, reload: async () => 0
});
server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({port: server.address().port})));
'''.replace('SOURCE_ACCOUNT', json.dumps((source / 'account-manager.js').as_uri()))
               .replace('SOURCE_SERVER', json.dumps((source / 'server.js').as_uri())))
            process = subprocess.Popen(['node', str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = process.stdout.readline()
                if not line:
                    self.fail(process.stderr.read())
                port = json.loads(line)['port']
                config = {'proxy': {'port': port, 'apiKey': 'synthetic-test-key', 'mcp': 'full'},
                          'accounts': [{'name': 'Synthetic test'}]}
                client = b.Client(config)
                result = b.normalize(client.call('status'), client.call('quota'))
                self.assertEqual(result['accounts'][0]['meters'][0]['percent'], .35)
                self.assertNotIn('not-a-real-token', json.dumps(result))
                client.action('switch', {'account': 'Synthetic test'})
                with patch.object(b, 'read_config', return_value=config):
                    self.assertIn('removed', b.action('remove', 'Synthetic test'))
                self.assertEqual(client.call('status')['accounts'], [])
            finally:
                process.terminate()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
