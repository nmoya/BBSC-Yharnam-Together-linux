"""Linux script: per-server identities and redirects never clobber the player's files."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/linux_coop.py'
spec = importlib.util.spec_from_file_location('linux_coop', SCRIPT)
linux_coop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linux_coop)


class LinuxCoopTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.user = Path(self.temp.name) / 'user'

    def test_identity_persists_and_pins_only_matching_keys(self):
        first = linux_coop.identity(self.user, 'example.org')
        self.assertEqual(first, linux_coop.identity(self.user, 'example.org'))
        self.assertNotEqual(first['account'], linux_coop.identity(self.user, 'other.org')['account'])
        self.assertEqual((self.user / linux_coop.IDENTITIES).stat().st_mode & 0o777, 0o600)
        key = 'a' * 64
        linux_coop.identity(self.user, 'example.org', key)
        with self.assertRaisesRegex(ValueError, 'differs'):
            linux_coop.identity(self.user, 'example.org', 'b' * 64)
        self.assertEqual(linux_coop.identity(self.user, 'example.org')['key'], key)

    def test_redirect_requires_explicit_replacement(self):
        path = linux_coop.overrides(self.user, '192.0.2.1')
        self.assertEqual(json.loads(path.read_text())[linux_coop.GAME_SERVER], 'http://192.0.2.1:20443')
        with self.assertRaisesRegex(ValueError, '--replace-overrides'):
            linux_coop.overrides(self.user, '192.0.2.2')
        linux_coop.overrides(self.user, '192.0.2.2', replace=True)
        self.assertEqual(json.loads(path.read_text())[linux_coop.GAME_SERVER], 'http://192.0.2.2:20443')
        custom = self.user / 'host_overrides.custom.json'
        custom.write_text('{}')
        self.assertEqual(linux_coop.overrides(self.user, '192.0.2.3'), custom)

    def test_unmarked_files_are_never_overwritten(self):
        self.user.mkdir()
        (self.user / linux_coop.IDENTITIES).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'refusing'):
            linux_coop.identity(self.user, 'example.org')
        (self.user / linux_coop.OVERRIDES).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'differs'):
            linux_coop.overrides(self.user, '192.0.2.1', replace=True)

    def test_address_default_and_invalid_port(self):
        with patch.object(linux_coop.socket, 'gethostbyname', return_value='192.0.2.1'):
            self.assertEqual(linux_coop.address('Example.org'), ('example.org', 31314, '192.0.2.1'))
        with self.assertRaises(ValueError):
            linux_coop.address('127.0.0.1:99999')

    def test_only_the_games_confirmed_key_is_learned(self):
        linux_coop.identity(self.user, 'friend.example')
        log = self.user / 'log.txt'
        key = 'a' * 64
        log.write_text(f'[Lib.Net] <Info> (Net Thread) p2p_sockets.cpp:865 OnLinkDatagram: '
                       f'{linux_coop.coop.LEARNED_KEY_LINE}{key}\n')
        linux_coop.learn_key(self.user, 'friend.example', log)
        self.assertEqual(linux_coop.identity(self.user, 'friend.example')['key'], key)

    def test_launch_passes_native_coop_settings_to_existing_run_script(self):
        game = Path(self.temp.name) / 'game'
        game.mkdir()
        (game / 'eboot.bin').touch()
        data = Path(self.temp.name) / 'data'
        with patch.object(linux_coop.coop, 'game_version', return_value=('CUSA03173', '01.09')), \
             patch.object(linux_coop, 'events', return_value=data / 'coop-mods'), \
             patch.object(linux_coop.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(linux_coop.main(['--game-dir', str(game), '--server', '192.0.2.3',
                                               '--data-dir', str(data)]), 0)
        command, = run.call_args.args
        env = run.call_args.kwargs['env']
        self.assertEqual(command[:2], ['bash', str(linux_coop.PORT / 'run.sh')])
        self.assertEqual(env['BB_SHADNET_SERVER'], '192.0.2.3:31314')
        self.assertEqual(env['BB_SHADNET_WEBAPI'], 'http://192.0.2.3:31315')
        self.assertEqual(env['BB_GAME_DIR'], str(game))
        self.assertEqual(env['BB_FPS'], '60')
        self.assertEqual(env['BB_ONLINE'], '1')
        self.assertEqual(env['SHADPS4_BLOODBORNE_SEAMLESS_COOP'], '1')
        self.assertEqual(json.loads(Path(env['SHADPS4_HTTP_HOST_OVERRIDES_JSON']).read_text())
                         [linux_coop.GAME_SERVER], 'http://192.0.2.3:20443')


if __name__ == '__main__':
    unittest.main()
