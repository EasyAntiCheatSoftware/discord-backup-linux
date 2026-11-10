# Guided recovery and the private bot hub

Choose **2 — Recover / restore a backup** in the main menu, or run `./run.sh recover`. The picker checks the current directory, its `backups` subfolder, the last location used in this session, and the default XDG backup directory. It lists recent `.bkup` files without decrypting them. Press Enter for the newest file, select a number, or enter a custom folder/file path. A folder opens another list. `D` returns to the default search and `0` cancels.

You can also start in a particular folder or open a file directly:

```sh
./run.sh recover /path/to/backups
./run.sh recover /path/to/backup.bkup
```

After unlocking once with the backup passphrase, the recovery menu offers:

1. **Local recovery page + profile files:** offline HTML, invite/profile links, avatar/banner and bio extraction. Choose a new private output folder and optionally open its page.
2. **Private Discord recovery hub:** your bot creates a private category and organized channels containing saved server invitations grouped by folder, group links, relationships, DM contacts and warnings.
3. **Server folders:** preview for the authenticated target account, then explicitly apply after an encrypted rollback is saved.
4. **Favourite GIF settings:** preview and explicitly replace the opaque frecency block after encrypted rollback. Other preferences inside that block can change too.

For a settings restore to another account, the wizard shows both identities and requires **DIFFERENT** before previewing, then **APPLY** before writing.

You can choose another recovery method without repeatedly entering the backup passphrase. Leaving the recovery menu ends that in-memory session. No passphrase file is created.

## What the original workflow actually does

The [original project's README](https://github.com/itschasa/Discord-Backup#restoring) lists joining servers/groups, adding relationships, and applying profile files as manual actions. Its recovery server organizes invitations and contact references. This implementation offers that same recovery-hub approach using an official bot, plus the offline page.

The bot **does not automatically join arbitrary servers, add friends, change your personal profile, or bypass CAPTCHA**. Discord's supported [Add Guild Member API](https://docs.discord.com/developers/resources/guild#add-guild-member) requires user OAuth authorization and a bot already installed in each destination server; it is not a universal account-restore mechanism. Complete any verification requested by Discord through its normal interface. The app stops if a CAPTCHA response is returned.

## Set up your bot once

1. Create a trusted private server in the normal Discord client, or choose one you already own. Do not use a public/community server for personal recovery data.
2. Open the [Discord Developer Portal](https://discord.com/developers/applications), create your own application, and obtain its **bot token** from the Bot settings. Keep it private; do not paste it into GitHub, chat or an issue.
3. Add the bot to your private server using the application's OAuth2 bot installation link. It needs **Manage Channels, View Channels, Send Messages and Read Message History**. Administrator permission and privileged gateway intents are not required by this tool.
4. In the recovery menu, choose the bot hub. Enter the bot token at the hidden prompt. It is not saved. Select the server from the bot's server list, or enter its ID.
5. Review the destination, included sections, number of channels/messages and privacy notice. Type **PUBLISH** to proceed, or press Enter to cancel. You can exclude relationship/DM contact links in the wizard.

If the bot is not installed anywhere yet, the app prints its installation URL using the required permission value. Finish adding it in Discord, then enter the server ID or rerun the hub setup. Enable Discord Developer Mode if you need the client’s Copy Server ID option.

The bot does not need a separately running gateway service for this one-time REST operation. An existing server is required; the app does not create servers with a normal account token. No user-account token is needed for the hub.

## Privacy and partial completion

Each run creates a **new** recovery category. The app denies View Channel to `@everyone`, explicitly allows the server owner and bot, and applies the same overwrites to every child channel. It reads back and validates each channel before posting recovery messages, and checks again before each logical send. Server owners and administrators can still access the data and change permissions between requests: use a server you trust.

All messages disable mentions and link embeds. Imported names are escaped, links use validated Discord IDs/invite codes, and messages are split to fit Discord limits. The hub is limited to 250 messages; use fewer included sections or the local export for a larger backup. Credentials, encrypted backup files and raw frecency settings are never uploaded. Profile images and bio stay in the separately selected local export.

The publisher follows server rate-limit headers and bounded retries. It does not repeat a POST after an ambiguous network/server failure. A failure or cancellation stops publishing and reports the category URL/confirmed counts where known. Created channels are kept, and a request whose response was lost might have succeeded. Inspect the server before rerunning; a new run does not resume or delete an older hub.

## Command line

```sh
# Preview; selects/unlocks the backup and uses a hidden bot-token prompt.
./run.sh restore-hub /path/to/backup.bkup --guild SERVER_ID

# Explicit publish. Private credential files use the same ownership/mode checks.
./run.sh restore-hub /path/to/backup.bkup --guild SERVER_ID \
  --bot-token-file /path/to/private-bot-token --apply

# Keep contacts/relationships out of the selected hub sections.
./run.sh restore-hub /path/to/backup.bkup --guild SERVER_ID \
  --include servers groups warnings --apply
```

Both file and directory selection are supported by `inspect`, `export`, `restore-folders`, `restore-gifs`, `restore-hub` and `recover`. Directory selection and omitted paths require an interactive terminal. For unattended commands, provide a direct file path and private credential/passphrase files. Raw credentials are not accepted as command-line values.

## Verification limits

The implementation uses the documented [bot channel API](https://docs.discord.com/developers/resources/guild#create-guild-channel), [message API](https://docs.discord.com/developers/resources/message#create-message), and [permission overwrites](https://docs.discord.com/developers/topics/permissions). Offline tests cover previews, bot authorization separation, destination changes, channel privacy failures, mention suppression, payload bounds and ambiguous write failures. No live bot/server publication was performed during development; the documented API support is not a guarantee against future Discord changes or account-specific verification.
