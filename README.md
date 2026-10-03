# Zetsubo 2.0 — Seven Deadly Sins Discord Bot

A Railway-ready Python Discord bot. The bot source is `seven_sins_bot.py`.

Use `!myrole` to see your current role, cooldowns, and abilities. The response
includes an interactive button panel: buttons run abilities without arguments,
and abilities that need a target open a small form for a member mention or ID.
The original `!ability_name` text commands remain available as a fallback.

The Hope/Despair legacy kit is included in this 2.0 build: Hope's
`!inspire_strike` and `!despair_wave`, the Ultimate Despair event and
brainwashing actions, summoned Sister and Reserve Course actions, and the
interactive text modal for `!sister_say` / `!sister_anything`. Their outcomes
use 2.0 effects such as wards, ability locks, cooldown tax, misfire, and speech
lag rather than the removed HP/damage combat system.

## Deploy through GitHub to Railway

1. Extract this ZIP.
2. Create a new GitHub repository and push the extracted files to it.
3. In Railway, choose **New Project → Deploy from GitHub repo** and select that repository.
4. Add the required Railway variable:
   - `DISCORD_TOKEN` = your bot token from the Discord Developer Portal.
5. Deploy. Railway will install `requirements.txt` and run `python seven_sins_bot.py`.

Never commit the real token or put it in this ZIP. Add it as a Railway variable only.

## Discord setup

In the Discord Developer Portal, enable these privileged intents under **Bot**:

- **Message Content Intent**
- **Server Members Intent**

Give the bot the permissions it needs for this bot's features:

- View Channels
- Send Messages
- Read Message History
- Embed Links
- Add Reactions
- Manage Messages
- Manage Roles
- Manage Channels
- Moderate Members

Keep the bot's highest role above the roles it needs to create or manage. Discord will not let a bot assign or edit roles above its own highest role.

## Keeping bot data across Railway restarts

The bot writes state to `sins2_data.json`. Railway's regular filesystem is ephemeral. For persistent state:

1. Add a Railway Volume to the service and mount it at `/data`.
2. Add the Railway variable `RAILWAY_VOLUME_MOUNT_PATH=/data`.
3. Redeploy.

Without a volume, the bot still runs, but role ownership, requests, configuration, and audit data can be lost when Railway recreates the container.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DISCORD_TOKEN="your-token"
python seven_sins_bot.py
```
