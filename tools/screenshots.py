#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Capture real CLI output with offline fixtures and render a neutral terminal to PNG.

Developer-only dependency: Pillow plus the system Noto Sans Mono fonts.
No desktop capture, shell configuration, saved credentials or live Discord access.
"""

import argparse
import errno
import fcntl
import os
from pathlib import Path
import pty
import re
import selectors
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]


def demo(mode):
    from unittest.mock import patch
    import secrets
    sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
    from test_backup import FakeHTTP, TOKEN
    from discord_backup.api import DiscordClient
    from discord_backup.cli import main
    if mode == 'menu':
        print('$ ./run.sh', flush=True)
        return main(['--color', 'always'])
    names = ['Linux Community', 'Python Workshop', 'Weekend Projects']
    groups = ['Study group', 'Game night']
    routes = {
        ('GET', '/users/@me'): {'id': '1', 'username': 'demo-account', 'bio': 'Example profile', 'avatar': None, 'banner': None},
        ('GET', '/users/@me/guilds?limit=200&after=0'): [
            {'id': str(10+i), 'name': name, 'features': []} for i, name in enumerate(names)],
        ('GET', '/users/@me/channels'): [
            {'id': str(30+i), 'type': 3, 'name': name, 'recipients': []} for i, name in enumerate(groups)] + [
            {'id': '40', 'type': 1, 'last_message_id': '90', 'recipients': [{'id': '2', 'username': 'demo-friend'}]}],
    }
    for i in range(len(names)):
        routes[('GET', f'/guilds/{10+i}/channels')] = [{'id': str(20+i), 'type': 0, 'name': 'general'}]
        routes[('POST', f'/channels/{20+i}/invites')] = {'code': f'demo-server-{i}'}
    for i in range(len(groups)):
        routes[('POST', f'/channels/{30+i}/invites')] = {'code': f'demo-group-{i}'}
    if mode == 'warnings':
        routes[('GET', '/users/@me/settings')] = (404, {}, {})
        routes[('GET', '/guilds/10/channels')] = (403, {}, {})
    backend = FakeHTTP(routes)

    def transport(request):
        time.sleep(0.04)  # Deliberate fixture latency, not a live benchmark.
        return backend(request)

    with tempfile.TemporaryDirectory(prefix='discord-screenshot-data-') as directory:
        os.chdir(directory)
        with patch('discord_backup.cli.client_for', return_value=DiscordClient(TOKEN, transport=transport)), \
             patch('discord_backup.cli.passphrase_for', return_value=secrets.token_urlsafe(32)), \
             patch('socket.socket.connect', side_effect=RuntimeError('Live network disabled in screenshot capture')):
            print('$ ./run.sh backup', flush=True)
            return main(['--color', 'always', 'backup', '--output', 'backups'])


def capture(mode, *, record=False):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 100, 0, 0))
    with tempfile.TemporaryDirectory(prefix='discord-screenshot-env-') as directory:
        env = {'PATH': os.defpath, 'TERM': 'xterm-256color', 'LANG': 'C.UTF-8',
               'PYTHONDONTWRITEBYTECODE': '1', 'XDG_DATA_HOME': '/data',
               'XDG_CONFIG_HOME': directory + '/config', 'XDG_CACHE_HOME': directory + '/cache'}
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--capture', mode],
                                   stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT, close_fds=True)
        os.close(slave)
        output, answered, events = bytearray(), False, []
        started = time.monotonic()
        selector = selectors.DefaultSelector()
        selector.register(master, selectors.EVENT_READ)
        deadline = time.monotonic() + 45
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError('Screenshot capture timed out')
                if not selector.select(0.1):
                    if process.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
                if record:
                    end = output.rfind(b'\n') + 1
                    if end:
                        snapshot = output[:end].decode('utf-8')
                        if not events or events[-1][1] != snapshot:
                            events.append((time.monotonic() - started, snapshot))
                if mode == 'menu' and b'Choice:' in output and not answered:
                    os.write(master, b'0\n')
                    answered = True
            code = process.wait(timeout=5)
            if code != (2 if mode == 'warnings' else 0):
                raise RuntimeError('Demo failed; no screenshot published')
        finally:
            selector.close()
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()
    text = output.decode('utf-8')
    if str(Path.home()) in text or 'synthetic.test.token' in text or 'Traceback' in text:
        raise ValueError('Private/debug text in screenshot capture')
    if record and (not events or events[-1][1] != text):
        events.append((time.monotonic() - started, text))
    return (text, events) if record else text


def render(text, path=None, *, rows):
    from PIL import Image, ImageDraw, ImageFont
    font_dir = Path('/usr/share/fonts/noto')
    regular = ImageFont.truetype(str(font_dir / 'NotoSansMono-Regular.ttf'), 20)
    bold_font = ImageFont.truetype(str(font_dir / 'NotoSansMono-Bold.ttf'), 20)
    background, foreground = '#1e1e1e', '#dedede'
    palette = {91: '#ff6767', 92: '#9bde78', 93: '#f4d271', 94: '#81a2ff', 95: '#c79bea', 96: '#77d9e8'}
    lines, line, column = [], [], 0
    color, bold, dim = foreground, False, False
    for token in re.split(r'(\x1b\[[0-9;]*m)', text):
        if token.startswith('\x1b['):
            for code in [int(x or '0') for x in token[2:-1].split(';')]:
                if code == 0:
                    color, bold, dim = foreground, False, False
                elif code == 1:
                    bold = True
                elif code == 2:
                    dim = True
                elif code in palette:
                    color = palette[code]
            continue
        for character in token:
            if character == '\r':
                column = 0
                continue
            if character == '\n':
                lines.append(line)
                line, column = [], 0
                continue
            if ord(character) < 32:
                raise ValueError('Unexpected terminal control in capture')
            if column >= 100:
                lines.append(line)
                line, column = [], 0
            item = (character, color, bold, dim)
            if column < len(line):
                line[column] = item
            else:
                line.append(item)
            column += 1
    if line:
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    # The viewport behaves like a terminal: long output scrolls above the screen.
    lines = lines[-rows:]
    cell, leading, padding, titlebar = regular.getlength('M'), 29, 32, 48
    width = round(100 * cell + 2 * padding)
    height = titlebar + 2 * padding + max(rows, len(lines)) * leading
    image = Image.new('RGB', (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, titlebar), fill='#2b2b2b')
    draw.line((0, titlebar, width, titlebar), fill='#3b3b3b')
    draw.text((padding, 11), 'Terminal', font=regular, fill='#d8d8d8')
    draw.text((width - 93, 11), '−  □  ×', font=regular, fill='#bdbdbd')
    for y, row in enumerate(lines):
        for x, (character, ink, is_bold, is_dim) in enumerate(row):
            if is_dim:
                ink = tuple(round(int(ink[i:i+2], 16) * 0.7 + 30 * 0.3) for i in (1, 3, 5))
            draw.text((padding + x * cell, titlebar + padding + y * leading), character,
                      font=bold_font if is_bold else regular, fill=ink)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)  # No desktop, EXIF, hostname or user metadata.
    return image


def animate(events, path):
    """Replay captured backup output, slowed for readability and held at completion."""
    from PIL import Image
    if not events or 'COMPLETE' not in events[-1][1]:
        raise ValueError('Demo backup did not complete')
    first_estimate = next((i for i, (_, text) in enumerate(events) if 'preliminary;' in text), 0)
    events = events[first_estimate:]
    if len(events) > 28:
        indices = sorted({round(i * (len(events) - 1) / 27) for i in range(28)})
        events = [events[i] for i in indices]
    frames, durations = [], []
    for index, (stamp, text) in enumerate(events):
        frame = render(text, rows=28)
        size = (1100, round(frame.height * 1100 / frame.width))
        frame = frame.resize(size, Image.Resampling.LANCZOS)
        frames.append(frame.quantize(colors=128))
        gap = events[index + 1][0] - stamp if index + 1 < len(events) else 0
        durations.append(max(220, min(900, round(gap * 4500))))
    durations[0], durations[-1] = 900, 2800
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, disposal=1, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', choices=('menu', 'backup', 'warnings'), help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path, default=ROOT / 'builds/v1.5.1/screenshots')
    args = parser.parse_args()
    if args.capture:
        return demo(args.capture)
    for mode, rows in (('menu', 24), ('backup', 28), ('warnings', 30)):
        render(capture(mode), args.output / f'{mode}.png', rows=rows)
    _, events = capture('backup', record=True)
    animate(events, args.output / 'demo.gif')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
