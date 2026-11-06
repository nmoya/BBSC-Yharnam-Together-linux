#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run this checkout's native bbport client against a friend's shadNet server.

All generated files live under --data-dir; the original game directory is read only.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

PORT = Path(__file__).resolve().parent.parent
ROOT = PORT.parent
sys.path.insert(0, str(PORT / 'launcher'))
import bbport_coop as coop  # noqa: E402

GAME_SERVER = coop.GAME_SERVER
EVENT_MOD = 'yharnam-coop-events'
MARKER = '.yharnam-generated'
IDENTITIES = 'coop-linux.json'
OVERRIDES = 'host_overrides.yharnam.json'


def address(value):
    """Return the server name, optional link port and its resolved IPv4 address."""
    host, colon, port = value.rpartition(':')
    if not colon:
        host, port = value, '31314'
    if not host or not re.fullmatch(r'[A-Za-z0-9.-]+', host) or not port.isdecimal():
        raise ValueError('server must be an IPv4 address or DNS name, optionally :UDP-port')
    number = int(port)
    if not 1 <= number <= 65535:
        raise ValueError('server UDP port must be between 1 and 65535')
    try:
        ip = socket.gethostbyname(host)
    except OSError as error:
        raise ValueError(f'cannot resolve server {host}: {error}') from error
    return host.lower(), number, ip


def write_new(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(content)


def replace_own(path, content):
    """Replace only a file whose ownership marker was checked by the caller."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.yharnam-', text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def identity(user, host, requested_key=''):
    path = user / IDENTITIES
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('_generated_by') != 'linux_coop.py' or not isinstance(saved.get('servers'), dict):
            raise ValueError(f'{path} is not a Linux co-op identity file; refusing to change it')
    else:
        saved = {'_generated_by': 'linux_coop.py', 'servers': {}}
    servers = saved['servers']
    changed = False
    if host not in servers:
        fresh = coop.with_player_id({})
        servers[host] = {'account': fresh['account'], 'secret': fresh['password'], 'key': ''}
        changed = True
    entry = servers[host]
    if not coop.valid_name(entry.get('account', '')) or not coop.valid_secret(entry.get('secret', '')):
        raise ValueError(f'invalid identity in {path} for {host}')
    old_key = entry.get('key', '')
    if old_key and not coop.valid_link_key(old_key):
        raise ValueError(f'invalid pinned server key in {path}')
    if requested_key:
        if not coop.valid_link_key(requested_key):
            raise ValueError('server key must be 64 hexadecimal digits')
        if old_key and old_key.lower() != requested_key.lower():
            raise ValueError('server key differs from the one pinned; refusing to replace it')
        if not old_key:
            entry['key'] = requested_key.lower()
            changed = True
    if changed:
        text = json.dumps(saved, indent=2) + '\n'
        if path.exists():
            replace_own(path, text)
        else:
            write_new(path, text)
    return entry


def overrides(user, ip, replace=False):
    """Keep user's custom overrides; only replace a marked generated file on request."""
    custom = user / 'host_overrides.custom.json'
    if custom.exists():
        return custom
    path = user / OVERRIDES
    wanted = {'_generated_by': 'linux_coop.py', GAME_SERVER: f'http://{ip}:20443'}
    if path.exists():
        current = json.loads(path.read_text(encoding='utf-8'))
        if current == wanted:
            return path
        if not replace or current.get('_generated_by') != 'linux_coop.py':
            raise ValueError(f'{path} differs; inspect it and pass --replace-overrides to change it')
        replace_own(path, json.dumps(wanted, indent=2) + '\n')
    else:
        write_new(path, json.dumps(wanted, indent=2) + '\n')
    return path


def events(game, data):
    """Generate the checkout's co-op events into a private mod layer, not the ROM."""
    destination = data / 'coop-mods' / EVENT_MOD
    marker = destination / MARKER
    if destination.exists():
        if not marker.is_file() or not (destination / 'dvdroot_ps4/event/manifest.json').is_file():
            raise ValueError(f'{destination} exists but is not a complete generated event layer')
        manifest = json.loads((destination / 'dvdroot_ps4/event/manifest.json').read_text(encoding='utf-8'))
        for name, record in manifest.get('files', {}).items():
            original = game / 'dvdroot_ps4' / 'event' / name
            if not original.is_file():
                raise ValueError(f'{original} is missing; event layer must be regenerated')
            import hashlib
            if hashlib.sha256(original.read_bytes()).hexdigest() != record['input_sha256']:
                raise ValueError(f'{original} has changed; move aside {destination} and prepare again')
        return destination
    source = game / 'dvdroot_ps4' / 'event'
    if not (source / 'common.emevd.dcx').is_file():
        raise ValueError(f'missing Bloodborne event files in {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.events-') as temporary:
        layer = Path(temporary) / 'dvdroot_ps4' / 'event'
        subprocess.run([sys.executable, str(ROOT / 'tools/re/party_boss_events.py'),
                        str(layer), str(source)], check=True)
        if not (layer / 'manifest.json').is_file():
            raise ValueError('event patch generator did not produce a manifest')
        (Path(temporary) / MARKER).write_text('linux_coop.py\n', encoding='utf-8')
        Path(temporary).rename(destination)
    return destination


def learn_key(user, host, log):
    """Remember the key confirmed by the game after its first successful link."""
    if not log.exists():
        return
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        key = coop.learned_key(line)
        if key:
            identity(user, host, key)
            print(f'Pinned the server key for {host} in {user / IDENTITIES}')
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True, help='existing Bloodborne 01.09 game folder')
    parser.add_argument('--server', required=True, help='friend’s shadNet host or IPv4 address[:UDP port], default :31314')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('XDG_DATA_HOME',
                        Path.home() / '.local/share')) / 'yharnam-together')
    parser.add_argument('--server-key', default='', help='optional pinned server public key (64 hex digits)')
    parser.add_argument('--replace-overrides', action='store_true', help='replace only our generated HTTP redirect')
    parser.add_argument('--prepare-only', action='store_true', help='prepare files without starting the game')
    args, game_args = parser.parse_known_args(argv)
    if game_args and game_args[0] != '--':
        parser.error('pass game arguments after --')
    game_args = game_args[1:]
    game = args.game_dir.expanduser().resolve()
    data = args.data_dir.expanduser().resolve()
    if data == game or game in data.parents:
        parser.error('data directory must be outside the game directory')
    if not (game / 'eboot.bin').is_file():
        parser.error(f'no eboot.bin at {game}')
    version = coop.game_version(game)
    if not version or version[1] != coop.GAME_VERSION:
        parser.error(f'co-op requires game update 01.09; found {version or "no param.sfo"}')
    try:
        host, port, ip = address(args.server)
        if args.server_key and not coop.valid_link_key(args.server_key):
            raise ValueError('server key must be 64 hexadecimal digits')
        user = data / 'user'
        config = identity(user, host, args.server_key)
        layer = events(game, data)
        redirect = overrides(user, ip, args.replace_overrides)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(f'Game: {game}\nServer link: {ip}:{port}\nGame backend: http://{ip}:20443\nEvents: {layer}')
    if args.prepare_only:
        return 0
    log = user / 'log' / 'shad_log.txt'
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, BB_GAME_DIR=str(game), BB_DATA_DIR=str(data), BB_USER_DIR=str(user),
               BB_MODS_DIR=str(data / 'coop-mods'), BB_MODS_CONFIG=str(data / 'coop-mods.json'),
               BB_MODS_ENABLED='1', BB_ONLINE='1', BB_FPS='60',
               BB_LOG_FILE=str(log), BB_LOG_LEVEL='info',
               BB_SHADNET_SERVER=f'{ip}:{port}', BB_SHADNET_WEBAPI=f'http://{ip}:31315',
               BB_SHADNET_NPID=config['account'], BB_SHADNET_PASSWORD=config['secret'],
               BB_PATCHES_FILE=str(data / 'out' / 'patches.bin'),
               SHADPS4_HTTP_HOST_OVERRIDES_JSON=str(redirect),
               SHADPS4_BLOODBORNE_SEAMLESS_COOP='1')
    env.setdefault('BB_LTO', 'OFF')
    env.setdefault('BB_PGO', 'off')
    if config['key']:
        env['BB_SHADNET_SERVER_KEY'] = config['key']
    else:
        env.pop('BB_SHADNET_SERVER_KEY', None)
    # run.sh prepares/patches the game and builds the native client inside nix-shell.
    result = subprocess.run(['bash', str(PORT / 'run.sh'), *game_args], cwd=PORT, env=env,
                            check=False)
    learn_key(user, host, log)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
