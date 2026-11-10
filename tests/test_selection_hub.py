"""Synthetic recovery picker and official-bot publishing tests. No Discord connection."""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from discord_backup.api import DiscordError
from discord_backup.cli import execute, parser, settings_flow
from discord_backup.hub import DiscordBotClient, VIEW, hub_plan, prepare_hub, publish_hub
from discord_backup.selection import find_backups, select_backup
from discord_backup.storage import read_backup
from test_backup import FakeClock, FakeHTTP, PASSWORD, TemporaryTest, legacy

BOT_TOKEN = 'synthetic.bot.credential'


class BotHTTP:
    def __init__(self):
        self.calls, self.channels = [], {}
        self.guild = {'id': '500', 'owner_id': '1', 'name': 'Private recovery'}
        self.next_id = 800
        self.public = False
        self.fail_message = False
        self.mutate_before_send = False
        self.reads = {}

    def __call__(self, request):
        route = urlsplit(request.full_url).path.removeprefix('/api/v10')
        self.calls.append(request)
        method = request.get_method()
        payload = json.loads(request.data) if request.data else None
        if method == 'GET' and route == '/users/@me':
            data = {'id': '700', 'username': 'demo-bot', 'bot': True}
        elif method == 'GET' and route == '/guilds/500':
            data = self.guild
        elif method == 'POST' and route == '/guilds/500/channels':
            self.next_id += 1
            uid = str(self.next_id)
            data = {'id': uid, 'guild_id': '500', **payload}
            if self.public:
                data['permission_overwrites'] = []
            self.channels[uid] = copy.deepcopy(data)
        elif method == 'GET' and route.startswith('/channels/'):
            uid = route.rsplit('/', 1)[1]
            self.reads[uid] = self.reads.get(uid, 0) + 1
            data = copy.deepcopy(self.channels[uid])
            if self.mutate_before_send and self.reads[uid] > 1:
                data['permission_overwrites'] = []
        elif method == 'POST' and route.endswith('/messages'):
            if self.fail_message:
                return 500, {}, b'{}'
            data = {'id': '900', 'channel_id': route.split('/')[2]}
        else:
            raise AssertionError(f'Unexpected synthetic bot request: {method} {route}')
        return 200, {}, json.dumps(data).encode()

    def client(self):
        clock = FakeClock()
        return DiscordBotClient(BOT_TOKEN, transport=self, clock=clock, sleep=clock.sleep)

    def writes(self):
        return [call for call in self.calls if call.get_method() != 'GET']

    def messages(self):
        return [call for call in self.calls if call.full_url.endswith('/messages')]


class PickerTests(TemporaryTest):
    def test_discovery_uses_multiple_folders_sorts_newest_and_skips_links(self):
        first, second = self.directory / 'current', self.directory / 'default'
        first.mkdir(); second.mkdir()
        old, new = first / 'old.bkup', second / 'new.bkup'
        old.write_bytes(b'synthetic'); new.write_bytes(b'synthetic')
        os.utime(old, (10, 10)); os.utime(new, (20, 20))
        (first / 'link.bkup').symlink_to(new)
        os.mkfifo(first / 'fifo.bkup', 0o600)
        found = find_backups([first, second, first])
        self.assertEqual([row[1] for row in found], [new, old])

    def test_custom_folder_and_direct_file_paths_are_accepted(self):
        folder = self.directory / 'custom folder'; folder.mkdir()
        file = folder / 'saved.bkup'; file.write_bytes(b'synthetic')
        answers = iter(['p', str(folder), '1'])
        with patch('discord_backup.selection.default_locations', return_value=[]):
            chosen = select_backup(prompt=lambda value: next(answers), output=lambda value: None)
        self.assertEqual(chosen, file)
        self.assertEqual(select_backup(file, interactive=False), file)
        answers = iter([''])
        self.assertEqual(select_backup(folder, prompt=lambda value: next(answers), output=lambda value: None), file)

    def test_special_files_and_unattended_directory_selection_are_rejected(self):
        fifo = self.directory / 'fifo.bkup'; os.mkfifo(fifo, 0o600)
        with self.assertRaises(ValueError):
            select_backup(fifo, interactive=False)
        with self.assertRaises(ValueError):
            select_backup(self.directory, interactive=False)

    def test_guided_local_export_uses_selected_file_without_network(self):
        file = self.directory / 'saved.bkup'; file.write_text(json.dumps(legacy()))
        output = self.directory / 'recovery'
        answers = iter(['1', str(output), 'n', '0'])
        args = parser().parse_args(['recover', str(file)])
        with patch('discord_backup.cli.input', side_effect=lambda value: next(answers)), \
             patch('discord_backup.cli.DiscordClient', side_effect=AssertionError('Offline recovery must not authenticate')), \
             patch('discord_backup.cli.webbrowser.open') as browser, redirect_stdout(io.StringIO()):
            self.assertEqual(execute(args), 0)
        self.assertTrue((output / 'index.html').is_file())
        browser.assert_not_called()
        self.assertEqual(stat.S_IMODE((output / 'index.html').stat().st_mode), 0o600)


    def test_interactive_cross_account_restore_requires_explicit_target_and_apply(self):
        http = FakeHTTP({('GET', '/users/@me'): {'id': '2', 'username': 'new-account'}})
        args = parser().parse_args(['restore-folders', str(self.directory / 'synthetic.bkup'), '--rollback-dir', str(self.directory)])
        with patch('discord_backup.cli.client_for', return_value=http.client()), \
             patch('discord_backup.cli.input', return_value=''), redirect_stdout(io.StringIO()):
            settings_flow(args, legacy(), PASSWORD)
        self.assertEqual(http.writes(), [])
        answers = iter(['DIFFERENT', ''])
        with patch('discord_backup.cli.client_for', return_value=http.client()), \
             patch('discord_backup.cli.input', side_effect=lambda value: next(answers)), redirect_stdout(io.StringIO()):
            settings_flow(args, legacy(), PASSWORD)
        self.assertEqual(http.writes(), [])
        answers = iter(['DIFFERENT', 'APPLY'])
        with patch('discord_backup.cli.client_for', return_value=http.client()), \
             patch('discord_backup.cli.input', side_effect=lambda value: next(answers)), redirect_stdout(io.StringIO()):
            settings_flow(args, legacy(), PASSWORD)
        self.assertEqual(len(http.writes()), 1)
        self.assertEqual(read_backup(next(self.directory.glob('rollback-*.bkup')), passphrase=PASSWORD)['id'], '2')


class HubTests(TemporaryTest):
    def test_bot_auth_is_separate_fixed_origin_and_preview_never_writes(self):
        http = BotHTTP()
        plan = prepare_hub(http.client(), legacy(), '500')
        self.assertEqual(http.writes(), [])
        self.assertIn('servers', plan['channels'])
        self.assertTrue(all(call.full_url.startswith('https://discord.com/api/v10/') for call in http.calls))
        self.assertTrue(all(call.get_header('Authorization') == 'Bot ' + BOT_TOKEN for call in http.calls))
        self.assertEqual(DiscordBotClient('Bot ' + BOT_TOKEN, transport=http)._token, BOT_TOKEN)

    def test_publish_uses_private_channels_disabled_mentions_and_no_user_joins(self):
        http = BotHTTP(); client = http.client()
        prepared = prepare_hub(client, legacy(), '500')
        result = publish_hub(client, prepared, log=lambda value: None)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['channels'], 6)
        self.assertTrue(http.messages())
        for call in http.messages():
            body = json.loads(call.data)
            self.assertEqual(body['allowed_mentions'], {'parse': []})
            self.assertLessEqual(len(body['content'].encode('utf-16-le')) // 2, 1900)
            self.assertNotIn(BOT_TOKEN, body['content'])
        self.assertTrue(all('/guilds/500/channels' in call.full_url or call.full_url.endswith('/messages') for call in http.writes()))
        self.assertFalse(any('/invites/' in call.full_url or '/relationships' in call.full_url for call in http.calls))
        self.assertTrue(all(any(str(p['id']) == '500' and int(p['deny']) & VIEW for p in channel['permission_overwrites']) for channel in http.channels.values()))

    def test_public_or_changed_permissions_stop_before_any_recovery_message(self):
        for setting in ('public', 'mutate_before_send'):
            http = BotHTTP(); setattr(http, setting, True)
            result = publish_hub(http.client(), prepare_hub(http.client(), legacy(), '500'), log=lambda value: None)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(http.messages(), [])
            self.assertIn('permissions', result['error'])

    def test_changed_destination_owner_stops_before_creating_channels(self):
        http = BotHTTP(); prepared = prepare_hub(http.client(), legacy(), '500')
        # Use a distinct response object to model an actual subsequent API response.
        http.guild = {**http.guild, 'owner_id': '2'}
        with self.assertRaisesRegex(ValueError, 'changed after preview'):
            publish_hub(http.client(), prepared, log=lambda value: None)
        self.assertEqual(http.writes(), [])

    def test_ambiguous_post_failure_stops_without_duplicate_messages(self):
        http = BotHTTP(); http.fail_message = True
        result = publish_hub(http.client(), prepare_hub(http.client(), legacy(), '500'), log=lambda value: None)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(http.messages()), 1)
        self.assertEqual(result['messages'], 0)
        self.assertTrue(result['category_id'])

    def test_plan_is_bounded_escapes_names_and_rejects_untrusted_invite_strings(self):
        data = legacy(); data['guilds'][0]['name'] = '@everyone [click](javascript:bad)\nnew line'
        data['guilds'][0]['invite-code'] = 'bad?@everyone'
        plan = hub_plan(data, include=['servers'])
        content = '\n'.join(value for messages in plan.values() for value in messages)
        self.assertNotIn('https://discord.gg/bad', content)
        self.assertNotIn('@everyone', content)
        self.assertIn('No valid invitation saved', content)
        self.assertNotIn('relationships', plan)
        data['friends'] = ['2'] * 20000
        with self.assertRaisesRegex(ValueError, 'too large|250 messages'):
            hub_plan(data)

    def test_cli_preview_with_private_bot_file_cannot_publish(self):
        file = self.directory / 'source.bkup'; file.write_text(json.dumps(legacy()))
        key = self.directory / 'bot-key'; key.write_text(BOT_TOKEN); key.chmod(0o600)
        http = BotHTTP()
        args = parser().parse_args(['restore-hub', str(file), '--guild', '500', '--bot-token-file', str(key)])
        with patch('discord_backup.cli.DiscordBotClient', return_value=http.client()), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(execute(args), 0)
        self.assertEqual(http.writes(), [])
        self.assertNotIn(BOT_TOKEN, output.getvalue())
        self.assertIn('decrypted backup data', output.getvalue())
