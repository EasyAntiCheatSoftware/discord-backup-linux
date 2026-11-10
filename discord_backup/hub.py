# SPDX-License-Identifier: AGPL-3.0-only
"""Official bot API recovery hub. Organizes links; never joins/refriends as a user."""

import re

from . import __version__
from .api import DiscordClient, DiscordError
from .backup import user_label
from .storage import snowflake, validate_token

VIEW, SEND, HISTORY, MANAGE_CHANNELS = 1 << 10, 1 << 11, 1 << 16, 1 << 4
BOT_PERMISSIONS = VIEW | SEND | HISTORY | MANAGE_CHANNELS
MAX_MESSAGES = 250


def validate_bot_token(value):
    value = value.strip()
    if value.lower().startswith('bot '):
        value = value[4:]
    return validate_token(value)


class DiscordBotClient(DiscordClient):
    api_root = 'https://discord.com/api/v10'
    credential_label = 'bot'

    def __init__(self, token, **options):
        super().__init__(validate_bot_token(token), **options)

    def authorization_header(self):
        return 'Bot ' + self._token

    def user_agent(self):
        return f'DiscordBot (https://github.com/EasyAntiCheatSoftware/discord-backup-linux, {__version__})'


def text(value, limit=160):
    value = ' '.join(str(value).split())[:limit]
    value = ''.join(char for char in value if ord(char) >= 32 and not 127 <= ord(char) < 160)
    return re.sub(r'([\\`*_~|\[\]<>])', r'\\\1', value).replace('@', '@\u200b')


def invite(item):
    code = item.get('invite-code')
    return f'https://discord.gg/{code}' if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', code) else 'No valid invitation saved'


def chunks(lines):
    messages, current = [], ''
    for line in lines:
        line = str(line) + '\n'
        if len(line.encode('utf-16-le')) // 2 > 1800:
            raise ValueError('A recovery entry is too large; use the local recovery export')
        if len((current + line).encode('utf-16-le')) // 2 > 1900:
            messages.append(current.rstrip())
            current = ''
        current += line
        if len(messages) > MAX_MESSAGES:
            raise ValueError('Recovery hub would be too large; use the local recovery export')
    if current.strip():
        messages.append(current.rstrip())
    return messages or ['No entries saved.']


def hub_plan(data, *, include=('servers', 'groups', 'relationships', 'contacts', 'warnings')):
    include = set(include)
    allowed = {'servers', 'groups', 'relationships', 'contacts', 'warnings'}
    if not include <= allowed:
        raise ValueError('Unknown recovery section')
    channels = {'read-me': chunks([
        'Discord account recovery', f"Account: {text(data['name'])} ({data['id']})",
        f"Backup status: {text(data.get('status', 'legacy status unknown'))}",
        'This private hub organizes your saved data. Join invitations and add contacts manually.',
        'It does not bypass verification, recover expired invitations, or replay messages.',
        'After rejoining servers, use Restore server folders in the Linux app.',
        'Use the local recovery export to extract your avatar, banner and bio; apply these in Discord.',
        'Favourite GIF/folder settings are separate preview-and-apply actions in the app.',
        'Server owners, administrators and the bot can access these channels. Keep this server trusted.',
    ])}
    if 'servers' in include:
        lines, seen = [], set()
        guilds = {str(item.get('id')): item for item in data.get('guilds', []) if snowflake(item.get('id'))}
        for folder in data.get('guild_folders') or []:
            lines.append('Folder: ' + text(folder.get('name') or 'Unfoldered'))
            for uid in folder['guild_ids']:
                uid = str(uid)
                if uid in seen:
                    continue
                seen.add(uid)
                item = guilds.get(uid, {'id': uid, 'name': 'Unknown server'})
                lines.append(f"{text(item.get('name', 'Unknown'))} ({uid}) — {invite(item)}")
        for uid, item in guilds.items():
            if uid not in seen:
                lines.append(f"{text(item.get('name', 'Unknown'))} ({uid}) — {invite(item)}")
        channels['servers'] = chunks(lines)
    if 'groups' in include:
        channels['group-chats'] = chunks(['Group invitations may expire or stop working after access changes.'] + [
            f"{text(item.get('name', 'Group'))} — {invite(item)}" for item in data.get('group-chats', [])])
    if 'relationships' in include:
        users, lines = data.get('users', {}), []
        for key, title in (('friends', 'Friends'), ('blocked', 'Blocked users'), ('incoming', 'Incoming requests'), ('outgoing', 'Outgoing requests')):
            lines.append(title)
            for uid in data.get(key, []):
                user = users.get(str(uid))
                label = user_label(user) if isinstance(user, dict) else str(uid)
                lines.append(f'{text(label)} — https://discord.com/users/{uid}')
        channels['relationships'] = chunks(lines)
    if 'contacts' in include:
        channels['dm-contacts'] = chunks(['Open-DM contacts only; message contents were not backed up.'] + [
            f"{text(item.get('user', item.get('user_id', 'Unknown')))} — https://discord.com/users/{item['user_id']}"
            for item in data.get('dm-history', []) if snowflake(item.get('user_id'))])
    if 'warnings' in include:
        channels['backup-warnings'] = chunks([text(value, 500) for value in data.get('warnings', [])])
    if sum(len(messages) for messages in channels.values()) > MAX_MESSAGES:
        raise ValueError('Recovery hub exceeds 250 messages; use the local recovery export or fewer sections')
    return channels


def bot_identity(client):
    me = client.request('GET', '/users/@me')
    if not isinstance(me, dict) or me.get('bot') is not True or not snowflake(me.get('id')):
        raise DiscordError('This recovery method requires a bot token from your own Discord application')
    return me


def prepare_hub(client, data, guild_id, *, include=('servers', 'groups', 'relationships', 'contacts', 'warnings')):
    if not snowflake(guild_id):
        raise ValueError('Enter a valid recovery server ID')
    me = bot_identity(client)
    guild = client.request('GET', f'/guilds/{guild_id}')
    if not isinstance(guild, dict) or str(guild.get('id')) != str(guild_id) or not snowflake(guild.get('owner_id')) or not isinstance(guild.get('name'), str):
        raise DiscordError('Cannot verify the recovery server; add your bot to that server first')
    return {'bot_id': str(me['id']), 'guild': guild, 'channels': hub_plan(data, include=include)}


def overwrites(guild_id, owner_id, bot_id):
    access = str(VIEW | SEND | HISTORY)
    return [{'id': str(guild_id), 'type': 0, 'allow': '0', 'deny': str(VIEW)},
            {'id': str(owner_id), 'type': 1, 'allow': access, 'deny': '0'},
            {'id': str(bot_id), 'type': 1, 'allow': access, 'deny': '0'}]


def verify_private(channel, guild_id, owner_id, bot_id, *, kind, parent):
    try:
        if not isinstance(channel, dict) or not snowflake(channel.get('id')) or str(channel.get('guild_id')) != str(guild_id) or type(channel.get('type')) is not int or channel.get('type') != kind:
            raise ValueError
        if kind == 0 and str(channel.get('parent_id')) != str(parent):
            raise ValueError
        entries = channel['permission_overwrites']
        if not isinstance(entries, list) or len(entries) != 3:
            raise ValueError
        actual = {(int(item['type']), str(item['id'])): item for item in entries}
        expected = {(0, str(guild_id)), (1, str(owner_id)), (1, str(bot_id))}
        if set(actual) != expected:
            raise ValueError
        everyone = actual[(0, str(guild_id))]
        if not int(everyone['deny']) & VIEW or int(everyone['allow']) & VIEW:
            raise ValueError
        for uid in (owner_id, bot_id):
            if not int(actual[(1, str(uid))]['allow']) & VIEW or int(actual[(1, str(uid))]['deny']) & VIEW:
                raise ValueError
    except (ValueError, TypeError, KeyError):
        raise DiscordError('Private channel permissions could not be verified; no recovery messages will be posted') from None


def publish_hub(client, prepared, *, log=print):
    guild, bot_id = prepared['guild'], prepared['bot_id']
    current = client.request('GET', f"/guilds/{guild['id']}")
    if not isinstance(current, dict) or any(str(current.get(key)) != str(guild.get(key)) for key in ('id', 'owner_id', 'name')):
        raise ValueError('Recovery server changed after preview; preview again before publishing')
    guild_id, owner_id = str(guild['id']), str(guild['owner_id'])
    permissions = overwrites(guild_id, owner_id, bot_id)
    report = {'category_id': None, 'messages': 0, 'channels': 0, 'status': 'partial'}

    def create(name, kind, parent=None):
        payload = {'name': name, 'type': kind, 'permission_overwrites': permissions}
        if parent:
            payload['parent_id'] = parent
        result = client.request('POST', f'/guilds/{guild_id}/channels', payload)
        if not isinstance(result, dict) or not snowflake(result.get('id')):
            raise DiscordError('Discord did not confirm channel creation; inspect the server before retrying')
        uid = str(result['id'])
        if kind == 4:
            report['category_id'] = uid
            log(f'Recovery category: https://discord.com/channels/{guild_id}/{uid}')
        actual = client.request('GET', f'/channels/{uid}')
        if not isinstance(actual, dict) or str(actual.get('id')) != uid:
            raise DiscordError('Discord returned a different channel; publication stopped')
        verify_private(actual, guild_id, owner_id, bot_id, kind=kind, parent=parent)
        return uid

    try:
        category = create('Account recovery', 4)
        for name, messages in prepared['channels'].items():
            channel = create(name, 0, category)
            report['channels'] += 1
            for message in messages:
                # Check each logical send. Administrators remain trusted and can change permissions.
                actual = client.request('GET', f'/channels/{channel}')
                if not isinstance(actual, dict) or str(actual.get('id')) != channel:
                    raise DiscordError('Discord returned a different channel; publication stopped')
                verify_private(actual, guild_id, owner_id, bot_id, kind=0, parent=category)
                sent = client.request('POST', f'/channels/{channel}/messages',
                                      {'content': message, 'allowed_mentions': {'parse': []}, 'flags': 4})
                if not isinstance(sent, dict) or not snowflake(sent.get('id')) or str(sent.get('channel_id')) != channel:
                    raise DiscordError('Discord did not confirm message delivery; inspect the server before retrying')
                report['messages'] += 1
            log(f'Published #{name} ({len(messages)} messages)')
        report['status'] = 'complete'
    except (DiscordError, KeyboardInterrupt) as error:
        report['error'] = str(error) if isinstance(error, DiscordError) else 'Cancelled'
        log(f"Recovery hub stopped: {report['error']}. Published {report['messages']} messages; inspect the server before retrying. Created channels were kept.")
    return report
