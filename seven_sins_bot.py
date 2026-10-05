#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
# SEVEN DEADLY SINS TRIAL SYSTEM — Full Version
# Requirements: discord.py >= 2.0, python-dotenv
# pip install "discord.py>=2.0" python-dotenv
# ═══════════════════════════════════════════════════════════════════

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# ───────────────────────────────────────────────────────────────────
# CONFIGURATION — Edit these to match your server
# ───────────────────────────────────────────────────────────────────

DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ".")
DATA_FILE = os.getenv("SINS_DATA_FILE", os.path.join(DATA_DIR, "sins_data.json"))

# Permissions integer for invite URL
# Includes: Manage Roles, Moderate Members, View Channels, Send Messages,
#           Embed Links, Read Message History, Add Reactions, Manage Messages
PERMISSIONS_INT = 268528960

TRIAL_CHANNEL_NAME   = "sins-tribunal"   # All trial announcements go here
GLUTTONY_CHANNEL_NAME = "gluttony-feast" # Gluttony trial monitors this channel

EXPOSE_THRESHOLD      = 5    # 🔍 reacts needed to trigger an expose vote
EXPOSE_VOTE_THRESHOLD = 3    # ✅ votes needed to actually expose the actor
EXPOSE_VOTE_DURATION  = 60   # Seconds the expose vote stays open
FALL_TIMEOUT_DAYS     = 3    # Days a fallen member is timed out
REDEMPTION_COUNT      = 10   # !repent uses required for redemption

PACT_EXPOSE_BONUS     = 3    # Extra 🔍 reacts needed to trigger expose on a pact member
PACT_ALERT_AT         = 3    # Alert partner when this many 🔍 reacts accumulate

# Curse word list — extend as needed
CURSE_WORDS = {
    "fuck", "fucking", "fucked", "fucker", "fucks",
    "shit", "shitting", "shitty", "shitstorm",
    "ass", "asshole", "asses",
    "bitch", "bitches", "bitching",
    "bastard", "bastards",
    "damn", "damned", "damnit",
    "crap", "crappy",
    "hell", "piss", "pissed",
    "dick", "dicks",
    "cock", "cocks",
    "cunt", "cunts",
    "whore", "slut",
    "wtf", "stfu", "gtfo",
}

# ───────────────────────────────────────────────────────────────────
# SIN DEFINITIONS
# ───────────────────────────────────────────────────────────────────
# power         — determines overall difficulty tier and ordering
# role          — the interim trial role shown while active
# final_role    — the actual role granted after passing the trial
# cooldown_hrs  — base cooldown on failure (multiplied by corruption)
# corruption_on_fail — permanent corruption points added on failure
# trial_hours   — window to complete the trial
# ───────────────────────────────────────────────────────────────────

SINS = {
    "lust": {
        "power": 1,
        "role": "Trial — Lust",
        "final_role": "Desire Bound Lust",
        "evolved_role": "Desire Bound Lust",
        "cooldown_hrs": 24,
        "corruption_on_fail": 1,
        "trial_hours": 24,
        "trial_desc": (
            "**Trial of Lust** — Seduce the masses.\n\n"
            "Collect **5 unique ❤️ reactions** from different members on your messages "
            "within **24 hours**. Charm them. Make them want to react.\n\n"
            "Each ❤️ from a new soul counts. Fewer than 5 when time runs out — you fall."
        ),
        "trial_desc_evolved": (
            "**Trial of Lust (Evolved)** — Desperation rises.\n\n"
            "Your corruption has made you less charming. You need **10 unique ❤️ reactions** "
            "from different members within **18 hours**. The masses distrust the corrupted."
        ),
    },
    "gluttony": {
        "power": 2,
        "role": "Trial — Gluttony",
        "final_role": "The Devoured",
        "evolved_role": "The Devoured",
        "cooldown_hrs": 48,
        "corruption_on_fail": 1,
        "trial_hours": 24,
        "trial_desc": (
            "**Trial of Gluttony** — Consume without mercy.\n\n"
            f"React to **every message** posted in **#gluttony-feast** within **5 minutes** "
            "of it being posted, for **24 hours straight**.\n\n"
            "Miss a single message. Wait too long. React after the window. You fall.\n"
            "Gluttony demands total consumption."
        ),
        "trial_desc_evolved": (
            "**Trial of Gluttony (Evolved)** — The feast grows larger.\n\n"
            f"React to every message in **#gluttony-feast** within **2 minutes**, "
            "for **36 hours**. Your appetite was found insufficient once before."
        ),
    },
    "greed": {
        "power": 3,
        "role": "Trial — Greed",
        "final_role": "The False King",
        "evolved_role": "The False King",
        "cooldown_hrs": 72,
        "corruption_on_fail": 2,
        "trial_hours": 8,
        "trial_desc": (
            "**Trial of Greed** — Take what isn't yours.\n\n"
            "Within the next **8 hours**, use `!kill @user` to silence someone. "
            "The server will be told a shadow moved — but **not who**. "
            "The victim cannot speak for **1 hour**.\n\n"
            "⚠️ If **5 members** react 🔍 to the announcement, an expose vote opens. "
            "If the majority votes yes — **you fall from grace.**\n\n"
            "Rule by fear. Don't get caught."
        ),
        "trial_desc_evolved": (
            "**Trial of Greed (Evolved)** — A hungrier king.\n\n"
            "You must silence **2 people** within **6 hours**. "
            "Both silencings carry full expose risk. Your greed has grown insatiable."
        ),
    },
    "sloth": {
        "power": 4,
        "role": "Trial — Sloth",
        "final_role": "The vessel of sloth",
        "evolved_role": "The vessel of sloth",
        "cooldown_hrs": 48,
        "corruption_on_fail": 2,
        "trial_hours": 48,
        "trial_desc": (
            "**Trial of Sloth** — Too lazy to speak properly.\n\n"
            "For **48 hours**, abbreviate **every word** in every message you send. "
            "Any word longer than **4 characters** that is not shortened = **immediate fall from grace**.\n\n"
            "✅ `i hv 2 abbr evry wrd or i fall` — correct\n"
            "❌ `I have to abbreviate` — FALL\n\n"
            "The bot watches every word. Commit to the laziness."
        ),
        "trial_desc_evolved": (
            "**Trial of Sloth (Evolved)** — Deeper into decay.\n\n"
            "For **72 hours**, every word must be **3 characters or fewer**. "
            "Your sloth has consumed what little effort remained."
        ),
    },
    "wrath": {
        "power": 5,
        "role": "Trial — Wrath",
        "final_role": "Crimson heir",
        "evolved_role": "Crimson heir",
        "cooldown_hrs": 72,
        "corruption_on_fail": 2,
        "trial_hours": 24,
        "trial_desc": (
            "**Trial of Wrath** — Let rage consume you.\n\n"
            "For **24 hours**, every message you send **must contain at least one curse word**. "
            "Every. Single. Message.\n\n"
            "Send a message without one — you **fall from grace immediately**.\n\n"
            "The bot monitors everything. Speak with fire or not at all."
        ),
        "trial_desc_evolved": (
            "**Trial of Wrath (Evolved)** — Undying fury.\n\n"
            "For **36 hours**, every message must contain **at least two distinct curse words**. "
            "Your wrath must burn hotter than before."
        ),
    },
    "envy": {
        "power": 6,
        "role": "Trial — Envy",
        "final_role": "The Pale Mirror",
        "evolved_role": "The Pale Mirror",
        "cooldown_hrs": 96,
        "corruption_on_fail": 3,
        "trial_hours": 12,
        "trial_desc": (
            "**Trial of Envy** — Take what they have.\n\n"
            "Use `!envy_strike @user` to silently strip a role from a server member. "
            "The server will be told envy has claimed a role — **not who struck or who lost it**.\n\n"
            "⚠️ If **5 members** react 🔍, an expose vote begins. Majority vote exposes you — "
            "and you **fall from grace**.\n\n"
            "You have **12 hours** to act. Covet. Strike. Stay hidden."
        ),
        "trial_desc_evolved": (
            "**Trial of Envy (Evolved)** — Strip two.\n\n"
            "Strip roles from **2 different members** within **8 hours**. "
            "Both strikes carry full expose risk. Your envy has deepened past reason."
        ),
    },
    "pride": {
        "power": 7,
        "role": "Trial — Pride",
        "final_role": "The bearer of pride",
        "evolved_role": "The bearer of pride",
        "cooldown_hrs": 168,
        "corruption_on_fail": 3,
        "trial_hours": 48,
        "trial_desc": (
            "**Trial of Pride** — Make everyone bow.\n\n"
            "Use `!proclaim <your words>` to demand the server's submission. "
            "Every member is notified. They must react 🙇 to bow, or ❌ to defy you.\n\n"
            "You need **60% of online members** to bow within **48 hours**.\n"
            "If **20+ members** actively defy you (❌) — you **fall immediately**.\n\n"
            "The weight of pride is immense. Rule them all. Or be crushed beneath it."
        ),
        "trial_desc_evolved": (
            "**Trial of Pride (Evolved)** — A crueler crown.\n\n"
            "You need **75% of online members** to bow within **36 hours**, "
            "and **10+ refusals** will crush you immediately. "
            "Your pride already failed once. The bar is higher now."
        ),
    },

    # ── Special Class — not one of the Seven Sins ────────────────────
    "gooner": {
        "power": 1,
        "role": "Trial — Gooner",
        "final_role": "The Fox Gooner",
        "evolved_role": "The Fox Gooner",
        "cooldown_hrs": 72,
        "corruption_on_fail": 1,
        "trial_hours": 168,   # 7 days
        "trial_desc": (
            "**Trial of the Gooner** — Prove your devotion.\n\n"
            "Post **100 images** in **#gooner-trial** within **7 days**. "
            "Every image or video attachment counts as one submission.\n\n"
            "Text-only messages don't count. The bot watches every post.\n\n"
            "Use `!gooner_meter` to track progress at any time.\n\n"
            "Reach 100 — and **The Fox Gooner** title is yours."
        ),
        "trial_desc_evolved": (
            "**Trial of the Gooner (Evolved)** — More. Always more.\n\n"
            "Submit **200 images** within **5 days**. "
            "You failed once. Your devotion must be proven far more intensely."
        ),
    },
}

# ───────────────────────────────────────────────────────────────────
# TRIAL CHANNEL NAMES  (one per sin — these must exist in Discord)
# ───────────────────────────────────────────────────────────────────

TRIAL_CHANNELS = {
    "lust":     "lust",
    "gluttony": "gluttony",
    "greed":    "greed",
    "sloth":    "sloth",
    "wrath":    "wrath",
    "envy":     "envy",
    "pride":    "pride",
    "gooner":   "gooner-trial",
}

# Role-specific channels are created by !setup under the matching Discord
# category.  Shared channels such as #myths and #hope remain available too.
LLORONA_TIMEZONE = "America/Chicago"
LLORONA_DROWN_REQUIRED = 2

# ───────────────────────────────────────────────────────────────────
# TRIAL WELCOME MESSAGES  (shown privately to the new trial holder)
# ───────────────────────────────────────────────────────────────────

TRIAL_WELCOME_MESSAGES: dict[str, dict] = {
    "lust": {
        "title": "❤️ Welcome to the Trial of Lust",
        "color": 0xe91e8c,
        "body": (
            "You have entered the most *intimate* of the seven trials.\n\n"
            "**Your charge:** Seduce the masses. Make them want you.\n\n"
            "Collect **5 unique ❤️ reactions** from different members on your messages "
            "within your trial window. Each soul who reacts is one step closer to your crown.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🕯️ *Lust does not beg. It draws. It lingers. It consumes.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "If you gather enough desire — **Desire Bound Lust** awaits.\n"
            "If you fall short — corruption claims another piece of you.\n\n"
            "This channel is yours for the duration. When your trial ends, this door closes."
        ),
        "footer": "Trial — Lust  |  Power 1  |  The door is open. Step through.",
    },
    "gluttony": {
        "title": "🍔 Welcome to the Trial of Gluttony",
        "color": 0xf4a423,
        "body": (
            "Appetite brought you here. Now let it rule you.\n\n"
            "**Your charge:** Consume without mercy.\n\n"
            "React to **every message** posted in **#gluttony-feast** within **5 minutes** "
            "of it appearing — for the entire duration of your trial. Every message. No exceptions.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🍽️ *Gluttony is not hunger. It is the refusal to stop.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Miss one window — you fall. React late — you fall.\n"
            "Sustain the feast and **The Devoured** is yours.\n\n"
            "This channel is yours alone while the trial lasts."
        ),
        "footer": "Trial — Gluttony  |  Power 2  |  The feast has begun.",
    },
    "greed": {
        "title": "💰 Welcome to the Trial of Greed",
        "color": 0xffd700,
        "body": (
            "Power is taken, not given. You knew this when you came here.\n\n"
            "**Your charge:** Act in shadow. Silence someone.\n\n"
            "Use `!kill @user` to mute a member anonymously. The server will know "
            "a shadow moved — but **not who moved it**. The victim cannot speak for an hour.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👑 *Greed does not steal. It simply redistributes power to the worthy.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ If **5 members** react 🔍 to your announcement, an expose vote opens.\n"
            "If the majority exposes you — **you fall from grace immediately.**\n\n"
            "Rule by fear. Don't get caught. **The False King** awaits the cunning."
        ),
        "footer": "Trial — Greed  |  Power 3  |  The throne is one move away.",
    },
    "sloth": {
        "title": "🛌 Welcome to the Trial of Sloth",
        "color": 0x7b68ee,
        "body": (
            "You chose stillness. Now let laziness become your law.\n\n"
            "**Your charge:** Abbreviate every word — always.\n\n"
            "For the duration of your trial, **every word longer than 4 characters "
            "must be shortened**. In every message. In every channel. Without exception.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💤 *Sloth is not weakness. It is a refusal to waste effort on the unnecessary.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✅ `i hv 2 abbr evry wrd or i fall`\n"
            "❌ `I have to abbreviate` — **FALL**\n\n"
            "The bot reads everything. Commit to the laziness or be consumed by it.\n"
            "Survive — and become **The Vessel of Sloth**."
        ),
        "footer": "Trial — Sloth  |  Power 4  |  Words cost too much. Spend fewer.",
    },
    "wrath": {
        "title": "🔥 Welcome to the Trial of Wrath",
        "color": 0xff2400,
        "body": (
            "You came here burning. Good. Don't stop.\n\n"
            "**Your charge:** Let rage consume every word you speak.\n\n"
            "For the duration of your trial, **every message you send must contain "
            "at least one curse word**. Every. Single. Message. Across the entire server.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚔️ *Wrath is not anger. It is the truth that politeness was always a cage.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Send a clean message — you **fall from grace immediately**. No warnings.\n"
            "The bot is watching every channel. Speak with fire or do not speak at all.\n\n"
            "Hold the flame through your trial — and claim **Crimson Heir**."
        ),
        "footer": "Trial — Wrath  |  Power 5  |  Burn until nothing clean remains.",
    },
    "envy": {
        "title": "👁️ Welcome to the Trial of Envy",
        "color": 0x00b4d8,
        "body": (
            "You have always wanted what they have. Now you can take it.\n\n"
            "**Your charge:** Strip what belongs to another.\n\n"
            "Use `!envy_strike @user` to anonymously remove a role from a server member. "
            "The server will know envy has moved — **not who moved it, not who lost it.**\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🌑 *Envy does not covet in silence. It acts in the dark and watches from a distance.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ Five 🔍 reacts on your announcement opens an expose vote.\n"
            "If exposed — **you fall.**\n\n"
            "Stay hidden. Strike clean. Become **The Pale Mirror**."
        ),
        "footer": "Trial — Envy  |  Power 6  |  Take what was never yours to begin with.",
    },
    "pride": {
        "title": "👑 Welcome to the Trial of Pride",
        "color": 0xffffff,
        "body": (
            "You believe you are above them. Now prove it.\n\n"
            "**Your charge:** Make the entire server bow to you.\n\n"
            "Use `!proclaim <your words>` to demand submission. Every member is notified. "
            "They react 🙇 to bow — or ❌ to defy you openly.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🌟 *Pride is not arrogance. It is the certainty that you were built differently.*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "You need **60% of online members** to bow within your trial window.\n"
            "If **20+ members** actively defy you — you are **crushed immediately**.\n\n"
            "Break them. Bend them. And take your place as **The Bearer of Pride.**\n\n"
            "*This is the highest sin. The weight of it is real.*"
        ),
        "footer": "Trial — Pride  |  Power 7  |  The crown is earned by those who demand it.",
    },
}

# ───────────────────────────────────────────────────────────────────
# VIRTUE DEFINITIONS (unlocked after completing the corresponding sin)
# ───────────────────────────────────────────────────────────────────

VIRTUES = {
    "lust":     {"role": "The Chaste",           "power": 8,  "virtue": "Chastity"},
    "gluttony": {"role": "The Fasting King",      "power": 9,  "virtue": "Temperance"},
    "greed":    {"role": "The Open Hand",         "power": 10, "virtue": "Charity"},
    "sloth":    {"role": "The Waking",            "power": 11, "virtue": "Diligence"},
    "wrath":    {"role": "The Still Flame",       "power": 12, "virtue": "Patience"},
    "envy":     {"role": "The Mirror's Grace",    "power": 13, "virtue": "Kindness"},
    "pride":    {"role": "The Humble Sovereign",  "power": 14, "virtue": "Humility"},
}

# ───────────────────────────────────────────────────────────────────
# MYTH DEFINITIONS
# ───────────────────────────────────────────────────────────────────
# Myths are standalone roles. They do not replace a member's sin or virtue
# and are assigned by an administrator with !grant_myth.

MYTHS = {
    "la_llorona": {
        "name": "La Llorona",
        "role": "La Llorona",
        "color": discord.Color.from_rgb(70, 150, 175),
        "lore": (
            "The Weeping Woman who wanders beside the river, searching for what "
            "she lost. Her sorrow is a warning, her cry is a curse, and the river "
            "never truly lets its chosen escape."
        ),
        "abilities": (
            ("!llorona_wail @user", "The Wail — locks the target's abilities for 10 minutes and weakens their clash power for 20 minutes. (1-hour cooldown)"),
            ("!llorona_veil", "Weeping Veil — the next attack against you is nullified within 30 minutes. (2-hour cooldown)"),
            ("!llorona_lure @user", "River's Lure — pulls a target into silence with a 1-minute timeout; if Discord refuses the timeout, the target is ability-locked for 5 minutes. (3-hour cooldown)"),
        ),
    },
}

VIRTUE_TRIALS = {
    "lust": (
        "**Virtue Trial — Chastity**\n\n"
        "For **48 hours**, do not react ❤️ to a single message. Not one.\n"
        "Resist every temptation. Any ❤️ reaction you add — you fail."
    ),
    "gluttony": (
        "**Virtue Trial — Temperance**\n\n"
        "For **24 hours**, add **no reactions at all** to any message.\n"
        "Consume nothing. Be still. Any reaction fails the trial."
    ),
    "greed": (
        "**Virtue Trial — Charity**\n\n"
        "Use `!give_role @user <role name>` to give a role you hold to another member.\n"
        "An admin must confirm with `!confirm_give @user`.\n"
        "Complete within **24 hours**."
    ),
    "sloth": (
        "**Virtue Trial — Diligence**\n\n"
        "Send at least one message of **20+ words** every hour, for **24 consecutive hours**.\n"
        "Silence during any hour = failure. The bot tracks each unique hour."
    ),
    "wrath": (
        "**Virtue Trial — Patience**\n\n"
        "For **48 hours**, send **no curse words** in any message.\n"
        "One slip — you fail. The bot watches every word."
    ),
    "envy": (
        "**Virtue Trial — Kindness**\n\n"
        "Use `!praise @user <message>` to compliment **5 different members** within **24 hours**.\n"
        "Each message must be at least **10 words**. Admins may verify authenticity."
    ),
    "pride": (
        "**Virtue Trial — Humility**\n\n"
        "Use `!bow_down <message>` to publicly honor others above yourself.\n"
        "Get **10 unique members** to react 🙏 within **48 hours**.\n"
        "Your message must genuinely elevate others."
    ),
}

FALLEN_ROLE   = "Fallen from Grace"
EVERYONE_ROLE = "@everyone"
JUSTICE_ROLE      = "The Scales of Justice"
PRUDENCE_ROLE     = "The Prudent Eye"
FORTITUDE_ROLE    = "The Unbroken"
FAITH_ROLE        = "The Faithful"
HOPE_ROLE         = "The Hopeful"
LIBERALITY_ROLE   = "The Open Spirit"

STANDALONE_VIRTUE_ROLES = {
    "justice":    JUSTICE_ROLE,
    "prudence":   PRUDENCE_ROLE,
    "fortitude":  FORTITUDE_ROLE,
    "faith":      FAITH_ROLE,
    "hope":       HOPE_ROLE,
    "liberality": LIBERALITY_ROLE,
}

# Commands that mark a user as having done something sinful (used for Justice's clean-record check)
SINFUL_COMMANDS = frozenset({
    "devour", "feast", "gorge", "flash", "withered_meat",
    "jealousy_mark", "envy_strike", "schizo", "steal_ability",
    "weaken", "claim", "stop_time", "rage_strike", "meteor_drop",
    "bloodlust", "lose_yourself", "deep_sleep", "slow_type",
    "obsession_clash", "obsess", "i_dont_care_if_theyre_watching",
})

# ───────────────────────────────────────────────────────────────────
# INTENTS & BOT
# ───────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds          = True
intents.members         = True
intents.reactions       = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ───────────────────────────────────────────────────────────────────
# DATA PERSISTENCE
# ───────────────────────────────────────────────────────────────────

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return _empty_data()
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

def _empty_data() -> dict:
    return {
        "users": {},
        "claimed_sins": {},      # sin -> user_id (str)
        "expose_votes": {},      # msg_id -> vote info
        "greed_actions": {},     # action_id -> details
        "envy_actions": {},      # action_id -> details
        "bounties": {},          # target_user_id -> list of { placer_id, ts, expires }
        "pacts": {},             # user_id -> { partner_id, status: pending/active, ts }
        "envy_marks": {},        # envy_holder_id -> { target_id, target_sin, expires, resolved }
        "weakened_sins": {},     # sin -> { weakened_by, expires, power_penalty }
        "active_claims": {},     # msg_id -> claim info dict
        "stolen_abilities": [],  # [{holder_id, ability_key, expires, original_holder_id}]
        "stop_time_active": False, # True while Pride has server frozen
        "stop_time_until":  0,   # timestamp when freeze ends
        "feast_cursed": {},      # uid -> {expires, marks, by_id}
        "force_lazy_targets": {},  # uid -> {expires, by_id}
        "slowdown_targets": {},  # uid -> {expires, last_msg_ts, by_id}
        "pending_trials":    {},  # trial_key -> trial dict (jacobs / scale_of_wrongdoing)
        "brainwashed":       {},     # target_id -> { by_id, until, self_damage }
        "disaster_active":   False,
        "disaster_until":    0,
        "disaster_by":       None,
        "reserve_course":    {},     # user_id -> list of { uid, name, hp }
        "tragic_event_chains": {},   # channel_id -> { last_despair_user_id, ts }
        "despair_sister":    {},     # holder_id -> { active, name, summoned_at }
    }
def get_user(data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            # Core state
            "corruption":         0,
            "completed_sins":     [],
            "completed_virtues":  [],
            "sin_role":           None,   # sin name they currently hold (post-trial)
            "fallen":             False,
            "fallen_until":       None,
            "redemption_count":   0,
            "total_falls":        0,
            "cooldowns":          {},     # sin -> expire timestamp

            # Active sin trial
            "trial_sin":          None,
            "trial_end":          None,

            # Per-sin trial progress (reset each trial)
            "lust_hearts":            [],  # list of user_ids who reacted ❤️
            "gluttony_pending":       {},  # msg_id -> deadline timestamp
            "wrath_fail":             False,
            "sloth_fail":             False,
            "greed_kills_done":       0,
            "greed_kills_needed":     1,
            "envy_strikes_done":      0,
            "envy_strikes_needed":    1,
            "pride_msg_id":           None,
            "pride_channel_id":       None,
            "pride_bows":             0,
            "pride_refusals":         0,

            # Virtue trial
            "virtue_trial_sin":       None,
            "virtue_trial_end":       None,
            "virtue_progress":        {},

            # Full history log — list of event dicts, oldest first
            # Each entry: { type, sin, ts, outcome, reason, corruption_after }
            "trial_log":              [],

            # New ability fields
            "marks_of_insecurity":    0,      # from Pride claim mechanic
            "ability_locked_until":   None,   # Krodingers Effect lockout
            "envy_ability_locked_until": None, # from failed jealousy check
            "jealousy_role_cds":      {},     # sin -> expire ts (1d per role)
            "stolen_roles":           [],     # [{ role, expires, from_id }]
            "claim_cooldown":         None,   # Pride claim cooldown timestamp

            # Lust Obsession System
            "obsession_target":       None,
            "obsession_meter":        0,
            "obsession_phrase_cds":   {},
            "heart_react_cds":        {},
            "possession_marks":       {},
            "obsession_clash_cd":     None,
            "obsession_switch_cd":    None,

            # Gluttony abilities
            "gluttony_ability_cds":   {},   # ability_key -> ts
            "gorge_active_until":     None,
            "clash_power_bonus":      0,    # temporary +coins bonus (gorge, frenzy, etc.)
            "clash_power_penalty":    0,    # temporary -coins penalty
            "clash_penalty_until":    None,

            # Greed abilities
            "anger_meter":            0,    # 0-100
            "frenzy_active":          False,
            "frenzy_used":            False,
            "greed_steals_today":     0,
            "greed_steals_reset_ts":  None,
            "greed_recent_steals":    [],   # list of timestamps (lose-yourself check)
            "greed_ability_cds":      {},
            "lose_yourself_until":    None,

            # Wrath abilities
            "wrath_ability_cds":      {},
            "bloodlust_active":       False,
            "bloodlust_until":        None,

            # Sloth abilities
            "laziness_meter":         0,    # 0-100
            "deep_sleep_count":       0,    # voluntary deep sleeps accumulated
            "deep_sleep_until":       None,
            "sleepwalker_unlocked":   False,
            "sleepwalker_active_until": None,
            "slow_type_until":        None,
            "slow_type_last_msg_ts":  None,
            "sloth_ability_cds":      {},

            # Pride — stop time
            "pride_recognition":      0,    # accumulated from claim bows
            "stop_time_unlocked":     False,
            "stop_time_cd":           None,
            "stop_time_passive":      False, # if True, next clash against Pride auto-fails
            "speaking_restricted_until": None,

            # Gooner abilities
            "gooner_ability_cds":     {},
            "gooner_images_submitted": 0,
            "withered_until":         None,  # ability lock from Gooner's !withered_meat
            "devoured_until":         None,  # command lock from Gluttony's !devour

            # Justice fields
            "justice_ability_cds":      {},
            "last_sin_action_ts":       None,  # when user last used a sinful command
            "last_sin_abilities_used":  [],    # [ability_name, ...] — last 5 sinful actions

            # Cardinal/Heavenly standalone virtue fields
            "prudence_ability_cds":     {},
            "fortitude_ability_cds":    {},
            "endure_until":             None,  # Fortitude self-buff
            "fortify_until":            None,  # Fortify shield on target (stored on target)
            "faith_ability_cds":        {},
            "faith_invoke_until":       None,  # Faith +1 effective clash power
            "prayer_shield_until":      None,  # Faith prayer halves next ability-lock duration
            "hope_ability_cds":         {},
            "beacon_until":             None,  # Hope beacon buff window
            "liberality_ability_cds":   {},
            "condemned_until":          None,  # Justice !condemn — -1 clash power passive

            # Danganronpa character system
            "character":              None,
            "character_hope":         False,
            "character_despair":      False,
            "myth":                   None,
            "myth_ability_cds":       {},
            "llorona_veil_until":     None,
            "llorona_drown_day":      None,
            "llorona_drown_targets":  [],
            "reserve_course":         True,
            "shock_turns":            0,
            "panic_turns":            0,
            "shock_active":           False,
            "panic_active":           False,
            "izuru_approval_votes":   {},
            "izuru_approved_by":      [],
            "izuru_surgery_done":     False,
            "izuru_mastery_locked":   True,
            "izuru_mastery_unlocked": False,
            "chiaki_dead":            False,
        }
    else:
        u = data["users"][uid]
        u.setdefault("marks_of_insecurity",    0)
        u.setdefault("ability_locked_until",   None)
        u.setdefault("envy_ability_locked_until", None)
        u.setdefault("jealousy_role_cds",      {})
        u.setdefault("stolen_roles",           [])
        u.setdefault("claim_cooldown",         None)
        u.setdefault("obsession_target",       None)
        u.setdefault("obsession_meter",        0)
        u.setdefault("obsession_phrase_cds",   {})
        u.setdefault("heart_react_cds",        {})
        u.setdefault("possession_marks",       {})
        u.setdefault("obsession_clash_cd",     None)
        u.setdefault("obsession_switch_cd",    None)
        u.setdefault("gluttony_ability_cds",   {})
        u.setdefault("gorge_active_until",     None)
        u.setdefault("clash_power_bonus",      0)
        u.setdefault("clash_power_penalty",    0)
        u.setdefault("clash_penalty_until",    None)
        u.setdefault("anger_meter",            0)
        u.setdefault("frenzy_active",          False)
        u.setdefault("frenzy_used",            False)
        u.setdefault("greed_steals_today",     0)
        u.setdefault("greed_steals_reset_ts",  None)
        u.setdefault("greed_recent_steals",    [])
        u.setdefault("greed_ability_cds",      {})
        u.setdefault("lose_yourself_until",    None)
        u.setdefault("wrath_ability_cds",      {})
        u.setdefault("bloodlust_active",       False)
        u.setdefault("bloodlust_until",        None)
        u.setdefault("laziness_meter",         0)
        u.setdefault("deep_sleep_count",       0)
        u.setdefault("deep_sleep_until",       None)
        u.setdefault("sleepwalker_unlocked",   False)
        u.setdefault("sleepwalker_active_until", None)
        u.setdefault("slow_type_until",        None)
        u.setdefault("slow_type_last_msg_ts",  None)
        u.setdefault("sloth_ability_cds",      {})
        u.setdefault("pride_recognition",      0)
        u.setdefault("stop_time_unlocked",     False)
        u.setdefault("stop_time_cd",           None)
        u.setdefault("stop_time_passive",      False)
        u.setdefault("speaking_restricted_until", None)
        # Gooner ability data
        u.setdefault("gooner_ability_cds",      {})
        u.setdefault("gooner_images_submitted", 0)
        u.setdefault("withered_until",          None)
        u.setdefault("devoured_until",          None)
        # Justice ability data
        u.setdefault("justice_ability_cds",     {})
        u.setdefault("last_sin_action_ts",      None)
        u.setdefault("last_sin_abilities_used", [])
        # Cardinal/Heavenly standalone virtue data
        u.setdefault("prudence_ability_cds",    {})
        u.setdefault("fortitude_ability_cds",   {})
        u.setdefault("endure_until",            None)
        u.setdefault("fortify_until",           None)
        u.setdefault("faith_ability_cds",       {})
        u.setdefault("faith_invoke_until",      None)
        u.setdefault("prayer_shield_until",     None)
        u.setdefault("hope_ability_cds",        {})
        u.setdefault("beacon_until",            None)
        u.setdefault("liberality_ability_cds",  {})
        u.setdefault("condemned_until",         None)
        # Virtue ability data
        u.setdefault("virtue_ability_cds",    {})
        u.setdefault("abstain_shield_until",  None)
        u.setdefault("power_gifted",          None)
        u.setdefault("absorb_active",         False)
        u.setdefault("absorb_until",          None)
        u.setdefault("insecurity_shield_until", None)
        # Myth ability data
        u.setdefault("myth",                  None)
        u.setdefault("myth_ability_cds",      {})
        u.setdefault("llorona_veil_until",    None)
        u.setdefault("llorona_drown_day",     None)
        u.setdefault("llorona_drown_targets", [])
        # Path system
        u.setdefault("path",                  None)   # "support"|"attack"|"hybrid"|"tacht"|"reverence"
        u.setdefault("path_change_cd",        None)   # ts when path can be changed again
        u.setdefault("path_ability_cds",      {})     # ability_key -> ts
        u.setdefault("clash_shield_until",    None)   # support path: soaks next clash loss
        u.setdefault("tacht_burst_until",     None)   # tacht burst window
        u.setdefault("reverence_aura_until",  None)   # reverence aura active
        u.setdefault("tribute_owed",          None)   # {from_id, expires, msg_id}
        u.setdefault("reverence_stacks",      {})     # uid -> count of clashes against this user
    _dr_ensure(data["users"][uid])
    return data["users"][uid]

# ───────────────────────────────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────────────────────────────

def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def ts_fmt(ts: float) -> str:
    """Discord relative timestamp."""
    return f"<t:{int(ts)}:R>"

def remaining_fmt(end_ts: float) -> str:
    secs = end_ts - now_ts()
    if secs <= 0:
        return "expired"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    return f"{h}h {m}m"

def is_evolved(user: dict) -> bool:
    return user.get("corruption", 0) >= 5

def has_curse(text: str) -> bool:
    return any(w in CURSE_WORDS for w in re.findall(r"\w+", text.lower()))

def count_distinct_curses(text: str) -> int:
    words = set(re.findall(r"\w+", text.lower()))
    return len(words & CURSE_WORDS)

def _clean(word: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", word)

def check_sloth(text: str, evolved: bool) -> bool:
    """True = message passes sloth rule (all words abbreviated)."""
    limit = 3 if evolved else 4
    for word in text.split():
        c = _clean(word)
        if not c or c.isdigit():
            continue
        if len(c) > limit:
            return False
    return True

async def trial_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    return discord.utils.get(guild.text_channels, name=TRIAL_CHANNEL_NAME)

async def gluttony_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    return discord.utils.get(guild.text_channels, name=GLUTTONY_CHANNEL_NAME)

# ───────────────────────────────────────────────────────────────────
# COIN FLIP SYSTEM
# ───────────────────────────────────────────────────────────────────

# How many coins (rolls) each ability gets — more coins = better odds
ABILITY_COINS: dict[str, int] = {
    "schizo":  2,   # Envy ability 2 — 2 rolls, take highest
    "weaken":  3,   # Pride ability 1 — 3 rolls, take highest
}

# Coin power for EVERY ability (clashable or not) — used by Greed steal clashes
ABILITY_COIN_POWER: dict[str, int] = {
    "lust_obsession":      2,
    "gluttony_feast":      2,
    "gluttony_gorge":      2,
    "greed_steal":         3,
    "wrath_rage_strike":   3,
    "wrath_bloodlust":     3,
    "sloth_force_lazy":    2,
    "sloth_slowdown":      2,
    "sloth_sleep":         3,
    "sloth_sleepwalker":   5,
    "pride_stop_time":     5,
    "pride_weaken":        3,
    "pride_claim":         4,
    "envy_jealousy_mark":  2,
    "envy_schizo":         2,
}

# Primary ability per sin (what Greed targets when stealing)
SIN_PRIMARY_ABILITY: dict[str, str] = {
    "lust":     "lust_obsession",
    "gluttony": "gluttony_feast",
    "greed":    "greed_steal",
    "sloth":    "sloth_sleep",
    "wrath":    "wrath_rage_strike",
    "envy":     "envy_jealousy_mark",
    "pride":    "pride_claim",
}

# ── Greed constants ──────────────────────────────────────
GREED_MAX_STEALS_PER_DAY    = 5
GREED_LOSE_YOURSELF_WINDOW  = 30 * 60   # 30 min window for rapid-steal check
GREED_LOSE_YOURSELF_THRESH  = 3         # 3 steals in window = lose yourself
ANGER_METER_PER_LOSS        = 20        # 5 losses → 100% → frenzy
STOLEN_ABILITY_DURATION     = 30 * 60   # Stolen ability returns after 30 min

# ── Sloth constants ──────────────────────────────────────
LAZINESS_METER_PER_USE      = 20        # 5 ability uses → 100% → forced deep sleep
SLOW_TYPE_INTERVAL          = 45        # seconds required between messages when type-slowed
DEEP_SLEEP_THRESHOLD        = 5         # voluntary deep sleeps to unlock Sleepwalker
DEEP_SLEEP_DURATION         = 15 * 60   # forced/voluntary deep sleep lasts 15 min
SLOTH_ABILITY_COOLDOWN      = 60 * 60   # base cooldown for sloth abilities

# ── Wrath constants ──────────────────────────────────────
WRATH_BLOODLUST_DURATION    = 20 * 60   # 20 minutes

# ── Pride / Stop Time constants ───────────────────────────
PRIDE_RECOGNITION_THRESHOLD = 15        # bow-recognition points to unlock stop time
STOP_TIME_DURATION          = 2 * 60    # server freeze lasts 2 minutes
STOP_TIME_COOLDOWN          = 4 * 3600  # 4-hour cooldown
STOP_TIME_SPEAK_BAN         = 5 * 60    # 5-min speaking restriction after use

# ── Gluttony constants ────────────────────────────────────
FOOD_EMOJIS = {
    "🍕","🍔","🌮","🍜","🍩","🥩","🍰","🌽","🍣","🍝",
    "🥗","🍦","🍺","🍗","🍖","🥪","🍱","🥐","🧁","🫔",
}
FEAST_DURATION              = 20 * 60   # feast curse lasts 20 min
FEAST_MARKS_FOR_PENALTY     = 3         # marks before clash power penalty
GORGE_DURATION              = 15 * 60   # gorge buff lasts 15 min
GORGE_ACTIVITY_WINDOW       = 10 * 60   # look back 10 min for server msgs

# ── VIRTUE ABILITY CONSTANTS ─────────────────────────────────────────
VIRTUE_CD_SHORT    = 3600       # 1 hr
VIRTUE_CD_MEDIUM   = 7200       # 2 hr
VIRTUE_CD_LONG     = 10800      # 3 hr
VIRTUE_SHIELD_DURATION   = 3600   # 1 hr for chastity shield / other shields
VIRTUE_INSPIRE_BONUS     = 1      # +1 clash coin from Diligence inspire
VIRTUE_ABSORB_DURATION   = 1800   # 30 min patience absorb

# ── PATH SYSTEM CONSTANTS ─────────────────────────────────────────
VALID_PATHS = ("support", "attack", "hybrid", "tacht", "reverence")
PATH_CHANGE_COOLDOWN  = 7 * 86400   # 7 days to change paths
TACHT_BURST_DURATION  = 20 * 60     # speed burst window
TACHT_BURST_CD        = 3 * 3600
TACHT_STRIKE_CD       = 3600
REVERENCE_AURA_DURATION = 30 * 60
REVERENCE_AURA_CD     = 3 * 3600
TRIBUTE_DURATION      = 20 * 60
TRIBUTE_CD            = 2 * 3600
METEOR_COINS          = 5           # Wrath meteor (very powerful)
DESPAIR_ROLE                = "The Ultimate Despair"
REMNANT_OF_DESPAIR_ROLE     = "Remnant of Despair"
RESERVE_COURSE_ROLE         = "Reserve Course Student"
DESPAIR_SISTER_ROLE         = "Despair Sister"
HOPE_ROLE                   = "The Hopeful"

DESPAIR_CORRUPTION_REQUIRED = 50    # corruption needed to obtain Despair
DESPAIR_DAY                 = 4     # 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday
DESPAIR_HOUR                = 20    # 8 PM (24h format)
DESPAIR_MINUTE              = 12    # 8:12 PM

DESPAIR_OBTAINMENT_WINDOW_MINUTES = 5  # 5-minute window at exactly 8:12 PM

BRAINWASH_DURATION_MINUTES  = 30    # how long brainwash lasts
BRAINWASH_SELF_DAMAGE       = 5     # HP damage when brainwashed target attacks
DISASTER_DURATION_MINUTES   = 30    # disaster event length
RESERVE_COURSE_COUNT        = 3     # how many students summon brings
EVERYONE_ROLE = "@everyone"

SPECIAL_ROLE_KEYS = {
    "justice": JUSTICE_ROLE,
    "prudence": PRUDENCE_ROLE,
    "fortitude": FORTITUDE_ROLE,
    "faith": FAITH_ROLE,
    "hope": HOPE_ROLE,
    "liberality": LIBERALITY_ROLE,
    "despair": DESPAIR_ROLE,
    "remnant": REMNANT_OF_DESPAIR_ROLE,
    "reserve": RESERVE_COURSE_ROLE,
    "sister": DESPAIR_SISTER_ROLE,
}

# ───────────────────────────────────────────────────────────────────
# DANGANRONPA CHARACTER SYSTEM
# ───────────────────────────────────────────────────────────────────

# Character definitions: each has a Hope and Despair version role
# Chiaki has NO despair version (pure hope)
CHARACTERS = {
    "nagito": {
        "name": "Nagito Komaeda",
        "talent": "Ultimate Luck",
        "hope_role": "Nagito Komaeda: Ultimate Luck",
        "despair_role": "Nagito Komaeda: Ultimate Despair",
        "stats": (100, 12, 5),
        "color_hope": discord.Color.from_rgb(0, 200, 100),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "akane": {
        "name": "Akane Owari",
        "talent": "Ultimate Gymnast",
        "hope_role": "Akane Owari: Ultimate Gymnast",
        "despair_role": "Akane Owari: Ultimate Despair",
        "stats": (110, 14, 4),
        "color_hope": discord.Color.from_rgb(200, 100, 0),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "sonia": {
        "name": "Sonia Nevermind",
        "talent": "Ultimate Princess",
        "hope_role": "Sonia Nevermind: Ultimate Princess",
        "despair_role": "Sonia Nevermind: Ultimate Despair",
        "stats": (95, 10, 7),
        "color_hope": discord.Color.from_rgb(150, 50, 200),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "fuyuhiko": {
        "name": "Fuyuhiko Kuzuryu",
        "talent": "Ultimate Yakuza",
        "hope_role": "Fuyuhiko Kuzuryu: Ultimate Yakuza",
        "despair_role": "Fuyuhiko Kuzuryu: Ultimate Despair",
        "stats": (105, 13, 6),
        "color_hope": discord.Color.from_rgb(200, 50, 50),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "kazuichi": {
        "name": "Kazuichi Soda",
        "talent": "Ultimate Mechanic",
        "hope_role": "Kazuichi Soda: Ultimate Mechanic",
        "despair_role": "Kazuichi Soda: Ultimate Despair",
        "stats": (90, 11, 6),
        "color_hope": discord.Color.from_rgb(100, 150, 50),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "hiyoko": {
        "name": "Hiyoko Saionji",
        "talent": "Ultimate Traditional Dancer",
        "hope_role": "Hiyoko Saionji: Ultimate Traditional Dancer",
        "despair_role": "Hiyoko Saionji: Ultimate Despair",
        "stats": (85, 10, 4),
        "color_hope": discord.Color.from_rgb(255, 200, 220),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "mikan": {
        "name": "Mikan Tsumiki",
        "talent": "Ultimate Nurse",
        "hope_role": "Mikan Tsumiki: Ultimate Nurse",
        "despair_role": "Mikan Tsumiki: Ultimate Despair",
        "stats": (80, 8, 5),
        "color_hope": discord.Color.from_rgb(200, 100, 200),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "ibuki": {
        "name": "Ibuki Mioda",
        "talent": "Ultimate Musician",
        "hope_role": "Ibuki Mioda: Ultimate Musician",
        "despair_role": "Ibuki Mioda: Ultimate Despair",
        "stats": (95, 12, 4),
        "color_hope": discord.Color.from_rgb(100, 0, 200),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "mahiru": {
        "name": "Mahiru Koizumi",
        "talent": "Ultimate Photographer",
        "hope_role": "Mahiru Koizumi: Ultimate Photographer",
        "despair_role": "Mahiru Koizumi: Ultimate Despair",
        "stats": (90, 10, 5),
        "color_hope": discord.Color.from_rgb(200, 100, 100),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "nekomaru": {
        "name": "Nekomaru Nidai",
        "talent": "Ultimate Athlete",
        "hope_role": "Nekomaru Nidai: Ultimate Athlete",
        "despair_role": "Nekomaru Nidai: Ultimate Despair",
        "stats": (130, 15, 8),
        "color_hope": discord.Color.from_rgb(100, 50, 0),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "gundham": {
        "name": "Gundham Tanaka",
        "talent": "Ultimate Breeder",
        "hope_role": "Gundham Tanaka: Ultimate Breeder",
        "despair_role": "Gundham Tanaka: Ultimate Despair",
        "stats": (100, 11, 6),
        "color_hope": discord.Color.from_rgb(50, 0, 100),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "teruteru": {
        "name": "Teruteru Hanamura",
        "talent": "Ultimate Chef",
        "hope_role": "Teruteru Hanamura: Ultimate Chef",
        "despair_role": "Teruteru Hanamura: Ultimate Despair",
        "stats": (85, 10, 5),
        "color_hope": discord.Color.from_rgb(200, 50, 150),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "peko": {
        "name": "Peko Pekoyama",
        "talent": "Ultimate Swordswoman",
        "hope_role": "Peko Pekoyama: Ultimate Swordswoman",
        "despair_role": "Peko Pekoyama: Ultimate Despair",
        "stats": (110, 16, 6),
        "color_hope": discord.Color.from_rgb(100, 100, 150),
        "color_despair": discord.Color.from_rgb(80, 0, 0),
    },
    "chiaki": {
        "name": "Chiaki Nanami",
        "talent": "Ultimate Gamer",
        "hope_role": "Chiaki Nanami: Ultimate Gamer",
        "despair_role": None,  # NO despair version — pure hope
        "stats": (95, 11, 6),
        "color_hope": discord.Color.from_rgb(150, 50, 150),
        "color_despair": None,
    },
}

# Izuru Kamakura roles
IZURU_DESPAIR_ROLE = "Izuru Kamakura: Ultimate Despair"
IZURU_HOPE_ROLE = "Izuru Kamakura: Ultimate Hope"

# Izuru Hope obtainment requirements
IZURU_HOPE_CORRUPTION_REQUIRED = 32
IZURU_HOPE_POINTS_REQUIRED = 7
IZURU_HOPE_APPROVALS_REQUIRED = 5

METEOR_CD             = 4 * 3600
SUPPORT_SHIELD_USES   = 1           # shield soaks 1 clash loss
PATH_ABILITY_CD       = 2 * 3600    # default sin-specific path ability CD
PATH_DESCRIPTIONS = {
    "support":   "**Support** — Protect and heal allies. Counteract debuffs, absorb damage for others.",
    "attack":    "**Attack** — Pure offense. Stronger strikes, new debuffs, raw clash power.",
    "hybrid":    "**Hybrid** — Attack+Support. Abilities that buff an ally and debuff an enemy in one action.",
    "tacht":     "**TACHT (Tactical Athletic Combat High-speed Technique)** — Speed and Strength. Reduced cooldowns, preemptive strikes, and power bursts.",
    "reverence": "**Reverence** — Command presence. Project aura, demand tribute, make others bow or suffer.",
}

def coin_flip(coins_a: int, coins_b: int) -> tuple[str, int, int]:
    """
    Roll d20s. Each side takes the max of their rolls.
    Returns ('a'|'b', roll_a, roll_b). Ties are rerolled automatically.
    """
    while True:
        roll_a = max(random.randint(1, 20) for _ in range(max(1, coins_a)))
        roll_b = max(random.randint(1, 20) for _ in range(max(1, coins_b)))
        if roll_a != roll_b:
            return ("a" if roll_a > roll_b else "b"), roll_a, roll_b

# ───────────────────────────────────────────────────────────────────
# PRIDE / ENVY ABILITY HELPERS
# ───────────────────────────────────────────────────────────────────

def krodingers_threshold(power: int) -> int:
    """Marks of insecurity needed to trigger Krodingers Effect (ability lockout)."""
    if power >= 7:   return 3
    elif power >= 5: return 4
    elif power >= 3: return 5
    else:            return 6

def bow_window_secs(power: int) -> int:
    """Seconds a sin holder has to bow after a Pride claim. Lower power → more time."""
    table = {1: 20*60, 2: 18*60, 3: 16*60, 4: 14*60, 5: 10*60, 6: 7*60, 7: 5*60}
    return table.get(power, 10*60)

def steal_duration_secs(power: int) -> int:
    """How long Envy holds a stolen role. Higher target power → shorter steal window."""
    base      = 60 * 60          # 1 hour base
    reduction = power * 8 * 60   # 8 min per power level
    return max(base - reduction, 15 * 60)  # floor: 15 minutes

def effective_sin_power(sin: str, data: dict) -> int:
    """Current effective power of a sin (reduced if weakened by Pride)."""
    base = SINS[sin]["power"]
    w    = data.get("weakened_sins", {}).get(sin)
    if w and now_ts() < w.get("expires", 0):
        return max(1, base - w.get("power_penalty", 0))
    return base

async def _resolve_expired_envy_marks(data: dict):
    """Resolve jealousy marks whose window expired without an envy_check."""
    now   = now_ts()
    marks = data.get("envy_marks", {})
    for envy_uid, info in list(marks.items()):
        if info.get("resolved") or now <= info.get("expires", 0):
            continue
        info["resolved"] = True
        target_id  = info.get("target_id")
        target_sin = info.get("target_sin")
        if not target_id or not target_sin or target_sin not in SINS:
            continue
        envy_holder = None
        target      = None
        for g in bot.guilds:
            envy_holder = envy_holder or g.get_member(int(envy_uid))
            target      = target      or g.get_member(int(target_id))
        if not envy_holder or not target:
            continue
        envy_user = get_user(data, int(envy_uid))
        power     = SINS[target_sin]["power"]
        duration  = steal_duration_secs(power)
        expires   = now + duration
        role_name = SINS[target_sin]["final_role"]
        envy_user.setdefault("stolen_roles", []).append({
            "role": role_name, "expires": expires, "from_id": target_id,
        })
        envy_user.setdefault("jealousy_role_cds", {})[target_sin] = now + 86400
        try:
            role_obj = discord.utils.get(envy_holder.guild.roles, name=role_name)
            if role_obj:
                await envy_holder.add_roles(role_obj, reason="Envy role steal")
        except Exception:
            pass
        ch = await trial_channel(envy_holder.guild)
        if ch:
            mins = duration // 60
            await ch.send(embed=discord.Embed(
                title="🌑 Envy Has Taken",
                description=(
                    f"The marked one did not check themselves in time. "
                    f"**Envy has seized** the aura of **{role_name}** for **{mins} minutes**.\n\n"
                    "The stolen power vanishes when the clock runs out."
                ),
                color=discord.Color.from_rgb(0, 100, 130),
            ))

async def _return_stolen_roles(data: dict):
    """Remove stolen roles whose duration has expired."""
    now = now_ts()
    for uid, user in data["users"].items():
        for entry in list(user.get("stolen_roles", [])):
            if now < entry.get("expires", 0):
                continue
            role_name = entry.get("role")
            for g in bot.guilds:
                member = g.get_member(int(uid))
                if member:
                    await remove_role(member, role_name)
                    break
            user["stolen_roles"].remove(entry)

async def _resolve_claim_deadlines(data: dict):
    """Check Pride claim bow windows; assign marks of insecurity to those who didn't bow."""
    now = now_ts()
    for msg_id, claim in list(data.get("active_claims", {}).items()):
        all_resolved = True
        for uid_str, subject in claim.get("subjects", {}).items():
            if subject.get("processed"):
                continue
            if now <= subject.get("deadline", 0):
                all_resolved = False
                continue
            subject["processed"] = True
            if subject.get("bowed"):
                continue
            target_user = get_user(data, int(uid_str))
            target_user["marks_of_insecurity"] = target_user.get("marks_of_insecurity", 0) + 1
            new_marks = target_user["marks_of_insecurity"]
            sin_held  = target_user.get("sin_role")
            power     = SINS.get(sin_held, {}).get("power", 0) if sin_held else 0
            thresh    = krodingers_threshold(power) if power else 6
            member    = None
            for g in bot.guilds:
                member = g.get_member(int(uid_str))
                if member: break
            ch = None
            for g in bot.guilds:
                ch = await trial_channel(g)
                if ch: break
            krodingers = new_marks >= thresh
            if ch:
                desc = (
                    f"**{member.display_name if member else uid_str}** failed to bow in time "
                    f"and gains a **Mark of Insecurity** ({new_marks}/{thresh})."
                )
                if krodingers:
                    desc += (
                        "\n\n⚠️ **Krodingers Effect** — Anxiety became reality. "
                        "Their ability is **locked for 30 minutes**."
                    )
                await ch.send(embed=discord.Embed(
                    title="😰 Mark of Insecurity",
                    description=desc,
                    color=discord.Color.dark_orange(),
                ))
            if krodingers:
                target_user["ability_locked_until"]  = now + 30 * 60
                target_user["marks_of_insecurity"]   = 0
        if all_resolved or now > claim.get("created_ts", 0) + 86400:
            del data["active_claims"][msg_id]

async def send_trial_welcome(member: discord.Member, sin: str):
    """
    Posts a private welcome embed in the sin-specific channel.

    The channel is permission-locked so only the 'Trial — <Sin>' role
    (plus the bot and admins) can read it.  When the trial ends and that
    role is removed the member loses access automatically — the message
    effectively disappears for them, and the next holder sees it fresh.
    """
    guild      = member.guild
    sd         = SINS[sin]
    trial_role = discord.utils.get(guild.roles, name=sd["role"])
    ch_name    = TRIAL_CHANNELS.get(sin)
    if not ch_name:
        return

    ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not ch:
        return

    # ── Lock the channel to this trial role only ──
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    if trial_role:
        overwrites[trial_role] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True
        )
    # Keep existing admin/owner overrides intact
    for target, overwrite in ch.overwrites.items():
        if isinstance(target, discord.Role) and target.permissions.administrator:
            overwrites[target] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        await ch.edit(overwrites=overwrites, reason=f"Trial of {sin.capitalize()} claimed by {member.display_name}")
    except Exception:
        pass  # Missing permissions — channel stays open, message still sent

    # ── Build and send the welcome embed ──
    wm = TRIAL_WELCOME_MESSAGES.get(sin, {})
    if not wm:
        return

    embed = discord.Embed(
        title       = wm["title"],
        description = wm["body"],
        color       = wm["color"],
    )
    embed.set_footer(text=wm["footer"])
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)

    try:
        await ch.send(
            content = f"Welcome, {member.mention}. This channel is yours alone.",
            embed   = embed,
        )
    except Exception:
        pass

async def add_role(member: discord.Member, role_name: str) -> bool:
    role = discord.utils.get(member.guild.roles, name=role_name)
    if not role:
        print(f"[add_role] Role not found on server: '{role_name}' (guild: {member.guild.id})")
        return False
    try:
        await member.add_roles(role)
        return True
    except Exception as e:
        print(
            f"[add_role] FAILED assigning '{role_name}' to {member} ({member.id}) "
            f"in guild {member.guild.id}: {type(e).__name__}: {e}"
        )
        return False

def has_role_name(guild: discord.Guild, user_id: int, role_name: str) -> bool:
    """Check if a member has a specific role name."""
    member = guild.get_member(user_id)
    if not member:
        return False
    return any(r.name == role_name for r in member.roles)

async def remove_role(member: discord.Member, role_name: str):
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role and role in member.roles:
        try:
            await member.remove_roles(role)
        except Exception:
            pass

async def remove_all_sin_roles(member: discord.Member):
    for sin_data in SINS.values():
        await remove_role(member, sin_data["role"])
        await remove_role(member, sin_data["final_role"])
        await remove_role(member, sin_data["evolved_role"])
    for v in VIRTUES.values():
        await remove_role(member, v["role"])

# ───────────────────────────────────────────────────────────────────
# FALL FROM GRACE
# ───────────────────────────────────────────────────────────────────

async def fall_from_grace(member: discord.Member, reason: str, data: dict = None):
    owns_data = data is None
    if owns_data:
        data = load_data()

    user = get_user(data, member.id)
    guild = member.guild

    sin = user.get("trial_sin") or user.get("sin_role")

    # Add corruption
    pts = SINS[sin]["corruption_on_fail"] if sin and sin in SINS else 1
    user["corruption"] += pts

    # Cool down
    if sin and sin in SINS:
        base_hrs = SINS[sin]["cooldown_hrs"]
        extra    = 1 + (user["corruption"] // 5)
        user["cooldowns"][sin] = now_ts() + (base_hrs * extra * 3600)

    # Strip all sin / virtue roles
    await remove_all_sin_roles(member)

    # Strip character roles
    for char in CHARACTERS.values():
        for r_name in [char["hope_role"], char.get("despair_role")]:
            if r_name:
                await remove_role(member, r_name)
    await remove_role(member, IZURU_DESPAIR_ROLE)
    await remove_role(member, IZURU_HOPE_ROLE)
    await remove_role(member, RESERVE_COURSE_ROLE)
    await _dr_strip_roles(member)      # Despair / Remnant / Hopeful / character / Izuru roles
    _dr_reset(user, data, member.id)   # keep save data in sync so they can re-claim later

    # Give fallen role
    await add_role(member, FALLEN_ROLE)

    # Timeout for FALL_TIMEOUT_DAYS
    until = datetime.now(timezone.utc) + timedelta(days=FALL_TIMEOUT_DAYS)
    try:
        await member.timeout(until, reason=f"Fall from Grace: {reason}")
    except Exception:
        pass

    # Update user record
    user["fallen"]           = True
    user["fallen_until"]     = until.timestamp()
    user["redemption_count"] = 0
    user["total_falls"]      = user.get("total_falls", 0) + 1
    user["trial_sin"]        = None
    user["trial_end"]        = None
    user["sin_role"]         = None
    user["virtue_trial_sin"] = None
    user["virtue_trial_end"] = None
    _reset_trial_progress(user)

    user.setdefault("trial_log", []).append({
        "type":              "fall",
        "sin":               sin or "unknown",
        "ts":                now_ts(),
        "outcome":           "failed",
        "reason":            reason,
        "corruption_after":  user["corruption"],
    })

    # Remove from claimed_sins
    for s in list(data["claimed_sins"].keys()):
        if data["claimed_sins"][s] == str(member.id):
            del data["claimed_sins"][s]

    # ── Cascade fall to pact partner ──
    uid_str    = str(member.id)
    pact_entry = data.get("pacts", {}).get(uid_str)
    partner_member = None
    if pact_entry and pact_entry.get("status") == "active":
        partner_id = pact_entry.get("partner_id")
        if partner_id:
            partner_member = guild.get_member(int(partner_id))
            # Break the pact on both sides before cascading
            data["pacts"].pop(uid_str, None)
            data["pacts"].pop(partner_id, None)
            if owns_data:
                save_data(data)
            if partner_member:
                ch_pre = await trial_channel(guild)
                if ch_pre:
                    await ch_pre.send(embed=discord.Embed(
                        title="💀 The Pact Shatters",
                        color=discord.Color.dark_red(),
                        description=(
                            f"**{member.display_name}** has fallen — and their pact partner "
                            f"{partner_member.mention} **falls with them**.\n\n"
                            "A shared fate. A shared ruin."
                        ),
                    ))
                await fall_from_grace(
                    partner_member,
                    f"Pact partner {member.display_name} fell from grace — you fall together.",
                    data,
                )

    # ── Pay out active bounties ──
    uid_str   = str(member.id)
    bounties  = data.get("bounties", {}).get(uid_str, [])
    paid_out  = []
    if bounties:
        for b in bounties:
            if now_ts() <= b.get("expires", 0):
                placer_id = b.get("placer_id")
                if placer_id and placer_id in data["users"]:
                    placer_data = data["users"][placer_id]
                    old_corr = placer_data.get("corruption", 0)
                    placer_data["corruption"] = max(0, old_corr - 1)
                    paid_out.append(placer_id)
        data["bounties"][uid_str] = []   # clear paid bounties

    if owns_data:
        save_data(data)

    ch = await trial_channel(guild)
    if ch:
        bounty_line = ""
        if paid_out:
            hunter_names = []
            for pid in paid_out:
                m = guild.get_member(int(pid))
                hunter_names.append(m.mention if m else f"<@{pid}>")
            bounty_line = (
                f"\n\n🎯 **Bounties paid out:** {', '.join(hunter_names)} "
                f"{'was' if len(hunter_names) == 1 else 'were'} each cleansed of **1 corruption point**."
            )

        embed = discord.Embed(
            title="⬇️ A Soul Has Fallen from Grace",
            color=discord.Color.dark_red(),
            description=(
                f"{member.mention} **has fallen**.\n\n"
                f"**Reason:** {reason}\n\n"
                f"Silenced for **{FALL_TIMEOUT_DAYS} days**. All power stripped.\n"
                f"**Corruption gained:** +{pts} (Total: {user['corruption']})\n\n"
                f"Type `!repent <words>` {REDEMPTION_COUNT} times to begin redemption."
                f"{bounty_line}"
            ),
        )
        await ch.send(embed=embed)

def _reset_trial_progress(user: dict):
    user["lust_hearts"]        = []
    user["gluttony_pending"]   = {}
    user["wrath_fail"]         = False
    user["sloth_fail"]         = False
    user["greed_kills_done"]   = 0
    user["greed_kills_needed"] = 1
    user["envy_strikes_done"]  = 0
    user["envy_strikes_needed"]= 1
    user["pride_msg_id"]       = None
    user["pride_channel_id"]   = None
    user["pride_bows"]         = 0
    user["pride_refusals"]     = 0
    user["virtue_progress"]    = {}

# ───────────────────────────────────────────────────────────────────
# COMPLETE TRIAL
# ───────────────────────────────────────────────────────────────────

async def complete_trial(member: discord.Member, sin: str, data: dict = None):
    owns_data = data is None
    if owns_data:
        data = load_data()

    user   = get_user(data, member.id)
    guild  = member.guild
    evolved = is_evolved(user)
    sin_data = SINS[sin]

    final = sin_data["evolved_role"] if evolved else sin_data["final_role"]
    await remove_role(member, sin_data["role"])   # remove trial placeholder
    await add_role(member, final)

    data["claimed_sins"][sin] = str(member.id)

    user["trial_sin"]  = None
    user["trial_end"]  = None
    user["sin_role"]   = sin
    if sin not in user["completed_sins"]:
        user["completed_sins"].append(sin)
    _reset_trial_progress(user)

    user.setdefault("trial_log", []).append({
        "type":              "trial",
        "sin":               sin,
        "ts":                now_ts(),
        "outcome":           "passed",
        "reason":            "Trial completed successfully.",
        "corruption_after":  user.get("corruption", 0),
    })

    if owns_data:
        save_data(data)

    ch = await trial_channel(guild)
    if ch:
        embed = discord.Embed(
            title="⚡ A Trial Has Been Survived",
            color=discord.Color.purple(),
            description=(
                f"{member.mention} endured the **Trial of {sin.capitalize()}** "
                f"and claimed **{final}**.\n\n"
                f"Power Level: **{sin_data['power']}**\n\n"
                "This sin is now sealed. No other may claim it while this bearer lives."
            ),
        )
        await ch.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMPLETE VIRTUE TRIAL
# ───────────────────────────────────────────────────────────────────

async def complete_virtue_trial(member: discord.Member, sin: str, data: dict = None):
    owns_data = data is None
    if owns_data:
        data = load_data()

    user   = get_user(data, member.id)
    guild  = member.guild
    virtue = VIRTUES[sin]

    await add_role(member, virtue["role"])

    user["virtue_trial_sin"] = None
    user["virtue_trial_end"] = None
    user["virtue_progress"]  = {}
    if sin not in user["completed_virtues"]:
        user["completed_virtues"].append(sin)

    user.setdefault("trial_log", []).append({
        "type":              "virtue",
        "sin":               sin,
        "ts":                now_ts(),
        "outcome":           "passed",
        "reason":            f"Virtue of {VIRTUES[sin]['virtue']} earned.",
        "corruption_after":  user.get("corruption", 0),
    })

    if owns_data:
        save_data(data)

    ch = await trial_channel(guild)
    if ch:
        embed = discord.Embed(
            title="✨ A Virtue Has Been Unlocked",
            color=discord.Color.blue(),
            description=(
                f"{member.mention} transcended their sin and earned **{virtue['role']}** "
                f"— **{virtue['virtue']}**, Power {virtue['power']}.\n\n"
                "The virtues are more powerful than the sins. Guard this title well."
            ),
        )
        await ch.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# BACKGROUND TASK — Expiry Checker (every 5 minutes)
# ───────────────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def trial_expiry_check():
    data = load_data()
    now  = now_ts()
    changed = False

    for uid, user in list(data["users"].items()):
        sin = user.get("trial_sin")
        end = user.get("trial_end")
        if not sin or not end or now < end:
            continue

        guild = None
        member = None
        for g in bot.guilds:
            m = g.get_member(int(uid))
            if m:
                guild = g
                member = m
                break
        if not member:
            continue

        evolved = is_evolved(user)

        if sin == "lust":
            needed = 10 if evolved else 5
            hearts = len(set(user.get("lust_hearts", [])))
            if hearts >= needed:
                await complete_trial(member, sin, data)
            else:
                await fall_from_grace(member, "Not enough hearts collected in the Trial of Lust.", data)

        elif sin == "wrath":
            if user.get("wrath_fail"):
                pass  # Already handled in on_message
            else:
                await complete_trial(member, sin, data)

        elif sin == "sloth":
            if user.get("sloth_fail"):
                pass  # Already handled in on_message
            else:
                await complete_trial(member, sin, data)

        elif sin == "gluttony":
            if user.get("gluttony_pending"):
                await fall_from_grace(member, "Failed to consume all messages in the Trial of Gluttony.", data)
            else:
                await complete_trial(member, sin, data)

        elif sin == "greed":
            needed = user.get("greed_kills_needed", 1)
            done   = user.get("greed_kills_done", 0)
            if done < needed:
                await fall_from_grace(member, "Failed to silence enough souls in the Trial of Greed.", data)
            else:
                await complete_trial(member, sin, data)

        elif sin == "envy":
            needed = user.get("envy_strikes_needed", 1)
            done   = user.get("envy_strikes_done", 0)
            if done < needed:
                await fall_from_grace(member, "Failed to strike enough victims in the Trial of Envy.", data)
            else:
                await complete_trial(member, sin, data)

        elif sin == "pride":
            evolved = is_evolved(user)
            needed_pct   = 0.75 if evolved else 0.60
            online       = [m for m in guild.members if m.status != discord.Status.offline and not m.bot]
            needed_bows  = max(1, int(len(online) * needed_pct))
            if user.get("pride_bows", 0) >= needed_bows:
                await complete_trial(member, sin, data)
            else:
                await fall_from_grace(member, "Not enough bows received in the Trial of Pride.", data)

        changed = True

    # Check gluttony pending message deadlines
    for uid, user in data["users"].items():
        if user.get("trial_sin") != "gluttony":
            continue
        pending = user.get("gluttony_pending", {})
        expired = [mid for mid, deadline in pending.items() if now > deadline]
        if expired:
            member = None
            guild  = None
            for g in bot.guilds:
                m = g.get_member(int(uid))
                if m:
                    member = m
                    guild  = g
                    break
            if member:
                await fall_from_grace(member, "Reacted too slowly (or not at all) during the Trial of Gluttony.", data)
            changed = True

    # Check virtue trial expiry
    for uid, user in list(data["users"].items()):
        vs  = user.get("virtue_trial_sin")
        ve  = user.get("virtue_trial_end")
        if not vs or not ve or now < ve:
            continue

        member = None
        guild  = None
        for g in bot.guilds:
            m = g.get_member(int(uid))
            if m:
                member = m
                guild  = g
                break
        if not member:
            continue

        vp = user.get("virtue_progress", {})

        if vs == "sloth":
            hours = len(vp.get("hours_tracked", []))
            if hours >= 24:
                await complete_virtue_trial(member, vs, data)
            else:
                await fall_from_grace(member, "Failed the Virtue Trial of Diligence — not enough hours covered.", data)

        elif vs == "wrath":
            # Patience: if no curse words logged as violations, they passed
            if not vp.get("patience_fail"):
                await complete_virtue_trial(member, vs, data)

        elif vs == "lust":
            if not vp.get("temptation_fail"):
                await complete_virtue_trial(member, vs, data)

        elif vs == "gluttony":
            if not vp.get("abstinence_fail"):
                await complete_virtue_trial(member, vs, data)

        elif vs == "pride":
            bows = vp.get("bows", 0)
            if bows >= 10:
                await complete_virtue_trial(member, vs, data)
            else:
                await fall_from_grace(member, "Failed the Virtue Trial of Humility — not enough acknowledgments.", data)

        elif vs == "envy":
            praised = len(vp.get("praised", []))
            if praised >= 5:
                await complete_virtue_trial(member, vs, data)
            else:
                await fall_from_grace(member, "Failed the Virtue Trial of Admiration — not enough praises given.", data)

        changed = True

    if changed:
        save_data(data)

    # ── New mechanics checks ──────────────────────────────────────
    data = load_data()
    await _resolve_expired_envy_marks(data)
    await _return_stolen_roles(data)
    await _resolve_claim_deadlines(data)
    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !sinslist
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def sinslist(ctx):
    data    = load_data()
    user    = get_user(data, ctx.author.id)
    ordered = sorted(SINS.items(), key=lambda x: x[1]["power"])

    embed = discord.Embed(
        title="⚖️ The Seven Deadly Sins",
        description=(
            "Greater power demands greater sacrifice. "
            "Once a sin is **claimed**, it cannot be contested until the bearer **falls from grace**."
        ),
        color=discord.Color.dark_purple(),
    )

    for sin_name, sd in ordered:
        claimed_id = data["claimed_sins"].get(sin_name)
        if claimed_id:
            m      = ctx.guild.get_member(int(claimed_id))
            status = f"🔴 Claimed by **{m.display_name if m else 'Unknown'}**"
        else:
            status = "🟢 Available"

        cd = user["cooldowns"].get(sin_name, 0)
        cd_str = f"\n⏳ Your cooldown: {remaining_fmt(cd)}" if cd > now_ts() else ""

        embed.add_field(
            name=f"{'★' * sd['power']}  {sin_name.capitalize()}  (Power {sd['power']})",
            value=f"Role: **{sd['final_role']}**\n{status}{cd_str}",
            inline=False,
        )

    save_data(data)
    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !mytrial
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def mytrial(ctx):
    """Live status card for the caller's active trial."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    sin  = user.get("trial_sin")

    if not sin:
        await ctx.send(
            f"{ctx.author.mention} — you are not currently undergoing any trial.\n"
            "Use `!sinslist` to see what's available, then `!trial <sin>` to begin.",
            delete_after=12,
        )
        save_data(data)
        return

    sd        = SINS[sin]
    evolved   = is_evolved(user)
    end_ts    = user.get("trial_end", 0)
    secs_left = max(0, end_ts - now_ts())
    pct_left  = secs_left / (sd["trial_hours"] * 3600) if sd["trial_hours"] else 0
    expired   = secs_left == 0

    sin_colors = {
        "lust":     0xe91e8c,
        "gluttony": 0xf4a423,
        "greed":    0xffd700,
        "sloth":    0x7b68ee,
        "wrath":    0xff2400,
        "envy":     0x00b4d8,
        "pride":    0xf0f0f0,
    }
    color = sin_colors.get(sin, 0x8b0000)

    def time_bar(pct: float, width: int = 12) -> str:
        filled = round(pct * width)
        return "█" * filled + "░" * (width - filled)

    def danger(msg: str) -> str:
        return f"⚠️ **{msg}**"

    warnings: list[str] = []
    progress_lines: list[str] = []

    # ── Per-sin progress ──────────────────────────────────────────────
    if sin == "lust":
        goal    = 10 if evolved else 5
        hearts  = len(set(user.get("lust_hearts", [])))
        remain  = goal - hearts
        bar     = time_bar(hearts / goal)
        progress_lines.append(f"❤️ Unique reactions: **{hearts} / {goal}**")
        progress_lines.append(f"`{bar}` {hearts}/{goal}")
        if remain <= 1 and pct_left < 0.3:
            warnings.append(danger(f"Only {remain} heart(s) left to collect — time is almost up!"))
        elif hearts == 0 and pct_left < 0.5:
            warnings.append(danger("No hearts collected yet and you're past the halfway mark."))

    elif sin == "gluttony":
        pending = user.get("gluttony_pending", {})
        # Count how many pending reactions are still within deadline
        now = now_ts()
        overdue = [mid for mid, dl in pending.items() if now > dl]
        active  = len(pending) - len(overdue)
        window  = "2 min" if evolved else "5 min"
        progress_lines.append(f"🍽️ Reactions still pending in window: **{active}**")
        progress_lines.append(f"React window per message: **{window}**")
        if active > 0:
            warnings.append(danger(f"{active} message(s) awaiting your reaction — react now or fall!"))
        elif len(overdue) > 0:
            warnings.append(danger(f"{len(overdue)} reaction(s) missed. Your fall may already be logged."))
        else:
            progress_lines.append("✅ No pending reactions — feast is clean so far.")

    elif sin == "greed":
        done   = user.get("greed_kills_done", 0)
        needed = user.get("greed_kills_needed", 1)
        bar    = time_bar(done / needed)
        progress_lines.append(f"💀 Silencings used: **{done} / {needed}**")
        progress_lines.append(f"`{bar}` {done}/{needed}")
        if done < needed and pct_left < 0.25:
            warnings.append(danger(f"You still need {needed - done} kill(s) and the window is almost closed!"))
        elif done >= needed:
            progress_lines.append("✅ Objective complete — hold steady until time expires.")

    elif sin == "sloth":
        fail = user.get("sloth_fail", False)
        if fail:
            warnings.append(danger("A violation was detected — fall from grace is imminent or already triggered."))
        else:
            progress_lines.append("✅ No violations detected so far.")
        abbrev = "3 chars or fewer per word" if evolved else "abbreviate words > 4 chars"
        progress_lines.append(f"📏 Rule: {abbrev} in every message, every channel.")
        progress_lines.append("🔍 The bot reads every message you send across the server.")

    elif sin == "wrath":
        fail = user.get("wrath_fail", False)
        if fail:
            warnings.append(danger("A clean message was detected — fall is imminent or already triggered."))
        else:
            progress_lines.append("✅ No clean messages detected so far.")
        rule = "at least **2 distinct curse words** per message" if evolved else "at least **1 curse word** per message"
        progress_lines.append(f"🔥 Rule: {rule}, in every message, every channel.")
        progress_lines.append("🔍 The bot reads every message you send across the server.")

    elif sin == "envy":
        done   = user.get("envy_strikes_done", 0)
        needed = user.get("envy_strikes_needed", 1)
        bar    = time_bar(done / needed)
        progress_lines.append(f"👁️ Role strips used: **{done} / {needed}**")
        progress_lines.append(f"`{bar}` {done}/{needed}")
        if done < needed and pct_left < 0.25:
            warnings.append(danger(f"{needed - done} strike(s) still needed — the window is closing fast!"))
        elif done >= needed:
            progress_lines.append("✅ Objective complete — stay hidden until time expires.")

    elif sin == "pride":
        bows      = user.get("pride_bows", 0)
        refusals  = user.get("pride_refusals", 0)
        max_ref   = 10 if evolved else 20
        bow_target = "75%" if evolved else "60%"
        progress_lines.append(f"🙇 Bows received: **{bows}**  (need {bow_target} of online members)")
        progress_lines.append(f"❌ Defiances: **{refusals} / {max_ref}** max")
        ref_bar = time_bar(refusals / max_ref)
        progress_lines.append(f"`{ref_bar}` defiance meter")
        if refusals >= max_ref - 3:
            warnings.append(danger(f"Defiance is at {refusals}/{max_ref} — {max_ref - refusals} more and you fall immediately!"))
        if bows == 0 and pct_left < 0.4:
            warnings.append(danger("No bows yet and you're past 60% of your window. Use `!proclaim` now."))

    # ── Time bar ──────────────────────────────────────────────────────
    h = int(secs_left // 3600)
    m = int((secs_left % 3600) // 60)
    time_str = f"{h}h {m}m remaining" if not expired else "⌛ Window expired"
    time_bar_str = time_bar(pct_left)

    if not expired and pct_left < 0.15:
        warnings.append(danger("Less than 15% of your trial window remains!"))

    # ── Assemble embed ───────────────────────────────────────────────
    title_icon = {
        "lust": "❤️", "gluttony": "🍔", "greed": "💰",
        "sloth": "🛌", "wrath": "🔥", "envy": "👁️", "pride": "👑",
    }.get(sin, "🔺")

    embed = discord.Embed(
        title=f"{title_icon} Trial of {sin.capitalize()} — Live Status",
        color=color,
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    embed.add_field(
        name="⏱️ Time Remaining",
        value=f"`{time_bar_str}` {time_str}\nExpires: {ts_fmt(end_ts)}",
        inline=False,
    )
    embed.add_field(
        name="📊 Progress",
        value="\n".join(progress_lines) or "No progress data available.",
        inline=False,
    )

    reward = sd["evolved_role"] if evolved else sd["final_role"]
    embed.add_field(name="🏆 Reward",        value=f"**{reward}**",                  inline=True)
    embed.add_field(name="⚡ Power",         value=str(sd["power"]),                 inline=True)
    embed.add_field(name="☠️ Corruption",    value=str(user.get("corruption", 0)),   inline=True)

    if evolved:
        embed.add_field(
            name="⚠️ Evolved Difficulty",
            value=f"Corruption **{user.get('corruption',0)}** — requirements are harder.",
            inline=False,
        )

    if warnings:
        embed.add_field(
            name="🚨 Warnings",
            value="\n".join(warnings),
            inline=False,
        )
        embed.color = discord.Color.red()

    embed.set_footer(text="Use !mytrial anytime to refresh this card.")
    await ctx.send(embed=embed)
    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !virtueslist
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def virtueslist(ctx):
    embed = discord.Embed(
        title="✨ The Seven Virtues — Secret Ranks",
        description=(
            "Virtues are the hidden counterparts to sins. **More powerful. Harder to earn.**\n"
            "Hold a sin role and use `!virtue_trial` to attempt your virtue."
        ),
        color=discord.Color.blue(),
    )
    for sin_name, v in sorted(VIRTUES.items(), key=lambda x: x[1]["power"]):
        embed.add_field(
            name=f"{'★' * v['power']}  {v['role']}  (Power {v['power']})",
            value=f"Virtue: **{v['virtue']}** | Unlocked by: **{sin_name.capitalize()}** bearer",
            inline=False,
        )
    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !trial <sin>
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def trial(ctx, sin: str):
    sin = sin.lower()
    if sin not in SINS:
        await ctx.send(f"That sin does not exist. Use `!sinslist` to see valid sins.")
        return

    # Guard: must be used in #sins-tribunal
    if ctx.channel.name != TRIAL_CHANNEL_NAME:
        tribunal = discord.utils.get(ctx.guild.text_channels, name=TRIAL_CHANNEL_NAME)
        dest     = tribunal.mention if tribunal else f"#{TRIAL_CHANNEL_NAME}"
        await ctx.message.delete()
        try:
            await ctx.author.send(
                f"Trial requests must be made in {dest}. Head there and try again."
            )
        except Exception:
            pass
        return

    data = load_data()
    user = get_user(data, ctx.author.id)
    sd   = SINS[sin]

    # Guard: fallen
    if user.get("fallen"):
        await ctx.send(f"{ctx.author.mention} — you are **fallen from grace**. Use `!repent` to begin redemption.")
        save_data(data)
        return

    # Guard: already in trial
    if user.get("trial_sin"):
        await ctx.send(f"{ctx.author.mention} — you are already in the Trial of **{user['trial_sin'].capitalize()}**.")
        save_data(data)
        return

    # Guard: already holds a sin role
    if user.get("sin_role"):
        await ctx.send(
            f"{ctx.author.mention} — you already hold **{SINS[user['sin_role']]['final_role']}**. "
            "Attempt `!virtue_trial` or fall from grace before seeking another sin."
        )
        save_data(data)
        return

    # Guard: sin is claimed
    claimed = data["claimed_sins"].get(sin)
    if claimed:
        holder = ctx.guild.get_member(int(claimed))
        name   = holder.display_name if holder else "someone"
        await ctx.send(f"**{sin.capitalize()}** is claimed by **{name}**. Wait for them to fall.")
        save_data(data)
        return

    # Guard: cooldown
    cd = user["cooldowns"].get(sin, 0)
    if cd > now_ts():
        await ctx.send(f"{ctx.author.mention} — cooldown: **{remaining_fmt(cd)}** remaining.")
        save_data(data)
        return

    # Start trial
    evolved = is_evolved(user)
    hours   = sd["trial_hours"]
    if evolved:
        _evolved_hours = {"greed": 6, "sloth": 72, "wrath": 36, "envy": 8, "pride": 36, "gluttony": 36, "lust": 18}
        hours = _evolved_hours.get(sin, hours)

    end_ts = now_ts() + hours * 3600

    user["trial_sin"] = sin
    user["trial_end"] = end_ts
    _reset_trial_progress(user)
    if evolved:
        user["greed_kills_needed"]  = 2 if sin == "greed"  else 1
        user["envy_strikes_needed"] = 2 if sin == "envy"   else 1

    # Assign placeholder trial role
    await add_role(ctx.author, sd["role"])

    # Send private welcome to the trial channel (locks it to this trial role)
    await send_trial_welcome(ctx.author, sin)

    save_data(data)

    desc = sd["trial_desc_evolved"] if evolved else sd["trial_desc"]
    embed = discord.Embed(
        title=f"🔺 Trial of {sin.capitalize()} — Initiated",
        description=desc,
        color=discord.Color.red(),
    )
    embed.add_field(name="Reward",        value=sd["evolved_role"] if evolved else sd["final_role"], inline=True)
    embed.add_field(name="Power Level",   value=str(sd["power"]),  inline=True)
    embed.add_field(name="Window",        value=f"{hours}h",       inline=True)
    embed.add_field(name="Expires",       value=ts_fmt(end_ts),    inline=False)
    if evolved:
        embed.add_field(name="⚠️ Evolved Difficulty",
                        value=f"Corruption: **{user['corruption']}** — the trial is harder now.", inline=False)
    embed.set_footer(text=f"Corruption Points: {user['corruption']}  |  Failures compound.")
    await ctx.send(f"{ctx.author.mention}", embed=embed)

    ch = await trial_channel(ctx.guild)
    if ch and ch != ctx.channel:
        await ch.send(embed=discord.Embed(
            title="⚠️ A Trial Has Begun",
            description=f"{ctx.author.mention} has entered the **Trial of {sin.capitalize()}**.",
            color=discord.Color.orange(),
        ))

# ───────────────────────────────────────────────────────────────────
# COMMAND: !kill @user  (Greed — silent mute)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def kill(ctx, target: discord.Member):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("trial_sin") != "greed":
        await ctx.send("You are not undergoing the Trial of Greed.", delete_after=5)
        save_data(data)
        return

    if now_ts() > user.get("trial_end", 0):
        await ctx.send("Your trial window has expired.", delete_after=5)
        save_data(data)
        return

    done   = user.get("greed_kills_done",   0)
    needed = user.get("greed_kills_needed", 1)
    if done >= needed:
        await ctx.send("You have already used all your kills.", delete_after=5)
        save_data(data)
        return

    if target.id == ctx.author.id or target.guild_permissions.administrator:
        await ctx.send("Invalid target.", delete_after=5)
        save_data(data)
        return

    # Delete the command immediately to hide identity
    try:
        await ctx.message.delete()
    except Exception:
        pass

    until = datetime.now(timezone.utc) + timedelta(hours=1)
    try:
        await target.timeout(until, reason="A shadow has claimed you.")
    except Exception:
        await ctx.author.send("Could not silence that target (insufficient bot permissions or role hierarchy).")
        save_data(data)
        return

    user["greed_kills_done"] = done + 1

    action_id = f"greed_{ctx.author.id}_{int(now_ts())}"
    data["greed_actions"][action_id] = {
        "killer_id": str(ctx.author.id),
        "target_id": str(target.id),
        "ts":        now_ts(),
        "exposed":   False,
    }

    ch = await trial_channel(ctx.guild)
    if ch:
        embed = discord.Embed(
            title="🌑 A Shadow Has Moved",
            description=(
                "An unseen hand has **silenced** a soul among you. "
                "Someone cannot speak for **1 hour**.\n\n"
                "React 🔍 if you suspect someone — "
                f"**{EXPOSE_THRESHOLD}** reactions open an expose vote."
            ),
            color=discord.Color.dark_gray(),
        )
        embed.set_footer(text=f"ref:{action_id}")
        msg = await ch.send(embed=embed)
        await msg.add_reaction("🔍")
        data["expose_votes"][str(msg.id)] = {
            "type":      "greed",
            "action_id": action_id,
            "votes":     [],
            "active":    True,
        }

    if user["greed_kills_done"] >= needed:
        save_data(data)
        await complete_trial(ctx.author, "greed", data)
    else:
        save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !envy_strike @user  (Envy — strip a role)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def envy_strike(ctx, target: discord.Member):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("trial_sin") != "envy":
        await ctx.send("You are not undergoing the Trial of Envy.", delete_after=5)
        save_data(data)
        return

    if now_ts() > user.get("trial_end", 0):
        await ctx.send("Your trial window has expired.", delete_after=5)
        save_data(data)
        return

    done   = user.get("envy_strikes_done",   0)
    needed = user.get("envy_strikes_needed", 1)
    if done >= needed:
        await ctx.send("You have already used all your strikes.", delete_after=5)
        save_data(data)
        return

    if target.id == ctx.author.id or target.guild_permissions.administrator:
        await ctx.send("Invalid target.", delete_after=5)
        save_data(data)
        return

    sin_role_names    = {sd["role"] for sd in SINS.values()} | {sd["final_role"] for sd in SINS.values()} | {sd["evolved_role"] for sd in SINS.values()}
    virtue_role_names = {v["role"] for v in VIRTUES.values()}
    protected         = sin_role_names | virtue_role_names | {FALLEN_ROLE, "@everyone"}

    strippable = [
        r for r in target.roles
        if r.name not in protected and not r.managed and not r.permissions.administrator
    ]

    if not strippable:
        await ctx.send("This target has no strippable roles.", delete_after=5)
        save_data(data)
        return

    stolen = random.choice(strippable)

    try:
        await ctx.message.delete()
    except Exception:
        pass

    try:
        await target.remove_roles(stolen, reason="Envy has taken.")
    except Exception:
        await ctx.author.send("Could not strip that role.")
        save_data(data)
        return

    user["envy_strikes_done"] = done + 1

    action_id = f"envy_{ctx.author.id}_{int(now_ts())}"
    data["envy_actions"][action_id] = {
        "striker_id": str(ctx.author.id),
        "target_id":  str(target.id),
        "role":       stolen.name,
        "ts":         now_ts(),
        "exposed":    False,
    }

    ch = await trial_channel(ctx.guild)
    if ch:
        embed = discord.Embed(
            title="👁️ Envy Has Claimed",
            description=(
                "A role has been **stripped** from someone in this server. "
                "Neither the striker nor the victim is known.\n\n"
                "React 🔍 if you suspect someone — "
                f"**{EXPOSE_THRESHOLD}** reactions open an expose vote."
            ),
            color=discord.Color.teal(),
        )
        embed.set_footer(text=f"ref:{action_id}")
        msg = await ch.send(embed=embed)
        await msg.add_reaction("🔍")
        data["expose_votes"][str(msg.id)] = {
            "type":      "envy",
            "action_id": action_id,
            "votes":     [],
            "active":    True,
        }

    if user["envy_strikes_done"] >= needed:
        save_data(data)
        await complete_trial(ctx.author, "envy", data)
    else:
        save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !proclaim <words>  (Pride trial)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def proclaim(ctx, *, words: str):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("trial_sin") != "pride":
        await ctx.send("You are not undergoing the Trial of Pride.", delete_after=10)
        save_data(data)
        return

    if user.get("pride_msg_id"):
        await ctx.send("You have already posted your proclamation.", delete_after=10)
        save_data(data)
        return

    evolved     = is_evolved(user)
    needed_pct  = 0.75 if evolved else 0.60
    max_refusals = 10 if evolved else 20
    online      = [m for m in ctx.guild.members if m.status != discord.Status.offline and not m.bot]
    needed_bows = max(1, int(len(online) * needed_pct))

    ch = await trial_channel(ctx.guild) or ctx.channel

    embed = discord.Embed(
        title=f"👑 {ctx.author.display_name} Proclaims Dominion",
        description=(
            f"*\"{words}\"*\n\n— **{ctx.author.display_name}**\n\n"
            f"🙇 **Bow** to submit | ❌ **Defy** to resist\n\n"
            f"Needed: **{needed_bows} bows** ({int(needed_pct*100)}% of {len(online)} online members)\n"
            f"Maximum defiance: **{max_refusals} ❌ before you fall**"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="The weight of pride is immense. Rule them all — or be crushed.")

    msg = await ch.send(f"@everyone — {ctx.author.mention} demands your attention.", embed=embed)
    await msg.add_reaction("🙇")
    await msg.add_reaction("❌")

    user["pride_msg_id"]    = str(msg.id)
    user["pride_channel_id"] = str(ch.id)
    user["pride_bows"]       = 0
    user["pride_refusals"]   = 0
    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !virtue_trial
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def virtue_trial(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    sin  = user.get("sin_role")

    if not sin:
        await ctx.send("You must hold a sin role before attempting a virtue trial.", delete_after=10)
        save_data(data)
        return
    if sin in user.get("completed_virtues", []):
        await ctx.send("You have already earned the virtue of your sin.", delete_after=10)
        save_data(data)
        return
    if user.get("virtue_trial_sin"):
        await ctx.send("You are already undergoing a virtue trial.", delete_after=10)
        save_data(data)
        return

    end_ts = now_ts() + 48 * 3600
    user["virtue_trial_sin"] = sin
    user["virtue_trial_end"] = end_ts
    user["virtue_progress"]  = {}
    save_data(data)

    virtue = VIRTUES[sin]
    embed  = discord.Embed(
        title=f"✨ Virtue Trial — {virtue['role']}",
        description=VIRTUE_TRIALS[sin],
        color=discord.Color.blue(),
    )
    embed.add_field(name="Virtue",       value=virtue["virtue"],    inline=True)
    embed.add_field(name="Power Level",  value=str(virtue["power"]), inline=True)
    embed.add_field(name="Expires",      value=ts_fmt(end_ts),       inline=True)
    embed.set_footer(text="Virtues are the highest tier. Earn it cleanly.")
    await ctx.send(f"{ctx.author.mention}", embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !praise @user <message>  (Envy virtue)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def praise(ctx, target: discord.Member, *, message: str):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("virtue_trial_sin") != "envy":
        await ctx.send("You are not undergoing the Envy virtue trial.", delete_after=5)
        save_data(data)
        return
    if len(message.split()) < 10:
        await ctx.send("Your praise must be at least 10 words.", delete_after=5)
        save_data(data)
        return

    praised = user["virtue_progress"].get("praised", [])
    if str(target.id) in praised:
        await ctx.send("You have already praised this person.", delete_after=5)
        save_data(data)
        return

    praised.append(str(target.id))
    user["virtue_progress"]["praised"] = praised
    save_data(data)

    await ctx.send(embed=discord.Embed(
        title="🌟 Praise Given",
        description=f"{ctx.author.mention} honors {target.mention}:\n\n*\"{message}\"*",
        color=discord.Color.green(),
    ))

    if len(praised) >= 5:
        await complete_virtue_trial(ctx.author, "envy", data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !bow_down <message>  (Pride virtue)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def bow_down(ctx, *, message: str):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("virtue_trial_sin") != "pride":
        await ctx.send("You are not undergoing the Pride virtue trial.", delete_after=5)
        save_data(data)
        return
    if user["virtue_progress"].get("bow_msg_id"):
        await ctx.send("You have already posted your bow.", delete_after=5)
        save_data(data)
        return

    embed = discord.Embed(
        title=f"🙏 {ctx.author.display_name} Bows Before All",
        description=f"*\"{message}\"*",
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"React 🙏 to acknowledge their humility. (Need 10 unique)")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🙏")

    user["virtue_progress"]["bow_msg_id"]  = str(msg.id)
    user["virtue_progress"]["bow_channel"] = str(ctx.channel.id)
    user["virtue_progress"]["bows"]        = 0
    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !give_role @user <role>  (Greed virtue)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def give_role(ctx, target: discord.Member, *, role_name: str):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("virtue_trial_sin") != "greed":
        await ctx.send("You are not undergoing the Greed virtue trial.", delete_after=5)
        save_data(data)
        return

    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role or role not in ctx.author.roles:
        await ctx.send("You don't hold that role.", delete_after=5)
        save_data(data)
        return

    user["virtue_progress"]["pending_give"] = {
        "target_id": str(target.id),
        "role":      role_name,
        "giver_id":  str(ctx.author.id),
    }
    save_data(data)
    await ctx.send(
        f"⏳ Pending admin confirmation. An admin must use `!confirm_give {target.mention}` to approve."
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def confirm_give(ctx, target: discord.Member):
    data = load_data()
    for uid, user in data["users"].items():
        if user.get("virtue_trial_sin") == "greed":
            pg = user.get("virtue_progress", {}).get("pending_give")
            if pg and pg.get("target_id") == str(target.id):
                giver = ctx.guild.get_member(int(uid))
                if not giver:
                    break
                role = discord.utils.get(ctx.guild.roles, name=pg["role"])
                if role:
                    try:
                        await giver.remove_roles(role)
                        await target.add_roles(role)
                    except Exception:
                        pass
                user["virtue_progress"]["give_done"] = True
                save_data(data)
                await complete_virtue_trial(giver, "greed", data)
                await ctx.send(f"✅ Confirmed. **{giver.display_name}** gave away **{pg['role']}**.")
                return

    await ctx.send("No pending role gift found.")

# ───────────────────────────────────────────────────────────────────
# COMMAND: !repent <words>  (Redemption)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def repent(ctx, *, words: str = "I repent"):
    data = load_data()
    user = get_user(data, ctx.author.id)

    if not user.get("fallen"):
        await ctx.send("You have not fallen from grace.", delete_after=5)
        save_data(data)
        return

    fallen_until = user.get("fallen_until", 0)
    if fallen_until and now_ts() < fallen_until:
        await ctx.send(
            f"{ctx.author.mention} — you are still silenced. You may repent {ts_fmt(fallen_until)}.",
            delete_after=10,
        )
        save_data(data)
        return

    user["redemption_count"] = user.get("redemption_count", 0) + 1
    remaining = REDEMPTION_COUNT - user["redemption_count"]

    if remaining > 0:
        await ctx.send(
            f"{ctx.author.mention} — repentance acknowledged. **{remaining}** more to go.",
            delete_after=10,
        )
    else:
        user["fallen"]           = False
        user["fallen_until"]     = None
        user["redemption_count"] = 0
        await remove_role(ctx.author, FALLEN_ROLE)
        save_data(data)

        ch = await trial_channel(ctx.guild) or ctx.channel
        await ch.send(embed=discord.Embed(
            title="🌅 Redemption Earned",
            description=(
                f"{ctx.author.mention} has completed their penance and returned to the fold.\n\n"
                f"**Corruption remaining:** {user['corruption']} (permanent)\n"
                "They may now seek a new trial."
            ),
            color=discord.Color.green(),
        ))
        return

    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !mystats
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def mystats(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)

    embed = discord.Embed(
        title=f"📜 {ctx.author.display_name}'s Sin Record",
        color=discord.Color.dark_purple(),
    )
    embed.add_field(name="Corruption",       value=str(user["corruption"]),         inline=True)
    embed.add_field(name="Trial Difficulty", value="EVOLVED" if is_evolved(user) else "Standard", inline=True)
    embed.add_field(name="Fallen",           value="Yes" if user.get("fallen") else "No", inline=True)
    embed.add_field(name="Sin Role",         value=(user.get("sin_role") or "None").capitalize(), inline=True)
    embed.add_field(name="Active Trial",     value=(user.get("trial_sin")  or "None").capitalize(), inline=True)
    embed.add_field(name="Virtue Trial",     value=(user.get("virtue_trial_sin") or "None").capitalize(), inline=True)

    cs = ", ".join(user.get("completed_sins",    [])) or "None"
    cv = ", ".join(user.get("completed_virtues", [])) or "None"
    embed.add_field(name="Completed Sins",    value=cs, inline=False)
    embed.add_field(name="Completed Virtues", value=cv, inline=False)

    if user.get("trial_end"):
        embed.add_field(name="Trial Expires", value=ts_fmt(user["trial_end"]), inline=False)

    cds = []
    for sin, cd_ts in user.get("cooldowns", {}).items():
        if cd_ts > now_ts():
            cds.append(f"{sin.capitalize()}: {remaining_fmt(cd_ts)}")
    if cds:
        embed.add_field(name="Cooldowns", value="\n".join(cds), inline=False)

    # ── PVP Combat Stats ──
    stats = get_role_stats(ctx.author)
    hp = user.get("hp", stats[0])
    max_hp = user.get("max_hp", stats[0])
    bar = "█" * int(hp / max_hp * 10) + "░" * (10 - int(hp / max_hp * 10))
    embed.add_field(name="HP", value=f"`{bar}` {hp}/{max_hp}", inline=False)
    embed.add_field(name="Attack", value=user.get("attack", stats[1]), inline=True)
    embed.add_field(name="Defense", value=user.get("defense", stats[2]), inline=True)
    embed.add_field(name="Kills", value=user.get("pvp_kills", 0), inline=True)
    embed.add_field(name="Deaths", value=user.get("pvp_deaths", 0), inline=True)
    embed.add_field(name="Hope Points", value=user.get("hope_points", 0), inline=True)
    embed.add_field(name="Despair Points", value=user.get("despair_points", 0), inline=True)
    _fx = _effects_text(user)
    if _fx:
        embed.add_field(name="Active Effects", value=_fx, inline=False)

    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# UNIVERSAL PVP SYSTEM
# ───────────────────────────────────────────────────────────────────

# Role-based base stats mapping
ROLE_BASE_STATS: dict[str, tuple[int, int, int]] = {
    # (hp, attack, defense)
    "Desire Bound Lust":    (100, 12, 4),
    "The Devoured":         (120, 10, 6),
    "The False King":       (90,  15, 3),
    "The vessel of sloth":  (140, 8,  8),
    "Crimson heir":         (110, 14, 4),
    "The Pale Mirror":      (85,  16, 2),
    "The bearer of pride":  (100, 13, 5),
    "The Ultimate Despair": (200, 25, 10),
    "Remnant of Despair":   (150, 18, 7),
    "Reserve Course Student":(80, 8, 3),
    "Despair Sister":       (180, 20, 8),
    "The Hopeful":          (160, 12, 12),
    "La Llorona":           (130, 18, 7),
    "The Chaste":           (110, 11, 6),
    "The Fasting King":     (115, 10, 7),
    "The Open Hand":        (105, 12, 5),
    "The Waking":           (130, 9,  9),
    "The Still Flame":      (105, 15, 4),
    "The Mirror's Grace":   (90,  14, 3),
    "The Humble Sovereign": (100, 13, 5),
    "Fallen from Grace":    (50,  5,  2),
    # Danganronpa characters
    "Nagito Komaeda: Ultimate Luck":         (100, 12, 5),
    "Nagito Komaeda: Ultimate Despair":      (120, 14, 6),
    "Akane Owari: Ultimate Gymnast":         (110, 14, 4),
    "Akane Owari: Ultimate Despair":         (130, 16, 5),
    "Sonia Nevermind: Ultimate Princess":    (95, 10, 7),
    "Sonia Nevermind: Ultimate Despair":     (115, 12, 8),
    "Fuyuhiko Kuzuryu: Ultimate Yakuza":     (105, 13, 6),
    "Fuyuhiko Kuzuryu: Ultimate Despair":    (125, 15, 7),
    "Kazuichi Soda: Ultimate Mechanic":      (90, 11, 6),
    "Kazuichi Soda: Ultimate Despair":       (110, 13, 7),
    "Hiyoko Saionji: Ultimate Traditional Dancer": (85, 10, 4),
    "Hiyoko Saionji: Ultimate Despair":      (105, 12, 5),
    "Mikan Tsumiki: Ultimate Nurse":         (80, 8, 5),
    "Mikan Tsumiki: Ultimate Despair":       (100, 10, 6),
    "Ibuki Mioda: Ultimate Musician":         (95, 12, 4),
    "Ibuki Mioda: Ultimate Despair":          (115, 14, 5),
    "Mahiru Koizumi: Ultimate Photographer":  (90, 10, 5),
    "Mahiru Koizumi: Ultimate Despair":       (110, 12, 6),
    "Nekomaru Nidai: Ultimate Athlete":      (130, 15, 8),
    "Nekomaru Nidai: Ultimate Despair":       (150, 17, 9),
    "Gundham Tanaka: Ultimate Breeder":       (100, 11, 6),
    "Gundham Tanaka: Ultimate Despair":       (120, 13, 7),
    "Teruteru Hanamura: Ultimate Chef":       (85, 10, 5),
    "Teruteru Hanamura: Ultimate Despair":    (105, 12, 6),
    "Peko Pekoyama: Ultimate Swordswoman":    (110, 16, 6),
    "Peko Pekoyama: Ultimate Despair":        (130, 18, 7),
    "Chiaki Nanami: Ultimate Gamer":         (95, 11, 6),
    "Izuru Kamakura: Ultimate Despair":      (250, 30, 15),
    "Izuru Kamakura: Ultimate Hope":           (220, 25, 20),
}

# ── ROLE PRIORITY ───────────────────────────────────────────────────
# FIX: stats used to come from whichever role happened to appear first in
# ROLE_BASE_STATS, so a Despair/Izuru/character holder who also held a sin
# or virtue role got the WRONG stats.  Hope/Despair identities now win.
_STAT_PRIORITY: list[str] = (
    [IZURU_DESPAIR_ROLE, IZURU_HOPE_ROLE]
    + [c["despair_role"] for c in CHARACTERS.values() if c["despair_role"]]
    + [c["hope_role"] for c in CHARACTERS.values()]
    + [DESPAIR_ROLE, DESPAIR_SISTER_ROLE, REMNANT_OF_DESPAIR_ROLE, HOPE_ROLE]
)

def get_role_stats(member: discord.Member) -> tuple[int, int, int]:
    """Return (hp, attack, defense) from the member's highest-priority role."""
    role_names = {r.name for r in member.roles}
    for role_name in _STAT_PRIORITY:
        if role_name in role_names and role_name in ROLE_BASE_STATS:
            return ROLE_BASE_STATS[role_name]
    for role_name, stats in ROLE_BASE_STATS.items():
        if role_name in role_names:
            return stats
    return (100, 10, 5)  # default


# ═══════════════════════════════════════════════════════════════════
# HOPE & DESPAIR — UNIFIED STATUS-EFFECT + HIT ENGINE
# Everything Hope/Despair/Danganronpa runs on HP / ATK / DEF only.
# Nothing here touches the old clash-power / coin / path systems.
# ═══════════════════════════════════════════════════════════════════

# effect key -> (emoji, name, description, is_positive)
DR_EFFECTS: dict[str, tuple[str, str, str, bool]] = {
    "shock":     ("⚡", "Shock",        "Their attacks deal 40% less damage.", False),
    "panic":     ("😱", "Panic",        "25% of their attacks miss.", False),
    "brainwash": ("🌀", "Brainwash",    "Their attacks backfire on themselves.", False),
    "poison":    ("☠️", "Poison",       "Lose 3 HP every minute (cannot kill).", False),
    "fragile":   ("💔", "Fragile",      "Take 50% more damage.", False),
    "slowed":    ("🐌", "Slowed",       "Attack cooldown becomes 60 seconds.", False),
    "sleep":     ("💤", "Sleep",        "Cannot attack or use abilities.", False),
    "silence":   ("🤐", "Silence",      "Cannot use abilities (basic attacks still work).", False),
    "devoured":  ("🌑", "Void",         "Every message they send is deleted.", False),
    "empowered": ("✨", "Empowered",    "Deal 50% more damage.", True),
    "guarded":   ("🛡️", "Guarded",      "Take 40% less damage.", True),
    "regen":     ("💚", "Regeneration", "Recover 3 HP every minute.", True),
}

ATTACK_BASE_CD   = 8     # seconds between !attack uses
ATTACK_SLOWED_CD = 60
LUCK_EVADE_CHANCE = 0.99

def _eff_map(user: dict) -> dict:
    return user.setdefault("effects", {})

def _has_effect(user: dict, name: str) -> bool:
    e = _eff_map(user).get(name)
    if not e:
        return False
    if now_ts() >= e.get("until", 0):
        _eff_map(user).pop(name, None)
        return False
    return True

def _clear_effect(user: dict, name: str):
    _eff_map(user).pop(name, None)

def _apply_effect(user: dict, name: str, secs: float, by=None, once: bool = False):
    """Apply (or extend to the longer of) a timed status effect."""
    if name not in DR_EFFECTS:
        return
    until = now_ts() + secs
    old = _eff_map(user).get(name)
    if old and old.get("until", 0) > until:
        until = old["until"]
    _eff_map(user)[name] = {"until": until, "by": str(by) if by else None, "once": once}
    # Mirror onto the legacy lock fields so the older sin/virtue commands obey them too.
    if name == "devoured":
        user["devoured_until"] = max(user.get("devoured_until") or 0, until)
    if name in ("silence", "sleep"):
        user["ability_locked_until"] = max(user.get("ability_locked_until") or 0, until)

def _effects_text(user: dict) -> str:
    lines = []
    for name in list(_eff_map(user).keys()):
        if _has_effect(user, name):
            emo, nm, _desc, _pos = DR_EFFECTS[name]
            lines.append(f"{emo} **{nm}** — ends <t:{int(_eff_map(user)[name]['until'])}:R>")
    return "\n".join(lines)

def _dr_cd(user: dict, key: str, secs: int) -> Optional[str]:
    """Cooldown gate for Hope/Despair abilities. Returns an error string or sets the CD."""
    cds = user.setdefault("dr_cds", {})
    ts = cds.get(key, 0) or 0
    if now_ts() < ts:
        return f"**{key}** is on cooldown: {remaining_fmt(ts)}."
    cds[key] = now_ts() + secs
    return None

def _dr_gate(user: dict) -> Optional[str]:
    """Common 'may this person act right now' check for abilities."""
    if user.get("fallen"):
        return "You are fallen from grace. You cannot fight."
    if _has_effect(user, "sleep"):
        return "💤 You are asleep. You cannot use abilities."
    if _has_effect(user, "silence"):
        return "🤐 You are silenced. You cannot use abilities."
    return None

def _names(member: discord.Member) -> set:
    return {r.name for r in member.roles}

def _is_izuru(member: discord.Member) -> Optional[str]:
    n = _names(member)
    if IZURU_DESPAIR_ROLE in n:
        return "despair"
    if IZURU_HOPE_ROLE in n:
        return "hope"
    return None

def _alignment(member: discord.Member, user: dict) -> Optional[str]:
    n = _names(member)
    if n & {IZURU_DESPAIR_ROLE, DESPAIR_ROLE, REMNANT_OF_DESPAIR_ROLE, DESPAIR_SISTER_ROLE}:
        return "despair"
    if n & {IZURU_HOPE_ROLE, HOPE_ROLE}:
        return "hope"
    ck = user.get("character")
    if ck in CHARACTERS:
        c = CHARACTERS[ck]
        if c.get("despair_role") and c["despair_role"] in n:
            return "despair"
        if c["hope_role"] in n:
            return "hope"
    return None

def _luck_active(user: dict) -> bool:
    return now_ts() < (user.get("luck_until") or 0)

def _award_point(a_user: dict, d_user: dict, a_al: Optional[str], d_al: Optional[str], member: discord.Member):
    """Hope/Despair points for landing a damaging hit on the opposite side (10-min throttle)."""
    if not a_al or not d_al or a_al == d_al:
        return
    if now_ts() < (a_user.get("dr_point_ts") or 0):
        return
    a_user["dr_point_ts"] = now_ts() + 600
    key = "hope_points" if a_al == "hope" else "despair_points"
    gain = 2 if (a_al == "despair" and REMNANT_OF_DESPAIR_ROLE in _names(member)) else 1
    a_user[key] = a_user.get(key, 0) + gain

async def _hit(
    attacker: discord.Member,
    defender: discord.Member,
    data: dict,
    *,
    mult: float = 1.0,
    pierce: bool = False,
    src: str = "attack",          # attack | talent | special | summon
    flat: int = 0,
    can_crit: bool = True,
    attack_stat: Optional[int] = None,
    label: str = "strikes",
) -> tuple[str, int, str]:
    """
    Resolve ONE hit through every Hope/Despair rule.
    Returns (message, damage_dealt, outcome)
    outcome ∈ hit | miss | evaded | nullified | reflected | backfire | veiled
    """
    a_stats = get_role_stats(attacker)
    d_stats = get_role_stats(defender)
    a_user = get_user(data, attacker.id)
    d_user = get_user(data, defender.id)
    d_name = defender.display_name

    # Nagito remembers who tried to hit him (powers !fortune's 2-hour limit)
    if d_user.get("character") == "nagito" or _luck_active(d_user):
        data.setdefault("nagito_aggressors", {}).setdefault(str(defender.id), {})[str(attacker.id)] = now_ts()

    # La Llorona's veil
    veil_until = d_user.get("llorona_veil_until") or 0
    if now_ts() < veil_until:
        d_user["llorona_veil_until"] = None
        return (f"{attacker.mention} strikes at {defender.mention} through the mist...\n"
                f"🌫️ **Weeping Veil.** La Llorona's sorrow swallows the attack whole.", 0, "veiled")

    # Brainwash on the ATTACKER — the blow turns inward.
    legacy = data.get("brainwashed", {}).get(str(attacker.id))
    if legacy and now_ts() < legacy.get("until", 0):          # migrate old-format brainwash
        _apply_effect(a_user, "brainwash", legacy["until"] - now_ts(), by=legacy.get("by_id"), once=True)
        data["brainwashed"].pop(str(attacker.id), None)
    if _has_effect(a_user, "brainwash"):
        if _eff_map(a_user)["brainwash"].get("once"):
            _clear_effect(a_user, "brainwash")
        dmg = BRAINWASH_SELF_DAMAGE
        a_user["hp"] = max(0, a_user.get("hp", a_stats[0]) - dmg)
        return (f"{attacker.mention} **self-inflicted** **{dmg}** damage from brainwash!\n"
                f"🌀 The attack was redirected inward.", dmg, "backfire")

    # Panic on the attacker
    if _has_effect(a_user, "panic") and random.random() < 0.25:
        return (f"{attacker.mention} **panics** and misses {defender.mention}!\n😱 Panic caused a miss!", 0, "miss")

    # ── Defender-side avoidance ─────────────────────────────────────
    # NAGITO — Luck Switch: 99% of hits simply never land.
    if _luck_active(d_user) and random.random() < LUCK_EVADE_CHANCE:
        return (f"{attacker.mention} {label} {defender.mention}...\n"
                f"🍀 *\"My luck is so bad...\"* — a falling sign, a slip, a stray gust. "
                f"{d_name} is **not hit**.", 0, "evaded")

    izuru = _is_izuru(defender)
    if izuru == "hope" and random.random() < 0.15:
        return (f"{attacker.mention} {label} {defender.mention}...\n"
                f"👁️ **Foresight.** The Ultimate Hope saw it coming a moment ago. No damage.", 0, "evaded")

    if izuru == "despair":
        r = random.random()
        d_hp_now = d_user.get("hp", d_stats[0])
        if src in ("talent", "special") and r < 0.40:
            echo = max(1, int((a_stats[1] * mult) * 0.5))
            a_user["hp"] = max(0, a_user.get("hp", a_stats[0]) - echo)
            return (f"{attacker.mention} unleashes a talent on {defender.mention}...\n"
                    f"🧠 *\"If it's that, I have it too.\"* Izuru returns **{echo}** damage and takes none.",
                    0, "reflected")
        if src == "attack" and r < 0.30:
            return (f"{attacker.mention} **strikes** {defender.mention}...\n"
                    f"😳 **Who are y-you?** {d_name} stands there, unfazed. The attack was nullified.", 0, "nullified")
        if src == "summon" and r < 0.50:
            _apply_effect(a_user, "panic", 300, by=defender.id)
            return (f"A summoned ally lunges at {defender.mention}...\n"
                    f"😶 *\"Why would you...\"* Izuru dismisses it. {attacker.mention} is gripped by **Panic** (5 min).",
                    0, "nullified")
        if d_hp_now < d_stats[0] * 0.4 and r < 0.40:
            _apply_effect(a_user, "shock", 600, by=defender.id)
            return (f"{attacker.mention} presses the attack on {defender.mention}...\n"
                    f"🕳️ *\"What's the point?\"* The blow means nothing. {attacker.mention} is **Shocked** (10 min).",
                    0, "nullified")

    # ── Damage ──────────────────────────────────────────────────────
    atk = attack_stat if attack_stat is not None else a_stats[1]
    raw = max(1.0, atk * mult - (0 if pierce else d_stats[2]))
    roll = random.randint(1, 20)
    crit = can_crit and roll >= 18
    dmg = raw + (raw if crit else 0) + (roll // 4) + flat
    if _has_effect(a_user, "shock"):
        dmg *= 0.6
    if _has_effect(a_user, "empowered"):
        dmg *= 1.5
    if _has_effect(d_user, "fragile"):
        dmg *= 1.5
    if _has_effect(d_user, "guarded"):
        dmg *= 0.6
    if izuru == "hope":
        dmg *= 0.75
    dmg = max(1, int(dmg))

    d_user["hp"] = max(0, d_user.get("hp", d_stats[0]) - dmg)
    a_user["last_attack"] = int(now_ts())
    _award_point(a_user, d_user, _alignment(attacker, a_user), _alignment(defender, d_user), attacker)

    msg = (f"{attacker.mention} {label} {defender.mention} for **{dmg}** damage"
           f"{' ✨ CRITICAL HIT!' if crit else ''}"
           f"{' ⚡ (Shocked: weakened)' if _has_effect(a_user, 'shock') else ''}\n"
           f"🛡️ {d_name}: **{d_user['hp']} / {d_stats[0]}** HP")
    return (msg, dmg, "hit")


async def _resolve_combat(attacker: discord.Member, defender: discord.Member, data: dict) -> tuple[str, int]:
    """Back-compat wrapper: a plain !attack."""
    msg, dmg, _ = await _hit(attacker, defender, data, src="attack")
    return (msg, dmg)


async def _handle_defeat(ch, attacker: discord.Member, defender: discord.Member, data: dict, cause: str = "") -> bool:
    """Run the 'someone hit 0 HP' pipeline. Returns True if the defender actually fell."""
    d_user = get_user(data, defender.id)
    a_user = get_user(data, attacker.id)
    d_stats = get_role_stats(defender)
    if d_user.get("hp", d_stats[0]) > 0:
        return False

    # Chiaki's spirit cannot be broken by the Ultimate Hope
    if d_user.get("character") == "chiaki" and _is_izuru(attacker) == "hope":
        d_user["hp"] = 1
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🎮 Chiaki's Spirit Resists",
            description=f"{attacker.mention} cannot strike down {defender.mention}...\n"
                        "The Ultimate Gamer's spirit is protected from the Ultimate Hope.",
            color=discord.Color.purple(),
        ))
        return False

    a_user["pvp_kills"] = a_user.get("pvp_kills", 0) + 1
    d_user["pvp_deaths"] = d_user.get("pvp_deaths", 0) + 1
    # Winning the fight against the opposing side is worth bonus points
    a_al, d_al = _alignment(attacker, a_user), _alignment(defender, d_user)
    if a_al and d_al and a_al != d_al:
        k = "hope_points" if a_al == "hope" else "despair_points"
        a_user[k] = a_user.get(k, 0) + 2
    if d_user.get("character") == "chiaki":
        d_user["chiaki_dead"] = True

    save_data(data)
    await ch.send(embed=discord.Embed(
        title="☠️ A Soul Has Been Struck Down",
        description=f"{defender.mention} has been **defeated** by {attacker.mention}!"
                    + (f"\n*{cause}*" if cause else ""),
        color=discord.Color.red(),
    ))
    await fall_from_grace(defender, f"Defeated in PVP by {attacker.display_name}.", data)
    save_data(data)
    return True


@bot.command()
async def attack(ctx, target: discord.Member = None):
    """Universal PVP attack command. Works for any role."""
    if target is None:
        await ctx.send("Usage: `!attack @user`", delete_after=5)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot attack yourself.", delete_after=5)
        return

    data = load_data()
    a_user = get_user(data, ctx.author.id)
    d_user = get_user(data, target.id)

    if a_user.get("fallen"):
        await ctx.send("You are fallen from grace. You cannot fight.", delete_after=5)
        save_data(data); return
    if d_user.get("fallen"):
        await ctx.send("That target is fallen. Show mercy.", delete_after=5)
        save_data(data); return
    if _has_effect(a_user, "sleep"):
        await ctx.send("💤 You are asleep. You cannot attack.", delete_after=5)
        save_data(data); return

    a_stats = get_role_stats(ctx.author)
    d_stats = get_role_stats(target)
    if a_user.get("hp", a_stats[0]) <= 0:
        await ctx.send("You are too weak to fight. Heal first.", delete_after=5)
        save_data(data); return
    if d_user.get("hp", d_stats[0]) <= 0:
        await ctx.send("That target is already defeated.", delete_after=5)
        save_data(data); return

    cd_len = ATTACK_SLOWED_CD if _has_effect(a_user, "slowed") else ATTACK_BASE_CD
    last = a_user.get("dr_last_attack_ts", 0) or 0
    if now_ts() < last + cd_len:
        await ctx.send(f"Catch your breath — {int(last + cd_len - now_ts()) + 1}s until your next attack.", delete_after=5)
        save_data(data); return
    a_user["dr_last_attack_ts"] = now_ts()

    outcome, dmg = await _resolve_combat(ctx.author, target, data)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(outcome)
    await _handle_defeat(ch, ctx.author, target, data)


@bot.command()
async def heal(ctx):
    """Recover HP. 5-minute cooldown."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    cd = user.get("heal_cooldown", 0)
    if now_ts() < cd:
        await ctx.send(f"Heal on cooldown. {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return
    stats = get_role_stats(ctx.author)
    heal_amount = random.randint(15, 30)
    user["hp"] = min(stats[0], user.get("hp", stats[0]) + heal_amount)
    user["heal_cooldown"] = now_ts() + 300
    save_data(data)
    await ctx.send(f"{ctx.author.mention} healed for **{heal_amount}** HP. Current: **{user['hp']} / {stats[0]}**")


@bot.command(aliases=["status"])
async def effects(ctx, target: discord.Member = None):
    """Show active status effects on yourself or someone else."""
    target = target or ctx.author
    data = load_data()
    u = get_user(data, target.id)
    txt = _effects_text(u)
    luck = f"\n🍀 **Luck Switch** — ends <t:{int(u['luck_until'])}:R>" if _luck_active(u) else ""
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title=f"🧪 {target.display_name}'s Status Effects",
        description=(txt + luck) or "*No active effects.*",
        color=discord.Color.dark_teal(),
    ))


# ── Ability engine ──────────────────────────────────────────────────
def A(name, flavor, *, mult=1.0, hits=1, pierce=False, drain=0.0, execute=False,
      gamble=False, effect=None, self_effect=None, selfdmg=0.0, cd=1200):
    """Declarative ability. effect/self_effect = (effect_key, minutes[, chance])."""
    return dict(name=name, flavor=flavor, mult=mult, hits=hits, pierce=pierce, drain=drain,
                execute=execute, gamble=gamble, effect=effect, self_effect=self_effect,
                selfdmg=selfdmg, cd=cd)


async def _run_ability(ctx, data: dict, spec: dict, target: discord.Member, *,
                       src: str, power: float = 1.0, title_prefix: str = "", color=None) -> bool:
    """Execute a declarative ability on a target. Returns True if the defender fell."""
    user = get_user(data, ctx.author.id)
    t_user = get_user(data, target.id)
    a_stats = get_role_stats(ctx.author)
    t_stats = get_role_stats(target)
    ch = await trial_channel(ctx.guild) or ctx.channel

    mult = spec["mult"] * power
    lines, total, landed = [], 0, False
    for _u, _m, _st in ((user, ctx.author, a_stats), (t_user, target, t_stats)):
        _u.setdefault("hp", _st[0])          # needed so Poison / Regeneration can tick
        _u.setdefault("max_hp", _st[0])

    if spec["execute"] and t_user.get("hp", t_stats[0]) <= t_stats[0] * 0.35:
        mult *= 1.75
        lines.append("🗡️ **Execution** — the target is nearly broken. Damage greatly increased!")

    if spec["gamble"]:
        if random.random() < 0.5:
            mult *= 2.2
            lines.append("🎰 **The gamble pays off!** Damage greatly increased!")
        else:
            cost = max(1, int(a_stats[0] * 0.08))
            user["hp"] = max(1, user.get("hp", a_stats[0]) - cost)
            mult *= 0.5
            lines.append(f"🎰 **The gamble sours.** You lose **{cost}** HP and the strike is weak.")

    for i in range(spec["hits"]):
        msg, dmg, outcome = await _hit(ctx.author, target, data, mult=mult, pierce=spec["pierce"],
                                       src=src, label="strikes")
        total += dmg
        landed = landed or outcome == "hit"
        lines.append(msg if spec["hits"] == 1 else f"**Hit {i+1}:** {msg}")
        if outcome in ("evaded", "nullified", "reflected", "veiled", "backfire"):
            break   # defensive effect ends the combo

    if spec["drain"] and total > 0:
        gain = int(total * spec["drain"])
        user["hp"] = min(a_stats[0], user.get("hp", a_stats[0]) + gain)
        lines.append(f"🩸 Drained **{gain}** HP.")
    if spec["selfdmg"]:
        cost = max(1, int(a_stats[0] * spec["selfdmg"]))
        user["hp"] = max(1, user.get("hp", a_stats[0]) - cost)
        lines.append(f"💥 Recoil: you lose **{cost}** HP.")

    if spec["effect"] and landed:
        eff, mins = spec["effect"][0], spec["effect"][1]
        chance = spec["effect"][2] if len(spec["effect"]) > 2 else 1.0
        if random.random() < chance:
            _apply_effect(t_user, eff, mins * 60, by=ctx.author.id)
            lines.append(f"{DR_EFFECTS[eff][0]} {target.mention} suffers **{DR_EFFECTS[eff][1]}** for **{mins} min**.")
    if spec["self_effect"]:
        eff, mins = spec["self_effect"][0], spec["self_effect"][1]
        _apply_effect(user, eff, mins * 60, by=ctx.author.id)
        lines.append(f"{DR_EFFECTS[eff][0]} You gain **{DR_EFFECTS[eff][1]}** for **{mins} min**.")

    save_data(data)
    await ch.send(embed=discord.Embed(
        title=f"{title_prefix}{spec['name']}",
        description=f"*{spec['flavor']}*\n\n" + "\n".join(lines),
        color=color or discord.Color.from_rgb(120, 0, 60),
    ))
    return await _handle_defeat(ch, ctx.author, target, data)



# ── Ability 1: Tragic Event ──
@bot.command()
async def tragic_event(ctx):
    """Activate passive: next person to talk in any channel gets a Hope/Despair choice debuff."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("despair_role"):
        await ctx.send("Only the Ultimate Despair may use this.", delete_after=5)
        save_data(data)
        return
    cd = user.get("despair_ability_cds", {}).get("tragic_event", 0)
    if now_ts() < cd:
        await ctx.send(f"Cooldown: {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return
    user.setdefault("despair_ability_cds", {})["tragic_event"] = now_ts() + 60 * 60  # 1h CD
    user["tragic_event_active"] = True
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💀 The Biggest, Most Atrocious, Most Tragic Event in History",
        description="The next person to speak in any channel will face a choice.\n\nHope — or Despair?",
        color=discord.Color.from_rgb(80, 0, 0),
    ))

# ── Ability 2: Brainwash ──
@bot.command()
async def brainwash(ctx, target: discord.Member = None):
    """Send backrooms party song video. Target's next attack will self-inflict."""
    if target is None:
        await ctx.send("Usage: `!brainwash @user`", delete_after=5)
        return
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("despair_role"):
        await ctx.send("Only the Ultimate Despair may use this.", delete_after=5)
        save_data(data)
        return
    cd = user.get("despair_ability_cds", {}).get("brainwash", 0)
    if now_ts() < cd:
        await ctx.send(f"Cooldown: {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot brainwash yourself.", delete_after=5)
        save_data(data)
        return

    user.setdefault("despair_ability_cds", {})["brainwash"] = now_ts() + 60 * 10  # 10m CD
    _apply_effect(get_user(data, target.id), "brainwash",
                  BRAINWASH_DURATION_MINUTES * 60, by=ctx.author.id, once=True)
    save_data(data)

    try:
        await target.send(
            "🔴💀 **You have been brainwashed.**\n\n"
            "https://www.youtube.com/watch?v=niwUUtgn4-o\n\n"
            "*The party is waiting for you...*\n\n"
            "⚠️ Your next attack will **self-inflict** damage instead."
        )
    except Exception:
        pass

    await ctx.send(embed=discord.Embed(
        title="🔴 Brainwash Complete",
        description=f"{target.mention} has been brainwashed with the Backrooms Party Song.\nTheir next attack will backfire.",
        color=discord.Color.from_rgb(80, 0, 0),
    ))

# ── Ability 3: Disaster ──
@bot.command()
async def disaster(ctx):
    """Threaten every role in the server. Everyone must defend or lose their role."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("despair_role"):
        await ctx.send("Only the Ultimate Despair may use this.", delete_after=5)
        save_data(data)
        return
    if data.get("disaster_active"):
        await ctx.send("A disaster is already active.", delete_after=5)
        save_data(data)
        return
    cd = user.get("despair_ability_cds", {}).get("disaster", 0)
    if now_ts() < cd:
        await ctx.send(f"Cooldown: {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return

    user.setdefault("despair_ability_cds", {})["disaster"] = now_ts() + 60 * 60 * 24  # 24h CD
    data["disaster_active"] = True
    data["disaster_until"] = now_ts() + DISASTER_DURATION_MINUTES * 60
    data["disaster_by"] = str(ctx.author.id)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🚨🔴 DISASTER EVENT — ALL ROLES THREATENED",
        description=(
            f"{ctx.author.mention} has unleashed a **Disaster** upon the server!\n\n"
            "**All role holders are threatened.**\n"
            "Use `!defend` to protect your role.\n"
            "Those who do not defend within 30 minutes will **fall from grace** automatically.\n\n"
            f"Event ends: <t:{int(data['disaster_until'])}:R>"
        ),
        color=discord.Color.from_rgb(80, 0, 0),
    ))

@bot.command()
async def defend(ctx):
    """Defend against an active disaster event."""
    data = load_data()
    if not data.get("disaster_active"):
        await ctx.send("No disaster is currently active.", delete_after=5)
        save_data(data)
        return
    if now_ts() > data.get("disaster_until", 0):
        data["disaster_active"] = False
        save_data(data)
        await ctx.send("The disaster has ended.", delete_after=5)
        return
    user = get_user(data, ctx.author.id)
    if user.get("disaster_defended"):
        await ctx.send("You have already defended.", delete_after=5)
        save_data(data)
        return
    user["disaster_defended"] = True
    save_data(data)
    await ctx.send(f"{ctx.author.mention} has **defended** their role against the disaster!")

# Background task: disaster resolution
@tasks.loop(minutes=1)
async def disaster_resolution_check():
    data = load_data()
    if not data.get("disaster_active"):
        return
    if now_ts() < data.get("disaster_until", 0):
        return
    # Disaster expired — penalize those who didn't defend
    data["disaster_active"] = False
    for uid, u in data.get("users", {}).items():
        if u.get("sin_role") and not u.get("disaster_defended"):
            for guild in bot.guilds:
                member = guild.get_member(int(uid))
                if member:
                    await fall_from_grace(member, "Failed to defend during the Disaster event.", data)
    # Reset defense flags
    for u in data.get("users", {}).values():
        u["disaster_defended"] = False
    save_data(data)

# Background task: checks for Despair obtainment window
@tasks.loop(minutes=1)
async def despair_timer_check():
    """Check if it's Friday 8:12 PM — if a user has 50+ corruption and is in a sin role, grant Despair."""
    now = datetime.now(timezone.utc)
    if now.weekday() != DESPAIR_DAY or now.hour != DESPAIR_HOUR or now.minute != DESPAIR_MINUTE:
        return

    data = load_data()
    if data.get("despair_active"):
        return  # Someone already holds Despair

    for uid, u in data.get("users", {}).items():
        if u.get("corruption", 0) >= DESPAIR_CORRUPTION_REQUIRED and u.get("sin_role") and not u.get("despair_role"):
            for guild in bot.guilds:
                member = guild.get_member(int(uid))
                if member:
                    await _grant_despair(member, data)
                    save_data(data)
                    ch = await trial_channel(guild)
                    if ch:
                        await ch.send(embed=discord.Embed(
                            title="🔴💀 A New Ultimate Despair Has Been Born",
                            description=(
                                f"{member.mention} has transcended to **{DESPAIR_ROLE}**!\n\n"
                                f"**Corruption:** {u['corruption']}\n"
                                "The ultimate despair has been unleashed upon the server."
                            ),
                            color=discord.Color.from_rgb(80, 0, 0),
                        ))
                    return

async def _grant_despair(member: discord.Member, data: dict):
    """Grant the Despair role to a member."""
    await _give_role(member, DESPAIR_ROLE, discord.Color.from_rgb(80, 0, 0))
    user = get_user(data, member.id)
    user["despair_role"] = True
    user["ultimate_despair"] = True
    user["alignment"] = "despair"
    user["hp"] = ROLE_BASE_STATS[DESPAIR_ROLE][0]
    user["max_hp"] = ROLE_BASE_STATS[DESPAIR_ROLE][0]
    data["despair_active"] = True

# ── Ability 4: Summon Despair Sister ──
@bot.command()
async def summon_sister(ctx):
    """Summon the Despair Sister — an NPC who obeys your commands."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("despair_role"):
        await ctx.send("Only the Ultimate Despair may use this.", delete_after=5)
        save_data(data)
        return
    if user.get("sister_summoned"):
        await ctx.send("You already have a Despair Sister active.", delete_after=5)
        save_data(data)
        return
    cd = user.get("despair_ability_cds", {}).get("summon_sister", 0)
    if now_ts() < cd:
        await ctx.send(f"Cooldown: {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return

    user.setdefault("despair_ability_cds", {})["summon_sister"] = now_ts() + 60 * 60 * 2  # 2h CD
    user["sister_summoned"] = True
    data["despair_sister"][str(ctx.author.id)] = {
        "active": True,
        "name": "Junko Enoshima",
        "summoned_at": now_ts(),
    }
    save_data(data)

    # Create sister role if not exists
    guild = ctx.guild
    sister_role = discord.utils.get(guild.roles, name=DESPAIR_SISTER_ROLE)
    if not sister_role:
        try:
            sister_role = await guild.create_role(
                name=DESPAIR_SISTER_ROLE,
                color=discord.Color.from_rgb(120, 0, 60),
                reason="Despair Sister summoned",
            )
        except discord.Forbidden:
            pass

    await ctx.send(embed=discord.Embed(
        title="👸 Despair Sister Summoned",
        description=(
            f"{ctx.author.mention} has summoned the **Despair Sister**!\n\n"
            "She will obey your every command:\n"
            "• `!sister_kill @user` — attempt to kill a target\n"
            "• `!sister_say <message>` — make her say something\n"
            "• `!sister_seduce @user` — seduce a target\n"
            "• `!sister_anything <action>` — do anything you ask"
        ),
        color=discord.Color.from_rgb(120, 0, 60),
    ))

@bot.command()
async def sister_kill(ctx, target: discord.Member = None):
    """Despair Sister attempts to kill a target."""
    if target is None:
        await ctx.send("Usage: `!sister_kill @user`", delete_after=5)
        return
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("sister_summoned"):
        await ctx.send("You have no Despair Sister summoned.", delete_after=5)
        save_data(data)
        return

    # Sister attacks as a high-power combatant
    sister_hp = 180
    sister_atk = 20
    sister_def = 8

    err = _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6)
        save_data(data)
        return
    msg, dmg, outcome = await _hit(ctx.author, target, data, attack_stat=sister_atk,
                                   src="summon", label="👸 sets the Despair Sister on")
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(msg)
    await _handle_defeat(ch, ctx.author, target, data, "Slain by the Despair Sister.")

@bot.command()
async def sister_say(ctx, *, message: str):
    """Make the Despair Sister say something."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("sister_summoned"):
        await ctx.send("You have no Despair Sister summoned.", delete_after=5)
        save_data(data)
        return
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="👸 Despair Sister says:",
        description=f"*{message}*",
        color=discord.Color.from_rgb(120, 0, 60),
    ))

@bot.command()
async def sister_seduce(ctx, target: discord.Member = None):
    """Despair Sister seduces a target."""
    if target is None:
        await ctx.send("Usage: `!sister_seduce @user`", delete_after=5)
        return
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("sister_summoned"):
        await ctx.send("You have no Despair Sister summoned.", delete_after=5)
        save_data(data)
        return
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="👸 Despair Sister seduces",
        description=f"The Despair Sister whispers to {target.mention}...\n\n*Despair is so much more exciting than hope, don't you think?*",
        color=discord.Color.from_rgb(120, 0, 60),
    ))

@bot.command()
async def sister_anything(ctx, *, action: str):
    """Make the Despair Sister do anything."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("sister_summoned"):
        await ctx.send("You have no Despair Sister summoned.", delete_after=5)
        save_data(data)
        return
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="👸 Despair Sister acts",
        description=f"The Despair Sister {action}",
        color=discord.Color.from_rgb(120, 0, 60),
    ))

# ── Ability 5: Summon Reserve Course Students ──
@bot.command()
async def summon_reserve(ctx):
    """Summon Reserve Course Students to fight for you."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("despair_role"):
        await ctx.send("Only the Ultimate Despair may use this.", delete_after=5)
        save_data(data)
        return
    cd = user.get("despair_ability_cds", {}).get("summon_reserve", 0)
    if now_ts() < cd:
        await ctx.send(f"Cooldown: {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return

    user.setdefault("despair_ability_cds", {})["summon_reserve"] = now_ts() + 60 * 60 * 4  # 4h CD
    user["reserve_course_summoned"] = user.get("reserve_course_summoned", 0) + 1
    students = []
    for i in range(RESERVE_COURSE_COUNT):
        student_name = f"Reserve Course Student #{i+1}"
        students.append({
            "uid": f"reserve_{ctx.author.id}_{i}_{int(now_ts())}",
            "name": student_name,
            "hp": 80,
            "attack": 8,
            "defense": 3,
        })
    data.setdefault("reserve_course", {})[str(ctx.author.id)] = students
    save_data(data)

    # Create reserve course roles
    guild = ctx.guild
    for i in range(RESERVE_COURSE_COUNT):
        role_name = f"Reserve Course Student #{i+1}"
        existing = discord.utils.get(guild.roles, name=role_name)
        if not existing:
            try:
                await guild.create_role(name=role_name, color=discord.Color.from_rgb(100, 100, 100))
            except discord.Forbidden:
                pass

    await ctx.send(embed=discord.Embed(
        title="🏫 Reserve Course Students Summoned",
        description=(
            f"{ctx.author.mention} has summoned **{RESERVE_COURSE_COUNT}** Reserve Course Students!\n\n"
            "They will fight for you in PVP.\n"
            "Each student: 80 HP, 8 ATK, 3 DEF\n\n"
            "Use `!student_attack @user` to command them."
        ),
        color=discord.Color.from_rgb(100, 100, 100),
    ))

@bot.command()
async def student_attack(ctx, target: discord.Member = None):
    """Command a Reserve Course Student to attack."""
    if target is None:
        await ctx.send("Usage: `!student_attack @user`", delete_after=5)
        return
    data = load_data()
    user = get_user(data, ctx.author.id)
    students = data.get("reserve_course", {}).get(str(ctx.author.id), [])
    if not students:
        await ctx.send("You have no Reserve Course Students active.", delete_after=5)
        save_data(data)
        return

    # Use the first available student
    student = students[0]
    err = _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6)
        save_data(data)
        return
    msg, dmg, outcome = await _hit(ctx.author, target, data, attack_stat=student["attack"],
                                   src="summon", label=f"🏫 sends **{student['name']}** after")
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(msg)
    await _handle_defeat(ch, ctx.author, target, data, "Defeated by a Reserve Course Student.")

# ── Ability 6: Brainwash Remnant of Despair ──
@bot.command()
async def brainwash_remnant(ctx, target: discord.Member = None):
    """Attempt to convert a target into a Remnant of Despair."""
    if target is None:
        await ctx.send("Usage: `!brainwash_remnant @user`", delete_after=5)
        return
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not user.get("despair_role"):
        await ctx.send("Only the Ultimate Despair may use this.", delete_after=5)
        save_data(data)
        return
    cd = user.get("despair_ability_cds", {}).get("brainwash_remnant", 0)
    if now_ts() < cd:
        await ctx.send(f"Cooldown: {remaining_fmt(cd)}", delete_after=5)
        save_data(data)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot convert yourself.", delete_after=5)
        save_data(data)
        return

    t_user = get_user(data, target.id)
    if t_user.get("remnant_of_despair"):
        await ctx.send("They are already a Remnant of Despair.", delete_after=5)
        save_data(data)
        return

    # Chance based on target's corruption (higher corruption = easier to convert)
    corruption = t_user.get("corruption", 0)
    chance = min(0.8, 0.1 + (corruption / 100))
    roll = random.random()

    user.setdefault("despair_ability_cds", {})["brainwash_remnant"] = now_ts() + 60 * 30  # 30m CD

    if roll <= chance:
        t_user["remnant_of_despair"] = True
        await add_role(target, REMNANT_OF_DESPAIR_ROLE)
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title="🔴 Conversion Successful",
            description=f"{target.mention} has been converted into a **Remnant of Despair**!",
            color=discord.Color.from_rgb(60, 0, 0),
        ))
        try:
            await target.send(
                "🔴 You have been converted into a **Remnant of Despair**.\n\n"
                "Your despair points now generate faster.\n"
                "You serve the Ultimate Despair."
            )
        except Exception:
            pass
    else:
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title="❌ Conversion Failed",
            description=f"{target.mention} resisted the brainwashing.",
            color=discord.Color.greyple(),
        ))


# ═══════════════════════════════════════════════════════════════════
# DANGANRONPA CHARACTER SYSTEM v2 — Hope + Despair versions
# Replaces the old flat !claim_* block.  HP/ATK/DEF + status effects only.
# ═══════════════════════════════════════════════════════════════════

LUCK_SWITCH_DURATION   = 20 * 60        # how long Nagito's luck stays "bad"
LUCK_SWITCH_CD         = 2 * 3600
FORTUNE_CD             = 45 * 60
FORTUNE_NORMAL_MAX_MIN = 60             # up to an hour...
FORTUNE_GRUDGE_MAX_MIN = 120            # ...two hours if they tried to hit Nagito
FORTUNE_GRUDGE_WINDOW  = 24 * 3600      # how long Nagito remembers an attack on him
TALENT_CD              = 1200
SPECIAL_CD             = 2700
ALIGNMENT_SWITCH_CD    = 3600

# Every character: [talent (attack), special] for each version.
# Hope kits are all attacks/specials — no support moves.
KITS: dict[str, dict[str, list[dict]]] = {
    "nagito": {
        "hope":    [A("Stroke of Luck", "Hope itself favors you — a perfectly lucky blow.", mult=1.5, effect=("shock", 8, 0.4)),
                    A("Gambler's Fortune", "All in. Win big, or pay for it.", mult=1.6, gamble=True, cd=SPECIAL_CD)],
        "despair": [A("Stepping Stone", "Your despair is a delicious stepping stone.", mult=1.7, effect=("poison", 10, 0.5)),
                    A("Luck Reversal", "Good luck always follows bad. Now it's your turn.", mult=1.4, execute=True, effect=("fragile", 10, 1.0), cd=SPECIAL_CD)],
    },
    "akane": {
        "hope":    [A("Gymnast's Flurry", "Flip, spin, strike.", mult=0.6, hits=3),
                    A("Ravenous Smash", "Hunger fuels the fist.", mult=1.3, drain=0.4, cd=SPECIAL_CD)],
        "despair": [A("Starving Frenzy", "Nothing left but hunger.", mult=0.65, hits=4, effect=("panic", 6, 0.3)),
                    A("Devour", "She takes everything.", mult=1.5, drain=0.6, execute=True, cd=SPECIAL_CD)],
    },
    "sonia": {
        "hope":    [A("Royal Decree", "By royal authority — kneel.", mult=1.0, effect=("shock", 10, 0.6)),
                    A("Novoselic Magic", "An occult flourish that finds every gap.", mult=1.4, pierce=True, cd=SPECIAL_CD)],
        "despair": [A("Tyrant's Command", "The princess no longer asks.", mult=1.2, effect=("sleep", 3, 0.35)),
                    A("Execution Order", "Off with their head.", mult=1.5, execute=True, cd=SPECIAL_CD)],
    },
    "fuyuhiko": {
        "hope":    [A("Yakuza Blade", "A clean cut through the guard.", mult=1.6, pierce=True),
                    A("Honor Debt", "You owe me. Pay up.", mult=1.2, effect=("fragile", 10, 1.0), cd=SPECIAL_CD)],
        "despair": [A("Blood Debt", "Two cuts. Both deep.", mult=0.9, hits=2, pierce=True, effect=("poison", 8, 0.5)),
                    A("Dragon's Fury", "A boss with nothing left to lose.", mult=1.6, execute=True, cd=SPECIAL_CD)],
    },
    "kazuichi": {
        "hope":    [A("Spanner Barrage", "Three wrenches, one target.", mult=0.6, hits=3),
                    A("Overclock Rig", "Redline everything.", mult=1.4, effect=("shock", 8, 0.5), self_effect=("empowered", 10), cd=SPECIAL_CD)],
        "despair": [A("Self-Destruct Bot", "Boom. Obviously.", mult=2.0, selfdmg=0.10),
                    A("Meltdown", "Everything overheats.", mult=1.0, hits=2, effect=("fragile", 8, 0.6), cd=SPECIAL_CD)],
    },
    "hiyoko": {
        "hope":    [A("Dancer's Kick", "Graceful and vicious.", mult=1.1, effect=("slowed", 10, 0.6)),
                    A("Geta Stomp", "Stomp, stomp.", mult=0.8, hits=2, effect=("panic", 8, 0.4), cd=SPECIAL_CD)],
        "despair": [A("Venomous Tongue", "Words that cut deeper than steel.", mult=1.0, effect=("shock", 12, 0.8)),
                    A("Hex Dance", "A dance that rots the dancer's audience.", mult=1.2, effect=("poison", 12, 1.0), cd=SPECIAL_CD)],
    },
    "mikan": {
        "hope":    [A("Syringe Jab", "Just a little pinch...", mult=0.8, effect=("poison", 10, 1.0)),
                    A("Overdose", "Too much of a good thing.", mult=1.1, effect=("sleep", 3, 0.4), cd=SPECIAL_CD)],
        "despair": [A("Tripping Disaster", "Clumsy... and everything goes wrong.", mult=0.8, hits=2, effect=("panic", 8, 0.5)),
                    A("Nurse's Cruelty", "Her smile never wavers.", mult=1.3, effect=("poison", 15, 1.0), cd=SPECIAL_CD)],
    },
    "ibuki": {
        "hope":    [A("Sonic Riff", "A chord that rattles the skull.", mult=1.0, effect=("silence", 6, 0.7)),
                    A("Encore!", "Again! Again!", mult=0.9, hits=2, self_effect=("empowered", 8), cd=SPECIAL_CD)],
        "despair": [A("Noise Pollution", "Pure wall-of-sound.", mult=1.2, effect=("silence", 10, 1.0)),
                    A("Screaming Finale", "The last song.", mult=0.7, hits=3, effect=("panic", 8, 0.5), cd=SPECIAL_CD)],
    },
    "mahiru": {
        "hope":    [A("Flash Shot", "Blinding. Perfectly framed.", mult=0.9, effect=("panic", 10, 0.8)),
                    A("Decisive Moment", "The shutter clicks at the exact right instant.", mult=1.5, pierce=True, cd=SPECIAL_CD)],
        "despair": [A("Cruel Exposure", "Everything about you, on display.", mult=1.1, effect=("fragile", 10, 1.0)),
                    A("Shutter Storm", "A hundred flashes a second.", mult=0.6, hits=3, effect=("shock", 8, 0.4), cd=SPECIAL_CD)],
    },
    "nekomaru": {
        "hope":    [A("Training Camp Smash", "Fifty laps and a fist.", mult=1.8),
                    A("Never-Quit Charge", "Bull rush!", mult=1.3, effect=("shock", 8, 0.5), self_effect=("guarded", 10), cd=SPECIAL_CD)],
        "despair": [A("Overtraining Crush", "Pain is just progress.", mult=2.0, effect=("slowed", 10, 0.6)),
                    A("Coach's Wrath", "Two punishing hits.", mult=1.2, hits=2, cd=SPECIAL_CD)],
    },
    "gundham": {
        "hope":    [A("Four Dark Devas", "The Four Dark Devas of Destruction attack!", mult=0.55, hits=4),
                    A("Forbidden Seal", "A sealing curse from the Dark Lord.", mult=1.1, effect=("silence", 8, 0.8), cd=SPECIAL_CD)],
        "despair": [A("Hellfire Devas", "The Devas burn with despair.", mult=0.65, hits=4, effect=("poison", 8, 0.4)),
                    A("Dark Lord's Curse", "Doom wears many faces.", mult=1.3, effect=("fragile", 12, 0.9), cd=SPECIAL_CD)],
    },
    "teruteru": {
        "hope":    [A("Flambé Fury", "Served flaming.", mult=1.2, effect=("poison", 8, 0.6)),
                    A("Culinary Assault", "Two courses of pain.", mult=0.9, hits=2, cd=SPECIAL_CD)],
        "despair": [A("Poisoned Platter", "Bon appétit.", mult=1.0, effect=("poison", 15, 1.0)),
                    A("Reckless Rush", "He lunges — completely shameless.", mult=1.2, effect=("panic", 10, 0.7), cd=SPECIAL_CD)],
    },
    "peko": {
        "hope":    [A("Bamboo Sword Slash", "Two flawless cuts.", mult=1.0, hits=2, pierce=True),
                    A("Iaido Draw", "Sheathed, then gone.", mult=1.7, pierce=True, cd=SPECIAL_CD)],
        "despair": [A("Blade Dance", "Three cuts that don't stop.", mult=0.8, hits=3, pierce=True),
                    A("Soulless Cut", "A tool has no hesitation.", mult=1.5, pierce=True, execute=True, cd=SPECIAL_CD)],
    },
    "chiaki": {
        "hope":    [A("Combo Chain", "Input accepted. Three hits.", mult=0.7, hits=3, self_effect=("empowered", 8)),
                    A("Game Over", "Continue? No.", mult=1.6, execute=True, effect=("sleep", 2, 0.5), cd=SPECIAL_CD)],
        "despair": [],   # Chiaki is pure hope
    },
}

# Izuru's own signature moves
IZURU_BOREDOM  = A("How boring...", "Everything is predictable. Everything is boring.", mult=2.0, pierce=True, effect=("shock", 10, 1.0), cd=3600)
IZURU_OVERDRIVE = A("Hope Overdrive", "Every talent at once. The Ultimate Hope.", mult=2.4, pierce=True, effect=("fragile", 15, 1.0), cd=7200)

# The Hopeful (standalone virtue) — all attack / special moves
HOPEFUL_KIT = {
    "radiant_strike": A("Radiant Strike", "A beam of light too stubborn to dim.", mult=1.5, pierce=True, effect=("shock", 5, 0.5), cd=1800),
    "hope_barrage":   A("Hope Barrage", "Wave after wave of unbroken optimism.", mult=0.7, hits=3, self_effect=("empowered", 10), cd=7200),
    "inspire_strike": A("Inspire Strike", "Relentless optimism, weaponized.", mult=1.2, effect=("slowed", 20, 1.0), cd=2700),
}


# ── Helpers ─────────────────────────────────────────────────────────
def _dr_ensure(u: dict):
    """Backfill every Hope/Despair field so older save data never KeyErrors."""
    u.setdefault("character", None)
    u.setdefault("character_hope", False)
    u.setdefault("character_despair", False)
    u.setdefault("alignment", None)
    u.setdefault("reserve_course", True)
    u.setdefault("izuru_approval_votes", {})
    u.setdefault("izuru_approved_by", [])
    u.setdefault("izuru_surgery_done", False)
    u.setdefault("izuru_mastery_locked", True)
    u.setdefault("izuru_mastery_unlocked", False)
    u.setdefault("izuru_via_pride", False)
    u.setdefault("chiaki_dead", False)
    u.setdefault("hope_points", 0)
    u.setdefault("despair_points", 0)
    u.setdefault("effects", {})
    u.setdefault("dr_cds", {})
    u.setdefault("luck_until", None)
    u.setdefault("remnant_of_despair", False)
    u.setdefault("despair_ability_cds", {})
    u.setdefault("despair_role", False)

async def _ensure_role(guild: discord.Guild, name: str, color=None) -> Optional[discord.Role]:
    """Find the role, or create it if the server never ran !setup (the old 'broken role' cause)."""
    role = discord.utils.get(guild.roles, name=name)
    if role:
        return role
    try:
        return await guild.create_role(name=name, color=color or discord.Color.default(),
                                       hoist=True, reason="Hope/Despair role auto-created")
    except Exception as e:
        print(f"[ensure_role] could not create '{name}': {type(e).__name__}: {e}")
        return None

async def _give_role(member: discord.Member, name: str, color=None) -> bool:
    role = await _ensure_role(member.guild, name, color)
    if not role:
        return False
    try:
        await member.add_roles(role)
        return True
    except Exception as e:
        print(f"[give_role] '{name}' -> {member}: {type(e).__name__}: {e}")
        return False

async def _dr_strip_char_roles(member: discord.Member):
    for c in CHARACTERS.values():
        await remove_role(member, c["hope_role"])
        if c.get("despair_role"):
            await remove_role(member, c["despair_role"])
    await remove_role(member, IZURU_DESPAIR_ROLE)
    await remove_role(member, IZURU_HOPE_ROLE)

async def _dr_strip_roles(member: discord.Member):
    """Remove EVERY Hope/Despair role (used when someone falls)."""
    await _dr_strip_char_roles(member)
    for r in (DESPAIR_ROLE, REMNANT_OF_DESPAIR_ROLE, HOPE_ROLE):
        await remove_role(member, r)

def _dr_reset(user: dict, data: dict, uid: int):
    """Make the save data match the stripped roles (otherwise users are locked out of re-claiming)."""
    if user.get("ultimate_despair"):
        data["despair_active"] = False
    user["ultimate_despair"] = False
    data.get("despair_sister", {}).pop(str(uid), None)
    data.get("reserve_course", {}).pop(str(uid), None)
    for k in ("character", "alignment", "luck_until"):
        user[k] = None
    for k in ("character_hope", "character_despair", "despair_role", "remnant_of_despair",
              "sister_summoned", "tragic_event_active", "izuru_surgery_done", "izuru_mastery_unlocked",
              "izuru_via_pride"):
        user[k] = False
    user["reserve_course"] = True
    user["izuru_mastery_locked"] = True
    user["izuru_approved_by"] = []
    user["effects"] = {}
    for k in ("hp", "max_hp", "attack", "defense"):
        user.pop(k, None)

def _izuru_mastery(data: dict, user: dict, uid: int) -> bool:
    """Izuru-Hope mastery is dynamic: Chiaki's fall, or (if obtained via Pride) a pact with a Despair."""
    if user.get("izuru_mastery_unlocked"):
        return True
    if user.get("izuru_via_pride"):
        pid = _active_pact_partner(data, str(uid))
        ok = bool(pid and get_user(data, int(pid)).get("despair_role"))
    else:
        ok = any(u.get("chiaki_dead") for u in data.get("users", {}).values())
    if ok:
        user["izuru_mastery_unlocked"] = True
        user["izuru_mastery_locked"] = False
    return ok

def _fmt_min(m: int) -> str:
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} hour{'s' if h > 1 else ''}" + (f" {r} min" if r else "")

def _stop_time(data: dict) -> bool:
    return bool(data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0))

def _check_target(ctx, data, user, target) -> Optional[str]:
    if target is None:
        return "You need to @mention a target."
    if target.id == ctx.author.id:
        return "You cannot target yourself with that."
    if target.bot:
        return "Bots cannot be targeted."
    t_user = get_user(data, target.id)
    if t_user.get("fallen"):
        return "That target is fallen. Show mercy."
    if t_user.get("hp", get_role_stats(target)[0]) <= 0:
        return "That target is already defeated."
    if user.get("hp", get_role_stats(ctx.author)[0]) <= 0:
        return "You are too weak to fight. `!heal` first."
    if _stop_time(data):
        return "⏸️ Time is frozen."
    return None


# ── Roster / info ───────────────────────────────────────────────────
@bot.command()
async def characters(ctx):
    """List all Danganronpa characters with their Hope and Despair versions."""
    embed = discord.Embed(
        title="🎭 Danganronpa Character Roles",
        description=("Claim a character to become their **Ultimate** talent. Every character has a "
                     "**Hope** version and a **Despair** version, each with its own attack + special.\n"
                     "Despair unlocks after claiming Hope; once unlocked, swap freely with `!alignment`."),
        color=discord.Color.purple(),
    )
    for key, char in CHARACTERS.items():
        kit = KITS.get(key, {})
        hope_names = " / ".join(a["name"] for a in kit.get("hope", []))
        if char["despair_role"]:
            despair_names = " / ".join(a["name"] for a in kit.get("despair", []))
            despair_text = f"\n🔴 **Despair:** `{char['despair_role']}` — {despair_names}"
        else:
            despair_text = "\n🌟 **Pure Hope** (no despair version)"
        embed.add_field(
            name=f"{char['name']} — {char['talent']}  (`{key}`)",
            value=f"✨ **Hope:** `{char['hope_role']}` — {hope_names}{despair_text}\n"
                  f"HP/ATK/DEF: {char['stats'][0]}/{char['stats'][1]}/{char['stats'][2]}",
            inline=False,
        )
    embed.add_field(
        name="💀 Special Roles",
        value=(f"`{IZURU_DESPAIR_ROLE}` — all despair talents + passives, `!boredom`, `!analyze`\n"
               f"`{IZURU_HOPE_ROLE}` — all hope talents (mastery-gated), `!hope_overdrive`, `!analyze`\n"
               f"`{RESERVE_COURSE_ROLE}` — default starting role"),
        inline=False,
    )
    embed.add_field(
        name="Commands",
        value=("`!claim_hope <character>` · `!claim_despair <character>` · `!alignment [hope|despair]`\n"
               "`!talent @user` · `!special @user` · `!talents [character]` · `!mycharacter`\n"
               "Nagito: `!luck_switch` · `!fortune @user`\n"
               "Izuru: `!talent <character> @user` · `!special <character> @user`"),
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command()
async def talents(ctx, character: str = None):
    """Show a character's abilities. Usage: !talents [character]"""
    data = load_data()
    user = get_user(data, ctx.author.id)
    key = (character or user.get("character") or "").lower().strip()
    save_data(data)
    if key not in CHARACTERS:
        await ctx.send("Name a character: `!talents nagito` (see `!characters`).", delete_after=8)
        return
    char, kit = CHARACTERS[key], KITS.get(key, {})
    e = discord.Embed(title=f"🎭 {char['name']} — Abilities", color=char["color_hope"])
    for ver, label in (("hope", "✨ Hope"), ("despair", "🔴 Despair")):
        specs = kit.get(ver, [])
        if not specs:
            continue
        txt = "\n".join(
            f"**{'`!talent`' if i == 0 else '`!special`'} — {s['name']}** · CD {s['cd']//60}m\n*{s['flavor']}*"
            for i, s in enumerate(specs))
        e.add_field(name=label, value=txt, inline=False)
    if key == "nagito":
        e.add_field(name="🍀 Signature (both versions)",
                    value=("**`!luck_switch`** — \"My luck is so bad...\" **99%** chance every hit misses for "
                           f"{LUCK_SWITCH_DURATION//60} min.\n"
                           "**`!fortune @user`** — apply **any** effect with a duration picker "
                           "(up to **1 hour**, **2 hours** if they tried to attack you)."),
                    inline=False)
    await ctx.send(embed=e)


@bot.command()
async def claim_hope(ctx, character: str = None):
    """Claim a character's Hope version. Usage: !claim_hope nagito"""
    if character is None:
        await ctx.send(f"Usage: `!claim_hope <character>` — valid: `{', '.join(CHARACTERS)}`", delete_after=8)
        return
    character = character.lower().strip()
    data = load_data()
    user = get_user(data, ctx.author.id)

    if character not in CHARACTERS:
        await ctx.send(f"Unknown character. Valid: `{', '.join(CHARACTERS)}`", delete_after=8)
        save_data(data); return
    if user.get("fallen"):
        await ctx.send("You are fallen from grace. Redeem yourself first.", delete_after=6)
        save_data(data); return
    if _is_izuru(ctx.author):
        await ctx.send("You are already Izuru Kamakura. You hold every talent.", delete_after=6)
        save_data(data); return
    if user.get("character"):
        await ctx.send("You already have a character. Use `!claim_despair` / `!alignment` for their other version.", delete_after=8)
        save_data(data); return

    char = CHARACTERS[character]
    hp, atk, df = char["stats"]
    user.update(character=character, character_hope=True, alignment="hope", reserve_course=False,
                hp=hp, max_hp=hp, attack=atk, defense=df)
    save_data(data)

    ok = await _give_role(ctx.author, char["hope_role"], char["color_hope"])
    await remove_role(ctx.author, RESERVE_COURSE_ROLE)
    e = discord.Embed(
        title="✨ Character Claimed",
        description=(f"{ctx.author.mention} has become **{char['name']}**!\n\nTalent: **{char['talent']}**\n"
                     f"Stats: {hp} HP / {atk} ATK / {df} DEF\n"
                     f"Abilities: `!talent` ({KITS[character]['hope'][0]['name']}) · "
                     f"`!special` ({KITS[character]['hope'][1]['name']})"
                     + ("" if ok else "\n\n⚠️ I couldn't assign the role — give me **Manage Roles** (my role must sit above it) or run `!setup`.")),
        color=char["color_hope"],
    )
    await ctx.send(embed=e)


@bot.command()
async def claim_despair(ctx, character: str = None):
    """Unlock and switch to a character's Despair version (needs their Hope version first)."""
    if character is None:
        await ctx.send("Usage: `!claim_despair <character>`", delete_after=8)
        return
    character = character.lower().strip()
    data = load_data()
    user = get_user(data, ctx.author.id)

    if character not in CHARACTERS:
        await ctx.send(f"Unknown character. Valid: `{', '.join(CHARACTERS)}`", delete_after=8)
        save_data(data); return
    char = CHARACTERS[character]
    if not char["despair_role"]:
        await ctx.send(f"{char['name']} has no despair version. They are pure hope.", delete_after=6)
        save_data(data); return
    if user.get("character") != character:
        await ctx.send("You must first claim the Hope version with `!claim_hope`.", delete_after=6)
        save_data(data); return
    if user.get("character_despair"):
        await ctx.send("You already unlocked the Despair version. Use `!alignment despair` to switch to it.", delete_after=8)
        save_data(data); return

    user["character_despair"] = True
    save_data(data)
    await _switch_alignment(ctx.author, data, user, "despair", free=True)
    await ctx.send(embed=discord.Embed(
        title="🔴 Despair Unleashed",
        description=(f"{ctx.author.mention} has fallen into **{char['despair_role']}**!\n\n"
                     "The talent remains... but the soul has twisted.\n"
                     f"Abilities: `!talent` ({KITS[character]['despair'][0]['name']}) · "
                     f"`!special` ({KITS[character]['despair'][1]['name']})\n"
                     "Swap back any time with `!alignment hope`."),
        color=char["color_despair"],
    ))


async def _switch_alignment(member: discord.Member, data: dict, user: dict, to: str, free: bool = False):
    char = CHARACTERS[user["character"]]
    old_stats = get_role_stats(member)
    ratio = max(0.05, min(1.0, user.get("hp", old_stats[0]) / max(1, old_stats[0])))
    if to == "despair":
        await remove_role(member, char["hope_role"])
        await _give_role(member, char["despair_role"], char["color_despair"])
        hp, atk, df = ROLE_BASE_STATS[char["despair_role"]]
    else:
        await remove_role(member, char["despair_role"])
        await _give_role(member, char["hope_role"], char["color_hope"])
        hp, atk, df = ROLE_BASE_STATS[char["hope_role"]]
    user.update(alignment=to, max_hp=hp, attack=atk, defense=df, hp=max(1, int(hp * ratio)))
    if not free:
        user.setdefault("dr_cds", {})["alignment"] = now_ts() + ALIGNMENT_SWITCH_CD
    save_data(data)


@bot.command()
async def alignment(ctx, side: str = None):
    """Swap between your character's Hope and Despair versions. Usage: !alignment [hope|despair]"""
    data = load_data()
    user = get_user(data, ctx.author.id)
    ck = user.get("character")
    if not ck:
        await ctx.send("You have no character. Use `!claim_hope`.", delete_after=6)
        save_data(data); return
    cur = user.get("alignment") or "hope"
    if side is None:
        await ctx.send(f"Current alignment: **{cur.title()}**. Use `!alignment hope` or `!alignment despair`.", delete_after=10)
        save_data(data); return
    side = side.lower().strip()
    if side not in ("hope", "despair"):
        await ctx.send("Choose `hope` or `despair`.", delete_after=6)
        save_data(data); return
    if side == "despair" and not user.get("character_despair"):
        await ctx.send("Despair isn't unlocked yet — use `!claim_despair`." if CHARACTERS[ck]["despair_role"]
                       else f"{CHARACTERS[ck]['name']} is pure hope.", delete_after=8)
        save_data(data); return
    if side == cur:
        await ctx.send(f"You are already **{cur.title()}**.", delete_after=6)
        save_data(data); return
    cd = user.get("dr_cds", {}).get("alignment", 0)
    if now_ts() < cd:
        await ctx.send(f"You can swap again in {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    await _switch_alignment(ctx.author, data, user, side)
    char = CHARACTERS[ck]
    await ctx.send(embed=discord.Embed(
        title=("✨ Hope Reclaimed" if side == "hope" else "🔴 Despair Embraced"),
        description=f"{ctx.author.mention} is now **{char['hope_role'] if side == 'hope' else char['despair_role']}**.",
        color=char["color_hope"] if side == "hope" else char["color_despair"],
    ))


@bot.command()
async def mycharacter(ctx):
    """Show your current character, alignment, stats and status effects."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    izuru = _is_izuru(ctx.author)
    stats = get_role_stats(ctx.author)
    hp = user.get("hp", stats[0])

    if izuru:
        mastery = _izuru_mastery(data, user, ctx.author.id) if izuru == "hope" else True
        title, color = ("Izuru Kamakura — Ultimate " + izuru.title()), discord.Color.from_rgb(0, 160, 200) if izuru == "hope" else discord.Color.from_rgb(80, 0, 0)
        status = f"{'✨ Hope' if izuru == 'hope' else '🔴 Despair'}" + ("" if izuru == "despair" else (" · 💎 Mastery unlocked" if mastery else " · 🔒 Mastery locked"))
        talent_name = "All talents"
    else:
        ck = user.get("character")
        if not ck:
            await ctx.send("You have no character. Use `!characters` to see options and `!claim_hope` to claim one.", delete_after=8)
            save_data(data); return
        char = CHARACTERS[ck]
        title, color, talent_name = char["name"], char["color_hope"], char["talent"]
        al = user.get("alignment") or "hope"
        status = "✨ Hope" if al == "hope" else "🔴 Despair"
        if al == "despair":
            color = char["color_despair"]
        status += " (despair unlocked)" if user.get("character_despair") and al == "hope" else ""
    save_data(data)

    e = discord.Embed(title=f"🎭 {title}", color=color)
    e.add_field(name="Talent", value=talent_name, inline=True)
    e.add_field(name="Status", value=status, inline=True)
    e.add_field(name="HP", value=f"{hp}/{stats[0]}", inline=True)
    e.add_field(name="Attack", value=stats[1], inline=True)
    e.add_field(name="Defense", value=stats[2], inline=True)
    e.add_field(name="Kills / Deaths", value=f"{user.get('pvp_kills', 0)} / {user.get('pvp_deaths', 0)}", inline=True)
    e.add_field(name="Corruption", value=user.get("corruption", 0), inline=True)
    e.add_field(name="Hope Points", value=user.get("hope_points", 0), inline=True)
    e.add_field(name="Despair Points", value=user.get("despair_points", 0), inline=True)
    fx = _effects_text(user)
    if _luck_active(user):
        fx += f"\n🍀 **Luck Switch** — ends <t:{int(user['luck_until'])}:R>"
    if fx:
        e.add_field(name="Active Effects", value=fx, inline=False)
    await ctx.send(embed=e)


# ── Talent / Special (works for every character AND Izuru) ──────────
async def _use_kit(ctx, args: str, idx: int):
    data = load_data()
    user = get_user(data, ctx.author.id)
    err = _dr_gate(user)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return

    target = next((m for m in ctx.message.mentions if m.id != ctx.me.id), None) if ctx.message.mentions else None
    tokens = [t.lower() for t in args.split() if not t.startswith("<@")]
    arg_key = tokens[0] if tokens else None

    iz = _is_izuru(ctx.author)
    power = 1.0
    if iz:
        if arg_key not in CHARACTERS:
            await ctx.send(f"As Izuru you hold every talent — name one: `!{'talent' if idx == 0 else 'special'} <character> @user`.\n"
                           f"Characters: `{', '.join(CHARACTERS)}`", delete_after=10)
            save_data(data); return
        key = arg_key
        version = "despair" if (iz == "despair" and KITS[key]["despair"]) else "hope"
        if iz == "hope":
            if not _izuru_mastery(data, user, ctx.author.id):
                if idx == 1:
                    await ctx.send("🔒 Your **Mastery is locked** — specials are unavailable until it's unlocked.", delete_after=8)
                    save_data(data); return
                power = 0.6
    else:
        key = user.get("character")
        if not key:
            await ctx.send("You have no character. Use `!claim_hope <character>`.", delete_after=6)
            save_data(data); return
        version = user.get("alignment") or "hope"
        if version == "despair" and not KITS[key]["despair"]:
            version = "hope"

    spec = KITS[key][version][idx]
    err = _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    err = _dr_cd(user, f"{key}:{version}:{idx}", spec["cd"])
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    char = CHARACTERS[key]
    color = char["color_despair"] if version == "despair" else char["color_hope"]
    prefix = f"{'🔴' if version == 'despair' else '✨'} {char['name']}: "
    await _run_ability(ctx, data, spec, target, src=("talent" if idx == 0 else "special"),
                       power=power, title_prefix=prefix, color=color)


@bot.command()
async def talent(ctx, *, args: str = ""):
    """Use your character's attack talent. Izuru: !talent <character> @user"""
    await _use_kit(ctx, args, 0)

@bot.command()
async def special(ctx, *, args: str = ""):
    """Use your character's special ability. Izuru: !special <character> @user"""
    await _use_kit(ctx, args, 1)


# ── IZURU KAMAKURA ──────────────────────────────────────────────────
@bot.command()
async def izuru_despair(ctx):
    """Become Izuru Kamakura (Despair). All talents, despair passives."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("fallen"):
        await ctx.send("You are fallen from grace.", delete_after=6); save_data(data); return
    if _is_izuru(ctx.author):
        await ctx.send("You are already Izuru Kamakura.", delete_after=6); save_data(data); return
    if user.get("despair_role"):
        await ctx.send("You already hold a despair role.", delete_after=6); save_data(data); return
    if user.get("corruption", 0) < 50 and not user.get("sin_role"):
        await ctx.send("You need 50+ corruption or a sin role to become Izuru Kamakura (Despair).", delete_after=8)
        save_data(data); return

    await _dr_strip_char_roles(ctx.author)
    hp, atk, df = ROLE_BASE_STATS[IZURU_DESPAIR_ROLE]
    user.update(despair_role=True, character=None, character_hope=False, character_despair=False,
                alignment="despair", reserve_course=False, hp=hp, max_hp=hp, attack=atk, defense=df)
    save_data(data)

    ok = await _give_role(ctx.author, IZURU_DESPAIR_ROLE, discord.Color.from_rgb(80, 0, 0))
    await remove_role(ctx.author, RESERVE_COURSE_ROLE)
    await ctx.send(embed=discord.Embed(
        title="💀 Izuru Kamakura — Ultimate Despair",
        description=(
            f"{ctx.author.mention} has become **{IZURU_DESPAIR_ROLE}**!\n\nAll talents in the world are yours.\n\n"
            "**Passives**\n"
            "• **How boring...** — anyone who speaks gets **Shock + Panic** (5 min)\n"
            "• **Who are y-you?** — 30% to nullify a basic attack\n"
            "• **If it's ___, I have it too** — 40% to reflect a character talent/special\n"
            "• **What's the point?** — below 40% HP, 40% to nullify a hit and Shock the attacker\n"
            "• **Why would you...** — 50% to dismiss summoned attackers and Panic their owner\n\n"
            "**Abilities**\n"
            "• `!talent <character> @user` / `!special <character> @user` — any character's **despair** kit\n"
            "• `!boredom @user` — pierce strike + 10 min Shock (1h CD)\n"
            "• `!analyze @user` — read stats and expose them (**Fragile** 5 min)\n"
            "• All Ultimate Despair powers (`!tragic_event`, `!brainwash`, `!disaster`, `!summon_sister`...)"
            + ("" if ok else "\n\n⚠️ I couldn't assign the role — give me **Manage Roles** or run `!setup`.")),
        color=discord.Color.from_rgb(80, 0, 0),
    ))


@bot.command()
async def izuru_hope(ctx):
    """Attempt to become Izuru Kamakura (Ultimate Hope)."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("fallen"):
        await ctx.send("You are fallen from grace.", delete_after=6); save_data(data); return
    if _is_izuru(ctx.author):
        await ctx.send("You are already Izuru Kamakura.", delete_after=6); save_data(data); return
    if not user.get("reserve_course"):
        await ctx.send("You must be a **Reserve Course Student** (no character or despair role) to get life-changing surgery.", delete_after=8)
        save_data(data); return
    if user.get("corruption", 0) < IZURU_HOPE_CORRUPTION_REQUIRED:
        await ctx.send(f"You need **{IZURU_HOPE_CORRUPTION_REQUIRED}** corruption. You have {user.get('corruption', 0)}.", delete_after=8)
        save_data(data); return
    if user.get("hope_points", 0) < IZURU_HOPE_POINTS_REQUIRED:
        await ctx.send(f"You need **{IZURU_HOPE_POINTS_REQUIRED}** hope points. You have {user.get('hope_points', 0)}.", delete_after=8)
        save_data(data); return
    approvals = user.get("izuru_approved_by", [])
    if len(approvals) < IZURU_HOPE_APPROVALS_REQUIRED:
        await ctx.send(f"You need **{IZURU_HOPE_APPROVALS_REQUIRED}** approvals. You have {len(approvals)}.\n"
                       "Ask others to use `!approve_izuru @you`.", delete_after=10)
        save_data(data); return

    via_pride = any(
        get_user(data, int(uid)).get("izuru_approval_votes", {}).get(str(ctx.author.id), {}).get("via_pride")
        for uid in approvals)

    hp, atk, df = ROLE_BASE_STATS[IZURU_HOPE_ROLE]
    user.update(izuru_surgery_done=True, reserve_course=False, izuru_via_pride=via_pride,
                izuru_mastery_unlocked=False, izuru_mastery_locked=True, alignment="hope",
                hp=hp, max_hp=hp, attack=atk, defense=df)
    mastery = _izuru_mastery(data, user, ctx.author.id)
    save_data(data)

    ok = await _give_role(ctx.author, IZURU_HOPE_ROLE, discord.Color.from_rgb(0, 180, 220))
    await remove_role(ctx.author, RESERVE_COURSE_ROLE)

    if mastery:
        lock_txt = "💎 **Mastery unlocked.** All talents are yours at full power."
    elif via_pride:
        lock_txt = ("🔒 **Mastery locked** (obtained via Pride). Form a `!pact` with an Ultimate Despair to unlock it.\n"
                    "Until then your copied talents hit at **60%** and specials are sealed.")
    else:
        lock_txt = ("🔒 **Mastery locked.** The Ultimate Gamer (Chiaki) must fall to unlock your full potential — "
                    "but **you cannot kill her yourself.**\nUntil then your copied talents hit at **60%** and specials are sealed.")
    await ctx.send(embed=discord.Embed(
        title="✨ Izuru Kamakura — Ultimate Hope",
        description=(
            f"{ctx.author.mention} has undergone **life-changing surgery** and become the **Ultimate Hope**!\n\n{lock_txt}\n\n"
            "**Passives**\n"
            "• **Foresight** — 15% to evade any hit\n"
            "• **Calculated Resolve** — all damage taken reduced by 25%\n\n"
            "**Abilities**\n"
            "• `!talent <character> @user` / `!special <character> @user` — any character's **hope** kit\n"
            "• `!hope_overdrive @user` — *(mastery)* 2.4× pierce strike + 15 min Fragile (2h CD)\n"
            "• `!analyze @user` — read stats and expose them (**Fragile** 5 min)"
            + ("" if ok else "\n\n⚠️ I couldn't assign the role — give me **Manage Roles** or run `!setup`.")),
        color=discord.Color.from_rgb(0, 160, 200),
    ))


@bot.command()
async def approve_izuru(ctx, target: discord.Member = None):
    """Approve someone for Izuru Kamakura's life-changing surgery."""
    if target is None:
        await ctx.send("Usage: `!approve_izuru @user`", delete_after=5); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot approve yourself.", delete_after=5); return
    if target.bot:
        await ctx.send("Bots cannot undergo surgery.", delete_after=5); return
    data = load_data()
    voter = get_user(data, ctx.author.id)
    target_user = get_user(data, target.id)

    if voter.get("izuru_approval_votes", {}).get(str(target.id), {}).get("voted"):
        await ctx.send("You already approved this person.", delete_after=5); save_data(data); return

    pride = SINS["pride"]
    via_pride = any(r.name in (pride["final_role"], pride["evolved_role"]) for r in ctx.author.roles)
    voter.setdefault("izuru_approval_votes", {})[str(target.id)] = {"voted": True, "via_pride": via_pride}
    if str(ctx.author.id) not in target_user["izuru_approved_by"]:
        target_user["izuru_approved_by"].append(str(ctx.author.id))
    save_data(data)

    await ctx.send(embed=discord.Embed(
        title="💾 Approval Given",
        description=f"{ctx.author.mention} has approved {target.mention} for **life-changing surgery**.\n"
                    f"Approvals: {len(target_user['izuru_approved_by'])}/{IZURU_HOPE_APPROVALS_REQUIRED}",
        color=discord.Color.green(),
    ))


@bot.command()
async def boredom(ctx, target: discord.Member = None):
    """(Izuru — Despair) 'How boring...' pierce strike + Shock."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if _is_izuru(ctx.author) != "despair":
        await ctx.send("Only **Izuru Kamakura (Despair)** may use this.", delete_after=6); save_data(data); return
    err = _dr_gate(user) or _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    err = _dr_cd(user, "boredom", IZURU_BOREDOM["cd"])
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    await _run_ability(ctx, data, IZURU_BOREDOM, target, src="special",
                       title_prefix="💀 ", color=discord.Color.from_rgb(80, 0, 0))


@bot.command()
async def hope_overdrive(ctx, target: discord.Member = None):
    """(Izuru — Hope, mastery) Every talent at once."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if _is_izuru(ctx.author) != "hope":
        await ctx.send("Only **Izuru Kamakura (Hope)** may use this.", delete_after=6); save_data(data); return
    if not _izuru_mastery(data, user, ctx.author.id):
        await ctx.send("🔒 Your **Mastery is locked.**", delete_after=6); save_data(data); return
    err = _dr_gate(user) or _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    err = _dr_cd(user, "hope_overdrive", IZURU_OVERDRIVE["cd"])
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    await _run_ability(ctx, data, IZURU_OVERDRIVE, target, src="special",
                       title_prefix="✨ ", color=discord.Color.from_rgb(0, 200, 255))


@bot.command()
async def analyze(ctx, target: discord.Member = None):
    """(Izuru) Read a target completely — and leave them Fragile for 5 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_izuru(ctx.author):
        await ctx.send("Only **Izuru Kamakura** may use this.", delete_after=6); save_data(data); return
    err = _dr_gate(user)
    if err is None and (target is None or target.id == ctx.author.id or target.bot):
        err = "You need to @mention someone else."
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    err = _dr_cd(user, "analyze", 1200)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    t_user = get_user(data, target.id)
    st = get_role_stats(target)
    hp = t_user.get("hp", st[0])
    _apply_effect(t_user, "fragile", 300, by=ctx.author.id)
    al = _alignment(target, t_user)
    kit_line = ""
    if t_user.get("character") in CHARACTERS:
        kit_line = f"\n**Character:** {CHARACTERS[t_user['character']]['name']}"
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title=f"🧠 Analysis — {target.display_name}",
        description=(f"*Every move, every habit, every weakness. Predictable.*\n\n"
                     f"**HP:** {hp}/{st[0]} · **ATK:** {st[1]} · **DEF:** {st[2]}\n"
                     f"**Alignment:** {(al or 'none').title()} · **Corruption:** {t_user.get('corruption', 0)}"
                     f"{kit_line}\n**Active effects:** {_effects_text(t_user) or 'none'}\n\n"
                     f"💔 {target.mention} is left **Fragile** for 5 minutes."),
        color=discord.Color.from_rgb(0, 160, 200) if _is_izuru(ctx.author) == "hope" else discord.Color.from_rgb(80, 0, 0),
    ))


# ── NAGITO KOMAEDA — Luck Switch & Fortune ─────────────────────────
def _is_nagito(member: discord.Member, user: dict) -> bool:
    return user.get("character") == "nagito" or bool(_is_izuru(member))

@bot.command()
async def luck_switch(ctx):
    """(Nagito) Flip the switch: 'My luck is so bad...' — 99% chance every hit misses. Toggle."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_nagito(ctx.author, user):
        await ctx.send("Only **Nagito Komaeda** (or Izuru) may flip the Luck Switch.", delete_after=6)
        save_data(data); return
    if user.get("fallen"):
        await ctx.send("You are fallen from grace.", delete_after=6); save_data(data); return

    if _luck_active(user):
        user["luck_until"] = None
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title="🍀 Luck Switch — OFF",
            description=f"*{ctx.author.display_name}'s luck settles back to normal... for now.*",
            color=discord.Color.from_rgb(0, 200, 100)))
        return

    err = _dr_cd(user, "luck_switch", LUCK_SWITCH_CD)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    user["luck_until"] = now_ts() + LUCK_SWITCH_DURATION
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🍀 Luck Switch — ON",
        description=(f"**\"My luck is so bad...\"**\n\n"
                     f"*Ahaha... something terrible is bound to happen — just not to {ctx.author.display_name}.*\n\n"
                     f"For **{LUCK_SWITCH_DURATION // 60} minutes** every hit against {ctx.author.mention} has a "
                     f"**99% chance to miss**.\nEnds <t:{int(user['luck_until'])}:R> · use `!luck_switch` again to flip it off early."),
        color=discord.Color.from_rgb(0, 200, 100)))


class FortuneMinutesModal(discord.ui.Modal, title="Custom duration"):
    minutes_input = discord.ui.TextInput(label="Minutes", placeholder="e.g. 45", min_length=1, max_length=3)

    def __init__(self, view: "FortuneView"):
        super().__init__()
        self.fview = view
        self.minutes_input.label = f"Minutes (1 – {view.max_min})"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            m = int(str(self.minutes_input.value).strip())
        except ValueError:
            await interaction.response.send_message("Enter a whole number of minutes.", ephemeral=True)
            return
        self.fview.minutes = max(1, min(self.fview.max_min, m))
        for opt in self.fview.dur_select.options:
            opt.default = (opt.value == str(self.fview.minutes))
        await interaction.response.edit_message(embed=self.fview.build_embed(), view=self.fview)


class FortuneView(discord.ui.View):
    """Effect dropdown + duration dropdown (the 'scroll bar') + Custom / Cast / Cancel."""

    def __init__(self, author: discord.Member, target: discord.Member, max_min: int, grudge: bool):
        super().__init__(timeout=180)
        self.author, self.target, self.max_min, self.grudge = author, target, max_min, grudge
        self.effect: Optional[str] = None
        self.minutes = min(10, max_min)
        self.finished = False

        self.effect_select = discord.ui.Select(
            placeholder="1️⃣  Choose ANY effect…",
            options=[discord.SelectOption(label=f"{emo} {nm}", value=key, description=desc[:100])
                     for key, (emo, nm, desc, _pos) in DR_EFFECTS.items()],
        )
        self.effect_select.callback = self._on_effect
        self.add_item(self.effect_select)

        steps = [m for m in (1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 75, 90, 105, 120) if m <= max_min]
        self.dur_select = discord.ui.Select(
            placeholder="2️⃣  Slide the duration…",
            options=[discord.SelectOption(label=_fmt_min(m), value=str(m), default=(m == self.minutes)) for m in steps],
        )
        self.dur_select.callback = self._on_duration
        self.add_item(self.dur_select)

    def build_embed(self) -> discord.Embed:
        eff = DR_EFFECTS.get(self.effect)
        e = discord.Embed(
            title="🍀 Ultimate Luck — Fortune",
            description=(f"*Ahaha... whatever happens to {self.target.display_name} is just luck.*\n\n"
                         f"**Target:** {self.target.mention}\n"
                         f"**Effect:** {f'{eff[0]} {eff[1]} — {eff[2]}' if eff else '*not chosen*'}\n"
                         f"**Duration:** {_fmt_min(self.minutes)}  *(max {_fmt_min(self.max_min)})*"
                         + ("\n\n⚠️ They tried to attack you — your limit is raised to **2 hours**." if self.grudge else "")),
            color=discord.Color.from_rgb(0, 200, 100))
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This isn't your luck to spend.", ephemeral=True)
            return False
        return True

    async def _on_effect(self, interaction: discord.Interaction):
        self.effect = self.effect_select.values[0]
        for opt in self.effect_select.options:
            opt.default = (opt.value == self.effect)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_duration(self, interaction: discord.Interaction):
        self.minutes = int(self.dur_select.values[0])
        for opt in self.dur_select.options:
            opt.default = (opt.value == str(self.minutes))
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Custom minutes", style=discord.ButtonStyle.secondary, emoji="⌨️", row=2)
    async def custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FortuneMinutesModal(self))

    @discord.ui.button(label="Cast Fortune", style=discord.ButtonStyle.success, emoji="🍀", row=2)
    async def cast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.effect:
            await interaction.response.send_message("Pick an effect first.", ephemeral=True)
            return
        data = load_data()
        user = get_user(data, self.author.id)
        err = _dr_gate(user)
        if err is None:
            err = _dr_cd(user, "fortune", FORTUNE_CD)
        if err:
            save_data(data)
            await interaction.response.send_message(err, ephemeral=True)
            return
        t_user = get_user(data, self.target.id)
        t_stats = get_role_stats(self.target)
        t_user.setdefault("hp", t_stats[0])
        t_user.setdefault("max_hp", t_stats[0])
        _apply_effect(t_user, self.effect, self.minutes * 60, by=self.author.id)
        save_data(data)
        self.finished = True
        self.stop()
        emo, nm, desc, _ = DR_EFFECTS[self.effect]
        await interaction.response.edit_message(view=None, embed=discord.Embed(
            title="🍀 Fortune Cast",
            description=(f"{self.author.mention} spins the wheel of luck...\n\n"
                         f"{emo} {self.target.mention} is afflicted with **{nm}** for **{_fmt_min(self.minutes)}**.\n"
                         f"*{desc}*"
                         + ("\n\n😈 *They tried to hurt him. His luck remembers.* (2-hour limit)" if self.grudge else "")),
            color=discord.Color.from_rgb(0, 200, 100)))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        self.stop()
        await interaction.response.edit_message(content="Fortune cancelled.", embed=None, view=None)


@bot.command()
async def fortune(ctx, target: discord.Member = None):
    """(Nagito) Apply ANY effect to anybody — choose effect + duration (1h max, 2h if they attacked you)."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_nagito(ctx.author, user):
        await ctx.send("Only **Nagito Komaeda** (or Izuru) may tempt fate like this.", delete_after=6)
        save_data(data); return
    if target is None or target.bot:
        await ctx.send("Usage: `!fortune @user`", delete_after=6); save_data(data); return
    err = _dr_gate(user)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    cd = user.get("dr_cds", {}).get("fortune", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"**fortune** is on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    seen = data.get("nagito_aggressors", {}).get(str(ctx.author.id), {}).get(str(target.id), 0) or 0
    grudge = (now_ts() - seen) < FORTUNE_GRUDGE_WINDOW and seen > 0
    max_min = FORTUNE_GRUDGE_MAX_MIN if grudge else FORTUNE_NORMAL_MAX_MIN
    save_data(data)

    view = FortuneView(ctx.author, target, max_min, grudge)
    await ctx.send(embed=view.build_embed(), view=view)


# ── THE HOPEFUL — attack / special moves (replaces rally & beacon) ──
async def _hopeful_cast(ctx, target, key: str):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "hope"):
        await ctx.send("Only **The Hopeful** may use this.", delete_after=6); save_data(data); return
    err = _dr_gate(user) or _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    spec = HOPEFUL_KIT[key]
    err = _dr_cd(user, key, spec["cd"])
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    await _run_ability(ctx, data, spec, target, src="special", title_prefix="💫 ",
                       color=discord.Color.from_rgb(100, 180, 255))

@bot.command()
async def radiant_strike(ctx, target: discord.Member = None):
    """(Hope) Pierce strike with a chance to Shock. Replaces !rally."""
    await _hopeful_cast(ctx, target, "radiant_strike")

@bot.command()
async def hope_barrage(ctx, target: discord.Member = None):
    """(Hope) Three-hit barrage that leaves you Empowered. Replaces !beacon."""
    await _hopeful_cast(ctx, target, "hope_barrage")

@bot.command()
async def inspire_strike(ctx, target: discord.Member = None):
    """(Hope) Relentless optimism attack — hits and Slows the target for 20 min."""
    await _hopeful_cast(ctx, target, "inspire_strike")

@bot.command()
async def despair_wave(ctx, target: discord.Member = None):
    """(Hope) Crash a wave of despair — hits 1.5x harder on an already-afflicted target, else inflicts Panic."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "hope"):
        await ctx.send("Only **The Hopeful** may weaponize despair.", delete_after=6); save_data(data); return
    err = _dr_gate(user) or _check_target(ctx, data, user, target)
    if err:
        await ctx.send(err, delete_after=6); save_data(data); return
    err = _dr_cd(user, "despair_wave", 3600)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    t_user = get_user(data, target.id)
    afflicted = any(_has_effect(t_user, n) for n, v in DR_EFFECTS.items() if not v[3])
    spec = A("Despair Wave",
             "A wave of hopelessness crashes into an already-weakened foe." if afflicted else "A wave of hopelessness rolls over them.",
             mult=1.5 if afflicted else 1.0, effect=None if afflicted else ("panic", 10, 1.0))
    await _run_ability(ctx, data, spec, target, src="special", title_prefix="💫 ",
                       color=discord.Color.from_rgb(100, 180, 255))


# ── Passive hooks & background tick ─────────────────────────────────
class TragicChoiceView(discord.ui.View):
    def __init__(self, speaker: discord.Member, holder_id: str):
        super().__init__(timeout=60)
        self.speaker, self.holder_id = speaker, holder_id
        self.message: Optional[discord.Message] = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.speaker.id:
            await interaction.response.send_message("This choice isn't yours.", ephemeral=True)
            return False
        return True

    def _resolve(self, choice: str) -> str:
        data = load_data()
        s = get_user(data, self.speaker.id)
        h = get_user(data, int(self.holder_id))
        if choice == "hope":
            _apply_effect(s, "shock", 600, by=self.holder_id)
            s["hope_points"] = s.get("hope_points", 0) + 1
            txt = f"✨ **Hope.** {self.speaker.mention} clings to it, but is left **Shocked** (10 min) and gains a Hope point."
        else:
            _apply_effect(s, "panic", 600, by=self.holder_id)
            _apply_effect(s, "fragile", 600, by=self.holder_id)
            s["despair_points"] = s.get("despair_points", 0) + 1
            h["despair_points"] = h.get("despair_points", 0) + 1
            txt = f"💀 **Despair.** {self.speaker.mention} breaks — **Panic + Fragile** (10 min). Despair points to both."
        save_data(data)
        return txt

    async def _finish(self, interaction, choice):
        if self.resolved:
            return
        self.resolved = True
        self.stop()
        await interaction.response.edit_message(view=None, embed=discord.Embed(
            title="💀 The Tragic Event", description=self._resolve(choice), color=discord.Color.from_rgb(80, 0, 0)))

    @discord.ui.button(label="Hope", style=discord.ButtonStyle.primary, emoji="✨")
    async def hope_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "hope")

    @discord.ui.button(label="Despair", style=discord.ButtonStyle.danger, emoji="💀")
    async def despair_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "despair")

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        txt = self._resolve("despair")
        if self.message:
            try:
                await self.message.edit(view=None, embed=discord.Embed(
                    title="💀 The Tragic Event — No Answer",
                    description="Silence is its own answer.\n" + txt, color=discord.Color.from_rgb(80, 0, 0)))
            except Exception:
                pass


async def _dr_message_passives(message: discord.Message, data: dict, is_cmd: bool):
    """Izuru Despair 'How boring...' and the Tragic Event choice. Called from on_message."""
    guild = message.guild
    if not guild or is_cmd or message.author.bot:
        return
    speaker = message.author
    s_user = get_user(data, speaker.id)

    # ── Tragic Event: the next person to speak faces the choice ──
    for uid, u in data.get("users", {}).items():
        if u.get("tragic_event_active") and int(uid) != speaker.id:
            u["tragic_event_active"] = False
            save_data(data)
            view = TragicChoiceView(speaker, uid)
            view.message = await message.channel.send(
                content=speaker.mention,
                embed=discord.Embed(
                    title="💀 The Biggest, Most Atrocious, Most Tragic Event in History",
                    description=f"{speaker.mention}, the world just ended. Do you cling to **Hope** — or give in to **Despair**?\n"
                                "*(60 seconds. Silence counts as despair.)*",
                    color=discord.Color.from_rgb(80, 0, 0)),
                view=view)
            break

    # ── Izuru Despair: How boring... ──
    role = discord.utils.get(guild.roles, name=IZURU_DESPAIR_ROLE)
    if role and role.members and not _is_izuru(speaker):
        if not (_has_effect(s_user, "shock") and _has_effect(s_user, "panic")):
            _apply_effect(s_user, "shock", 300, by=role.members[0].id)
            _apply_effect(s_user, "panic", 300, by=role.members[0].id)
            try:
                await message.channel.send(
                    f"😱 **{speaker.display_name}** feels a wave of despair... *\"How boring...\"* "
                    f"**Shock** and **Panic** for 5 minutes!", delete_after=8)
            except Exception:
                pass


@tasks.loop(minutes=1)
async def dr_effect_tick():
    """Poison / Regeneration ticks and effect cleanup."""
    data = load_data()
    changed = False
    for uid, u in data.get("users", {}).items():
        fx = u.get("effects")
        if not fx:
            continue
        mx = u.get("max_hp") or u.get("hp") or 100
        for name in list(fx.keys()):
            if now_ts() >= fx[name].get("until", 0):
                fx.pop(name, None)
                changed = True
        if "poison" in fx and "hp" in u:
            u["hp"] = max(1, u["hp"] - 3); changed = True
        if "regen" in fx and "hp" in u:
            u["hp"] = min(mx, u["hp"] + 3); changed = True
    if changed:
        save_data(data)

@dr_effect_tick.before_loop
async def _before_dr_tick():
    await bot.wait_until_ready()



@bot.command()
@commands.has_permissions(administrator=True)
async def grant_despair(ctx, member: discord.Member):
    """Admin: crown a member as The Ultimate Despair (bypasses the Friday window)."""
    data = load_data()
    if data.get("despair_active"):
        await ctx.send("Someone already holds the Ultimate Despair. Use `!reset_user` / `!force_fall` on them first.", delete_after=10)
        save_data(data); return
    await _grant_despair(member, data)
    save_data(data)
    await ctx.send(f"✅ **{DESPAIR_ROLE}** granted to {member.mention}.")

# ───────────────────────────────────────────────────────────────────
# COMMAND: !bounty @user
# ───────────────────────────────────────────────────────────────────

BOUNTY_DURATION_HOURS = 72   # How long a bounty stays active

@bot.command()
async def bounty(ctx, target: discord.Member = None):
    """Place a bounty on a sin holder. If they fall within 72h you lose 1 corruption."""
    data = load_data()

    # ── No target: list active bounties ──
    if target is None:
        bounties = data.get("bounties", {})
        embed = discord.Embed(
            title="🎯 Active Bounties",
            description=(
                "When a bounty target falls from grace, everyone who placed a bounty on them "
                "is **cleansed of 1 corruption point**.\n\n"
                "Use `!bounty @user` to place a bounty on a sin holder."
            ),
            color=discord.Color.gold(),
        )
        any_bounty = False
        for target_id, blist in bounties.items():
            active = [b for b in blist if now_ts() <= b.get("expires", 0)]
            if not active:
                continue
            t_member = ctx.guild.get_member(int(target_id))
            t_name   = t_member.display_name if t_member else f"Unknown ({target_id})"
            placers  = []
            for b in active:
                p = ctx.guild.get_member(int(b["placer_id"]))
                placers.append(p.display_name if p else "Unknown")
            sin_held = None
            for s, holder in data["claimed_sins"].items():
                if holder == target_id:
                    sin_held = s
                    break
            embed.add_field(
                name=f"🎯 {t_name}" + (f" — {sin_held.capitalize()}" if sin_held else ""),
                value=(
                    f"Placed by: **{', '.join(placers)}**\n"
                    f"Expires: {ts_fmt(active[0]['expires'])}"
                ),
                inline=False,
            )
            any_bounty = True
        if not any_bounty:
            embed.description += "\n\n*No bounties are currently active.*"
        save_data(data)
        await ctx.send(embed=embed)
        return

    # ── Placing a bounty ──
    if target.id == ctx.author.id:
        await ctx.send("You cannot place a bounty on yourself.", delete_after=5)
        return

    target_id = str(target.id)
    user      = get_user(data, ctx.author.id)

    # Must not be fallen
    if user.get("fallen"):
        await ctx.send("You have fallen from grace and cannot place bounties.", delete_after=8)
        save_data(data)
        return

    # Target must currently hold a sin
    sin_held = None
    for s, holder in data["claimed_sins"].items():
        if holder == target_id:
            sin_held = s
            break
    if not sin_held:
        await ctx.send(
            f"**{target.display_name}** does not currently hold a sin. "
            "Bounties can only be placed on active sin holders.",
            delete_after=10,
        )
        save_data(data)
        return

    # Check placer hasn't already placed a bounty on this target
    existing = data.setdefault("bounties", {}).get(target_id, [])
    placer_id_str = str(ctx.author.id)
    already = any(
        b["placer_id"] == placer_id_str and now_ts() <= b.get("expires", 0)
        for b in existing
    )
    if already:
        await ctx.send(
            f"You already have an active bounty on **{target.display_name}**.",
            delete_after=8,
        )
        save_data(data)
        return

    # Place the bounty
    expires = now_ts() + BOUNTY_DURATION_HOURS * 3600
    existing.append({
        "placer_id": placer_id_str,
        "ts":        now_ts(),
        "expires":   expires,
    })
    data["bounties"][target_id] = existing
    save_data(data)

    sd = SINS[sin_held]
    embed = discord.Embed(
        title="🎯 Bounty Placed",
        color=discord.Color.gold(),
        description=(
            f"{ctx.author.mention} has placed a bounty on **{target.display_name}** "
            f"— bearer of **{sd['final_role']}** ({sin_held.capitalize()}, Power {sd['power']}).\n\n"
            f"If **{target.display_name}** falls from grace within **{BOUNTY_DURATION_HOURS} hours**, "
            f"{ctx.author.mention} will be **cleansed of 1 corruption point**.\n\n"
            f"Bounty expires: {ts_fmt(expires)}"
        ),
    )
    embed.set_footer(text=f"Your current corruption: {user.get('corruption', 0)}")
    await ctx.send(embed=embed)

    # Quietly notify the target via DM (optional — they know someone is after them)
    try:
        await target.send(
            f"⚠️ A bounty has been placed on you. "
            f"Someone wants to see you fall from grace. Watch yourself."
        )
    except Exception:
        pass


@bot.command()
async def mybounties(ctx):
    """Show bounties placed on you and bounties you've placed."""
    data = load_data()
    uid  = str(ctx.author.id)

    # Bounties on the caller
    on_me = [
        b for b in data.get("bounties", {}).get(uid, [])
        if now_ts() <= b.get("expires", 0)
    ]
    # Bounties the caller placed
    by_me = []
    for target_id, blist in data.get("bounties", {}).items():
        for b in blist:
            if b.get("placer_id") == uid and now_ts() <= b.get("expires", 0):
                t = ctx.guild.get_member(int(target_id))
                by_me.append((t.display_name if t else target_id, b["expires"]))

    embed = discord.Embed(
        title=f"🎯 Bounty Status — {ctx.author.display_name}",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="Bounties on You",
        value=f"**{len(on_me)}** active bounty hunters are watching you." if on_me else "None.",
        inline=False,
    )
    if by_me:
        embed.add_field(
            name="Bounties You Placed",
            value="\n".join(f"• **{name}** — expires {ts_fmt(exp)}" for name, exp in by_me),
            inline=False,
        )
    else:
        embed.add_field(name="Bounties You Placed", value="None.", inline=False)

    save_data(data)
    await ctx.send(embed=embed)


# ───────────────────────────────────────────────────────────────────
# COMMANDS: Pact / Alliance System
# ───────────────────────────────────────────────────────────────────

def _get_pact(data: dict, user_id: str) -> Optional[dict]:
    return data.get("pacts", {}).get(user_id)

def _active_pact_partner(data: dict, user_id: str) -> Optional[str]:
    p = _get_pact(data, user_id)
    if p and p.get("status") == "active":
        return p.get("partner_id")
    return None

@bot.command()
async def pact(ctx, target: discord.Member = None):
    """Propose a pact to another sin holder, or view your current pact."""
    data = load_data()
    uid  = str(ctx.author.id)
    user = get_user(data, ctx.author.id)

    # ── No target: show current pact status ──
    if target is None:
        pact_entry = _get_pact(data, uid)
        if not pact_entry:
            await ctx.send(
                f"{ctx.author.mention} — you have no active pact.\n"
                "Use `!pact @user` to propose one to a sin holder.",
                delete_after=15,
            )
        else:
            partner = ctx.guild.get_member(int(pact_entry["partner_id"]))
            pname   = partner.display_name if partner else "Unknown"
            status  = pact_entry["status"]
            icon    = "🤝" if status == "active" else "⏳"
            embed   = discord.Embed(
                title=f"{icon} Your Pact",
                color=discord.Color.dark_gold(),
                description=(
                    f"Partner: **{pname}**\n"
                    f"Status: **{status.capitalize()}**\n\n"
                    + ("You share expose immunity (+3 🔍 required) and fall together if exposed.\n"
                       "Use `!break_pact` to dissolve it."
                       if status == "active"
                       else f"Waiting for **{pname}** to accept with `!accept_pact`.")
                ),
            )
            await ctx.send(embed=embed)
        save_data(data)
        return

    # ── Proposing a pact ──
    if target.id == ctx.author.id:
        await ctx.send("You cannot form a pact with yourself.", delete_after=5)
        return

    target_id = str(target.id)

    # Guard: must hold a sin
    if not user.get("sin_role"):
        await ctx.send("You must hold a sin role to form a pact.", delete_after=8)
        save_data(data)
        return

    # Guard: target must hold a sin
    target_user = get_user(data, target.id)
    if not target_user.get("sin_role"):
        await ctx.send(f"**{target.display_name}** does not hold a sin role.", delete_after=8)
        save_data(data)
        return

    # Guard: neither can be fallen
    if user.get("fallen") or target_user.get("fallen"):
        await ctx.send("Fallen members cannot form pacts.", delete_after=8)
        save_data(data)
        return

    # Guard: already in a pact
    if _get_pact(data, uid):
        await ctx.send("You already have a pact. Use `!break_pact` first.", delete_after=8)
        save_data(data)
        return
    if _get_pact(data, target_id):
        await ctx.send(f"**{target.display_name}** already has a pact.", delete_after=8)
        save_data(data)
        return

    # Create pending pact on both sides
    data.setdefault("pacts", {})[uid]       = {"partner_id": target_id, "status": "pending", "ts": now_ts()}
    data["pacts"][target_id]                = {"partner_id": uid,       "status": "pending", "ts": now_ts()}
    save_data(data)

    author_sin  = SINS[user.get("sin_role")]
    target_sin  = SINS[target_user.get("sin_role")]

    embed = discord.Embed(
        title="🤝 A Pact Has Been Proposed",
        color=discord.Color.dark_gold(),
        description=(
            f"{ctx.author.mention} (**{author_sin['final_role']}**) proposes a pact with "
            f"{target.mention} (**{target_sin['final_role']}**).\n\n"
            "**Pact benefits:**\n"
            f"• Expose threshold raised by **+{PACT_EXPOSE_BONUS}** 🔍 for both members\n"
            "• Partner is **DM alerted** when investigation begins\n"
            "• If one is exposed — **both fall**\n\n"
            f"{target.mention} — use `!accept_pact` to seal the pact, or ignore to decline."
        ),
    )
    embed.set_footer(text="Power shared. Risk shared. Fall shared.")
    await ctx.send(embed=embed)

    # DM the target
    try:
        await target.send(
            f"⚔️ **{ctx.author.display_name}** ({author_sin['final_role']}) has proposed a pact with you.\n\n"
            f"Use `!accept_pact` in the server to accept.\n"
            "**Warning:** if either of you is exposed during a Greed or Envy trial, you both fall from grace."
        )
    except Exception:
        pass


@bot.command()
async def accept_pact(ctx):
    """Accept a pending pact proposal."""
    data = load_data()
    uid  = str(ctx.author.id)

    pact_entry = _get_pact(data, uid)
    if not pact_entry or pact_entry.get("status") != "pending":
        await ctx.send("You have no pending pact to accept.", delete_after=8)
        save_data(data)
        return

    partner_id = pact_entry["partner_id"]
    partner    = ctx.guild.get_member(int(partner_id))

    # Activate both sides
    data["pacts"][uid]["status"]        = "active"
    data["pacts"][partner_id]["status"] = "active"
    save_data(data)

    user_sin    = get_user(data, ctx.author.id).get("sin_role", "unknown")
    partner_data = get_user(data, int(partner_id))
    partner_sin  = partner_data.get("sin_role", "unknown")

    embed = discord.Embed(
        title="⚔️ Pact Sealed",
        color=discord.Color.dark_gold(),
        description=(
            f"{ctx.author.mention} (**{SINS.get(user_sin, {}).get('final_role', user_sin)}**) "
            f"and {partner.mention if partner else partner_id} "
            f"(**{SINS.get(partner_sin, {}).get('final_role', partner_sin)}**) "
            "have formed an alliance.\n\n"
            f"🛡️ Expose threshold: **+{PACT_EXPOSE_BONUS}** 🔍 for both\n"
            f"📡 Investigation alerts sent at **{PACT_ALERT_AT}** 🔍\n"
            "💀 If one falls — both fall\n\n"
            "The pact holds until broken or shattered by grace."
        ),
    )
    embed.set_footer(text="United in sin. Divided in virtue.")

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=embed)


@bot.command()
async def break_pact(ctx):
    """Dissolve your current pact."""
    data = load_data()
    uid  = str(ctx.author.id)

    pact_entry = _get_pact(data, uid)
    if not pact_entry:
        await ctx.send("You have no active pact to break.", delete_after=8)
        save_data(data)
        return

    partner_id = pact_entry["partner_id"]
    partner    = ctx.guild.get_member(int(partner_id))

    data.get("pacts", {}).pop(uid,        None)
    data.get("pacts", {}).pop(partner_id, None)
    save_data(data)

    embed = discord.Embed(
        title="💔 Pact Broken",
        color=discord.Color.greyple(),
        description=(
            f"{ctx.author.mention} has severed the pact with "
            f"{partner.mention if partner else 'their former partner'}.\n\n"
            "Both members lose expose immunity and fall independence is restored.\n"
            "If one falls now, the other is unaffected."
        ),
    )
    await ctx.send(embed=embed)

    if partner:
        try:
            await partner.send(
                f"⚠️ **{ctx.author.display_name}** has broken your pact. "
                "You are no longer bound together. Your fates are now separate."
            )
        except Exception:
            pass


@bot.command()
async def pacts(ctx):
    """View all active pacts in the server."""
    data   = load_data()
    seen   = set()
    active = []

    for uid, pact_entry in data.get("pacts", {}).items():
        if pact_entry.get("status") != "active":
            continue
        pid = pact_entry.get("partner_id", "")
        key = tuple(sorted([uid, pid]))
        if key in seen:
            continue
        seen.add(key)
        m1 = ctx.guild.get_member(int(uid))
        m2 = ctx.guild.get_member(int(pid))
        u1 = data["users"].get(uid, {})
        u2 = data["users"].get(pid, {})
        s1 = u1.get("sin_role", "?")
        s2 = u2.get("sin_role", "?")
        active.append((m1, m2, s1, s2, pact_entry.get("ts", 0)))

    embed = discord.Embed(
        title="⚔️ Active Pacts",
        color=discord.Color.dark_gold(),
        description=(
            "All current sin alliances. Pact members share expose immunity and fall together."
            if active else "No pacts are currently active."
        ),
    )
    for m1, m2, s1, s2, ts in active:
        n1 = m1.display_name if m1 else "Unknown"
        n2 = m2.display_name if m2 else "Unknown"
        r1 = SINS.get(s1, {}).get("final_role", s1)
        r2 = SINS.get(s2, {}).get("final_role", s2)
        embed.add_field(
            name=f"🤝 {n1}  ×  {n2}",
            value=(
                f"{n1}: **{r1}** (Power {SINS.get(s1, {}).get('power', '?')})\n"
                f"{n2}: **{r2}** (Power {SINS.get(s2, {}).get('power', '?')})\n"
                f"Formed: <t:{int(ts)}:d>"
            ),
            inline=False,
        )
    await ctx.send(embed=embed)


# ───────────────────────────────────────────────────────────────────
# COMMAND: !randomtrial
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def randomtrial(ctx):
    data    = load_data()
    user    = get_user(data, ctx.author.id)
    avail   = [s for s in SINS if s not in data["claimed_sins"] and user["cooldowns"].get(s, 0) <= now_ts()]
    save_data(data)

    if not avail:
        await ctx.send("No sins are currently available for you. Check `!sinslist`.")
        return

    sin = random.choice(avail)
    sd  = SINS[sin]
    embed = discord.Embed(
        title=f"🎲 Random Trial — {sin.capitalize()}",
        description=sd["trial_desc"],
        color=discord.Color.dark_red(),
    )
    embed.add_field(name="Power", value=str(sd["power"]), inline=True)
    embed.add_field(name="Role",  value=sd["final_role"], inline=True)
    embed.set_footer(text=f'Use `!trial {sin}` to begin.')
    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !rankings
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def rankings(ctx):
    data = load_data()

    # ── Current Sin Holders ──
    sin_embed = discord.Embed(
        title="⚖️ Current Sin Holders",
        description="The souls who currently bear a sin.",
        color=discord.Color.dark_purple(),
    )
    ordered_sins = sorted(SINS.items(), key=lambda x: x[1]["power"], reverse=True)
    any_sin = False
    for sin_name, sd in ordered_sins:
        holder_id = data["claimed_sins"].get(sin_name)
        if holder_id:
            member = ctx.guild.get_member(int(holder_id))
            name   = member.display_name if member else f"Unknown ({holder_id})"
            udata  = data["users"].get(holder_id, {})
            corr   = udata.get("corruption", 0)
            evolved = "⚠️ Evolved" if corr >= 5 else ""
            sin_embed.add_field(
                name=f"{'★' * sd['power']}  {sin_name.capitalize()}  (Power {sd['power']})",
                value=f"**{name}** — {sd['final_role']} {evolved}",
                inline=False,
            )
            any_sin = True
    if not any_sin:
        sin_embed.description = "No sins are currently claimed."

    # ── Current Virtue Holders ──
    virtue_embed = discord.Embed(
        title="✨ Current Virtue Holders",
        description="Those who have transcended their sin.",
        color=discord.Color.blue(),
    )
    any_virtue = False
    for sin_name, v in sorted(VIRTUES.items(), key=lambda x: x[1]["power"], reverse=True):
        for uid, udata in data["users"].items():
            if sin_name in udata.get("completed_virtues", []) and udata.get("sin_role") == sin_name:
                member = ctx.guild.get_member(int(uid))
                name   = member.display_name if member else f"Unknown ({uid})"
                virtue_embed.add_field(
                    name=f"{'★' * v['power']}  {v['role']}  (Power {v['power']})",
                    value=f"**{name}** — {v['virtue']}",
                    inline=False,
                )
                any_virtue = True
    if not any_virtue:
        virtue_embed.description = "No virtues have been earned yet."

    # ── Corruption Leaderboard ──
    corrupt_entries = []
    for uid, udata in data["users"].items():
        corr = udata.get("corruption", 0)
        if corr > 0:
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"Unknown ({uid})"
            corrupt_entries.append((name, corr, udata))

    corrupt_entries.sort(key=lambda x: x[1], reverse=True)

    corrupt_embed = discord.Embed(
        title="☠️ Corruption Leaderboard",
        description="Permanent corruption accumulates with every failure. It never fades.",
        color=discord.Color.dark_red(),
    )
    if corrupt_entries:
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, corr, udata) in enumerate(corrupt_entries[:10]):
            prefix  = medals[i] if i < 3 else f"#{i+1}"
            evolved = " ⚠️ *Evolved*" if corr >= 5 else ""
            fallen  = " 💀 *Fallen*"  if udata.get("fallen") else ""
            sins_done = len(udata.get("completed_sins", []))
            corrupt_embed.add_field(
                name=f"{prefix}  {name}",
                value=f"Corruption: **{corr}** pts{evolved}{fallen} | Sins completed: {sins_done}",
                inline=False,
            )
    else:
        corrupt_embed.description = "No corruption recorded yet. The trials have not been failed."

    # ── Hall of Shame (most falls) ──
    # Track falls via corruption proxy: corruption ÷ avg_corruption_per_fall ≈ failures
    shame_entries = []
    for uid, udata in data["users"].items():
        corr  = udata.get("corruption", 0)
        falls = udata.get("total_falls", 0)
        if falls > 0 or corr > 0:
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"Unknown ({uid})"
            shame_entries.append((name, falls, corr))

    shame_entries.sort(key=lambda x: (x[1], x[2]), reverse=True)

    shame_embed = discord.Embed(
        title="💀 Hall of Shame",
        description="Those who have fallen the most.",
        color=discord.Color.from_rgb(60, 0, 0),
    )
    if shame_entries:
        for i, (name, falls, corr) in enumerate(shame_entries[:5]):
            shame_embed.add_field(
                name=f"#{i+1}  {name}",
                value=f"Falls: **{falls}** | Corruption: **{corr}**",
                inline=False,
            )
    else:
        shame_embed.description = "No one has fallen yet. The trials are still young."

    # ── Trials in Progress ──
    active_entries = []
    for uid, udata in data["users"].items():
        ts = udata.get("trial_sin")
        te = udata.get("trial_end", 0)
        if ts and te > now_ts():
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"Unknown ({uid})"
            active_entries.append((name, ts, te))

    active_embed = discord.Embed(
        title="⏳ Trials in Progress",
        description="Members currently being tested.",
        color=discord.Color.orange(),
    )
    if active_entries:
        for name, ts, te in active_entries:
            sd = SINS[ts]
            active_embed.add_field(
                name=f"{name}",
                value=f"Trial: **{ts.capitalize()}** (Power {sd['power']}) — expires {ts_fmt(te)}",
                inline=False,
            )
    else:
        active_embed.description = "No trials are currently active."

    await ctx.send(embed=sin_embed)
    await ctx.send(embed=virtue_embed)
    await ctx.send(embed=corrupt_embed)
    await ctx.send(embed=shame_embed)
    await ctx.send(embed=active_embed)


@bot.command()
async def rankings_sins(ctx):
    """Quick view: just sin holders."""
    data = load_data()
    embed = discord.Embed(
        title="⚖️ Sin Holders",
        color=discord.Color.dark_purple(),
    )
    ordered = sorted(SINS.items(), key=lambda x: x[1]["power"], reverse=True)
    any_sin = False
    for sin_name, sd in ordered:
        holder_id = data["claimed_sins"].get(sin_name)
        if holder_id:
            member = ctx.guild.get_member(int(holder_id))
            name   = member.display_name if member else "Unknown"
            embed.add_field(
                name=f"{'★' * sd['power']}  {sin_name.capitalize()}",
                value=f"**{name}** — *{sd['final_role']}*",
                inline=True,
            )
            any_sin = True
    if not any_sin:
        embed.description = "No sins are currently claimed."
    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !history [@user]
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def history(ctx, target: discord.Member = None):
    target = target or ctx.author
    data   = load_data()
    uid    = str(target.id)
    user   = data["users"].get(uid)

    if not user or not user.get("trial_log"):
        await ctx.send(
            f"**{target.display_name}** has no trial history yet.",
            delete_after=15,
        )
        return

    log = user["trial_log"]

    # ── Summary embed ──
    total_attempts = len([e for e in log if e["type"] == "trial"])
    total_passes   = len([e for e in log if e["type"] == "trial"  and e["outcome"] == "passed"])
    total_falls    = len([e for e in log if e["type"] == "fall"])
    total_virtues  = len([e for e in log if e["type"] == "virtue" and e["outcome"] == "passed"])

    # Per-sin breakdown
    sin_stats = {}
    for e in log:
        s = e.get("sin", "unknown")
        if s not in sin_stats:
            sin_stats[s] = {"attempts": 0, "passes": 0, "falls": 0}
        if e["type"] == "trial":
            sin_stats[s]["attempts"] += 1
            if e["outcome"] == "passed":
                sin_stats[s]["passes"] += 1
        elif e["type"] == "fall":
            sin_stats[s]["falls"] += 1

    # Corruption timeline (highest ever)
    peak_corruption = max((e.get("corruption_after", 0) for e in log), default=0)

    # Status indicators
    currently_fallen  = "💀 Currently fallen" if user.get("fallen") else ""
    evolved_warning   = "⚠️ Evolved difficulty active" if user.get("corruption", 0) >= 5 else ""

    summary = discord.Embed(
        title=f"📜 Trial History — {target.display_name}",
        color=discord.Color.dark_purple(),
    )
    summary.add_field(name="Total Attempts",    value=str(total_attempts),  inline=True)
    summary.add_field(name="Trials Passed",     value=str(total_passes),    inline=True)
    summary.add_field(name="Falls from Grace",  value=str(total_falls),     inline=True)
    summary.add_field(name="Virtues Earned",    value=str(total_virtues),   inline=True)
    summary.add_field(name="Current Corruption",value=str(user.get("corruption", 0)), inline=True)
    summary.add_field(name="Peak Corruption",   value=str(peak_corruption), inline=True)

    if currently_fallen or evolved_warning:
        summary.add_field(
            name="Status",
            value="\n".join(filter(None, [currently_fallen, evolved_warning])),
            inline=False,
        )

    # Pass rate bar
    if total_attempts:
        rate  = total_passes / total_attempts
        filled = int(rate * 10)
        bar   = "█" * filled + "░" * (10 - filled)
        summary.add_field(
            name="Pass Rate",
            value=f"`{bar}` {int(rate * 100)}%",
            inline=False,
        )

    # ── Per-sin breakdown embed ──
    breakdown = discord.Embed(
        title=f"⚔️ Sin Breakdown — {target.display_name}",
        description="Attempts, passes, and falls per sin.",
        color=discord.Color.dark_red(),
    )
    for sin_name in sorted(sin_stats, key=lambda s: SINS.get(s, {}).get("power", 0), reverse=True):
        st  = sin_stats[sin_name]
        sd  = SINS.get(sin_name, {})
        pwr = sd.get("power", "?")
        p   = st["passes"]
        a   = st["attempts"]
        f   = st["falls"]
        icon = "✅" if p > 0 else ("❌" if f > 0 else "⬜")
        virtue_done = sin_name in user.get("completed_virtues", [])
        virtue_tag  = " ✨ *virtue earned*" if virtue_done else ""
        breakdown.add_field(
            name=f"{icon}  {sin_name.capitalize()}  (Power {pwr})",
            value=(
                f"Attempts: **{a}** | Passed: **{p}** | Falls: **{f}**"
                f"{virtue_tag}"
            ),
            inline=False,
        )

    if not sin_stats:
        breakdown.description = "No sin attempts on record."

    # ── Chronological event log embed (last 10 events) ──
    recent = log[-10:]
    timeline = discord.Embed(
        title=f"🕰️ Recent Events — {target.display_name}",
        description=f"Last {len(recent)} of {len(log)} total events.",
        color=discord.Color.blurple(),
    )
    for e in reversed(recent):
        etype   = e.get("type", "?")
        sin     = e.get("sin", "?").capitalize()
        outcome = e.get("outcome", "?")
        reason  = e.get("reason", "")
        corr    = e.get("corruption_after", 0)
        ts      = e.get("ts", 0)

        if etype == "trial" and outcome == "passed":
            icon  = "⚡"
            label = f"Passed Trial of {sin}"
        elif etype == "virtue" and outcome == "passed":
            icon  = "✨"
            label = f"Earned Virtue — {sin}"
        elif etype == "fall":
            icon  = "💀"
            label = f"Fell from Grace ({sin})"
        else:
            icon  = "❓"
            label = f"{etype.capitalize()} — {sin}"

        timeline.add_field(
            name=f"{icon}  {label}",
            value=(
                f"{f'<t:{int(ts)}:d>' if ts else 'Unknown date'} — "
                f"Corruption after: **{corr}**"
                + (f"\n*{reason}*" if reason and etype == "fall" else "")
            ),
            inline=False,
        )

    await ctx.send(embed=summary)
    await ctx.send(embed=breakdown)
    await ctx.send(embed=timeline)


# ───────────────────────────────────────────────────────────────────
# COMMAND: !invite  (Print invite link with correct permissions)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def invite(ctx):
    """Get the bot invite link with all required permissions."""
    app_id = str(ctx.bot.user.id)
    link = (
        f"https://discord.com/oauth2/authorize?"
        f"client_id={app_id}&permissions={PERMISSIONS_INT}&scope=bot"
    )
    embed = discord.Embed(
        title="Invite Link",
        description=f"Click below to add the bot to your server:\n{link}",
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"Permission integer: {PERMISSIONS_INT}")
    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !setup  (Admin — create all missing roles & channels)
# ───────────────────────────────────────────────────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """Create every missing role category, role, channel category, and channel the bot needs."""
    guild = ctx.guild
    created_roles: list[str]      = []
    existing_roles: list[str]     = []
    created_categories: list[str] = []
    existing_categories: list[str]= []
    created_channels: list[str]   = []
    existing_channels: list[str]  = []
    errors: list[str]             = []

    await ctx.send("⚙️ Running setup — this may take a moment…")

    # ── Sin role colors ───────────────────────────────────────────────
    sin_colors = {
        "lust":     discord.Color.from_str("#e91e8c"),
        "gluttony": discord.Color.from_str("#f4a423"),
        "greed":    discord.Color.from_str("#ffd700"),
        "sloth":    discord.Color.from_str("#7b68ee"),
        "wrath":    discord.Color.from_str("#ff2400"),
        "envy":     discord.Color.from_str("#00b4d8"),
        "pride":    discord.Color.from_str("#ffffff"),
        "gooner":   discord.Color.from_str("#dc6e1e"),
    }

    existing_role_names = {r.name for r in guild.roles}

    async def make_role(name: str, color: discord.Color, hoist: bool):
        if name in existing_role_names:
            existing_roles.append(name)
            return
        try:
            await guild.create_role(
                name=name, color=color, hoist=hoist,
                mentionable=False, reason="!setup — Seven Sins bot",
            )
            created_roles.append(name)
            existing_role_names.add(name)
        except discord.Forbidden:
            created_roles.append(f"~~{name}~~ *(missing permission)*")
        except Exception as e:
            errors.append(f"Role {name}: {type(e).__name__}")

    # ── Visual role category separators ──────────────────────────────
    # These display-only roles act as section headers in the server member list.
    # After setup, drag your other roles beneath them in Server Settings → Roles.
    SEPARATOR_ROLES = [
        ("╔══ SINNERS ══╗",  discord.Color.from_rgb(160, 20,  60)),
        ("╔══ VIRTUES ══╗",  discord.Color.from_rgb(200, 170,  0)),
        ("╔══ MYTHS ══╗",    discord.Color.from_rgb( 80,  0, 160)),
        ("╔══ DESPAIR ══╗",  discord.Color.from_rgb( 80,  0,   0)),
        ("╔══ HOPE ══╗",     discord.Color.from_rgb(  0, 160, 200)),
    ]
    for sep_name, sep_color in SEPARATOR_ROLES:
        await make_role(sep_name, sep_color, hoist=True)

    # ── Sin trial placeholder roles (no hoist — not displayed as groups) ──
    for sd in SINS.values():
        await make_role(sd["role"], discord.Color.dark_gray(), hoist=False)

    # ── Final / evolved sin roles  →  SINNERS category ───────────────
    for sin, sd in SINS.items():
        await make_role(sd["final_role"], sin_colors[sin], hoist=True)
        if sd["evolved_role"] != sd["final_role"]:
            await make_role(sd["evolved_role"], sin_colors[sin], hoist=True)

    # ── Virtue roles  →  VIRTUES category ────────────────────────────
    for v in VIRTUES.values():
        await make_role(v["role"], discord.Color.gold(), hoist=True)

    # ── Myth roles  →  MYTHS category ────────────────────────────────
    # Keep this driven by MYTHS so every future myth is created by !setup.
    for myth in MYTHS.values():
        await make_role(myth["role"], myth["color"], hoist=True)

    # ── Standalone, character, and special roles ──────────────────────
    standalone_roles = [
        (JUSTICE_ROLE,    discord.Color.from_rgb(255, 240, 100)),
        (PRUDENCE_ROLE,   discord.Color.from_rgb(200, 180,  80)),
        (FORTITUDE_ROLE,  discord.Color.from_rgb(150, 100,  60)),
        (FAITH_ROLE,      discord.Color.from_rgb(200, 200, 255)),
        (HOPE_ROLE,       discord.Color.from_rgb(100, 180, 255)),
        (LIBERALITY_ROLE, discord.Color.from_rgb(140, 200, 140)),
    ]
    for role_name, role_color in standalone_roles:
        await make_role(role_name, role_color, hoist=True)

    special_roles = [
        (FALLEN_ROLE,             discord.Color.dark_red(), False),
        (DESPAIR_ROLE,            discord.Color.from_rgb(80, 0, 0), True),
        (REMNANT_OF_DESPAIR_ROLE, discord.Color.from_rgb(60, 0, 0), True),
        (RESERVE_COURSE_ROLE,     discord.Color.from_rgb(100, 100, 100), True),
        (DESPAIR_SISTER_ROLE,     discord.Color.from_rgb(120, 0, 60), True),
        (IZURU_DESPAIR_ROLE,      discord.Color.from_rgb(80, 0, 0), True),
        (IZURU_HOPE_ROLE,         discord.Color.from_rgb(0, 180, 220), True),
    ]
    for role_name, role_color, role_hoist in special_roles:
        await make_role(role_name, role_color, hoist=role_hoist)

    for i in range(RESERVE_COURSE_COUNT):
        await make_role(
            f"Reserve Course Student #{i + 1}",
            discord.Color.from_rgb(100, 100, 100),
            hoist=False,
        )

    for char in CHARACTERS.values():
        await make_role(char["hope_role"], char["color_hope"], hoist=True)
        if char["despair_role"]:
            await make_role(char["despair_role"], char["color_despair"], hoist=True)

    # ── Channel categories (Discord folder-style groupings) ───────────
    CATEGORY_NAMES = ["DESPAIR", "SINNERS", "VIRTUES", "MYTHS", "HOPE"]
    existing_cat_map = {c.name.upper(): c for c in guild.categories}
    category_map: dict[str, discord.CategoryChannel] = {}

    for cat_name in CATEGORY_NAMES:
        if cat_name in existing_cat_map:
            existing_categories.append(cat_name)
            category_map[cat_name] = existing_cat_map[cat_name]
        else:
            try:
                cat = await guild.create_category(
                    cat_name, reason="!setup — Seven Sins bot",
                )
                created_categories.append(cat_name)
                category_map[cat_name] = cat
            except discord.Forbidden:
                created_categories.append(f"~~{cat_name}~~ *(missing permission)*")
            except Exception as e:
                errors.append(f"Category {cat_name}: {type(e).__name__}")

    # ── Text channels ─────────────────────────────────────────────────
    existing_channel_names = {c.name for c in guild.text_channels}

    async def ensure_channel(
        name: str,
        cat_key: str,
        overwrites: dict | None = None,
    ):
        if name in existing_channel_names:
            existing_channels.append(name)
            existing = discord.utils.get(guild.text_channels, name=name)
            edit_kwargs: dict = {}
            category = category_map.get(cat_key)
            if category and existing and existing.category_id != category.id:
                edit_kwargs["category"] = category
            if overwrites is not None and existing:
                edit_kwargs["overwrites"] = overwrites
            if existing and edit_kwargs:
                try:
                    await existing.edit(**edit_kwargs, reason="!setup — Seven Sins bot")
                except discord.Forbidden:
                    errors.append(f"Channel {name}: missing permission to align category/permissions")
                except Exception as e:
                    errors.append(f"Channel {name}: {type(e).__name__}")
            return
        kwargs: dict = {"reason": "!setup — Seven Sins bot"}
        if cat_key in category_map:
            kwargs["category"] = category_map[cat_key]
        if overwrites:
            kwargs["overwrites"] = overwrites
        try:
            await guild.create_text_channel(name, **kwargs)
            created_channels.append(name)
            existing_channel_names.add(name)
        except discord.Forbidden:
            created_channels.append(f"~~{name}~~ *(missing permission)*")
        except Exception as e:
            errors.append(f"Channel {name}: {type(e).__name__}")

    # DESPAIR — main tribunal + gluttony feast (public, no restrictions)
    await ensure_channel(TRIAL_CHANNEL_NAME,    "DESPAIR")
    await ensure_channel(GLUTTONY_CHANNEL_NAME, "DESPAIR")

    # SINNERS — individual sin trial channels, each locked to its trial role
    sin_only = set(TRIAL_CHANNELS.values()) - {TRIAL_CHANNEL_NAME, GLUTTONY_CHANNEL_NAME}
    for sin, ch_name in TRIAL_CHANNELS.items():
        if ch_name not in sin_only:
            continue
        trial_role = discord.utils.get(guild.roles, name=SINS[sin]["role"])
        ow = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if trial_role:
            ow[trial_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            if sin == "gooner":
                ow[trial_role].attach_files = True
        await ensure_channel(ch_name, "SINNERS", ow)

    # VIRTUES — shared virtue announcement channel
    await ensure_channel("virtues-hall", "VIRTUES")

    # MYTHS — lore and server history channel
    await ensure_channel("myths", "MYTHS")

    # HOPE — redemption and general channel
    await ensure_channel("hope", "HOPE")

    def role_channel_overwrites(
        role_names: list[str],
        attach_files: bool = False,
    ) -> dict:
        """Lock a role channel to its role, the bot, and server administrators."""
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
            ),
        }
        for role_name in role_names:
            role_obj = discord.utils.get(guild.roles, name=role_name)
            if role_obj:
                overwrites[role_obj] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=attach_files,
                )
        for role_obj in guild.roles:
            if role_obj.permissions.administrator:
                overwrites[role_obj] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                )
        return overwrites

    # SINNERS — final/evolved role halls (trial channels above remain tied
    # to their temporary Trial — <Sin> roles).
    for sin, sd in SINS.items():
        final_roles = list(dict.fromkeys([sd["final_role"], sd["evolved_role"]]))
        await ensure_channel(
            f"{sin}-hall",
            "SINNERS",
            role_channel_overwrites(final_roles, attach_files=(sin == "gooner")),
        )

    # VIRTUES — one private channel for every tied and standalone virtue role.
    for sin, virtue in VIRTUES.items():
        await ensure_channel(
            f"virtue-{sin}",
            "VIRTUES",
            role_channel_overwrites([virtue["role"]]),
        )
    standalone_channels = {
        "justice": JUSTICE_ROLE,
        "prudence": PRUDENCE_ROLE,
        "fortitude": FORTITUDE_ROLE,
        "faith": FAITH_ROLE,
        "hopeful": HOPE_ROLE,
        "liberality": LIBERALITY_ROLE,
    }
    for slug, role_name in standalone_channels.items():
        await ensure_channel(
            f"virtue-{slug}",
            "VIRTUES",
            role_channel_overwrites([role_name]),
        )

    # MYTHS — one private channel for every myth role.
    for myth_key, myth in MYTHS.items():
        await ensure_channel(
            f"myth-{myth_key.replace('_', '-')}",
            "MYTHS",
            role_channel_overwrites([myth["role"]]),
        )

    # DESPAIR — special roles and character Despair roles.
    despair_role_channels = [
        ("despair-sanctum", [DESPAIR_ROLE]),
        ("remnant-sanctum", [REMNANT_OF_DESPAIR_ROLE]),
        ("despair-sister", [DESPAIR_SISTER_ROLE]),
        ("reserve-course", [RESERVE_COURSE_ROLE] + [
            f"Reserve Course Student #{i + 1}" for i in range(RESERVE_COURSE_COUNT)
        ]),
        ("fallen-grace", [FALLEN_ROLE]),
        ("izuru-despair", [IZURU_DESPAIR_ROLE]),
    ]
    for channel_name, role_names in despair_role_channels:
        await ensure_channel(
            channel_name,
            "DESPAIR",
            role_channel_overwrites(role_names),
        )
    for char_key, char in CHARACTERS.items():
        if char["despair_role"]:
            await ensure_channel(
                f"despair-{char_key}",
                "DESPAIR",
                role_channel_overwrites([char["despair_role"]]),
            )

    # HOPE — character Hope roles, Izuru Hope, and The Hopeful.
    await ensure_channel(
        "hopeful-sanctum",
        "HOPE",
        role_channel_overwrites([HOPE_ROLE]),
    )
    await ensure_channel(
        "izuru-hope",
        "HOPE",
        role_channel_overwrites([IZURU_HOPE_ROLE]),
    )
    for char_key, char in CHARACTERS.items():
        await ensure_channel(
            f"hope-{char_key}",
            "HOPE",
            role_channel_overwrites([char["hope_role"]]),
        )

    # ── Report ────────────────────────────────────────────────────────
    embed = discord.Embed(title="✅ Setup Complete", color=discord.Color.green())

    def _field(title: str, items: list[str]):
        if items:
            val = "\n".join(f"• {x}" for x in items)
            if len(val) > 1000:
                val = val[:997] + "…"
            embed.add_field(name=title, value=val, inline=False)

    _field(f"🆕 Roles Created ({len(created_roles)})",           created_roles)
    _field(f"✔️ Roles Already Exist ({len(existing_roles)})",    existing_roles)
    _field(f"🆕 Categories Created ({len(created_categories)})", created_categories)
    _field(f"✔️ Categories Exist ({len(existing_categories)})",  existing_categories)
    _field(f"🆕 Channels Created ({len(created_channels)})",     created_channels)
    _field(f"✔️ Channels Already Exist ({len(existing_channels)})", existing_channels)
    if errors:
        _field(f"⚠️ Errors ({len(errors)})", errors)

    total_new = len(created_roles) + len(created_categories) + len(created_channels)
    if total_new == 0 and not errors:
        embed.description = "Everything was already in place. No changes made."
    else:
        embed.description = (
            f"Created **{len(created_roles)}** role(s), "
            f"**{len(created_categories)}** category/ies, and "
            f"**{len(created_channels)}** channel(s)."
        )

    embed.set_footer(text="Bot needs Manage Roles + Manage Channels permissions.")
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def grant_special(ctx, member: discord.Member, role_key: str):
    """Admin: grant one standalone virtue role by its safe key."""
    key = role_key.lower().strip().replace("-", "_").replace(" ", "_")
    standalone_keys = {
        "justice": JUSTICE_ROLE,
        "prudence": PRUDENCE_ROLE,
        "fortitude": FORTITUDE_ROLE,
        "faith": FAITH_ROLE,
        "hope": HOPE_ROLE,
        "liberality": LIBERALITY_ROLE,
    }
    if key not in standalone_keys:
        await ctx.send(
            "Choose one standalone virtue: "
            f"`{'` | `'.join(standalone_keys)}`",
            delete_after=8,
        )
        return

    role_name = standalone_keys[key]
    role_obj = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role_obj:
        await ctx.send("Run `!setup` first so all standalone virtue roles exist.", delete_after=8)
        return

    data = load_data()
    user = get_user(data, member.id)
    user["sin_role"] = key
    user["fallen"] = False
    try:
        await member.add_roles(role_obj, reason=f"!grant_special by {ctx.author}")
    except discord.Forbidden:
        await ctx.send(
            f"I cannot assign **{role_name}**. Move the bot's role above it in Server Settings → Roles.",
            delete_after=10,
        )
        return
    except discord.HTTPException as exc:
        await ctx.send(f"Discord rejected the role assignment (`{exc.status}`).", delete_after=8)
        return

    save_data(data)
    await ctx.send(f"✅ **{role_name}** granted to {member.mention}.")


# ───────────────────────────────────────────────────────────────────
# MYTH COMMANDS
# ───────────────────────────────────────────────────────────────────

def _llorona_local_now() -> datetime:
    """Return the current time in the configured La Llorona challenge timezone."""
    return datetime.now(ZoneInfo(LLORONA_TIMEZONE))


async def _assign_myth_role(
    member: discord.Member,
    myth_key: str,
    reason: str,
) -> discord.Role:
    """Replace any existing myth role and assign the requested myth role."""
    myth_info = MYTHS[myth_key]
    role_obj = discord.utils.get(member.guild.roles, name=myth_info["role"])
    if not role_obj:
        raise LookupError(myth_info["role"])

    for other_myth in MYTHS.values():
        other_role = discord.utils.get(member.guild.roles, name=other_myth["role"])
        if other_role and other_role in member.roles and other_role != role_obj:
            await member.remove_roles(other_role, reason=reason)
    await member.add_roles(role_obj, reason=reason)
    return role_obj


@bot.command()
async def myths(ctx):
    """List the available myths and their abilities."""
    embed = discord.Embed(
        title="🌫️ Myths",
        description="Standalone legendary roles assigned by an administrator.",
        color=discord.Color.from_rgb(70, 150, 175),
    )
    for myth in MYTHS.values():
        ability_text = "\n".join(
            f"• **{command}** — {description}"
            for command, description in myth["abilities"]
        )
        obtainment_text = (
            "Obtainment: use `!drown @user` at exactly **12:00 AM midnight** "
            f"in **{LLORONA_TIMEZONE}** against **{LLORONA_DROWN_REQUIRED} different "
            "online human members** during that midnight."
            if myth["name"] == "La Llorona"
            else "Obtainment: use the challenge described by `!myth_tutorial`."
        )
        embed.add_field(
            name=f"{myth['name']}  |  Role: {myth['role']}",
            value=f"{myth['lore']}\n\n**{obtainment_text}**\n\n{ability_text}",
            inline=False,
        )
    await ctx.send(embed=embed)


@bot.command()
async def drown(ctx, target: discord.Member = None):
    """In-game La Llorona obtainment challenge: drown two online members at midnight."""
    if target is None:
        await ctx.send("Usage: `!drown @user`", delete_after=6)
        return
    if target.bot:
        await ctx.send("Only living server members count for the river challenge.", delete_after=6)
        return
    if target.id == ctx.author.id:
        await ctx.send("The river needs someone else. You cannot drown yourself.", delete_after=6)
        return
    if target.status == discord.Status.offline:
        await ctx.send("That member is offline. Only online members can be claimed by the river.", delete_after=8)
        return

    local_now = _llorona_local_now()
    if local_now.hour != 0 or local_now.minute != 0:
        await ctx.send(
            f"La Llorona's obtainment ritual only counts at **exactly 12:00 AM "
            f"(midnight)** in **{LLORONA_TIMEZONE}**. It is currently "
            f"{local_now.strftime('%I:%M %p')} there.",
            delete_after=10,
        )
        return

    role_obj = discord.utils.get(ctx.guild.roles, name=MYTHS["la_llorona"]["role"])
    if not role_obj:
        await ctx.send("Run `!setup` first so the **La Llorona** role exists.", delete_after=8)
        return

    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("myth") == "la_llorona":
        await ctx.send("You already possess the **La Llorona** myth.", delete_after=6)
        save_data(data)
        return

    challenge_day = local_now.date().isoformat()
    if user.get("llorona_drown_day") != challenge_day:
        user["llorona_drown_day"] = challenge_day
        user["llorona_drown_targets"] = []

    targets = user.setdefault("llorona_drown_targets", [])
    target_id = str(target.id)
    if target_id in targets:
        await ctx.send(
            f"{target.mention} has already been counted tonight. "
            f"You need **{LLORONA_DROWN_REQUIRED} different online people**.",
            delete_after=8,
        )
        save_data(data)
        return

    targets.append(target_id)
    if len(targets) < LLORONA_DROWN_REQUIRED:
        save_data(data)
        await ctx.send(
            f"🌊 The river claims {target.mention} in-game. "
            f"La Llorona challenge progress: **{len(targets)}/{LLORONA_DROWN_REQUIRED}** "
            f"different online people at midnight.",
        )
        return

    try:
        await _assign_myth_role(
            ctx.author,
            "la_llorona",
            reason=f"La Llorona midnight obtainment by {ctx.author}",
        )
    except discord.Forbidden:
        save_data(data)
        await ctx.send(
            "The ritual is complete, but Discord would not assign the role. "
            "Move the bot's role above **La Llorona** and run `!drown` again at the next midnight.",
            delete_after=12,
        )
        return
    except discord.HTTPException as exc:
        save_data(data)
        await ctx.send(f"Discord rejected the myth role assignment (`{exc.status}`).", delete_after=8)
        return

    user["myth"] = "la_llorona"
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🌫️ La Llorona Has Risen",
        description=(
            f"{ctx.author.mention} drowned **two different online members** in-game "
            f"at exactly **12:00 AM** in **{LLORONA_TIMEZONE}**.\n\n"
            "The **La Llorona** myth role has been obtained. Use `!myth_tutorial` "
            "to learn her powers."
        ),
        color=MYTHS["la_llorona"]["color"],
    ))


@bot.command()
@commands.has_permissions(administrator=True)
async def grant_myth(ctx, member: discord.Member, myth: str):
    """Admin: assign one myth role to one member."""
    myth = myth.lower().strip().replace(" ", "_")
    if myth not in MYTHS:
        valid = " | ".join(MYTHS.keys())
        await ctx.send(f"❌ Unknown myth. Valid options: `{valid}`", delete_after=8)
        return

    myth_info = MYTHS[myth]
    role_obj = discord.utils.get(ctx.guild.roles, name=myth_info["role"])
    if not role_obj:
        await ctx.send(
            f"⚠️ The **{myth_info['role']}** role does not exist. Run `!setup` first.",
            delete_after=8,
        )
        return

    try:
        await _assign_myth_role(
            member,
            myth,
            reason=f"!grant_myth by {ctx.author}",
        )
    except discord.Forbidden:
        await ctx.send(
            "❌ I cannot manage that myth role. Move the bot's role above the myth role "
            "in **Server Settings → Roles**.",
            delete_after=10,
        )
        return
    except discord.HTTPException as exc:
        await ctx.send(f"❌ Discord rejected the role change: `{exc.status}`.", delete_after=8)
        return

    data = load_data()
    user = get_user(data, member.id)
    user["myth"] = myth
    save_data(data)
    await ctx.send(f"🌫️ **{myth_info['name']}** has chosen {member.mention}.")


def _is_llorona(member: discord.Member) -> bool:
    return any(
        role.name == MYTHS["la_llorona"]["role"]
        for role in member.roles
    )


@bot.command()
async def llorona_wail(ctx, target: discord.Member = None):
    """La Llorona: silence a target with her river wail."""
    if target is None:
        await ctx.send("Usage: `!llorona_wail @user`", delete_after=6)
        return
    if not _is_llorona(ctx.author):
        await ctx.send("Only **La Llorona** can use the river wail.", delete_after=6)
        return
    if target.id == ctx.author.id:
        await ctx.send("The river cannot wail at itself.", delete_after=5)
        return

    data = load_data()
    user = get_user(data, ctx.author.id)
    target_user = get_user(data, target.id)
    cooldowns = user.setdefault("myth_ability_cds", {})
    cooldown = cooldowns.get("llorona_wail", 0) or 0
    if now_ts() < cooldown:
        await ctx.send(f"Your wail returns {remaining_fmt(cooldown)}.", delete_after=8)
        save_data(data)
        return

    now = now_ts()
    cooldowns["llorona_wail"] = now + 3600
    target_user["ability_locked_until"] = max(
        target_user.get("ability_locked_until") or 0,
        now + 10 * 60,
    )
    target_user["clash_power_penalty"] = max(
        target_user.get("clash_power_penalty") or 0,
        1,
    )
    target_user["clash_penalty_until"] = max(
        target_user.get("clash_penalty_until") or 0,
        now + 20 * 60,
    )
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🌊 The Wail Beside the River",
        description=(
            f"{ctx.author.mention} cries for what was lost, and the sound reaches "
            f"{target.mention}.\n\n"
            f"🔇 Abilities locked for **10 minutes**.\n"
            f"⚖️ Clash power weakened for **20 minutes**."
        ),
        color=MYTHS["la_llorona"]["color"],
    ))


@bot.command()
async def llorona_veil(ctx):
    """La Llorona: hide one incoming attack behind a veil of mist."""
    if not _is_llorona(ctx.author):
        await ctx.send("Only **La Llorona** can summon the weeping veil.", delete_after=6)
        return

    data = load_data()
    user = get_user(data, ctx.author.id)
    cooldowns = user.setdefault("myth_ability_cds", {})
    cooldown = cooldowns.get("llorona_veil", 0) or 0
    if now_ts() < cooldown:
        await ctx.send(f"The veil returns {remaining_fmt(cooldown)}.", delete_after=8)
        save_data(data)
        return

    now = now_ts()
    cooldowns["llorona_veil"] = now + 2 * 3600
    user["llorona_veil_until"] = now + 30 * 60
    save_data(data)
    await ctx.send(
        f"🌫️ {ctx.author.mention} disappears behind a **Weeping Veil**. "
        "The next attack against you within **30 minutes** will be nullified."
    )


@bot.command()
async def llorona_lure(ctx, target: discord.Member = None):
    """La Llorona: pull one target toward the river in fearful silence."""
    if target is None:
        await ctx.send("Usage: `!llorona_lure @user`", delete_after=6)
        return
    if not _is_llorona(ctx.author):
        await ctx.send("Only **La Llorona** can call someone toward the river.", delete_after=6)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot lure yourself to the river.", delete_after=5)
        return

    data = load_data()
    user = get_user(data, ctx.author.id)
    target_user = get_user(data, target.id)
    cooldowns = user.setdefault("myth_ability_cds", {})
    cooldown = cooldowns.get("llorona_lure", 0) or 0
    if now_ts() < cooldown:
        await ctx.send(f"The river calls again {remaining_fmt(cooldown)}.", delete_after=8)
        save_data(data)
        return

    now = now_ts()
    cooldowns["llorona_lure"] = now + 3 * 3600
    timed_out = True
    try:
        await target.timeout(timedelta(minutes=1), reason=f"La Llorona lure by {ctx.author}")
    except discord.Forbidden:
        timed_out = False
    except discord.HTTPException:
        timed_out = False
    if not timed_out:
        target_user["ability_locked_until"] = max(
            target_user.get("ability_locked_until") or 0,
            now + 5 * 60,
        )
    save_data(data)

    effect = (
        "They are silenced for **1 minute**."
        if timed_out
        else "Discord refused the timeout, so their abilities are locked for **5 minutes** instead."
    )
    await ctx.send(embed=discord.Embed(
        title="🌊 The River's Lure",
        description=(
            f"{ctx.author.mention} whispers from the water, and {target.mention} hears it.\n\n"
            f"{effect}"
        ),
        color=MYTHS["la_llorona"]["color"],
    ))


# ───────────────────────────────────────────────────────────────────
# ADMIN COMMANDS
# ───────────────────────────────────────────────────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def grant(ctx, member: discord.Member, sin: str):
    """Admin: Manually assign a sin final role to a member. Run !setup first to ensure roles exist."""
    sin = sin.lower()
    if sin not in SINS:
        await ctx.send(
            f"❌ Invalid sin name: `{sin}`\n"
            f"Valid options: `{'` | `'.join(SINS.keys())}`"
        )
        return
    data = load_data()
    await complete_trial(member, sin, data)
    save_data(data)

    role_name = SINS[sin]["final_role"]
    role_obj  = discord.utils.get(ctx.guild.roles, name=role_name)

    if not role_obj:
        await ctx.send(
            f"⚠️ Data updated for {member.mention}, but **`{role_name}`** doesn't exist on "
            "this server yet. Run `!setup` first, then `!grant` again."
        )
        return

    # Always try to assign directly so we see the real Discord error if it fails
    try:
        await member.add_roles(role_obj, reason=f"!grant by {ctx.author}")
        await ctx.send(
            f"✅ **{role_name}** granted to {member.mention}. "
            f"(Power {SINS[sin]['power']})"
        )
    except discord.Forbidden:
        await ctx.send(
            f"❌ **Permission denied.** The bot cannot assign **`{role_name}`**.\n"
            "Fix: Go to **Server Settings → Roles** and drag the bot's role to the "
            "**very top** (or at least above `{role_name}`)."
        )
    except discord.HTTPException as e:
        await ctx.send(
            f"❌ Discord API error while assigning **`{role_name}`**: `{e.status} — {e.text}`"
        )

@bot.command()
@commands.has_permissions(administrator=True)
async def force_fall(ctx, member: discord.Member, *, reason: str = "Admin override"):
    data = load_data()
    await fall_from_grace(member, reason, data)
    save_data(data)
    await ctx.send(f"{member.mention} has been cast down.")

@bot.command()
@commands.has_permissions(administrator=True)
async def reset_user(ctx, member: discord.Member):
    data = load_data()
    uid  = str(member.id)
    if uid in data["users"]:
        del data["users"][uid]
    for s in list(data["claimed_sins"].keys()):
        if data["claimed_sins"][s] == uid:
            del data["claimed_sins"][s]
    save_data(data)
    await ctx.send(f"Reset all sin data for {member.mention}.")


@bot.command()
@commands.has_permissions(administrator=True)
async def strip_all(ctx, member: discord.Member):
    """Admin: remove every manageable role from exactly one member."""
    bot_member = ctx.guild.me
    if bot_member is None:
        await ctx.send("❌ I cannot verify my role position right now.", delete_after=8)
        return
    if member.id == ctx.guild.owner_id:
        await ctx.send("❌ The server owner's roles cannot be stripped by the bot.", delete_after=8)
        return
    if member.id == bot_member.id:
        await ctx.send("❌ I cannot strip my own bot role.", delete_after=8)
        return

    removable = [
        role for role in member.roles
        if role != ctx.guild.default_role
        and not role.managed
        and role < bot_member.top_role
    ]
    skipped = [
        role for role in member.roles
        if role != ctx.guild.default_role
        and (role.managed or role >= bot_member.top_role)
    ]

    removed: list[str] = []
    errors: list[str] = []
    for role in removable:
        try:
            await member.remove_roles(
                role,
                reason=f"!strip_all by {ctx.author} (single target)",
            )
            removed.append(role.name)
        except discord.Forbidden:
            errors.append(f"{role.name} (permission denied)")
        except discord.HTTPException as exc:
            errors.append(f"{role.name} (Discord {exc.status})")

    embed = discord.Embed(
        title="🧹 Roles Stripped",
        description=f"Only {member.mention} was targeted. `@everyone` is always retained.",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name=f"Removed ({len(removed)})",
        value=", ".join(removed) if removed else "No manageable roles found.",
        inline=False,
    )
    if skipped:
        embed.add_field(
            name=f"Skipped ({len(skipped)})",
            value=", ".join(role.name for role in skipped),
            inline=False,
        )
    if errors:
        embed.add_field(name=f"Errors ({len(errors)})", value=", ".join(errors), inline=False)
    await ctx.send(embed=embed)


def _role_directory_tutorial_pages() -> list[discord.Embed]:
    """Build a literal, one-entry-per-Discord-role obtainment directory."""
    role_entries: list[tuple[str, str, str]] = []

    def add(category: str, role_name: str, obtainment: str):
        role_entries.append((category, role_name, obtainment))

    separator_roles = {
        "╔══ SINNERS ══╗": "Display-only category separator created by `!setup`; it grants no abilities.",
        "╔══ VIRTUES ══╗": "Display-only category separator created by `!setup`; it grants no abilities.",
        "╔══ MYTHS ══╗": "Display-only category separator created by `!setup`; it grants no abilities.",
        "╔══ DESPAIR ══╗": "Display-only category separator created by `!setup`; it grants no abilities.",
        "╔══ HOPE ══╗": "Display-only category separator created by `!setup`; it grants no abilities.",
    }
    for role_name, method in separator_roles.items():
        category = role_name.split("══")[1].strip()
        add(category, role_name, method)

    # Every temporary trial role and every unique final/evolved role.
    for sin, sd in SINS.items():
        add(
            "SINNERS",
            sd["role"],
            f"Temporary role assigned by `!trial {sin}` while the trial is active. "
            f"Complete the challenge in `#{TRIAL_CHANNELS[sin]}` to move on.",
        )
        add(
            "SINNERS",
            sd["final_role"],
            f"Pass the `{sin}` trial to obtain this final role. "
            f"The role's private channel is `#{sin}-hall`.",
        )
        if sd["evolved_role"] != sd["final_role"]:
            add(
                "SINNERS",
                sd["evolved_role"],
                f"Complete the evolved `{sin}` trial to obtain this evolved role. "
                f"The role's private channel is `#{sin}-hall`.",
            )

    for sin, virtue in VIRTUES.items():
        add(
            "VIRTUES",
            virtue["role"],
            f"Complete the **{virtue['virtue']}** virtue trial tied to `{sin}`. "
            f"An administrator can start it with `!virtue_trial @user`; the role channel is `#virtue-{sin}`.",
        )

    standalone_virtues = {
        JUSTICE_ROLE: "justice",
        PRUDENCE_ROLE: "prudence",
        FORTITUDE_ROLE: "fortitude",
        FAITH_ROLE: "faith",
        HOPE_ROLE: "hope",
        LIBERALITY_ROLE: "liberality",
    }
    for role_name, key in standalone_virtues.items():
        add(
            "VIRTUES",
            role_name,
            f"Standalone virtue assigned by an administrator with `!grant_special @user {key}`. "
            f"Private channel: `#virtue-{key if key != 'hope' else 'hopeful'}`.",
        )

    for myth_key, myth in MYTHS.items():
        if myth_key == "la_llorona":
            method = (
                f"Use `!drown @user` at exactly **12:00 AM** in **{LLORONA_TIMEZONE}**. "
                f"The target must be online and non-bot; claim {LLORONA_DROWN_REQUIRED} different members "
                "during that midnight. Private channel: `#myth-la-llorona`."
            )
        else:
            method = f"Complete the myth challenge described by `!myth_tutorial`; private channel: `#myth-{myth_key.replace('_', '-')}`."
        add("MYTHS", myth["role"], method)

    despair_roles = [
        (
            DESPAIR_ROLE,
            f"Automatically granted during the Friday {DESPAIR_HOUR}:{DESPAIR_MINUTE:02d} PM UTC "
            f"window when you have a sin role and {DESPAIR_CORRUPTION_REQUIRED}+ corruption. Private channel: `#despair-sanctum`.",
        ),
        (
            REMNANT_OF_DESPAIR_ROLE,
            "Granted to a target when an Ultimate Despair successfully uses `!brainwash_remnant @user`. "
            "Private channel: `#remnant-sanctum`.",
        ),
        (
            RESERVE_COURSE_ROLE,
            "Created for the Reserve Course system when an Ultimate Despair uses `!summon_reserve`. "
            "Private channel: `#reserve-course`.",
        ),
        (
            DESPAIR_SISTER_ROLE,
            "Summoned by an Ultimate Despair with `!summon_sister`. Private channel: `#despair-sister`.",
        ),
        (
            FALLEN_ROLE,
            "Applied after a failed trial, defeat, or an administrator's `!force_fall @user [reason]`. "
            "Private channel: `#fallen-grace`.",
        ),
        (
            IZURU_DESPAIR_ROLE,
            "Use `!izuru_despair` with a sin role or at least 50 corruption. Private channel: `#izuru-despair`.",
        ),
    ]
    for role_name, method in despair_roles:
        add("DESPAIR", role_name, method)
    for i in range(RESERVE_COURSE_COUNT):
        add(
            "DESPAIR",
            f"Reserve Course Student #{i + 1}",
            f"Summoned as NPC #{i + 1} by an Ultimate Despair using `!summon_reserve`. "
            "Private channel: `#reserve-course`.",
        )

    for char_key, char in CHARACTERS.items():
        add(
            "HOPE",
            char["hope_role"],
            f"Claim with `!claim_hope {char_key}`. Character channel: `#hope-{char_key}`.",
        )
        if char["despair_role"]:
            add(
                "DESPAIR",
                char["despair_role"],
                f"First claim Hope with `!claim_hope {char_key}`, then use `!claim_despair {char_key}`. "
                f"Character channel: `#despair-{char_key}`.",
            )
    add(
        "HOPE",
        IZURU_HOPE_ROLE,
        f"Use `!izuru_hope` after meeting the requirements: {IZURU_HOPE_CORRUPTION_REQUIRED} corruption, "
        f"{IZURU_HOPE_POINTS_REQUIRED} Hope points, and {IZURU_HOPE_APPROVALS_REQUIRED} approvals. "
        "Private channel: `#izuru-hope`.",
    )

    pages: list[discord.Embed] = []
    page_size = 20
    total_pages = (len(role_entries) + page_size - 1) // page_size
    colors = {
        "SINNERS": discord.Color.dark_red(),
        "VIRTUES": discord.Color.gold(),
        "MYTHS": discord.Color.from_rgb(70, 150, 175),
        "DESPAIR": discord.Color.from_rgb(80, 0, 0),
        "HOPE": discord.Color.from_rgb(0, 160, 220),
    }
    for page_number, start in enumerate(range(0, len(role_entries), page_size), start=1):
        embed = discord.Embed(
            title=f"📚 Complete Role Directory — Page {page_number}/{total_pages}",
            description=(
                "Every role created or managed by `!setup` appears below exactly once. "
                "Use `!commands` for the powers unlocked by each role."
            ),
            color=discord.Color.blurple(),
        )
        for category, role_name, method in role_entries[start:start + page_size]:
            embed.add_field(
                name=f"[{category}] {role_name}",
                value=f"**How to obtain:** {method}",
                inline=False,
            )
        embed.color = colors.get(role_entries[start][0], discord.Color.blurple())
        pages.append(embed)
    return pages


def _category_tutorial_pages() -> list[discord.Embed]:
    """Build the role-specific tutorials used by !tutorial and category guides."""
    pages: list[discord.Embed] = []

    sin_power_details = {
        "lust": (
            "`!obsess @user` sets your obsession target. "
            "`!obsession_clash @user` starts an obsession clash. "
            "`!i_dont_care_if_theyre_watching` reveals the obsession and boosts your meter/power."
        ),
        "gluttony": (
            "`!gorge` builds a temporary clash bonus from server activity. "
            "`!feast @user` curses a target to use food emojis. "
            "`!devour @user` blocks the target's messages and commands for 5 minutes."
        ),
        "greed": (
            "`!steal_ability @user` steals a recent ability. "
            "`!i_always_get_what_i_want @user` takes a target's top bonus. "
            "`!frenzy_clash @user` gives extra coins with a larger loss if you lose."
        ),
        "sloth": (
            "`!force_lazy @user` slows a target's typing. "
            "`!slowdown @user` reduces their next clash power. "
            "`!force_sleep @user` locks abilities. "
            "`!deep_sleep @user` applies extended sleep. "
            "`!sleepwalker` gives a risky self-buff after it is unlocked."
        ),
        "wrath": (
            "`!rage_strike @user` launches a high-power clash strike. "
            "`!bloodlust` boosts clashes for an hour. "
            "`!summon_meteor @user` is Wrath's costly meteor attack."
        ),
        "envy": (
            "`!envy_strike @user` strips a role during the Envy trial. "
            "`!jealousy_mark @user` marks a target. "
            "`!envy_check` is the marked target's counter. "
            "`!schizo @user` creates fake messages. "
            "`!marks [@user]` and `!envy_meter` show progress."
        ),
        "pride": (
            "`!weaken <sin>` lowers a sin's effective power. "
            "`!claim @user` demands submission. "
            "`!recognition` shows bow recognition. "
            "`!stop_time freeze/@user | passive` uses unlocked time powers."
        ),
        "gooner": (
            "`!flash @user` stuns a target. "
            "`!withered_meat @user` disables their abilities. "
            "`!diane_foxington` summons Diane. "
            "`!gooner_meter [@user]` shows the image-trial progress."
        ),
    }
    sin_methods = {
        "lust": "Run `!trial lust`; collect 5 unique ❤️ reactions within 24 hours (evolved: 10 within 18 hours).",
        "gluttony": "Run `!trial gluttony`; react to every message in `#gluttony-feast` within 5 minutes (evolved: 2 minutes).",
        "greed": "Run `!trial greed`; use `!kill @user` to silence a member without being exposed (evolved: silence 2 people).",
        "sloth": "Run `!trial sloth`; abbreviate every word for 48 hours (evolved: every word must be 3 characters or fewer for 72 hours).",
        "wrath": "Run `!trial wrath`; include a curse word in every message for 24 hours (evolved: two distinct curse words for 36 hours).",
        "envy": "Run `!trial envy`; use `!envy_strike @user` and avoid the expose vote (evolved: strike 2 different members).",
        "pride": "Run `!trial pride`; use `!proclaim` and get 60% of online members to bow within 48 hours (evolved: 75% within 36 hours).",
        "gooner": "Run `!trial gooner`; submit 100 images in `#gooner-trial` within 7 days (evolved: 200 within 5 days).",
    }
    sin_page = discord.Embed(
        title="📖 Sin Tutorial — Powers & Obtainment",
        description="Choose a sin with `!trial <sin>`. Pass its trial to receive the listed role. Most powers require that role and have cooldowns.",
        color=discord.Color.dark_red(),
    )
    for sin, sd in SINS.items():
        sin_page.add_field(
            name=f"{sin.capitalize()} → {sd['final_role']}",
            value=f"**Obtainment:** {sin_methods[sin]}\n**Powers:** {sin_power_details[sin]}",
            inline=False,
        )
    pages.append(sin_page)

    virtue_power_details = {
        "lust": "`!abstain [@user]` blocks Lust obsession effects. `!purify` clears your obsession.",
        "gluttony": "`!fast [@user]` removes a feast curse and grants a brief boost. `!moderate @user` reduces a clash bonus.",
        "greed": "`!gift_power @user` gives a clash coin. `!return_ability` returns a stolen ability.",
        "sloth": "`!inspire @user` removes laziness/slowdown and grants a coin. `!rouse @user` wakes a sleeping target.",
        "wrath": "`!de_escalate @user` reduces Wrath effects. `!absorb_strike @user` absorbs and reflects a rage strike.",
        "envy": "`!bless @user` removes an insecurity mark and shields a target. `!forgive @user` clears a jealousy mark or bounty.",
        "pride": "`!submit` trades power for double next-clash coins. `!counter_claim` rejects a Pride claim.",
    }
    virtue_page = discord.Embed(
        title="📖 Virtue Tutorial — Powers & Obtainment",
        description="The seven tied virtues are earned by completing the matching virtue trial. Admins can start one with `!virtue_trial @user` or use `!grant_virtue @user <sin>`.",
        color=discord.Color.from_rgb(80, 140, 200),
    )
    for sin, virtue in VIRTUES.items():
        virtue_page.add_field(
            name=f"{virtue['virtue']} → {virtue['role']}",
            value=f"**Obtainment:** Complete the `{sin}` virtue trial: {VIRTUE_TRIALS[sin]}\n**Powers:** {virtue_power_details[sin]}",
            inline=False,
        )
    virtue_page.add_field(
        name="Standalone virtues",
        value=(
            "The Scales of Justice, The Prudent Eye, The Unbroken, The Faithful, "
            "The Hopeful, and The Open Spirit are assigned by an administrator with "
            "`!grant_special @user <justice|prudence|fortitude|faith|hope|liberality>`. "
            "Use `!commands` for every support and attack power."
        ),
        inline=False,
    )
    virtue_page.add_field(
        name="Standalone power commands",
        value=(
            "Justice: `!jacobs_ladder`, `!scale_of_wrongdoing`, `!divine_retribution`, `!condemn`.\n"
            "Prudence: `!discern`, `!wise_counsel`, `!expose`, `!anticipate`.\n"
            "Fortitude: `!endure`, `!fortify`, `!iron_will`, `!crush`.\n"
            "Faith: `!invoke_faith`, `!prayer`, `!smite`, `!holy_judgment`.\n"
            "Hope: `!radiant_strike`, `!hope_barrage`, `!inspire_strike`, `!despair_wave`.\n"
            "Liberality: `!grant_freedom`, `!bestow`, `!redistribution`, `!break_chains`."
        ),
        inline=False,
    )
    pages.append(virtue_page)

    myth_page = discord.Embed(
        title="📖 Myth Tutorial — Powers & Obtainment",
        description="Myths are standalone roles. Run `!setup` first so the MYTHS category, channels, and roles exist.",
        color=discord.Color.from_rgb(70, 150, 175),
    )
    for myth_key, myth in MYTHS.items():
        ability_text = "\n".join(f"• `{command}` — {description}" for command, description in myth["abilities"])
        obtainment = (
            "Use `!drown @user` at exactly **12:00 AM midnight** in "
            f"**{LLORONA_TIMEZONE}**. The target must be online, and you must drown "
            f"**{LLORONA_DROWN_REQUIRED} different people** during that midnight. "
            "This is an in-game challenge. An administrator may use "
            "`!grant_myth @user la_llorona` as an override."
            if myth_key == "la_llorona"
            else "Use the myth's listed obtainment challenge."
        )
        myth_page.add_field(
            name=f"{myth['name']} → {myth['role']}",
            value=f"**Obtainment:** {obtainment}\n**Powers:**\n{ability_text}",
            inline=False,
        )
    pages.append(myth_page)

    despair_page = discord.Embed(
        title="📖 Despair Tutorial — Powers & Obtainment",
        description="These special roles live in the DESPAIR category and use the channels created by `!setup`.",
        color=discord.Color.from_rgb(80, 0, 0),
    )
    despair_page.add_field(
        name=f"{DESPAIR_ROLE}",
        value=(
            f"**Obtainment:** Have a sin role and at least **{DESPAIR_CORRUPTION_REQUIRED} corruption**, "
            f"then be present during the Friday **{DESPAIR_HOUR}:{DESPAIR_MINUTE:02d} PM UTC** window, "
            "or use the admin role flow.\n"
            "**Powers:** `!tragic_event`, `!brainwash @user`, `!disaster`, `!defend`, "
            "`!summon_sister`, `!summon_reserve`, and `!brainwash_remnant @user`."
        ),
        inline=False,
    )
    despair_page.add_field(
        name=f"{DESPAIR_SISTER_ROLE} and Reserve Course",
        value=(
            f"**Obtainment:** The Ultimate Despair uses `!summon_sister` or `!summon_reserve`.\n"
            f"**Powers:** `!sister_kill @user`, `!sister_say <message>`, `!sister_seduce @user`, "
            f"`!sister_anything <action>`, and `!student_attack @user`."
        ),
        inline=False,
    )
    despair_page.add_field(
        name=f"{REMNANT_OF_DESPAIR_ROLE} and {FALLEN_ROLE}",
        value=(
            f"**{REMNANT_OF_DESPAIR_ROLE}:** The Ultimate Despair obtains it by succeeding with "
            "`!brainwash_remnant @user`.\n"
            f"**{FALLEN_ROLE}:** Applied after a failed trial or defeat; admins can use "
            "`!force_fall @user [reason]`."
        ),
        inline=False,
    )
    despair_page.add_field(
        name="Izuru Kamakura — Ultimate Despair",
        value=(
            "Use `!izuru_despair` with a sin role or at least 50 corruption. "
            "This grants the Izuru Despair role and all character talents/passives."
        ),
        inline=False,
    )
    despair_page.add_field(
        name="Character Despair roles",
        value=(
            "First claim a Hope character with `!claim_hope <character>`, then use "
            "`!claim_despair <character>`. View the full character list with `!characters`."
        ),
        inline=False,
    )
    pages.append(despair_page)

    hope_page = discord.Embed(
        title="📖 Hope Tutorial — Powers & Obtainment",
        description="Hope roles live in the HOPE category. Use `!characters` to see each talent and its channel.",
        color=discord.Color.from_rgb(0, 160, 220),
    )
    hope_page.add_field(
        name="Character Hope roles",
        value=(
            "Use `!claim_hope <character>` to claim an available Hope character. "
            "The command assigns that character's role and stats. `!mycharacter` "
            "shows your status. Every character has a Hope and a Despair kit (`!talent`, `!special`, `!talents`); "
            "swap with `!alignment`. Nagito also has `!luck_switch` and `!fortune`. Chiaki is Hope-only."
        ),
        inline=False,
    )
    for char_key, char in CHARACTERS.items():
        hope_page.add_field(
            name=f"{char['name']} → {char['hope_role']}",
            value=f"Obtain with `!claim_hope {char_key}`. Talent: **{char['talent']}**. Base stats: HP/ATK/DEF {char['stats'][0]}/{char['stats'][1]}/{char['stats'][2]}.",
            inline=False,
        )
    hope_page.add_field(
        name=IZURU_HOPE_ROLE,
        value=(
            f"Use `!approve_izuru @user` to receive approvals, then `!izuru_hope`. "
            f"Requirements: {IZURU_HOPE_CORRUPTION_REQUIRED} corruption, "
            f"{IZURU_HOPE_POINTS_REQUIRED} Hope points, and {IZURU_HOPE_APPROVALS_REQUIRED} approvals."
        ),
        inline=False,
    )
    pages.append(hope_page)

    path_page = discord.Embed(
        title="📖 Path Tutorial — Powers & Obtainment",
        description="Choose one path with `!choose_path <path>`. The choice is locked for 7 days. Use `!path_info` for the full sin-by-sin breakdown.",
        color=discord.Color.from_rgb(80, 80, 200),
    )
    path_page.add_field(name="Support", value=f"{PATH_DESCRIPTIONS['support']}\nUse `!support_ability [@ally]`.", inline=False)
    path_page.add_field(name="Attack", value=f"{PATH_DESCRIPTIONS['attack']}\nUse `!attack_ability @target`.", inline=False)
    path_page.add_field(name="Hybrid", value=f"{PATH_DESCRIPTIONS['hybrid']}\nUse `!hybrid_ability @ally [@enemy]`.", inline=False)
    path_page.add_field(name="TACHT", value=f"{PATH_DESCRIPTIONS['tacht']}\nUse `!tacht_strike @user` and `!tacht_burst`.", inline=False)
    path_page.add_field(name="Reverence", value=f"{PATH_DESCRIPTIONS['reverence']}\nUse `!reverence_aura` and `!demand_tribute @user`.", inline=False)
    path_page.add_field(name="Universal combat", value="Use `!attack @user`, `!heal`, and `!coin_power [@user]` alongside your selected path.", inline=False)
    pages.append(path_page)
    pages.extend(_role_directory_tutorial_pages())

    return pages


async def _send_tutorial_pages(ctx, pages: list[discord.Embed]):
    for page in pages:
        await ctx.author.send(embed=page)
        await asyncio.sleep(0.6)


async def _run_category_tutorial(ctx, page_index: int):
    try:
        await _send_tutorial_pages(ctx, [_category_tutorial_pages()[page_index]])
    except discord.Forbidden:
        await ctx.send(
            "❌ I could not DM you. Enable **Allow direct messages from server members** "
            "and try the tutorial command again.",
            delete_after=10,
        )


@bot.command(aliases=["sin_guide"])
async def sin_tutorial(ctx):
    """DM the complete sin powers and obtainment tutorial."""
    await _run_category_tutorial(ctx, 0)


@bot.command(aliases=["virtue_guide"])
async def virtue_tutorial(ctx):
    """DM the complete virtue powers and obtainment tutorial."""
    await _run_category_tutorial(ctx, 1)


@bot.command(aliases=["myth_guide"])
async def myth_tutorial(ctx):
    """DM the complete myth powers and obtainment tutorial."""
    await _run_category_tutorial(ctx, 2)


@bot.command(aliases=["despair_guide"])
async def despair_tutorial(ctx):
    """DM the complete Despair powers and obtainment tutorial."""
    await _run_category_tutorial(ctx, 3)


@bot.command(aliases=["hope_guide"])
async def hope_tutorial(ctx):
    """DM the complete Hope powers and obtainment tutorial."""
    await _run_category_tutorial(ctx, 4)


@bot.command(aliases=["path_guide"])
async def path_tutorial(ctx):
    """DM the complete combat path powers and obtainment tutorial."""
    await _run_category_tutorial(ctx, 5)


@bot.command(aliases=["role_guide", "roles_tutorial"])
async def role_tutorial(ctx):
    """DM a literal one-entry-per-role obtainment directory."""
    try:
        await _send_tutorial_pages(ctx, _role_directory_tutorial_pages())
    except discord.Forbidden:
        await ctx.send(
            "❌ I could not DM you. Enable **Allow direct messages from server members** "
            "and try `!role_tutorial` again.",
            delete_after=10,
        )


@bot.command(aliases=["role_obtainment"])
async def obtainment(ctx):
    """DM obtainment methods for every role category."""
    try:
        await _send_tutorial_pages(ctx, _category_tutorial_pages())
    except discord.Forbidden:
        await ctx.send(
            "❌ I could not DM you. Enable **Allow direct messages from server members** "
            "and try `!obtainment` again.",
            delete_after=10,
        )


@bot.command(aliases=["guide"])
async def tutorial(ctx):
    """DM the starter guide plus every category's powers and obtainment methods."""
    try:
        await ctx.message.delete()
    except Exception:
        pass

    setup_embed = discord.Embed(
        title="📖 Seven Sins Bot Tutorial — Start Here",
        description="Follow these steps in order if this is a new server.",
        color=discord.Color.blurple(),
    )
    setup_embed.add_field(
        name="1. Invite and enable intents",
        value=(
            "Invite the bot with the `bot` scope. In the Discord Developer Portal, "
            "enable **Server Members Intent** and **Message Content Intent**, then save."
        ),
        inline=False,
    )
    setup_embed.add_field(
        name="2. Build the server structure",
        value=(
            "Make sure the bot has **Manage Roles**, **Manage Channels**, and "
            "**Moderate Members**. Then run `!setup` once."
        ),
        inline=False,
    )
    setup_embed.add_field(
        name="3. Start a sin trial",
        value=(
            "Run `!sinslist` to see the choices, then use `!trial <sin>` such as "
            "`!trial wrath`. Read the instructions in the trial channel."
        ),
        inline=False,
    )
    setup_embed.add_field(
        name="4. Check your progress",
        value="Use `!mytrial`, `!mystats`, `!history`, and `!coin_power`.",
        inline=False,
    )

    play_embed = discord.Embed(
        title="📖 Tutorial — Roles, Combat, and Myths",
        description="The rest of the bot is optional and unlocks as you play.",
        color=discord.Color.from_rgb(70, 150, 175),
    )
    play_embed.add_field(
        name="Sin abilities",
        value=(
            "Use `!commands` for the complete command list. Most abilities require "
            "the matching sin role and have cooldowns."
        ),
        inline=False,
    )
    play_embed.add_field(
        name="Combat",
        value="Use `!attack @user` to fight and `!heal` to recover HP.",
        inline=False,
    )
    play_embed.add_field(
        name="Myths",
        value=(
            "Run `!myths` to read the lore and abilities. An administrator runs "
            "`!grant_myth @user la_llorona` after `!setup` (which creates the "
            "**MYTHS** category and **La Llorona** role); La Llorona then uses "
            "`!llorona_wail`, `!llorona_veil`, and `!llorona_lure`."
        ),
        inline=False,
    )
    play_embed.add_field(
        name="Complete power-by-power manual",
        value=(
            "After these starter pages, this tutorial also sends the complete "
            "categorized command manual. It covers every listed power for Lust, "
            "Gluttony, Greed, Wrath, Sloth, Envy, Pride, all seven tied virtues, "
            "the standalone virtues, every path, myths, character powers, combat, "
            "meters, and admin tools. Use `!commands` later to request the same "
            "manual again."
        ),
        inline=False,
    )
    play_embed.add_field(
        name="Administrator tools",
        value=(
            "Admins can use `!grant`, `!grant_virtue`, `!force_fall`, `!reset_user`, "
            "and `!strip_all @user`. `!strip_all` affects only the one member named."
        ),
        inline=False,
    )

    try:
        await ctx.author.send(embed=setup_embed)
        await ctx.author.send(embed=play_embed)
        await _send_tutorial_pages(ctx, _category_tutorial_pages())
        # The categorized command manual contains the individual instructions
        # for every power category. Keep it in the tutorial flow so !tutorial
        # is a complete guide rather than only an introduction.
        await all_commands.callback(ctx)
    except discord.Forbidden:
        await ctx.send(
            "❌ I could not DM you. Enable **Allow direct messages from server members** "
            "and run `!tutorial` again.",
            delete_after=10,
        )

@bot.command()
@commands.has_permissions(administrator=True)
async def release_sin(ctx, sin: str):
    sin = sin.lower()
    if sin not in SINS:
        await ctx.send("Invalid sin.")
        return
    data = load_data()
    data["claimed_sins"].pop(sin, None)
    save_data(data)
    await ctx.send(f"**{sin.capitalize()}** is now unclaimed.")

@bot.command()
@commands.has_permissions(administrator=True)
async def grant_virtue(ctx, member: discord.Member, sin: str):
    """Admin: Manually grant a virtue role to a member. Usage: !grant_virtue @user <sin_name>"""
    sin = sin.lower()
    if sin not in VIRTUES:
        await ctx.send(
            f"❌ Invalid sin name: `{sin}`\n"
            f"Virtue is granted by the sin that opposes it. Valid options: "
            f"`{'` | `'.join(VIRTUES.keys())}`\n"
            "Example: `!grant_virtue @user lust` grants the **Chastity** virtue (The Chaste)."
        )
        return
    data = load_data()
    # Also ensure the member has their sin_role set so virtue abilities work
    user = get_user(data, member.id)
    if not user.get("sin_role"):
        user["sin_role"] = sin  # set implicitly if missing, so _virtue_check passes
    await complete_virtue_trial(member, sin, data)
    save_data(data)

    virtue_info = VIRTUES[sin]
    role_name   = virtue_info["role"]
    role_obj    = discord.utils.get(ctx.guild.roles, name=role_name)

    if not role_obj:
        await ctx.send(
            f"⚠️ Data updated for {member.mention}, but **`{role_name}`** doesn't exist on "
            "this server yet. Run `!setup` first, then `!grant_virtue` again."
        )
        return

    # Always try to assign directly so we see the real Discord error if it fails
    try:
        await member.add_roles(role_obj, reason=f"!grant_virtue by {ctx.author}")
        await ctx.send(
            f"✅ **{virtue_info['virtue']}** virtue granted to {member.mention} "
            f"as **{role_name}** (Power {virtue_info['power']})."
        )
    except discord.Forbidden:
        await ctx.send(
            f"❌ **Permission denied.** The bot cannot assign **`{role_name}`**.\n"
            f"Fix: Go to **Server Settings → Roles** and drag the bot's role to the "
            f"**very top** (or at least above `{role_name}`)."
        )
    except discord.HTTPException as e:
        await ctx.send(
            f"❌ Discord API error while assigning **`{role_name}`**: `{e.status} — {e.text}`"
        )

# ───────────────────────────────────────────────────────────────────
# COMMAND: !jealousy_mark @user  (Envy — Role Steal ability)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def jealousy_mark(ctx, target: discord.Member):
    """Mark a target with jealousy. If they don't !envy_check, Envy temporarily steals their role."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("sin_role") != "envy":
        await ctx.send("You must be the fully unlocked holder of Envy to use this.", delete_after=8)
        save_data(data)
        return

    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5)
        save_data(data)
        return

    locked_until = user.get("envy_ability_locked_until", 0) or 0
    if now_ts() < locked_until:
        await ctx.send(
            f"Your envy is suppressed. Ability unlocks {ts_fmt(locked_until)}.", delete_after=10
        )
        save_data(data)
        return

    target_user = get_user(data, target.id)
    target_sin  = target_user.get("sin_role")
    if not target_sin or target_sin not in SINS:
        await ctx.send("Target does not hold a sin role.", delete_after=8)
        save_data(data)
        return
    if target_sin == "pride":
        await ctx.send(
            "Pride stands above Envy. You cannot mark the Bearer of Pride.", delete_after=10
        )
        save_data(data)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot mark yourself.", delete_after=5)
        save_data(data)
        return

    role_cds = user.get("jealousy_role_cds", {})
    cd       = role_cds.get(target_sin, 0) or 0
    if now_ts() < cd:
        await ctx.send(
            f"You've already targeted **{target_sin}** recently. Cooldown: {remaining_fmt(cd)}.",
            delete_after=10,
        )
        save_data(data)
        return

    uid_str      = str(ctx.author.id)
    active_marks = data.setdefault("envy_marks", {})
    if uid_str in active_marks and not active_marks[uid_str].get("resolved"):
        await ctx.send("You already have an active jealousy mark out.", delete_after=8)
        save_data(data)
        return

    expires = now_ts() + 30 * 60
    active_marks[uid_str] = {
        "target_id":  str(target.id),
        "target_sin": target_sin,
        "expires":    expires,
        "resolved":   False,
    }
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    try:
        await ctx.message.delete()
    except Exception:
        pass

    await ch.send(
        "@everyone",
        embed=discord.Embed(
            title="🌑 A Mark of Jealousy Has Been Placed",
            description=(
                "@everyone — Envy has stirred. Someone among you has been **marked with jealousy**.\n\n"
                "The marked one has **30 minutes** to use `!envy_check`.\n"
                "If they stay silent — their power will be **seized by the shadows**.\n\n"
                "⚠️ Only the marked one can act. No one else knows who it is."
            ),
            color=discord.Color.from_rgb(0, 180, 216),
        ),
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )

# ───────────────────────────────────────────────────────────────────
# COMMAND: !envy_check  (counter to jealousy_mark)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def envy_check(ctx):
    """Use this if you think you're the jealousy mark target. If correct, Envy is punished."""
    data   = load_data()
    uid    = str(ctx.author.id)
    marks  = data.get("envy_marks", {})

    envy_uid  = None
    mark_info = None
    for holder_id, info in marks.items():
        if (
            info.get("target_id") == uid
            and not info.get("resolved")
            and now_ts() <= info.get("expires", 0)
        ):
            envy_uid  = holder_id
            mark_info = info
            break

    if not mark_info:
        await ctx.send(
            f"{ctx.author.mention} — you are **not the marked one** (or no mark is active).",
            delete_after=10,
        )
        save_data(data)
        return

    mark_info["resolved"] = True
    envy_holder = ctx.guild.get_member(int(envy_uid))
    envy_user   = get_user(data, int(envy_uid))
    envy_user["corruption"] = envy_user.get("corruption", 0) + 1
    envy_user["envy_ability_locked_until"] = now_ts() + 3600
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="👁️ The Marked One Checked",
        description=(
            f"{ctx.author.mention} **checked themselves** and found the mark of jealousy.\n\n"
            f"The mark dissolved. The Envy holder gains **+1 Corruption** and loses "
            "their jealousy ability for **1 hour**.\n\n"
            "*The hunted outran the hunter.*"
        ),
        color=discord.Color.green(),
    ))

# ───────────────────────────────────────────────────────────────────
# COMMAND: !schizo @user  (Envy — Schizophrenia ability, uses coin flip)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def schizo(ctx, target: discord.Member):
    """Envy ability: flood the channel with fake messages as if from other server members."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("sin_role") != "envy":
        await ctx.send("You must hold the Envy role to use this.", delete_after=5)
        save_data(data)
        return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5)
        save_data(data)
        return

    locked_until = user.get("ability_locked_until", 0) or 0
    if now_ts() < locked_until:
        await ctx.send(
            f"⚠️ **Krodingers Effect** — your ability is locked until {ts_fmt(locked_until)}.",
            delete_after=10,
        )
        save_data(data)
        return

    if target.id == ctx.author.id:
        await ctx.send("You cannot target yourself.", delete_after=5)
        save_data(data)
        return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")
    target_power = SINS[target_sin]["power"] if target_sin and target_sin in SINS else 1
    envy_coins   = ABILITY_COINS["schizo"]
    target_coins = max(1, 1 + target_power // 3)

    winner, roll_a, roll_b = coin_flip(envy_coins, target_coins)

    ch = await trial_channel(ctx.guild) or ctx.channel
    flip_embed = discord.Embed(
        title="🎲 Coin Flip — Envy vs ???",
        description=(
            f"**Envy** rolled **{roll_a}** ({envy_coins} coins)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coin{'s' if target_coins > 1 else ''})\n\n"
        ),
        color=discord.Color.from_rgb(0, 180, 216),
    )

    if winner == "b":
        flip_embed.description += (
            f"**{target.display_name}** resisted the madness. "
            "The schizophrenia backfires — Envy sees phantoms instead."
        )
        await ch.send(embed=flip_embed)
        save_data(data)
        return

    flip_embed.description += "**Envy wins.** Reality fractures…"
    await ch.send(embed=flip_embed)

    members = [
        m for m in ctx.guild.members
        if not m.bot and m.id != target.id and m.id != ctx.author.id
    ]
    if not members:
        save_data(data)
        return

    fake_templates = [
        "i heard {name} was talking behind your back…",
        "did anyone else notice {name} acting weird lately?",
        "i genuinely dont trust {name} anymore ngl",
        "@{name} you good? something feels off",
        "something about {name} is giving me bad vibes today",
        "{name} was telling people some things about you btw",
        "bro {name} literally just messaged me about you lmao",
        "i saw {name} laughing when someone mentioned your name",
    ]

    await ch.send(embed=discord.Embed(
        title="🌀 Reality Fractures",
        description=(
            f"{target.mention} — the voices have found you. "
            "Something is wrong. You can feel it."
        ),
        color=discord.Color.from_rgb(60, 0, 100),
    ))

    for _ in range(3):
        faker = random.choice(members)
        msg   = random.choice(fake_templates).format(name=target.display_name)
        await asyncio.sleep(2)
        await ch.send(
            f"**[Phantom — {faker.display_name}]:** {msg}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !weaken <sin>  (Pride ability 1 — uses coin flip)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def weaken(ctx, sin: str):
    """Pride ability: temporarily reduce a sin's effective power level by 1 for 30 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    sin  = sin.lower()

    if user.get("sin_role") != "pride":
        await ctx.send("You must hold the Pride role to use this.", delete_after=5)
        save_data(data)
        return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5)
        save_data(data)
        return

    locked_until = user.get("ability_locked_until", 0) or 0
    if now_ts() < locked_until:
        await ctx.send(
            f"⚠️ **Krodingers Effect** — your ability is locked until {ts_fmt(locked_until)}.",
            delete_after=10,
        )
        save_data(data)
        return

    if sin not in SINS:
        await ctx.send(
            f"Unknown sin. Choose from: {', '.join(SINS.keys())}", delete_after=8
        )
        save_data(data)
        return
    if sin == "pride":
        await ctx.send("Pride cannot weaken itself.", delete_after=5)
        save_data(data)
        return

    holder_id = data["claimed_sins"].get(sin)
    if not holder_id:
        await ctx.send(f"**{sin.capitalize()}** is not currently claimed by anyone.", delete_after=8)
        save_data(data)
        return

    target_member = ctx.guild.get_member(int(holder_id))
    pride_coins   = ABILITY_COINS["weaken"]
    target_power  = effective_sin_power(sin, data)
    target_coins  = max(1, 1 + target_power // 2)

    winner, roll_a, roll_b = coin_flip(pride_coins, target_coins)

    ch = await trial_channel(ctx.guild) or ctx.channel
    flip_embed = discord.Embed(
        title="🎲 Coin Flip — Pride vs Sin",
        description=(
            f"**Pride** rolled **{roll_a}** ({pride_coins} coins)\n"
            f"**{sin.capitalize()}** rolled **{roll_b}** ({target_coins} coin{'s' if target_coins > 1 else ''})\n\n"
        ),
        color=discord.Color.gold(),
    )

    if winner == "b":
        flip_embed.description += (
            f"**{sin.capitalize()}** resisted! Pride's grasp slipped."
        )
        await ch.send(embed=flip_embed)
        save_data(data)
        return

    flip_embed.description += f"**Pride prevails.** The power of **{sin.capitalize()}** bends."
    await ch.send(embed=flip_embed)

    expires = now_ts() + 30 * 60
    data.setdefault("weakened_sins", {})[sin] = {
        "weakened_by":   str(ctx.author.id),
        "expires":       expires,
        "power_penalty": 1,
    }
    save_data(data)

    await ch.send(embed=discord.Embed(
        title="👑 A Sin Has Been Weakened",
        description=(
            f"**{sin.capitalize()}**'s effective power is reduced by **1** for **30 minutes**.\n"
            f"The Bearer of Pride holds dominion over lesser sins.\n\n"
            f"New power: **{target_power - 1}** | Expires: {ts_fmt(expires)}"
        ),
        color=discord.Color.gold(),
    ))

    if target_member:
        try:
            await target_member.send(
                f"⚠️ The Bearer of Pride has **weakened your sin**. "
                "Your effective power is reduced by 1 for 30 minutes."
            )
        except Exception:
            pass

# ───────────────────────────────────────────────────────────────────
# COMMAND: !claim @user  (Pride ability 2 — NO coin flip)
# ───────────────────────────────────────────────────────────────────

CLAIM_COOLDOWN_SECS = 2 * 3600  # 2 hours

@bot.command()
async def claim(ctx, target: discord.Member):
    """Pride ability: claim a target; all sin holders with equal or lower power must bow or gain marks."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("sin_role") != "pride":
        await ctx.send("You must hold the Pride role to use this.", delete_after=5)
        save_data(data)
        return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5)
        save_data(data)
        return

    locked_until = user.get("ability_locked_until", 0) or 0
    if now_ts() < locked_until:
        await ctx.send(
            f"⚠️ **Krodingers Effect** — your ability is locked until {ts_fmt(locked_until)}.",
            delete_after=10,
        )
        save_data(data)
        return

    cd = user.get("claim_cooldown", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Claim on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot claim yourself.", delete_after=5)
        save_data(data)
        return

    target_user = get_user(data, target.id)
    target_sin  = target_user.get("sin_role")
    if not target_sin or target_sin not in SINS:
        await ctx.send("Target does not hold a sin role.", delete_after=8)
        save_data(data)
        return

    target_power = effective_sin_power(target_sin, data)
    user["claim_cooldown"] = now_ts() + CLAIM_COOLDOWN_SECS

    ch = await trial_channel(ctx.guild) or ctx.channel

    # Collect all sin holders with power <= target_power (excluding Pride bearer)
    to_bow: list[tuple[discord.Member, str, int]] = []
    for s, holder_id in data["claimed_sins"].items():
        if s == "pride" or holder_id == str(ctx.author.id):
            continue
        eff_power = effective_sin_power(s, data)
        if eff_power <= target_power:
            m = ctx.guild.get_member(int(holder_id))
            if m:
                to_bow.append((m, s, eff_power))

    if not to_bow:
        await ctx.send("No eligible sin holders found below that power level.", delete_after=8)
        user["claim_cooldown"] = 0
        save_data(data)
        return

    bow_embed = discord.Embed(
        title=f"👑 {ctx.author.display_name} Has Claimed Dominion",
        description=(
            f"The Bearer of Pride has claimed **{target.display_name}**.\n\n"
            "All sin holders of equal or lesser power must **react 🙇** to this message "
            "within their time window — or gain a **Mark of Insecurity**.\n\n"
        ),
        color=discord.Color.gold(),
    )
    subjects: dict = {}
    for m, s, p in to_bow:
        window_secs = bow_window_secs(p)
        window_mins = window_secs // 60
        bow_embed.add_field(
            name=m.display_name,
            value=(
                f"**{SINS[s]['final_role']}** (Power {p})\n"
                f"Time to bow: **{window_mins} min**"
            ),
            inline=True,
        )
        subjects[str(m.id)] = {
            "sin":       s,
            "power":     p,
            "deadline":  now_ts() + window_secs,
            "bowed":     False,
            "processed": False,
        }

    msg = await ch.send(
        f"@everyone — {ctx.author.mention} commands attention.",
        embed=bow_embed,
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )
    await msg.add_reaction("🙇")

    data.setdefault("active_claims", {})[str(msg.id)] = {
        "claimer_id": str(ctx.author.id),
        "target_id":  str(target.id),
        "msg_id":     str(msg.id),
        "channel_id": str(ch.id),
        "subjects":   subjects,
        "created_ts": now_ts(),
    }
    save_data(data)

# ───────────────────────────────────────────────────────────────────
# COMMAND: !marks [@user]  (View marks of insecurity)
# ───────────────────────────────────────────────────────────────────

@bot.command()
async def marks(ctx, target: discord.Member = None):
    """View marks of insecurity for yourself or another member."""
    target = target or ctx.author
    data   = load_data()
    uid    = str(target.id)
    user   = data["users"].get(uid, {})

    mark_count = user.get("marks_of_insecurity", 0)
    sin_held   = user.get("sin_role")
    power      = SINS.get(sin_held, {}).get("power", 0) if sin_held else 0
    threshold  = krodingers_threshold(power) if power else 6

    locked_until = user.get("ability_locked_until", 0) or 0
    krodingers_active = now_ts() < locked_until

    embed = discord.Embed(
        title=f"😰 Marks of Insecurity — {target.display_name}",
        color=discord.Color.dark_orange() if mark_count > 0 else discord.Color.green(),
    )
    filled = min(mark_count, threshold)
    bar    = "▓" * filled + "░" * (threshold - filled)
    embed.add_field(
        name="Marks",
        value=f"`{bar}` **{mark_count} / {threshold}** to Krodingers Effect",
        inline=False,
    )
    if krodingers_active:
        embed.add_field(
            name="⚠️ Krodingers Effect ACTIVE",
            value=f"Ability locked until {ts_fmt(locked_until)}.",
            inline=False,
        )
    elif mark_count >= threshold:
        embed.add_field(
            name="⚠️ Krodingers Effect",
            value="This soul has worried too long. Their **ability is temporarily lost**.",
            inline=False,
        )
    elif mark_count > 0:
        embed.add_field(
            name="Status",
            value=f"**{threshold - mark_count}** more marks until Krodingers Effect.",
            inline=False,
        )
    else:
        embed.add_field(name="Status", value="No marks. Confidence holds.", inline=False)

    save_data(data)
    await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════════════
# ░░ GLUTTONY ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

def _gluttony_role_check(user: dict) -> bool:
    return user.get("sin_role") == "gluttony" and not user.get("fallen")

@bot.command()
async def gorge(ctx):
    """(Gluttony) Devour the server's energy — gain bonus clash coins based on recent activity."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _gluttony_role_check(user):
        await ctx.send("Only the Devoured may gorge.", delete_after=5); save_data(data); return

    cd = user["gluttony_ability_cds"].get("gorge", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Gorge on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    # Count server messages in last GORGE_ACTIVITY_WINDOW seconds
    # We approximate using a recent_messages count stored each loop
    gorge_until   = now_ts() + GORGE_DURATION
    user["gorge_active_until"] = gorge_until
    user["gluttony_ability_cds"]["gorge"] = now_ts() + 45 * 60  # 45-min cd

    # Bonus coins: we set in clash_power_bonus; will be cleared when gorge expires
    bonus = min(3, max(1, 1))  # baseline +1; gorge message count tracked in on_message
    user["clash_power_bonus"] = bonus
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🍽️ The Devoured Gorges",
        description=(
            f"{ctx.author.mention} feeds on the server's energy.\n\n"
            f"**+1 clash coin** for the next **15 minutes** — growing with every message that flows.\n"
            "The hungrier the server, the stronger the feast."
        ),
        color=discord.Color.from_rgb(180, 80, 0),
    ))

@bot.command()
async def feast(ctx, target: discord.Member):
    """(Gluttony) Coin flip — curse a target to include a food emoji in every message or gain starvation marks."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _gluttony_role_check(user):
        await ctx.send("Only the Devoured may feast upon others.", delete_after=5); save_data(data); return

    cd = user["gluttony_ability_cds"].get("feast", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Feast on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot curse yourself.", delete_after=5); save_data(data); return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")
    target_power = SINS[target_sin]["power"] if target_sin and target_sin in SINS else 1
    gluttony_coins = max(1, 1 + (user.get("clash_power_bonus") or 0))
    target_coins   = max(1, target_power // 2)

    winner, roll_a, roll_b = coin_flip(gluttony_coins, target_coins)
    ch = await trial_channel(ctx.guild) or ctx.channel

    flip_embed = discord.Embed(
        title="🎲 Coin Flip — Feast",
        description=(
            f"**Gluttony** rolled **{roll_a}** ({gluttony_coins} coins)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coins)\n\n"
        ),
        color=discord.Color.from_rgb(180, 80, 0),
    )
    if winner == "b":
        flip_embed.description += f"**{target.display_name}** resisted the hunger."
        await ch.send(embed=flip_embed); save_data(data); return

    flip_embed.description += f"**Hunger takes hold.** {target.display_name} is cursed."
    await ch.send(embed=flip_embed)

    expires = now_ts() + FEAST_DURATION
    data.setdefault("feast_cursed", {})[str(target.id)] = {
        "expires": expires, "marks": 0, "by_id": str(ctx.author.id),
    }
    user["gluttony_ability_cds"]["feast"] = now_ts() + int(1.5 * 3600)
    save_data(data)

    await ch.send(embed=discord.Embed(
        title="🍴 A Hunger Curse Falls",
        description=(
            f"{target.mention} is cursed with **bottomless hunger** for **20 minutes**.\n\n"
            "Every message must contain a food emoji 🍕🍔🌮🍜🍩 or worse.\n"
            "3 violations = **-1 clash power for 1 hour**."
        ),
        color=discord.Color.from_rgb(220, 100, 0),
    ))
    try:
        await target.send(
            "🍴 You've been cursed with **bottomless hunger**. Every message you send must "
            "include a food emoji (🍕🍔🌮🍜🍩🥩🍗 or similar) for the next 20 minutes. "
            "3 violations = -1 clash power."
        )
    except Exception:
        pass

@bot.command()
async def devour(ctx, target: discord.Member):
    """(Gluttony) Swallow a player whole — they cannot send any messages or commands for 5 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _gluttony_role_check(user):
        await ctx.send("Only the Devoured may swallow others whole.", delete_after=5); save_data(data); return

    cd = user["gluttony_ability_cds"].get("devour", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Devour on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot devour yourself. Even Gluttony has limits.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user = get_user(data, target.id)
    devoured_until = now_ts() + 5 * 60   # 5 minutes

    target_user["devoured_until"] = devoured_until
    user["gluttony_ability_cds"]["devour"] = now_ts() + 3 * 3600   # 3hr CD
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🌑 DEVOURED",
        description=(
            f"{ctx.author.mention} opens wide and **swallows** {target.mention} whole.\n\n"
            f"*They're not gone... just digesting.*\n\n"
            f"🤐 {target.mention} cannot send any messages or commands for **5 minutes**.\n"
            f"Expires: {ts_fmt(devoured_until)}"
        ),
        color=discord.Color.from_rgb(160, 50, 0),
    ))
    try:
        await target.send(
            f"🌑 **{ctx.author.display_name}** devoured you. "
            "You cannot send any messages for **5 minutes**. Sit tight."
        )
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════
# ░░ GREED ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

def _anger_bar(meter: int) -> str:
    filled = meter // 10
    return "🔴" * filled + "⚫" * (10 - filled) + f"  **{meter}%**"

def _greed_coins(user: dict) -> int:
    base   = ABILITY_COIN_POWER["greed_steal"]
    frenzy = 2 if user.get("frenzy_active") else 0
    bonus  = user.get("clash_power_bonus", 0) or 0
    return base + frenzy + bonus

def _effective_coins(user: dict) -> int:
    """Effective coins for any clash — applies bonus/penalty/path passives."""
    base    = SINS.get(user.get("sin_role", ""), {}).get("power", 1)
    bonus   = user.get("clash_power_bonus", 0) or 0
    penalty_until = user.get("clash_penalty_until") or 0
    penalty = user.get("clash_power_penalty", 0) if now_ts() < penalty_until else 0
    # TACHT passive: +1 coin while burst is active
    if user.get("path") == "tacht" and now_ts() < (user.get("tacht_burst_until") or 0):
        bonus += 1
    # Justice !condemn passive: condemned players lose 1 effective coin
    if now_ts() < (user.get("condemned_until") or 0):
        penalty += 1
    # Attack path passive: +1 coin on offense (caller may add another +1 manually for attack abilities)
    return max(1, base + bonus - penalty)

def _path_cd(user: dict, key: str, cd_secs: int) -> Optional[str]:
    """Path ability cooldown check. TACHT path gets 25% reduction on path CDs."""
    cds  = user.setdefault("path_ability_cds", {})
    ts   = cds.get(key, 0) or 0
    if now_ts() < ts:
        return f"**{key}** on cooldown: {remaining_fmt(ts)}."
    reduction = 0.75 if user.get("path") == "tacht" else 1.0
    cds[key] = now_ts() + int(cd_secs * reduction)
    return None

def _needs_path(user: dict, path: str) -> bool:
    return user.get("path") == path and (user.get("sin_role") or user.get("completed_virtues"))

def _has_role(user: dict) -> bool:
    return bool(user.get("sin_role")) and not user.get("fallen")

@bot.command()
async def steal_ability(ctx, target: discord.Member):
    """(Greed) Clash for a target's primary ability — steal it if you win."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "greed":
        await ctx.send("Only the False King may steal.", delete_after=5); save_data(data); return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5); save_data(data); return

    # Daily limit reset
    reset_ts = user.get("greed_steals_reset_ts") or 0
    if now_ts() > reset_ts:
        user["greed_steals_today"]    = 0
        user["greed_steals_reset_ts"] = now_ts() + 86400

    if user["greed_steals_today"] >= GREED_MAX_STEALS_PER_DAY:
        await ctx.send(
            f"You've stolen **{GREED_MAX_STEALS_PER_DAY}** abilities today. Your greed resets tomorrow.",
            delete_after=10,
        ); save_data(data); return

    if target.id == ctx.author.id:
        await ctx.send("You cannot steal from yourself.", delete_after=5); save_data(data); return

    # Stop time check — if Pride has frozen time, Greed can't act
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen. No ability clashes can occur.", delete_after=10)
        save_data(data); return

    target_user = get_user(data, target.id)
    target_sin  = target_user.get("sin_role")
    if not target_sin or target_sin not in SINS:
        await ctx.send("Target does not hold a sin role.", delete_after=8); save_data(data); return

    ability_key = SIN_PRIMARY_ABILITY[target_sin]
    target_coins_val = ABILITY_COIN_POWER.get(ability_key, 2)

    # Apply bloodlust bonus to target's coins if they have it
    if target_user.get("bloodlust_active") and now_ts() < (target_user.get("bloodlust_until") or 0):
        target_coins_val += 1

    greed_coins_val = _greed_coins(user)
    winner, roll_a, roll_b = coin_flip(greed_coins_val, target_coins_val)

    ch = await trial_channel(ctx.guild) or ctx.channel
    flip_embed = discord.Embed(
        title="🎲 Ability Clash — Greed Steals",
        description=(
            f"**Greed** rolled **{roll_a}** ({greed_coins_val} coins)\n"
            f"**{target.display_name}** ({ability_key.replace('_', ' ')}) rolled **{roll_b}** ({target_coins_val} coins)\n\n"
        ),
        color=discord.Color.from_rgb(200, 170, 0),
    )

    if winner == "b":
        # Greed loses — anger rises
        flip_embed.description += f"**{target.display_name}** held on. Greed grows angrier."
        await ch.send(embed=flip_embed)

        old_anger = user.get("anger_meter", 0)
        new_anger = min(100, old_anger + ANGER_METER_PER_LOSS)
        user["anger_meter"] = new_anger

        if old_anger < 100 <= new_anger:
            user["frenzy_active"] = True
            user["frenzy_used"]   = False
            await ch.send(embed=discord.Embed(
                title="🔴 FRENZY — The False King Snaps",
                description=(
                    f"{ctx.author.mention}'s anger has hit **100%**.\n\n"
                    "**FRENZY MODE** — They gain the ability **\"I always get what I WANT!\"**\n"
                    "Use `!i_always_get_what_i_want @user buff/debuff` to assert dominance.\n"
                    "Use `!frenzy_clash @user` for one buffed clash. **Fail it — lose the sin.**"
                ),
                color=discord.Color.red(),
            ))
        else:
            await ch.send(embed=discord.Embed(
                description=f"😤 Anger: {_anger_bar(new_anger)}",
                color=discord.Color.dark_red(),
            ))
        save_data(data); return

    # Greed wins — steal the ability
    flip_embed.description += f"**Greed wins.** The ability is seized."
    await ch.send(embed=flip_embed)

    expires = now_ts() + STOLEN_ABILITY_DURATION
    data.setdefault("stolen_abilities", []).append({
        "holder_id":          str(ctx.author.id),
        "ability_key":        ability_key,
        "expires":            expires,
        "original_holder_id": str(target.id),
    })

    user["greed_steals_today"] += 1
    now = now_ts()
    recent = [t for t in user.get("greed_recent_steals", []) if now - t < GREED_LOSE_YOURSELF_WINDOW]
    recent.append(now)
    user["greed_recent_steals"] = recent

    save_data(data)
    dur_min = STOLEN_ABILITY_DURATION // 60

    await ch.send(embed=discord.Embed(
        title="💰 Stolen",
        description=(
            f"{ctx.author.mention} has **seized** {target.mention}'s **{ability_key.replace('_', ' ')}** "
            f"for **{dur_min} minutes**.\n\n"
            "It will return when Greed's grip loosens."
        ),
        color=discord.Color.from_rgb(200, 170, 0),
    ))

    # Lose yourself check — too many steals in short window
    if len(recent) >= GREED_LOSE_YOURSELF_THRESH:
        user["lose_yourself_until"] = now_ts() + 3600
        user["corruption"] = user.get("corruption", 0) + 1
        user["greed_recent_steals"] = []
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="😵 Greed Loses Themselves",
            description=(
                f"{ctx.author.mention} has stolen too much, too fast. "
                "They are **losing themselves** — effective power reduced for **1 hour**, **+1 Corruption**."
            ),
            color=discord.Color.dark_purple(),
        ))
        user["clash_power_penalty"] = 1
        user["clash_penalty_until"] = now_ts() + 3600
        save_data(data)

    try:
        await target.send(
            f"⚠️ Your **{ability_key.replace('_', ' ')}** has been **stolen** by Greed. "
            f"It returns in **{dur_min} minutes**."
        )
    except Exception:
        pass

@bot.command(name="i_always_get_what_i_want")
async def i_always_get_what_i_want(ctx, target: discord.Member, effect: str):
    """(Greed frenzy) Buff or debuff any member. Use: !i_always_get_what_i_want @user buff/debuff"""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "greed":
        await ctx.send("Only the False King may use this.", delete_after=5); save_data(data); return
    if not user.get("frenzy_active"):
        await ctx.send("You are not in frenzy mode.", delete_after=5); save_data(data); return
    if user.get("frenzy_used"):
        await ctx.send("You already used the frenzy buff/debuff.", delete_after=5); save_data(data); return

    effect = effect.lower().strip()
    if effect not in ("buff", "debuff"):
        await ctx.send("Specify `buff` or `debuff`.", delete_after=5); save_data(data); return

    target_user = get_user(data, target.id)
    user["frenzy_used"] = True

    if effect == "buff":
        target_user["clash_power_bonus"]  = (target_user.get("clash_power_bonus") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 1800  # 30 min
    else:
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 1800

    save_data(data)
    ch = await trial_channel(ctx.guild) or ctx.channel
    icon = "⬆️" if effect == "buff" else "⬇️"
    await ch.send(embed=discord.Embed(
        title=f"👑 {icon} Greed Asserts Dominance",
        description=(
            f"{ctx.author.mention} has **{'buffed' if effect == 'buff' else 'debuffed'}** "
            f"{target.mention}.\n\n"
            f"Their clash power is {'**+1**' if effect == 'buff' else '**-1**'} for **30 minutes**."
        ),
        color=discord.Color.gold() if effect == "buff" else discord.Color.dark_red(),
    ))

@bot.command()
async def frenzy_clash(ctx, target: discord.Member):
    """(Greed frenzy) One final buffed clash — win or lose your sin."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "greed":
        await ctx.send("Only the False King may clash.", delete_after=5); save_data(data); return
    if not user.get("frenzy_active"):
        await ctx.send("You are not in frenzy mode.", delete_after=5); save_data(data); return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")
    target_power = SINS[target_sin]["power"] if target_sin in SINS else 1

    greed_coins  = _greed_coins(user)  # includes +2 frenzy bonus already
    target_coins = max(1, target_power // 2 + (1 if target_user.get("bloodlust_active") else 0))

    winner, roll_a, roll_b = coin_flip(greed_coins, target_coins)
    ch = await trial_channel(ctx.guild) or ctx.channel

    await ch.send(embed=discord.Embed(
        title="🎲 FRENZY CLASH",
        description=(
            f"**Greed** rolled **{roll_a}** ({greed_coins} coins — FRENZY BUFFED)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coins)\n\n"
        ) + (
            f"**Greed wins.** The frenzy subsides, satisfied."
            if winner == "a" else
            f"**DEFEATED.** The rage broke. The False King falls."
        ),
        color=discord.Color.red(),
    ))

    user["frenzy_active"] = False
    user["anger_meter"]   = 0

    if winner == "b":
        save_data(data)
        await fall_from_grace(ctx.author, "Lost the Frenzy Clash. The rage consumed them.", data)
    save_data(data)

# ═══════════════════════════════════════════════════════════════════
# ░░ WRATH ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

@bot.command()
async def rage_strike(ctx, target: discord.Member):
    """(Wrath) Force a target into an immediate coin-flip clash. Win to reduce their clash power."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "wrath":
        await ctx.send("Only Crimson Heir may rage-strike.", delete_after=5); save_data(data); return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5); save_data(data); return

    cd = user["wrath_ability_cds"].get("rage_strike", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Rage Strike on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot strike yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")

    # Pride passive evasion
    if target_sin == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        ch = await trial_channel(ctx.guild) or ctx.channel
        await ch.send(embed=discord.Embed(
            description=f"⏸️ {target.mention} **slipped through time.** The Rage Strike found nothing.",
            color=discord.Color.purple(),
        )); return

    bloodlust_bonus = 1 if (user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0)) else 0
    wrath_coins  = max(1, ABILITY_COIN_POWER["wrath_rage_strike"] + bloodlust_bonus)
    target_coins = _effective_coins(target_user)

    winner, roll_a, roll_b = coin_flip(wrath_coins, target_coins)
    ch = await trial_channel(ctx.guild) or ctx.channel

    flip_embed = discord.Embed(
        title="💢 Rage Strike",
        description=(
            f"**Wrath** rolled **{roll_a}** ({wrath_coins} coins)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coins)\n\n"
        ),
        color=discord.Color.red(),
    )
    user["wrath_ability_cds"]["rage_strike"] = now_ts() + 45 * 60

    if winner == "a":
        flip_embed.description += f"**Strike lands.** {target.display_name} is stunned by rage."
        await ch.send(embed=flip_embed)
        target_user["clash_power_penalty"] = max(target_user.get("clash_power_penalty", 0), 1)
        target_user["clash_penalty_until"] = now_ts() + 30 * 60
        save_data(data)
        await ch.send(embed=discord.Embed(
            description=f"💢 {target.mention} is **stunned** — clash power **-1** for **30 minutes**.",
            color=discord.Color.dark_red(),
        ))
        # Bloodlust loss check
        if user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0):
            pass  # They won so bloodlust stays
    else:
        flip_embed.description += f"**{target.display_name}** shrugged it off."
        await ch.send(embed=flip_embed)
        # Bloodlust — losing while active ends it + corruption
        if user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0):
            user["bloodlust_active"] = False
            user["corruption"] = user.get("corruption", 0) + 1
            save_data(data)
            await ch.send(embed=discord.Embed(
                description=f"🩸 {ctx.author.mention}'s **Bloodlust breaks.** Lost the strike, gained **+1 Corruption**.",
                color=discord.Color.dark_red(),
            ))
    save_data(data)

@bot.command()
async def bloodlust(ctx):
    """(Wrath) Toggle Bloodlust: +1 coin on all clashes for 20 min — but lose a clash and lose Bloodlust + gain corruption."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "wrath":
        await ctx.send("Only Crimson Heir may enter bloodlust.", delete_after=5); save_data(data); return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5); save_data(data); return

    cd = user["wrath_ability_cds"].get("bloodlust", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Bloodlust on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    if user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0):
        await ctx.send("Bloodlust is already active.", delete_after=5); save_data(data); return

    until = now_ts() + WRATH_BLOODLUST_DURATION
    user["bloodlust_active"] = True
    user["bloodlust_until"]  = until
    user["wrath_ability_cds"]["bloodlust"] = now_ts() + 7200  # 2hr cd
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🩸 Bloodlust Rises",
        description=(
            f"{ctx.author.mention} enters **Bloodlust**.\n\n"
            "**+1 clash coin** on every clash for **20 minutes**.\n\n"
            "⚠️ Lose **any** clash while active = **+1 Corruption** and Bloodlust ends immediately."
        ),
        color=discord.Color.from_rgb(180, 0, 0),
    ))

# ═══════════════════════════════════════════════════════════════════
# ░░ SLOTH ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

def _laziness_bar(meter: int) -> str:
    filled = meter // 10
    return "😴" * filled + "⬜" * (10 - filled) + f"  **{meter}%**"

def _sloth_role_check(user: dict) -> bool:
    return user.get("sin_role") == "sloth" and not user.get("fallen")

def _sloth_ability_use(user: dict, key: str, cd_secs: int, data: dict) -> Optional[str]:
    """Check and apply sloth ability: returns error string if blocked, else None."""
    # Sleepwalker halves all cooldowns
    multiplier = 0.5 if (user.get("sleepwalker_active_until") or 0) > now_ts() else 1.0
    cd = (user.get("sloth_ability_cds") or {}).get(key, 0) or 0
    if now_ts() < cd:
        return f"**{key}** on cooldown: {remaining_fmt(cd)}."
    # Laziness meter check
    laziness = user.get("laziness_meter", 0)
    if laziness >= 100:
        return "Your laziness meter is full — enter `!deep_sleep` to reset."
    # Apply laziness increase
    user["laziness_meter"] = min(100, laziness + LAZINESS_METER_PER_USE)
    user.setdefault("sloth_ability_cds", {})[key] = now_ts() + int(cd_secs * multiplier)
    if user["laziness_meter"] >= 100:
        user["deep_sleep_until"] = now_ts() + DEEP_SLEEP_DURATION
        # Will be announced by caller
    return None

@bot.command()
async def force_lazy(ctx, target: discord.Member):
    """(Sloth) Force a target to abbreviate all their words for 30 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _sloth_role_check(user):
        await ctx.send("Only the Vessel of Sloth may do this.", delete_after=5); save_data(data); return

    err = _sloth_ability_use(user, "force_lazy", SLOTH_ABILITY_COOLDOWN, data)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot target yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user = get_user(data, target.id)
    target_sin  = target_user.get("sin_role")
    if target_sin == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        await ctx.send(f"⏸️ {target.mention} slipped through time. Your laziness found nobody.", delete_after=8)
        return

    expires = now_ts() + 1800  # 30 min
    data.setdefault("force_lazy_targets", {})[str(target.id)] = {
        "expires": expires, "by_id": str(ctx.author.id),
    }

    forced_deep_sleep = user.get("laziness_meter", 0) >= 100
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="😴 Laziness Spreads",
        description=(
            f"{target.mention} is hit with **crushing lethargy**.\n\n"
            "For the next **30 minutes**, every word in every message must be abbreviated "
            "(max 4 characters). Normal speech is too much effort.\n\n"
            "*The Vessel of Sloth yawns in the distance.*"
        ),
        color=discord.Color.from_rgb(100, 100, 150),
    ))
    if forced_deep_sleep:
        await _announce_deep_sleep(ctx.author, user, ch, data, forced=True)
    try:
        await target.send(
            "😴 You've been hit with **Sloth's laziness** for 30 minutes. "
            "Every word you send must be abbreviated (max 4 chars). Type slow, keep it short."
        )
    except Exception:
        pass

@bot.command()
async def slowdown(ctx, target: discord.Member):
    """(Sloth) Force a target to wait 45 seconds between messages for 20 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _sloth_role_check(user):
        await ctx.send("Only the Vessel of Sloth may do this.", delete_after=5); save_data(data); return

    err = _sloth_ability_use(user, "slowdown", 2 * SLOTH_ABILITY_COOLDOWN, data)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot target yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user = get_user(data, target.id)
    if target_user.get("sin_role") == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        await ctx.send(f"⏸️ {target.mention} evaded. Time slipped away.", delete_after=8); return

    expires = now_ts() + 20 * 60
    data.setdefault("slowdown_targets", {})[str(target.id)] = {
        "expires": expires, "last_msg_ts": 0, "by_id": str(ctx.author.id),
    }

    forced_deep_sleep = user.get("laziness_meter", 0) >= 100
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="⏱️ Time Slows",
        description=(
            f"{target.mention}'s reactions **slow to a crawl**.\n\n"
            "They must wait **45 seconds** between messages for **20 minutes**. "
            "Messages sent too quickly will be **deleted**.\n\n"
            "*Even breathing takes effort now.*"
        ),
        color=discord.Color.from_rgb(80, 80, 120),
    ))
    if forced_deep_sleep:
        await _announce_deep_sleep(ctx.author, user, ch, data, forced=True)
    try:
        await target.send(
            "⏱️ You've been hit with Sloth's **slowdown** for 20 minutes. "
            f"You must wait **{SLOW_TYPE_INTERVAL} seconds** between messages or they'll be deleted."
        )
    except Exception:
        pass

@bot.command()
async def force_sleep(ctx, target: discord.Member):
    """(Sloth) Coin flip — put a target into deep sleep (timed out) for 10 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _sloth_role_check(user):
        await ctx.send("Only the Vessel of Sloth may do this.", delete_after=5); save_data(data); return

    err = _sloth_ability_use(user, "force_sleep", 3 * SLOTH_ABILITY_COOLDOWN, data)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot target yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user = get_user(data, target.id)
    if target_user.get("sin_role") == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        await ctx.send(f"⏸️ {target.mention} evaded. They slipped out of time.", delete_after=8); return

    sloth_coins  = ABILITY_COIN_POWER["sloth_sleep"]
    target_sin   = target_user.get("sin_role")
    target_coins = _effective_coins(target_user)

    winner, roll_a, roll_b = coin_flip(sloth_coins, target_coins)
    ch = await trial_channel(ctx.guild) or ctx.channel

    flip_embed = discord.Embed(
        title="🎲 Coin Flip — Force Sleep",
        description=(
            f"**Sloth** rolled **{roll_a}** ({sloth_coins} coins)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coins)\n\n"
        ),
        color=discord.Color.from_rgb(80, 80, 120),
    )
    forced_deep_sleep = user.get("laziness_meter", 0) >= 100

    if winner == "b":
        flip_embed.description += f"**{target.display_name}** stayed awake."
        await ch.send(embed=flip_embed)
        if forced_deep_sleep:
            await _announce_deep_sleep(ctx.author, user, ch, data, forced=True)
        save_data(data); return

    flip_embed.description += f"**Sleep takes {target.display_name}.**"
    await ch.send(embed=flip_embed)

    sleep_duration = timedelta(minutes=10)
    try:
        await target.timeout(sleep_duration, reason="Sloth force sleep ability")
    except Exception:
        pass

    target_user["slow_type_until"] = now_ts() + 20 * 60  # also wakes slow-typed for 20 min
    save_data(data)

    await ch.send(embed=discord.Embed(
        title="😴 Deep Sleep",
        description=(
            f"{target.mention} has been **put to sleep**.\n\n"
            "They are timed out for **10 minutes** and will wake up "
            "needing to **type slowly** for 20 minutes after."
        ),
        color=discord.Color.dark_blue(),
    ))
    if forced_deep_sleep:
        await _announce_deep_sleep(ctx.author, user, ch, data, forced=True)
    save_data(data)

async def _announce_deep_sleep(member: discord.Member, user: dict, ch, data: dict, forced: bool = False):
    user["deep_sleep_until"] = now_ts() + DEEP_SLEEP_DURATION
    label = "Forced" if forced else "Voluntary"
    count = user.get("deep_sleep_count", 0) if not forced else None

    try:
        await member.timeout(timedelta(minutes=15), reason="Sloth deep sleep")
    except Exception:
        pass

    user["slow_type_until"] = now_ts() + DEEP_SLEEP_DURATION + 20 * 60  # type slow after waking
    user["laziness_meter"]  = 0

    desc = (
        f"{member.mention} has collapsed into **Deep Sleep** ({label}).\n\n"
        "They are timed out for **15 minutes** and will wake up requiring slow typing for 20 minutes."
    )
    if count is not None:
        desc += f"\n\n*Voluntary deep sleeps: **{count}/{DEEP_SLEEP_THRESHOLD}** toward Sleepwalker.*"

    await ch.send(embed=discord.Embed(
        title="💤 Deep Sleep",
        description=desc,
        color=discord.Color.dark_blue(),
    ))

@bot.command()
async def deep_sleep(ctx):
    """(Sloth) Voluntarily enter deep sleep. After 5 times, unlock the Sleepwalker ability."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _sloth_role_check(user):
        await ctx.send("Only the Vessel of Sloth may sleep.", delete_after=5); save_data(data); return

    if now_ts() < (user.get("deep_sleep_until") or 0):
        await ctx.send("You're already asleep.", delete_after=5); save_data(data); return

    user["deep_sleep_count"] = user.get("deep_sleep_count", 0) + 1
    count = user["deep_sleep_count"]
    ch    = await trial_channel(ctx.guild) or ctx.channel

    await _announce_deep_sleep(ctx.author, user, ch, data, forced=False)

    if count >= DEEP_SLEEP_THRESHOLD and not user.get("sleepwalker_unlocked"):
        user["sleepwalker_unlocked"] = True
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🌙 The Sleepwalker Awakens",
            description=(
                f"{ctx.author.mention} has surrendered to sleep **{DEEP_SLEEP_THRESHOLD} times**.\n\n"
                "The laziness is so complete it becomes its own power. "
                "**Sleepwalker** is now unlocked. Use `!sleepwalker` to activate."
            ),
            color=discord.Color.from_rgb(20, 20, 80),
        ))
    else:
        save_data(data)

@bot.command()
async def sleepwalker(ctx):
    """(Sloth secret ability) Unlocked after 5 deep sleeps. Halves all cooldowns and gives +1 clash coin for 1 hour."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _sloth_role_check(user):
        await ctx.send("Only the Vessel of Sloth may use this.", delete_after=5); save_data(data); return
    if not user.get("sleepwalker_unlocked"):
        await ctx.send("You haven't unlocked Sleepwalker yet. Enter `!deep_sleep` 5 times first.", delete_after=8)
        save_data(data); return

    cd = (user.get("sloth_ability_cds") or {}).get("sleepwalker", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Sleepwalker on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    until = now_ts() + 3600
    user["sleepwalker_active_until"] = until
    user["clash_power_bonus"]        = (user.get("clash_power_bonus") or 0) + 1
    user.setdefault("sloth_ability_cds", {})["sleepwalker"] = now_ts() + 12 * 3600  # 12hr cd
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🌙 Sleepwalker Mode",
        description=(
            f"{ctx.author.mention} moves through the world asleep but unstoppable.\n\n"
            "For **1 hour**:\n"
            "• All Sloth ability cooldowns are **halved**\n"
            "• **+1 clash coin** on every clash\n"
            "• Type-slow penalties do not affect them\n\n"
            "*They don't need to be awake to be dangerous.*"
        ),
        color=discord.Color.from_rgb(20, 20, 100),
    ))

# ═══════════════════════════════════════════════════════════════════
# ░░ PRIDE — STOP TIME ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

@bot.command()
async def stop_time(ctx, mode: str = "freeze"):
    """(Pride) Stop Time — freeze the server OR use as passive evade. Unlocked via recognition."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "pride":
        await ctx.send("Only the Bearer of Pride commands time.", delete_after=5); save_data(data); return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5); save_data(data); return
    if not user.get("stop_time_unlocked"):
        rec = user.get("pride_recognition", 0)
        await ctx.send(
            f"Stop Time is not yet unlocked. Recognition: **{rec}/{PRIDE_RECOGNITION_THRESHOLD}**.\n"
            "Gain recognition by others bowing to your `!claim` commands.",
            delete_after=12,
        ); save_data(data); return

    cd = user.get("stop_time_cd") or 0
    if now_ts() < cd:
        await ctx.send(f"Stop Time on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    user["stop_time_cd"] = now_ts() + STOP_TIME_COOLDOWN
    user["speaking_restricted_until"] = now_ts() + STOP_TIME_SPEAK_BAN  # 5-min speak ban

    mode = mode.lower().strip()
    ch   = await trial_channel(ctx.guild) or ctx.channel

    if mode == "passive":
        user["stop_time_passive"] = True
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="⏸️ Time Awaits",
            description=(
                f"{ctx.author.mention} holds a fragment of stopped time.\n\n"
                "The **next ability used against Pride** will be **automatically evaded**. "
                "Once triggered, the passive is consumed.\n\n"
                f"🔇 The Bearer of Pride cannot speak for **5 minutes**."
            ),
            color=discord.Color.from_rgb(80, 0, 160),
        ))
    else:
        # Active freeze
        until = now_ts() + STOP_TIME_DURATION
        data["stop_time_active"] = True
        data["stop_time_until"]  = until
        save_data(data)

        await ch.send(
            "@everyone",
            embed=discord.Embed(
                title="⏸️ TIME STOPS",
                description=(
                    f"{ctx.author.mention} has **stopped time**.\n\n"
                    "For the next **2 minutes**, **no ability clashes can occur**. "
                    "Pride is untouchable.\n\n"
                    f"🔇 The Bearer of Pride cannot speak for **5 minutes** after this."
                ),
                color=discord.Color.from_rgb(80, 0, 160),
            ),
            allowed_mentions=discord.AllowedMentions(everyone=True),
        )

        await asyncio.sleep(STOP_TIME_DURATION)
        data = load_data()
        data["stop_time_active"] = False
        save_data(data)
        await ch.send(embed=discord.Embed(
            description="▶️ Time resumes. The moment passes.",
            color=discord.Color.from_rgb(60, 0, 120),
        ))

@bot.command()
async def recognition(ctx):
    """(Pride) Check your current recognition meter toward Stop Time."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    rec  = user.get("pride_recognition", 0)
    unlocked = user.get("stop_time_unlocked", False)

    filled = min(rec, PRIDE_RECOGNITION_THRESHOLD)
    bar    = "👑" * filled + "⬜" * (PRIDE_RECOGNITION_THRESHOLD - filled)
    embed  = discord.Embed(
        title="👑 Pride Recognition",
        description=(
            f"`{bar}`\n**{rec} / {PRIDE_RECOGNITION_THRESHOLD}** recognition\n\n"
        ) + (
            "✅ **Stop Time is unlocked.** Use `!stop_time freeze` or `!stop_time passive`."
            if unlocked else
            f"Gain recognition by getting members to **bow** to your `!claim` commands.\n"
            f"**{max(0, PRIDE_RECOGNITION_THRESHOLD - rec)}** more recognition needed."
        ),
        color=discord.Color.gold(),
    )
    save_data(data)
    await ctx.send(embed=embed)

# ───────────────────────────────────────────────────────────────────
# LUST OBSESSION SYSTEM — Commands
# ───────────────────────────────────────────────────────────────────

# How much each obsession phrase fills the red-heart meter
OBSESSION_PHRASES: dict[str, tuple[int, list[str]]] = {
    # key: (meter_add, list of raw patterns after ! to match)
    "dots":    (10, []),  # handled by regex: 4+ dots
    "oh,hi":   (15, ["oh,hi", "oh, hi"]),
    "heyy":    (15, []),  # handled by regex: hey + 2+ y
    "foundyou":(25, ["found you!", "found you"]),
    "lu":      (35, ["l u", "lu"]),
}

OBSESSION_PHRASE_CD  = 10 * 60   # 10 min cooldown per phrase
OBSESSION_SWITCH_CD  = 60 * 60   # 1 hr cooldown before changing target

# Atmospheric messages posted to trial channel for each phrase (anonymous)
OBSESSION_FLAVORS: dict[str, list[str]] = {
    "dots": [
        "Someone's fingers hover over the keyboard. The silence stretches.",
        "The dots appear. Then vanish. Then appear again.",
        "Waiting. Watching. Always watching.",
    ],
    "oh,hi": [
        "A casual greeting echoes through the hall. Nothing suspicious.",
        "\"Oh — hi.\" Like they weren't already there.",
        "What a coincidence to run into you here.",
    ],
    "heyy": [
        "Someone called out. Their voice was a little too eager.",
        "The extra letters betray them. They tried so hard.",
        "A heart reaches out. It always does.",
    ],
    "foundyou": [
        "Someone has been looking for you. They found you.",
        "You can't hide forever. Not from this.",
        "\"Found you.\" The words hang in the air like smoke.",
    ],
    "lu": [
        "Three letters. Infinite weight.",
        "Someone said something they can't take back.",
        "Love doesn't ask permission.",
    ],
}

def _detect_lust_phrase(raw: str) -> Optional[str]:
    """Return phrase key if `raw` (content after ! lowercased) matches an obsession phrase."""
    if re.fullmatch(r"\.{4,}", raw):
        return "dots"
    if re.fullmatch(r"hey+", raw) and raw.count("y") >= 2:
        return "heyy"
    for key, (_, patterns) in OBSESSION_PHRASES.items():
        if raw in patterns:
            return key
    return None

def _meter_bar(meter: int) -> str:
    filled = meter // 10
    return "❤️" * filled + "🖤" * (10 - filled) + f"  **{meter}%**"

@bot.command()
async def obsess(ctx, target: discord.Member):
    """(Lust role) Designate your obsession target. Red heart phrases will fill the meter against them."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("sin_role") != "lust":
        await ctx.send("Only the holder of Lust may obsess over another.", delete_after=6)
        save_data(data)
        return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5)
        save_data(data)
        return
    if target.id == ctx.author.id:
        await ctx.send("You cannot obsess over yourself.", delete_after=5)
        save_data(data)
        return

    # Cooldown on switching targets
    sw_cd = user.get("obsession_switch_cd") or 0
    if user.get("obsession_target") and now_ts() < sw_cd:
        await ctx.send(
            f"You are already fixated. You can shift your obsession {remaining_fmt(sw_cd)}.",
            delete_after=10,
        )
        save_data(data)
        return

    old_target = user.get("obsession_target")
    user["obsession_target"]    = str(target.id)
    user["obsession_switch_cd"] = now_ts() + OBSESSION_SWITCH_CD
    # Reset meter only if changing targets
    if old_target and old_target != str(target.id):
        user["obsession_meter"]      = 0
        user["obsession_phrase_cds"] = {}

    save_data(data)

    try:
        await ctx.message.delete()
    except Exception:
        pass

    await ctx.author.send(
        f"💘 Your obsession has been fixed on **{target.display_name}**.\n"
        "Use the red heart phrases to fill the meter. At 100%, use `!obsession_clash`.\n\n"
        "Phrases: `!....` (+10%) · `!oh,hi` (+15%) · `!heyy` (+15%) · `!found you!` (+25%) · `!L u` (+35%)\n"
        "Each phrase has a **10-minute** personal cooldown. You can only change targets after **1 hour**."
    )

@bot.command()
async def obsession_meter(ctx):
    """(Lust role) Check your current obsession meter level."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("sin_role") != "lust":
        await ctx.send("Only the holder of Lust may use this.", delete_after=5)
        save_data(data)
        return

    target_id = user.get("obsession_target")
    meter     = user.get("obsession_meter", 0)
    target    = ctx.guild.get_member(int(target_id)) if target_id else None

    embed = discord.Embed(
        title="💘 Obsession Meter",
        description=_meter_bar(meter),
        color=discord.Color.from_rgb(220, 40, 80),
    )
    if target:
        embed.add_field(name="Fixated On", value=target.display_name, inline=True)
    else:
        embed.add_field(name="Fixated On", value="*Nobody — use* `!obsess @user`", inline=True)

    if meter >= 100:
        embed.add_field(
            name="⚠️ FULL",
            value="Use `!obsession_clash` to strike.",
            inline=False,
        )

    save_data(data)
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.author.send(embed=embed)

@bot.command()
async def obsession_clash(ctx):
    """(Lust role) When meter is full, coin-flip clash against your obsession target."""
    data = load_data()
    user = get_user(data, ctx.author.id)

    if user.get("sin_role") != "lust":
        await ctx.send("Only the holder of Lust may clash.", delete_after=5)
        save_data(data)
        return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5)
        save_data(data)
        return

    clash_cd = user.get("obsession_clash_cd") or 0
    if now_ts() < clash_cd:
        await ctx.send(f"Clash is cooling down: {remaining_fmt(clash_cd)}.", delete_after=8)
        save_data(data)
        return

    meter     = user.get("obsession_meter", 0)
    target_id = user.get("obsession_target")
    if not target_id:
        await ctx.send("You have no obsession target. Use `!obsess @user` first.", delete_after=8)
        save_data(data)
        return
    if meter < 100:
        await ctx.send(
            f"Your obsession isn't full yet. ({meter}%)\n{_meter_bar(meter)}",
            delete_after=10,
        )
        save_data(data)
        return

    target = ctx.guild.get_member(int(target_id))
    if not target:
        await ctx.send("Your obsession target is no longer in this server.", delete_after=8)
        save_data(data)
        return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")
    target_power = SINS[target_sin]["power"] if target_sin and target_sin in SINS else 1

    lust_coins   = 2
    target_coins = max(1, target_power // 2)

    winner, roll_a, roll_b = coin_flip(lust_coins, target_coins)

    ch = await trial_channel(ctx.guild) or ctx.channel

    flip_embed = discord.Embed(
        title="💘 Obsession Clash — Lust vs the World",
        description=(
            f"**Lust** rolled **{roll_a}** ({lust_coins} coins)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coin{'s' if target_coins > 1 else ''})\n\n"
        ),
        color=discord.Color.from_rgb(220, 40, 80),
    )

    if winner == "a":
        flip_embed.description += (
            f"**Love overwhelms.** {target.display_name} is consumed by someone's obsession."
        )
        await ch.send(embed=flip_embed)

        target_user["ability_locked_until"] = now_ts() + 30 * 60
        user["obsession_meter"]  = 50   # meter drops to 50, doesn't fully reset
        user["obsession_clash_cd"] = now_ts() + 3600  # 1hr clash cooldown

        await ch.send(embed=discord.Embed(
            title="💔 Overwhelmed by Obsession",
            description=(
                f"{target.mention} has been consumed. "
                "They are too flustered to act — **ability locked for 30 minutes**.\n\n"
                "*Love is not kind when it isn't returned.*"
            ),
            color=discord.Color.from_rgb(180, 0, 60),
        ))
    else:
        flip_embed.description += (
            f"**{target.display_name}** broke free. The obsession shatters."
        )
        await ch.send(embed=flip_embed)

        user["obsession_meter"]    = 0
        user["obsession_phrase_cds"] = {}
        user["obsession_clash_cd"] = now_ts() + 3600
        user["corruption"]         = user.get("corruption", 0) + 1

        await ch.send(embed=discord.Embed(
            title="💔 Rejected",
            description=(
                f"{target.mention} resisted. The obsession falls apart.\n\n"
                "Lust gains **+1 Corruption**. The meter resets to zero.\n\n"
                "*Some things can't be forced.*"
            ),
            color=discord.Color.dark_gray(),
        ))

        try:
            await target.send(
                "💜 Someone's obsession with you just **broke**. You felt it — but you don't know who it was."
            )
        except Exception:
            pass

    save_data(data)

@bot.command(name="i_dont_care_if_theyre_watching")
async def i_dont_care_if_theyre_watching(ctx):
    """(Lust) Declare your obsession publicly — shameless devotion grants +30 obsession meter and +2 clash power."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "lust":
        await ctx.send("Only Desire Bound Lust can be this shameless.", delete_after=5); save_data(data); return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5); save_data(data); return

    cd = (user.get("obsession_phrase_cds") or {}).get("i_dont_care", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"You need to gather more courage first: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    target_id = user.get("obsession_target")
    if not target_id:
        await ctx.send("You have no obsession target. Use `!obsess @user` first.", delete_after=8)
        save_data(data); return

    target = ctx.guild.get_member(int(target_id))
    target_name = target.mention if target else "*(someone who left the server)*"

    old_meter = user.get("obsession_meter", 0)
    new_meter  = min(100, old_meter + 30)
    user["obsession_meter"] = new_meter
    user.setdefault("obsession_phrase_cds", {})["i_dont_care"] = now_ts() + 6 * 3600  # 6hr CD
    user["clash_power_bonus"]  = max(user.get("clash_power_bonus", 0), 2)
    user["clash_penalty_until"] = now_ts() + 30 * 60   # stores the bonus expiry too

    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🔥 I Don't Care If They're Watching",
        color=discord.Color.from_rgb(200, 20, 100),
        description=(
            f"{ctx.author.mention} stops hiding it.\n\n"
            f"*\"I don't care who sees this.\"*\n\n"
            f"Everyone now knows: their obsession is {target_name}.\n\n"
            f"💗 **+30 Obsession Meter** ({old_meter} → {new_meter})\n"
            "⚔️ **+2 clash power** for the next **30 minutes** — shamelessness is its own strength."
        ),
    ))

    if old_meter < 100 <= new_meter:
        try:
            await ctx.author.send(
                "❤️ **The meter hit 100.** Your obsession is at its peak — use `!obsession_clash` to strike."
            )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════
# ░░ JUSTICE ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

# ── Phrase sets for Scale of Wrongdoing ──────────────────────────

_TRIAL_DENY_PHRASES = {
    "i never did that", "i didn't do that", "i didnt do that",
    "i didn't do anything", "i didnt do anything",
    "i don't recognize that", "i dont recognize that",
    "that wasn't me", "that wasnt me",
    "not me", "i wasn't there", "i wasnt there",
    "i deny this", "i reject this", "i object",
    "that's false", "thats false", "that is false",
}

_TRIAL_DUMB_PHRASES = {
    "that happened?", "what happened?",
    "what are you talking about", "what is this about",
    "what did i do", "huh", "huh?", "what", "what?",
    "i don't know what you're talking about",
    "i dont know what youre talking about",
    "excuse me?", "pardon?", "come again?",
    "i'm confused", "im confused", "this is news to me",
}

_TRIAL_GUILTY_PHRASES = {
    "i'm guilty", "im guilty", "i am guilty", "guilty",
    "i did it", "i confess", "i admit it",
    "i plead guilty", "i accept the charges",
    "fine i did it", "ok i did it", "okay i did it",
    "yeah i did it", "yes i did it",
}

# ── Helpers ───────────────────────────────────────────────────────

def _justice_check(user: dict) -> bool:
    """True if user holds The Scales of Justice and has not fallen."""
    return user.get("sin_role") == "justice" and not user.get("fallen")

@bot.after_invoke
async def _track_sin_action(ctx):
    """After any sinful command completes, record the actor's last bad action timestamp."""
    if ctx.command and ctx.command.name in SINFUL_COMMANDS:
        data = load_data()
        user = get_user(data, ctx.author.id)
        user["last_sin_action_ts"] = now_ts()
        prev = list(user.get("last_sin_abilities_used") or [])
        if ctx.command.name not in prev:
            prev.insert(0, ctx.command.name)
        user["last_sin_abilities_used"] = prev[:5]
        save_data(data)

# ── Jacob's Ladder ────────────────────────────────────────────────

@bot.command()
async def jacobs_ladder(ctx, target: discord.Member):
    """(Justice) Cast Jacob's Ladder — a divine assault against sinners. Clean record required (no sinful action in last 5 min)."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _justice_check(user):
        await ctx.send("Only The Scales of Justice may cast Jacob's Ladder.", delete_after=5)
        save_data(data); return

    cd = (user.get("justice_ability_cds") or {}).get("jacobs_ladder", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Jacob's Ladder on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("Heaven's gate does not open for the self-righteous.", delete_after=5)
        save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    # Clean record check — must not have used a sinful command in the last 5 minutes
    last_bad = user.get("last_sin_action_ts") or 0
    elapsed  = now_ts() - last_bad
    if last_bad and elapsed < 5 * 60:
        remaining_s = int(5 * 60 - elapsed)
        m, s = divmod(remaining_s, 60)
        await ctx.send(
            f"⚖️ Your record is not clean. The light will not answer for another **{m}m {s}s**.",
            delete_after=10,
        )
        save_data(data); return

    expires   = now_ts() + 20   # 20-second counter-clash window
    trial_key = str(target.id) + "_jacobs"
    data.setdefault("pending_trials", {})[trial_key] = {
        "type":       "jacobs_ladder",
        "accuser_id": ctx.author.id,
        "target_id":  target.id,
        "expires":    expires,
        "channel_id": ctx.channel.id,
        "guild_id":   ctx.guild.id,
        "resolved":   False,
    }
    user.setdefault("justice_ability_cds", {})["jacobs_ladder"] = now_ts() + 4 * 3600
    save_data(data)

    ch = ctx.channel
    await ch.send(embed=discord.Embed(
        title="⚡ Jacob's Ladder",
        color=discord.Color.from_rgb(255, 245, 140),
        description=(
            f"*\"Throughout life and death, connecting heaven and earth —\n"
            f"I cast upon you: **Jacob's Ladder**\"*\n\n"
            f"— {ctx.author.mention} lowers the scales upon {target.mention}.\n\n"
            f"🛡️ {target.mention} has **20 seconds** to `!clash @{ctx.author.display_name}` and contest this.\n"
            f"*Silence* — and the light falls."
        ),
    ))

    async def _resolve_jacobs():
        await asyncio.sleep(22)
        d = load_data()
        t = d.get("pending_trials", {}).get(trial_key)
        if not t or t.get("resolved"):
            return
        t["resolved"] = True
        t_user = get_user(d, target.id)
        current_lock = t_user.get("ability_locked_until") or 0
        t_user["ability_locked_until"] = max(current_lock, now_ts() + 5 * 60)
        t_user["clash_power_penalty"]  = max(t_user.get("clash_power_penalty", 0), 1)
        t_user["clash_penalty_until"]  = now_ts() + 30 * 60
        save_data(d)

        guild_ = bot.get_guild(t["guild_id"])
        if guild_:
            chan_ = guild_.get_channel(t["channel_id"])
            if chan_:
                victim_ = guild_.get_member(t["target_id"])
                await chan_.send(embed=discord.Embed(
                    title="⚡ Jacob's Ladder — Struck",
                    color=discord.Color.from_rgb(255, 255, 180),
                    description=(
                        f"No defense was raised.\n\n"
                        f"The light **falls on {victim_.mention if victim_ else 'the target'}**:\n"
                        "• ⛔ Ability lock for **5 minutes**\n"
                        "• ⬇️ **-1 clash power** for **30 minutes**\n\n"
                        "*Justice was done.*"
                    ),
                ))

    asyncio.create_task(_resolve_jacobs())

# ── Scale of Wrongdoing ───────────────────────────────────────────

_SCALE_ABILITY_CD_MAP = {
    "devour":           "gluttony_ability_cds",
    "feast":            "gluttony_ability_cds",
    "gorge":            "gluttony_ability_cds",
    "flash":            "gooner_ability_cds",
    "withered_meat":    "gooner_ability_cds",
    "diane_foxington":  "gooner_ability_cds",
    "steal_ability":    "greed_ability_cds",
    "rage_strike":      "wrath_ability_cds",
    "meteor_drop":      "wrath_ability_cds",
    "bloodlust":        "wrath_ability_cds",
    "lose_yourself":    "greed_ability_cds",
    "jealousy_mark":    "jealousy_role_cds",
    "schizo":           "greed_ability_cds",
    "envy_strike":      "greed_ability_cds",
    "slow_type":        "sloth_ability_cds",
    "deep_sleep":       "sloth_ability_cds",
    "obsession_clash":  "obsession_clash_cd",
}

@bot.command()
async def scale_of_wrongdoing(ctx, target: discord.Member):
    """(Justice) Open a trial against a sinner — they must defend themselves within 30 seconds or be convicted."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _justice_check(user):
        await ctx.send("Only The Scales of Justice may open a trial.", delete_after=5)
        save_data(data); return

    cd = (user.get("justice_ability_cds") or {}).get("scale_of_wrongdoing", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Scale of Wrongdoing on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot put yourself on trial.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user = get_user(data, target.id)
    last_bad    = target_user.get("last_sin_action_ts") or 0
    if now_ts() - last_bad > 30 * 60:
        await ctx.send(
            f"⚖️ {target.mention} has a clean record. No charges can be filed against the innocent.",
            delete_after=10,
        )
        save_data(data); return

    trial_key = str(target.id) + "_scale"
    existing  = data.get("pending_trials", {}).get(trial_key, {})
    if existing and not existing.get("resolved"):
        await ctx.send(f"{target.mention} is already standing trial.", delete_after=8)
        save_data(data); return

    abilities  = list(target_user.get("last_sin_abilities_used") or [])
    expires    = now_ts() + 30
    data.setdefault("pending_trials", {})[trial_key] = {
        "type":       "scale_of_wrongdoing",
        "accuser_id": ctx.author.id,
        "target_id":  target.id,
        "expires":    expires,
        "channel_id": ctx.channel.id,
        "guild_id":   ctx.guild.id,
        "abilities":  abilities,
        "resolved":   False,
        "response":   None,
    }
    user.setdefault("justice_ability_cds", {})["scale_of_wrongdoing"] = now_ts() + 3 * 3600
    save_data(data)

    abilities_str = ", ".join(f"`!{a}`" for a in abilities) if abilities else "*(recent sinful actions)*"
    await ctx.channel.send(embed=discord.Embed(
        title="⚖️ Scale of Wrongdoing — Trial Opened",
        color=discord.Color.from_rgb(200, 160, 60),
        description=(
            f"{ctx.author.mention} (**The Scales of Justice**) brings {target.mention} before the court.\n\n"
            f"**Charges filed for:** {abilities_str}\n\n"
            f"🗣️ {target.mention} — you have **30 seconds** to speak:\n\n"
            f"‣ **Deny it** — *\"I never did that\", \"I don't recognize that\", \"That wasn't me\"...*\n"
            f"  → Opens a clash window so you may contest the ruling.\n\n"
            f"‣ **Play dumb** — *\"That happened?\", \"What are you talking about?\", \"Huh?\"...*\n"
            f"  → Same as denial — clash window opens.\n\n"
            f"‣ **Plead guilty** — *\"I'm guilty\", \"I did it\", \"I confess\"...*\n"
            f"  → Accepts a reduced penalty: **30 min** lock instead of **2 hours**.\n\n"
            f"*Silence = automatic conviction. Abilities used in wrongdoing disabled for **2 hours**.*"
        ),
    ))

    async def _resolve_scale():
        await asyncio.sleep(32)
        d = load_data()
        trial = d.get("pending_trials", {}).get(trial_key)
        if not trial or trial.get("resolved"):
            return
        trial["resolved"] = True

        t_user    = get_user(d, target.id)
        convicted = trial.get("abilities") or []
        two_hours = now_ts() + 2 * 3600

        for ab in convicted:
            cd_dict_key = _SCALE_ABILITY_CD_MAP.get(ab)
            if cd_dict_key and cd_dict_key.endswith("_cds"):
                t_user.setdefault(cd_dict_key, {})[ab] = two_hours
            elif cd_dict_key:
                t_user[cd_dict_key] = two_hours

        # General ability lock for 2 hours
        current_lock = t_user.get("ability_locked_until") or 0
        t_user["ability_locked_until"] = max(current_lock, two_hours)
        save_data(d)

        guild_ = bot.get_guild(trial["guild_id"])
        if guild_:
            chan_ = guild_.get_channel(trial["channel_id"])
            if chan_:
                victim_ = guild_.get_member(trial["target_id"])
                ab_list = ", ".join(f"`!{a}`" for a in convicted) if convicted else "*(all recent abilities)*"
                await chan_.send(embed=discord.Embed(
                    title="⚖️ CONVICTED — No Defense Raised",
                    color=discord.Color.from_rgb(180, 60, 0),
                    description=(
                        f"{victim_.mention if victim_ else 'The accused'} stood silent before the court.\n\n"
                        f"🔒 **Abilities disabled for 2 hours:** {ab_list}\n"
                        "⛔ General ability lock applied for **2 hours**.\n\n"
                        "*The scales have spoken.*"
                    ),
                ))

    asyncio.create_task(_resolve_scale())


# ═══════════════════════════════════════════════════════════════════
# ░░ GOONER ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

_DIANE_SEDUCTIVE = [
    "You came back. I was starting to miss you. 🦊",
    "You know what I like about you? You're bold enough to summon me.",
    "Come closer. I promise I don't bite… unless you want me to.",
    "*leans against the doorframe* Always you.",
    "For you, I'll make an exception. Just this once.",
    "Flattery is so common. But from you? I'll allow it.",
    "You really can't help yourself, can you? Good.",
]

_DIANE_COCKY = [
    "Oh don't mind me. I'm just here for **him**. The rest of you are furniture.",
    "Eyes up, darlings. I know — hard to look away.",
    "What? Did none of you expect a fox this refined? Cute.",
    "The rest of you should probably leave. This is a private audience.",
    "Is that envy I smell? Good. You should be.",
    "I'd say hi, but I'm really only here for one person.",
    "Try not to stare. Actually — go ahead. I don't mind.",
]

def _gooner_check(user: dict) -> bool:
    return user.get("sin_role") == "gooner" and not user.get("fallen")

@bot.command()
async def flash(ctx, target: discord.Member):
    """(Gooner) Flash Diane Foxington at a target, stunning them for 30 seconds."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _gooner_check(user):
        await ctx.send("Only The Fox Gooner may flash.", delete_after=5); save_data(data); return

    cd = (user.get("gooner_ability_cds") or {}).get("flash", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Flash on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You can't flash yourself. Be serious.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user = get_user(data, target.id)
    stun_end    = now_ts() + 30   # 30-second stun

    # Reuse ability_locked_until — already checked by every ability command
    current_lock = target_user.get("ability_locked_until") or 0
    target_user["ability_locked_until"] = max(current_lock, stun_end)
    user.setdefault("gooner_ability_cds", {})["flash"] = now_ts() + 90 * 60   # 90 min CD
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🦊 FLASH — Diane Foxington",
        color=discord.Color.from_rgb(220, 110, 30),
        description=(
            f"{ctx.author.mention} flashes **Diane Foxington** at {target.mention}.\n\n"
            f"*She turns, locking eyes with {target.display_name}. "
            "The world stops for exactly thirty seconds.*\n\n"
            f"⚡ {target.mention} is **stunned** — abilities locked for **30 seconds**."
        ),
    ))
    try:
        await target.send(
            f"🦊 **{ctx.author.display_name}** flashed Diane Foxington at you. "
            "You are stunned for **30 seconds** — abilities disabled."
        )
    except Exception:
        pass


@bot.command()
async def withered_meat(ctx, target: discord.Member):
    """(Gooner) Smack a target with withered meat, disabling all their abilities for 10 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _gooner_check(user):
        await ctx.send("Only The Fox Gooner may wield the withered meat.", delete_after=5); save_data(data); return

    cd = (user.get("gooner_ability_cds") or {}).get("withered_meat", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Withered Meat on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot hit yourself with it. Put the meat down.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    target_user  = get_user(data, target.id)
    disabled_end = now_ts() + 10 * 60   # 10 minutes

    current_lock = target_user.get("ability_locked_until") or 0
    target_user["ability_locked_until"] = max(current_lock, disabled_end)
    target_user["withered_until"]        = disabled_end
    user.setdefault("gooner_ability_cds", {})["withered_meat"] = now_ts() + 2 * 3600   # 2hr CD
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🥩 Withered Meat",
        color=discord.Color.from_rgb(120, 50, 20),
        description=(
            f"{ctx.author.mention} pulls out a **withered, desiccated slab of meat** and "
            f"slaps {target.mention} across the face with it.\n\n"
            f"*The impact is undignified. The smell is worse.*\n\n"
            f"😵 {target.mention}'s abilities are **rendered useless** for **10 minutes**.\n"
            f"Expires: {ts_fmt(disabled_end)}"
        ),
    ))
    try:
        await target.send(
            f"🥩 **{ctx.author.display_name}** smacked you with withered meat. "
            "Your abilities are disabled for **10 minutes**."
        )
    except Exception:
        pass


@bot.command()
async def diane_foxington(ctx):
    """(Gooner) Summon Diane Foxington — she whispers to you and dishes out cocky remarks to everyone else."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _gooner_check(user):
        await ctx.send("Only The Fox Gooner may summon her.", delete_after=5); save_data(data); return

    cd = (user.get("gooner_ability_cds") or {}).get("diane", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Diane is occupied. Try again {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    user.setdefault("gooner_ability_cds", {})["diane"] = now_ts() + 3 * 3600   # 3hr CD
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    embed = discord.Embed(
        title="🦊 Diane Foxington Appears",
        color=discord.Color.from_rgb(220, 110, 30),
    )
    embed.add_field(
        name=f"To {ctx.author.display_name}:",
        value=f"*\"{random.choice(_DIANE_SEDUCTIVE)}\"*",
        inline=False,
    )
    embed.add_field(
        name="To everyone else:",
        value=f"*\"{random.choice(_DIANE_COCKY)}\"*",
        inline=False,
    )
    embed.set_footer(text="— Diane Foxington, The Bad Guys (2022)")
    await ch.send(embed=embed)


@bot.command()
async def gooner_meter(ctx, target: discord.Member = None):
    """Show Gooner trial image submission progress."""
    target = target or ctx.author
    data   = load_data()
    user   = get_user(data, target.id)

    count   = user.get("gooner_images_submitted", 0)
    evolved = is_evolved(user)
    goal    = 200 if evolved else 100
    pct     = min(1.0, count / goal)
    width   = 15
    bar     = "█" * int(pct * width) + "░" * (width - int(pct * width))

    embed = discord.Embed(
        title=f"🦊 Gooner Devotion — {target.display_name}",
        color=discord.Color.from_rgb(220, 110, 30),
    )
    embed.add_field(
        name="Images Submitted",
        value=f"`{bar}` **{count} / {goal}**",
        inline=False,
    )
    if count >= goal:
        embed.add_field(name="Status", value="✅ Trial objective reached!", inline=False)
    elif user.get("trial_sin") == "gooner":
        embed.add_field(
            name="Remaining",
            value=f"**{goal - count}** images still needed in **#gooner-trial**",
            inline=False,
        )
    else:
        embed.add_field(name="Status", value="Not currently in Gooner trial.", inline=False)

    cds = user.get("gooner_ability_cds") or {}
    cd_lines = []
    for key, label in [("flash", "Flash"), ("withered_meat", "Withered Meat"), ("diane", "Diane Foxington")]:
        ts = cds.get(key, 0) or 0
        cd_lines.append(f"• **{label}**: {'Ready ✅' if now_ts() >= ts else remaining_fmt(ts)}")
    embed.add_field(name="Ability Cooldowns", value="\n".join(cd_lines), inline=False)

    save_data(data)
    await ctx.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════
# ░░ SIN METER COMMANDS ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

@bot.command()
async def greed_meter(ctx):
    """(Greed) Show your anger meter, frenzy state, stolen abilities, and daily steals."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "greed":
        await ctx.send("Only the False King has an anger meter.", delete_after=6)
        save_data(data); return

    anger  = user.get("anger_meter", 0)
    frenzy = user.get("frenzy_active", False)
    steals_today = user.get("greed_steals_today", 0)
    lose_until   = user.get("lose_yourself_until") or 0

    bar = _anger_bar(anger)
    embed = discord.Embed(
        title="💰 Greed Status",
        color=discord.Color.gold() if not frenzy else discord.Color.red(),
    )
    embed.add_field(name="😤 Anger Meter", value=bar, inline=False)

    if frenzy:
        frenzy_used = user.get("frenzy_used", False)
        embed.add_field(
            name="🔴 FRENZY ACTIVE",
            value=(
                "Use `!i_always_get_what_i_want @user buff/debuff`\n"
                "Use `!frenzy_clash @user` to spend it.\n"
            ) + ("*(buff/debuff already used)*" if frenzy_used else "*(buff/debuff available)*"),
            inline=False,
        )
    else:
        losses_to_frenzy = max(0, (100 - anger) // 20)
        embed.add_field(
            name="📊 Progress",
            value=f"{losses_to_frenzy} more loss{'es' if losses_to_frenzy != 1 else ''} until Frenzy",
            inline=True,
        )

    embed.add_field(
        name="🗡️ Steals Today",
        value=f"**{steals_today} / {GREED_MAX_STEALS_PER_DAY}**",
        inline=True,
    )

    if now_ts() < lose_until:
        embed.add_field(
            name="😵 Lose Yourself",
            value=f"Power penalty active: {remaining_fmt(lose_until)}",
            inline=False,
        )

    # List currently stolen abilities
    stolen = [s for s in data.get("stolen_abilities", []) if s["holder_id"] == str(ctx.author.id) and now_ts() < s["expires"]]
    if stolen:
        lines = []
        for s in stolen:
            orig = ctx.guild.get_member(int(s["original_holder_id"])) if ctx.guild else None
            lines.append(f"• **{s['ability_key'].replace('_',' ')}** from {orig.display_name if orig else 'Unknown'} — expires {remaining_fmt(s['expires'])}")
        embed.add_field(name="💼 Stolen Abilities", value="\n".join(lines), inline=False)

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


@bot.command()
async def sloth_meter(ctx):
    """(Sloth) Show laziness meter, deep sleep count, Sleepwalker progress, and active effects."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "sloth":
        await ctx.send("Only the Vessel of Sloth has a laziness meter.", delete_after=6)
        save_data(data); return

    laziness     = user.get("laziness_meter", 0)
    sleep_count  = user.get("deep_sleep_count", 0)
    sw_unlocked  = user.get("sleepwalker_unlocked", False)
    sw_until     = user.get("sleepwalker_active_until") or 0
    sleep_until  = user.get("deep_sleep_until") or 0
    slow_until   = user.get("slow_type_until") or 0

    bar = _laziness_bar(laziness)
    embed = discord.Embed(
        title="😴 Sloth Status",
        color=discord.Color.from_rgb(80, 80, 120),
    )
    embed.add_field(name="😴 Laziness Meter", value=bar, inline=False)

    if laziness >= 100:
        embed.add_field(name="⚠️ MAXED OUT", value="Use `!deep_sleep` to reset.", inline=False)

    embed.add_field(
        name="💤 Voluntary Deep Sleeps",
        value=f"**{sleep_count} / {DEEP_SLEEP_THRESHOLD}**" + (" — ✅ Sleepwalker Unlocked!" if sw_unlocked else f" ({DEEP_SLEEP_THRESHOLD - sleep_count} more needed)"),
        inline=False,
    )

    if now_ts() < sw_until:
        embed.add_field(name="🌙 Sleepwalker Active", value=f"Expires {remaining_fmt(sw_until)}", inline=True)
    elif sw_unlocked:
        sw_cd = (user.get("sloth_ability_cds") or {}).get("sleepwalker", 0) or 0
        embed.add_field(
            name="🌙 Sleepwalker",
            value=f"Unlocked — {'cooldown: ' + remaining_fmt(sw_cd) if now_ts() < sw_cd else 'Ready to use `!sleepwalker`'}",
            inline=True,
        )

    if now_ts() < sleep_until:
        embed.add_field(name="💤 Deep Sleeping", value=f"Wakes {remaining_fmt(sleep_until)}", inline=True)
    if now_ts() < slow_until:
        embed.add_field(name="⏱️ Type-Slow Active", value=f"Until {remaining_fmt(slow_until)}", inline=True)

    # Ability cooldowns
    cds = user.get("sloth_ability_cds") or {}
    cd_lines = []
    for k, label in [("force_lazy","!force_lazy"),("slowdown","!slowdown"),("force_sleep","!force_sleep")]:
        ts = cds.get(k, 0) or 0
        if now_ts() < ts:
            cd_lines.append(f"• **{label}** — {remaining_fmt(ts)}")
    if cd_lines:
        embed.add_field(name="⏳ Cooldowns", value="\n".join(cd_lines), inline=False)

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


@bot.command()
async def envy_meter(ctx):
    """(Envy) Show your marks of insecurity, Krodingers Effect status, and active jealousy mark."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "envy":
        await ctx.send("Only the holder of Envy has an envy meter.", delete_after=6)
        save_data(data); return

    marks     = user.get("marks_of_insecurity", 0)
    threshold = krodingers_threshold(SINS["envy"]["power"])
    lock_until = user.get("envy_ability_locked_until") or 0
    mark_info  = data.get("envy_marks", {}).get(str(ctx.author.id))

    bar_filled = min(marks, threshold)
    bar = "🔴" * bar_filled + "⬜" * (threshold - bar_filled) + f"  **{marks}/{threshold}**"

    embed = discord.Embed(
        title="👁️ Envy Status",
        color=discord.Color.from_rgb(20, 80, 20),
    )
    embed.add_field(name="😟 Marks of Insecurity", value=bar, inline=False)

    if marks >= threshold:
        embed.add_field(
            name="🔒 Krodingers Effect",
            value=(
                f"Abilities **locked** until {remaining_fmt(lock_until)}" if now_ts() < lock_until
                else "**Active** — abilities may be locked. Use `!envy_check` to confirm."
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="📊 Progress to Lockout",
            value=f"**{threshold - marks}** more mark{'s' if threshold - marks != 1 else ''} until Krodingers Effect triggers",
            inline=True,
        )

    if mark_info and now_ts() < mark_info.get("expires", 0):
        target_m = ctx.guild.get_member(int(mark_info["target_id"])) if ctx.guild else None
        embed.add_field(
            name="🎯 Active Jealousy Mark",
            value=(
                f"Targeting: **{target_m.display_name if target_m else mark_info['target_id']}**\n"
                f"Sin: **{mark_info.get('target_sin', '?')}**\n"
                f"Expires: {remaining_fmt(mark_info['expires'])}"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="🎯 Jealousy Mark", value="No active mark. Use `!jealousy_mark @user`.", inline=False)

    stolen_roles = user.get("stolen_roles") or []
    active_stolen = [r for r in stolen_roles if now_ts() < r.get("expires", 0)]
    if active_stolen:
        lines = [f"• **{r['role']}** — expires {remaining_fmt(r['expires'])}" for r in active_stolen]
        embed.add_field(name="🃏 Stolen Roles", value="\n".join(lines), inline=False)

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


@bot.command()
async def stolen_roles(ctx, target: discord.Member = None):
    """Publicly view which sin roles Envy is currently wearing via a successful jealousy mark steal."""
    data   = load_data()
    target = target or ctx.author
    user   = data["users"].get(str(target.id), {})

    stolen_list = [
        r for r in (user.get("stolen_roles") or [])
        if now_ts() < r.get("expires", 0)
    ]

    embed = discord.Embed(
        title=f"🌑 Stolen Roles — {target.display_name}",
        color=discord.Color.from_rgb(0, 80, 120),
    )

    if not stolen_list:
        embed.description = (
            f"**{target.display_name}** is not currently wearing any stolen sin roles.\n\n"
            "*The shadows hold nothing — for now.*"
        )
    else:
        lines = []
        for entry in stolen_list:
            orig_id  = entry.get("from_id")
            orig_m   = ctx.guild.get_member(int(orig_id)) if orig_id and ctx.guild else None
            orig_str = orig_m.mention if orig_m else f"(user {orig_id})"
            lines.append(
                f"• **{entry['role']}** — stolen from {orig_str}\n"
                f"  Expires: {remaining_fmt(entry['expires'])}"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text="Roles return to their owners when the timer expires.")

    save_data(data)
    await ctx.send(embed=embed)


@bot.command()
async def wrath_meter(ctx):
    """(Wrath) Show bloodlust status, active debuffs, and ability cooldowns."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "wrath":
        await ctx.send("Only Crimson Heir has a wrath meter.", delete_after=6)
        save_data(data); return

    bl_active = user.get("bloodlust_active", False) and now_ts() < (user.get("bloodlust_until") or 0)
    bl_until  = user.get("bloodlust_until") or 0
    penalty   = user.get("clash_power_penalty", 0) if now_ts() < (user.get("clash_penalty_until") or 0) else 0
    corruption = user.get("corruption", 0)

    embed = discord.Embed(
        title="💢 Wrath Status",
        color=discord.Color.red() if bl_active else discord.Color.dark_red(),
    )

    if bl_active:
        embed.add_field(
            name="🩸 BLOODLUST ACTIVE",
            value=f"+1 coin on all clashes — expires {remaining_fmt(bl_until)}\n⚠️ Lose any clash = +1 Corruption + Bloodlust ends",
            inline=False,
        )
    else:
        bl_cd = (user.get("wrath_ability_cds") or {}).get("bloodlust", 0) or 0
        embed.add_field(
            name="🩸 Bloodlust",
            value=f"Inactive — {'cooldown: ' + remaining_fmt(bl_cd) if now_ts() < bl_cd else 'Ready (`!bloodlust`)'}",
            inline=True,
        )

    rs_cd = (user.get("wrath_ability_cds") or {}).get("rage_strike", 0) or 0
    embed.add_field(
        name="💢 Rage Strike",
        value=f"{'cooldown: ' + remaining_fmt(rs_cd) if now_ts() < rs_cd else 'Ready (`!rage_strike @user`)'}",
        inline=True,
    )

    embed.add_field(name="💀 Corruption", value=f"**{corruption}**", inline=True)

    if penalty > 0:
        embed.add_field(
            name="⬇️ Power Penalty",
            value=f"-{penalty} clash coins — expires {remaining_fmt(user.get('clash_penalty_until') or 0)}",
            inline=False,
        )

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


@bot.command()
async def gluttony_meter(ctx):
    """(Gluttony) Show gorge status, active feast curses you've placed, and clash power bonus."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "gluttony":
        await ctx.send("Only the Devoured has a gluttony meter.", delete_after=6)
        save_data(data); return

    gorge_until = user.get("gorge_active_until") or 0
    bonus       = user.get("clash_power_bonus", 0) or 0
    gorge_cd    = (user.get("gluttony_ability_cds") or {}).get("gorge", 0) or 0
    feast_cd    = (user.get("gluttony_ability_cds") or {}).get("feast", 0) or 0

    embed = discord.Embed(
        title="🍽️ Gluttony Status",
        color=discord.Color.from_rgb(180, 80, 0),
    )

    if now_ts() < gorge_until:
        embed.add_field(
            name="🍽️ GORGE ACTIVE",
            value=f"Feeding on server energy — expires {remaining_fmt(gorge_until)}\n**+{bonus}** clash coin bonus (grows with server messages)",
            inline=False,
        )
    else:
        embed.add_field(
            name="🍽️ Gorge",
            value=f"Inactive — {'cooldown: ' + remaining_fmt(gorge_cd) if now_ts() < gorge_cd else 'Ready (`!gorge`)'}",
            inline=True,
        )

    embed.add_field(
        name="🍴 Feast",
        value=f"{'Cooldown: ' + remaining_fmt(feast_cd) if now_ts() < feast_cd else 'Ready (`!feast @user`)'}",
        inline=True,
    )

    # Active feast curses placed by this user
    active_curses = [
        (uid, entry) for uid, entry in data.get("feast_cursed", {}).items()
        if entry.get("by_id") == str(ctx.author.id) and now_ts() < entry.get("expires", 0)
    ]
    if active_curses:
        lines = []
        for uid, entry in active_curses:
            m = ctx.guild.get_member(int(uid)) if ctx.guild else None
            lines.append(f"• **{m.display_name if m else uid}** — {entry.get('marks',0)}/{FEAST_MARKS_FOR_PENALTY} marks — expires {remaining_fmt(entry['expires'])}")
        embed.add_field(name="🍴 Active Hunger Curses", value="\n".join(lines), inline=False)

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


@bot.command()
async def pride_meter(ctx):
    """(Pride) Show recognition toward Stop Time and all active Pride effects."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "pride":
        await ctx.send("Only the Bearer of Pride has a pride meter.", delete_after=6)
        save_data(data); return

    rec      = user.get("pride_recognition", 0)
    unlocked = user.get("stop_time_unlocked", False)
    st_cd    = user.get("stop_time_cd") or 0
    passive  = user.get("stop_time_passive", False)
    speak_ban = user.get("speaking_restricted_until") or 0
    claims    = data.get("active_claims", {})
    mine      = [(mid, c) for mid, c in claims.items() if c.get("claimer_id") == str(ctx.author.id)]

    filled = min(rec, PRIDE_RECOGNITION_THRESHOLD)
    bar    = "👑" * filled + "⬜" * (PRIDE_RECOGNITION_THRESHOLD - filled) + f"  **{rec}/{PRIDE_RECOGNITION_THRESHOLD}**"

    embed = discord.Embed(
        title="👑 Pride Status",
        color=discord.Color.from_rgb(80, 0, 160),
    )
    embed.add_field(name="👑 Recognition", value=bar, inline=False)

    if unlocked:
        if now_ts() < st_cd:
            st_status = f"On cooldown — {remaining_fmt(st_cd)}"
        else:
            st_status = "Ready — use `!stop_time freeze` or `!stop_time passive`"
        embed.add_field(name="⏸️ Stop Time", value=st_status, inline=False)
    else:
        embed.add_field(
            name="⏸️ Stop Time",
            value=f"Locked — {max(0, PRIDE_RECOGNITION_THRESHOLD - rec)} more recognition needed",
            inline=False,
        )

    if passive:
        embed.add_field(name="🛡️ Passive Evasion", value="Ready — next ability against you **auto-evades**", inline=True)
    if now_ts() < speak_ban:
        embed.add_field(name="🔇 Speak Ban", value=f"Until {remaining_fmt(speak_ban)}", inline=True)

    if mine:
        total_bows = sum(
            sum(1 for s in c.get("subjects", {}).values() if s.get("bowed")) for _, c in mine
        )
        embed.add_field(name="📜 Active Claims", value=f"**{len(mine)}** active — **{total_bows}** bows received", inline=False)

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════
# ░░ VIRTUE ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

def _virtue_check(user: dict, sin: str) -> bool:
    """True if user holds the virtue of the given sin."""
    return (
        sin in user.get("completed_virtues", [])
        and user.get("sin_role") == sin
        and not user.get("fallen")
    )

def _virtue_cd_check(user: dict, key: str, cd_secs: int) -> Optional[str]:
    """Returns error string if on cooldown, else sets cooldown and returns None."""
    cds = user.setdefault("virtue_ability_cds", {})
    ts  = cds.get(key, 0) or 0
    if now_ts() < ts:
        return f"**{key}** on cooldown: {remaining_fmt(ts)}."
    cds[key] = now_ts() + cd_secs
    return None

# ── CHASTITY (The Chaste — former Lust) ─────────────────────────────

@bot.command()
async def abstain(ctx, target: discord.Member):
    """(Chastity) Shield a target from all Lust obsession abilities and heart effects for 1 hour."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "lust"):
        await ctx.send("Only The Chaste may grant abstinence.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "abstain", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    target_user = get_user(data, target.id)
    target_user["abstain_shield_until"] = now_ts() + VIRTUE_SHIELD_DURATION
    # Remove possession marks placed on them
    for uid, u in data["users"].items():
        if u.get("sin_role") == "lust":
            pmarks = u.setdefault("possession_marks", {})
            if str(target.id) in pmarks:
                del pmarks[str(target.id)]
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🤍 Abstinence Shield",
        description=(
            f"{ctx.author.mention} (**The Chaste**) has shielded {target.mention}.\n\n"
            f"For **1 hour**, they are immune to all Lust obsession effects, heart reactions, and possession marks.\n"
            "All existing possession marks on them have been cleared."
        ),
        color=discord.Color.from_rgb(230, 210, 255),
    ))

@bot.command()
async def purify(ctx):
    """(Chastity) Release yourself from desire — clear your obsession meter and target."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "lust"):
        await ctx.send("Only The Chaste may purify their desire.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "purify", VIRTUE_CD_LONG)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    old_target = user.get("obsession_target")
    user["obsession_meter"] = 0
    user["obsession_target"] = None
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    t_mention = ""
    if old_target and ctx.guild:
        m = ctx.guild.get_member(int(old_target))
        if m:
            t_mention = f"\n*Released from fixation on {m.mention}.*"

    await ch.send(embed=discord.Embed(
        title="🤍 Purified",
        description=(
            f"{ctx.author.mention} has **released desire**. The obsession meter is cleared.{t_mention}\n\n"
            "*Chastity is not the absence of feeling — it is mastery over it.*"
        ),
        color=discord.Color.from_rgb(230, 210, 255),
    ))

# ── TEMPERANCE (The Fasting King — former Gluttony) ──────────────────

@bot.command()
async def fast(ctx, target: discord.Member):
    """(Temperance) Lift a feast curse from a target and grant them a brief power boost."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "gluttony"):
        await ctx.send("Only The Fasting King may lift hunger curses.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "fast", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    uid_str = str(target.id)
    had_curse = uid_str in data.get("feast_cursed", {})
    if had_curse:
        del data["feast_cursed"][uid_str]

    target_user = get_user(data, target.id)
    target_user["clash_power_bonus"]  = (target_user.get("clash_power_bonus") or 0) + 1
    target_user["clash_penalty_until"] = now_ts() + 1800  # 30-min boost
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🥗 The Fast Breaks the Curse",
        description=(
            f"{ctx.author.mention} (**The Fasting King**) lifts hunger from {target.mention}.\n\n"
        ) + (
            "The feast curse has been **removed**.\n" if had_curse else ""
        ) + (
            "**+1 clash coin** for the next **30 minutes** — moderation restores strength."
        ),
        color=discord.Color.from_rgb(180, 220, 150),
    ))

@bot.command()
async def moderate(ctx, target: discord.Member):
    """(Temperance) Reduce a target's clash power bonus by 1 (reins in Gorge, Frenzy, Sleepwalker etc)."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "gluttony"):
        await ctx.send("Only The Fasting King may moderate excess.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "moderate", VIRTUE_CD_SHORT)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot moderate yourself.", delete_after=5); save_data(data); return

    target_user = get_user(data, target.id)
    old_bonus   = target_user.get("clash_power_bonus", 0) or 0
    if old_bonus <= 0:
        await ctx.send(f"{target.display_name} has no power bonus to moderate.", delete_after=8)
        save_data(data); return

    target_user["clash_power_bonus"] = max(0, old_bonus - 1)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="⚖️ Moderation",
        description=(
            f"{ctx.author.mention} (**The Fasting King**) tempers {target.mention}'s excess.\n\n"
            f"Their clash power bonus drops from **+{old_bonus}** to **+{max(0, old_bonus-1)}**."
        ),
        color=discord.Color.from_rgb(180, 220, 150),
    ))

# ── CHARITY (The Open Hand — former Greed) ───────────────────────────

@bot.command()
async def gift_power(ctx, target: discord.Member):
    """(Charity) Give 1 of your clash coins to a target for 2 hours."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "greed"):
        await ctx.send("Only The Open Hand may gift power.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "gift_power", VIRTUE_CD_LONG)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot gift to yourself.", delete_after=5); save_data(data); return

    target_user = get_user(data, target.id)
    expires = now_ts() + 7200  # 2 hr

    # Self penalty
    user["clash_power_penalty"] = (user.get("clash_power_penalty") or 0) + 1
    user["clash_penalty_until"] = expires
    user["power_gifted"] = {"to_id": str(target.id), "expires": expires}

    # Target bonus
    target_user["clash_power_bonus"] = (target_user.get("clash_power_bonus") or 0) + 1

    save_data(data)
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🤲 Gift of Power",
        description=(
            f"{ctx.author.mention} (**The Open Hand**) surrenders power to {target.mention}.\n\n"
            f"**{target.mention}** gains **+1 clash coin** for **2 hours**.\n"
            f"**{ctx.author.mention}** loses **-1 clash coin** for the same duration.\n\n"
            "*True charity costs something.*"
        ),
        color=discord.Color.from_rgb(220, 200, 80),
    ))

@bot.command()
async def return_ability(ctx, target: discord.Member):
    """(Charity) Return a stolen ability back to its original owner early."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "greed"):
        await ctx.send("Only The Open Hand may return stolen abilities.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "return_ability", VIRTUE_CD_SHORT)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    # Find any active stolen ability whose original_holder_id matches target
    stolen = data.get("stolen_abilities", [])
    removed = [s for s in stolen if s["original_holder_id"] == str(target.id) and now_ts() < s["expires"]]
    if not removed:
        await ctx.send(f"{target.display_name} has no abilities currently stolen.", delete_after=8)
        save_data(data); return

    data["stolen_abilities"] = [s for s in stolen if s["original_holder_id"] != str(target.id) or now_ts() >= s["expires"]]
    save_data(data)

    ability_names = ", ".join(f"**{s['ability_key'].replace('_',' ')}**" for s in removed)
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🤲 Returned",
        description=(
            f"{ctx.author.mention} (**The Open Hand**) has returned {target.mention}'s {ability_names}.\n\n"
            "*What was taken is given back. That is its own power.*"
        ),
        color=discord.Color.from_rgb(220, 200, 80),
    ))
    try:
        await target.send(f"🤲 Your **{ability_names}** has been returned by The Open Hand.")
    except Exception:
        pass

# ── DILIGENCE (The Waking — former Sloth) ───────────────────────────

@bot.command()
async def inspire(ctx, target: discord.Member):
    """(Diligence) Remove laziness / slowdown curses from a target and grant them a +1 bonus."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "sloth"):
        await ctx.send("Only The Waking may inspire others.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "inspire", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    uid_str     = str(target.id)
    target_user = get_user(data, target.id)
    removed = []

    if uid_str in data.get("force_lazy_targets", {}):
        del data["force_lazy_targets"][uid_str]; removed.append("laziness curse")
    if uid_str in data.get("slowdown_targets", {}):
        del data["slowdown_targets"][uid_str]; removed.append("slowdown curse")
    if now_ts() < (target_user.get("slow_type_until") or 0):
        target_user["slow_type_until"] = None; removed.append("slow-type penalty")

    target_user["clash_power_bonus"] = (target_user.get("clash_power_bonus") or 0) + 1
    expires = now_ts() + 3600
    target_user["clash_penalty_until"] = expires  # reuse to track when bonus ends

    save_data(data)
    ch = await trial_channel(ctx.guild) or ctx.channel
    removed_str = ", ".join(removed) if removed else "no active curses"
    await ch.send(embed=discord.Embed(
        title="⚡ Inspired",
        description=(
            f"{ctx.author.mention} (**The Waking**) sparks life into {target.mention}.\n\n"
            f"Removed: *{removed_str}*\n"
            "**+1 clash coin** for **1 hour**.\n\n"
            "*Sometimes it just takes one person who believes in you.*"
        ),
        color=discord.Color.from_rgb(255, 220, 100),
    ))
    try:
        await target.send(f"⚡ You've been **inspired** by The Waking. Curses lifted, +1 power for 1 hour.")
    except Exception:
        pass

@bot.command()
async def rouse(ctx, target: discord.Member):
    """(Diligence) Attempt to wake a sleeping target early and reduce their laziness meter."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "sloth"):
        await ctx.send("Only The Waking may rouse others.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "rouse", VIRTUE_CD_LONG)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    target_user = get_user(data, target.id)
    sleep_until = target_user.get("deep_sleep_until") or 0
    lazy        = target_user.get("laziness_meter", 0)

    if now_ts() >= sleep_until and lazy < 80:
        await ctx.send(f"{target.display_name} is already awake and not near collapse.", delete_after=8)
        save_data(data); return

    target_user["deep_sleep_until"] = None
    target_user["laziness_meter"]   = max(0, lazy - 40)

    save_data(data)
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🌅 Roused",
        description=(
            f"{ctx.author.mention} (**The Waking**) pulls {target.mention} back from sleep.\n\n"
            "Deep sleep ended early. Laziness meter reduced by **40%**.\n\n"
            "*The hardest part is just getting up.*"
        ),
        color=discord.Color.from_rgb(255, 220, 100),
    ))
    try:
        await target.send("🌅 You've been **roused** — deep sleep ended, laziness meter -40%.")
    except Exception:
        pass

# ── PATIENCE (The Still Flame — former Wrath) ────────────────────────

@bot.command()
async def de_escalate(ctx, target: discord.Member):
    """(Patience) Remove a rage-strike debuff or reduce Bloodlust duration on a target."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "wrath"):
        await ctx.send("Only The Still Flame may de-escalate.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "de_escalate", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    target_user = get_user(data, target.id)
    actions     = []

    penalty_until = target_user.get("clash_penalty_until") or 0
    if now_ts() < penalty_until and (target_user.get("clash_power_penalty") or 0) > 0:
        target_user["clash_power_penalty"] = max(0, (target_user.get("clash_power_penalty") or 1) - 1)
        actions.append("rage-strike debuff removed")

    bl_until = target_user.get("bloodlust_until") or 0
    if target_user.get("bloodlust_active") and now_ts() < bl_until:
        target_user["bloodlust_until"] = max(now_ts(), bl_until - 600)  # shorten by 10 min
        actions.append("Bloodlust shortened by 10 minutes")

    if not actions:
        await ctx.send(f"{target.display_name} has no active wrath effects to de-escalate.", delete_after=8)
        save_data(data); return

    save_data(data)
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🕊️ De-Escalated",
        description=(
            f"{ctx.author.mention} (**The Still Flame**) calms the fire around {target.mention}.\n\n"
            + "\n".join(f"• {a}" for a in actions) +
            "\n\n*Rage burns brightest just before it fades.*"
        ),
        color=discord.Color.from_rgb(255, 180, 50),
    ))

@bot.command()
async def absorb_strike(ctx):
    """(Patience) Arm yourself to absorb the next rage-strike — reflect it back for 30 minutes."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "wrath"):
        await ctx.send("Only The Still Flame may absorb a strike.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "absorb_strike", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    until = now_ts() + VIRTUE_ABSORB_DURATION
    user["absorb_active"] = True
    user["absorb_until"]  = until
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🛡️ Absorb Primed",
        description=(
            f"{ctx.author.mention} (**The Still Flame**) steadies themselves.\n\n"
            "The **next rage-strike** used against them will be **absorbed** and reflected back "
            f"for **30 minutes**.\n\n"
            "*True patience is not weakness — it is a loaded weapon.*"
        ),
        color=discord.Color.from_rgb(255, 180, 50),
    ))

# ── KINDNESS (The Mirror's Grace — former Envy) ──────────────────────

@bot.command()
async def bless(ctx, target: discord.Member):
    """(Kindness) Remove 1 mark of insecurity from a target and shield them for 1 hour."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "envy"):
        await ctx.send("Only The Mirror's Grace may bless others.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "bless", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    target_user = get_user(data, target.id)
    old_marks   = target_user.get("marks_of_insecurity", 0)
    new_marks   = max(0, old_marks - 1)
    target_user["marks_of_insecurity"]    = new_marks
    target_user["insecurity_shield_until"] = now_ts() + VIRTUE_SHIELD_DURATION
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="💚 Blessed",
        description=(
            f"{ctx.author.mention} (**The Mirror's Grace**) sees worth in {target.mention}.\n\n"
            f"Marks of Insecurity: **{old_marks} → {new_marks}**\n"
            f"They are **shielded** from new insecurity marks for **1 hour**.\n\n"
            "*The kindest mirror shows you who you could be.*"
        ),
        color=discord.Color.from_rgb(100, 220, 100),
    ))
    try:
        await target.send("💚 The Mirror's Grace has blessed you — 1 mark of insecurity removed, +1hr shield.")
    except Exception:
        pass

@bot.command()
async def forgive(ctx, target: discord.Member):
    """(Kindness) Clear an active envy jealousy mark targeting someone."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "envy"):
        await ctx.send("Only The Mirror's Grace may forgive.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "forgive", VIRTUE_CD_SHORT)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    # Find any envy holder whose active mark targets this person
    cleared = False
    for uid, mark in list(data.get("envy_marks", {}).items()):
        if mark.get("target_id") == str(target.id) and now_ts() < mark.get("expires", 0):
            data["envy_marks"][uid]["resolved"] = True
            data["envy_marks"][uid]["expires"]  = 0
            cleared = True

    if not cleared:
        await ctx.send(f"{target.display_name} has no active envy marks against them.", delete_after=8)
        save_data(data); return

    save_data(data)
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="💚 Forgiven",
        description=(
            f"{ctx.author.mention} (**The Mirror's Grace**) dissolves the envy mark on {target.mention}.\n\n"
            "*Jealousy feeds on being remembered. Forgiveness starves it.*"
        ),
        color=discord.Color.from_rgb(100, 220, 100),
    ))

# ── HUMILITY (The Humble Sovereign — former Pride) ───────────────────

@bot.command()
async def submit(ctx):
    """(Humility) Voluntarily reduce your clash power for 30 min but gain double coins on next clash."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "pride"):
        await ctx.send("Only The Humble Sovereign may choose to submit.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "submit", VIRTUE_CD_SHORT)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    expires = now_ts() + 1800  # 30 min
    user["clash_power_penalty"] = (user.get("clash_power_penalty") or 0) + 1
    user["clash_penalty_until"] = expires
    user["clash_power_bonus"]   = (user.get("clash_power_bonus") or 0) + 2  # +2 on next clash
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🙏 The Sovereign Submits",
        description=(
            f"{ctx.author.mention} (**The Humble Sovereign**) bows their head.\n\n"
            "**-1 clash coin** for **30 minutes**.\n"
            "In exchange: **+2 clash coins** on every clash during this window.\n\n"
            "*The one who kneels first controls the room.*"
        ),
        color=discord.Color.from_rgb(200, 170, 255),
    ))

@bot.command()
async def counter_claim(ctx, target: discord.Member):
    """(Humility) Publicly reject a claim against you and reduce the claimer's recognition."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _virtue_check(user, "pride"):
        await ctx.send("Only The Humble Sovereign may counter a claim.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "counter_claim", VIRTUE_CD_MEDIUM)
    if err:
        await ctx.send(err, delete_after=8); save_data(data); return

    target_user = get_user(data, target.id)
    target_sin  = target_user.get("sin_role")
    if target_sin != "pride":
        await ctx.send("You can only counter-claim against the holder of Pride.", delete_after=8)
        save_data(data); return

    old_rec = target_user.get("pride_recognition", 0)
    new_rec = max(0, old_rec - 1)
    target_user["pride_recognition"] = new_rec
    if new_rec < PRIDE_RECOGNITION_THRESHOLD:
        target_user["stop_time_unlocked"] = False
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🙏 Claim Rejected",
        description=(
            f"{ctx.author.mention} (**The Humble Sovereign**) publicly denies the claim of {target.mention}.\n\n"
            f"Their recognition drops: **{old_rec} → {new_rec}**"
        ) + (
            "\n⚠️ Stop Time has been **de-activated** — recognition fell below threshold."
            if old_rec >= PRIDE_RECOGNITION_THRESHOLD > new_rec else ""
        ),
        color=discord.Color.from_rgb(200, 170, 255),
    ))

# ═══════════════════════════════════════════════════════════════════
# ░░ CARDINAL & HEAVENLY VIRTUES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# Prudence · Fortitude · Faith · Hope · Liberality
# (Humility/Kindness/Patience/Diligence/Chastity/Temperance/Charity
#  are the heavenly 7 tied to the sin roles — see VIRTUE ABILITIES)
# ═══════════════════════════════════════════════════════════════════

def _standalone_virtue_check(user: dict, key: str) -> bool:
    """True if user holds the given standalone virtue role and has not fallen."""
    return user.get("sin_role") == key and not user.get("fallen")

# ── PRUDENCE — The Prudent Eye ────────────────────────────────────

@bot.command()
async def discern(ctx, target: discord.Member):
    """(Prudence) Reveal the last 3 sinful actions of a target publicly."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "prudence"):
        await ctx.send("Only The Prudent Eye may discern another's wrongdoings.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "discern", 45 * 60)   # 45-min CD (uses virtue_ability_cds dict)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    t_user   = get_user(data, target.id)
    sins_raw = t_user.get("last_sin_abilities_used") or []
    sins_str = ", ".join(f"`!{a}`" for a in sins_raw[:3]) if sins_raw else "*none recorded*"
    last_ts  = t_user.get("last_sin_action_ts") or 0
    last_str = f"<t:{int(last_ts)}:R>" if last_ts else "*never*"
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🔍 Discern — The Prudent Eye",
        color=discord.Color.from_rgb(200, 180, 80),
        description=(
            f"{ctx.author.mention} (**The Prudent Eye**) opens the book on {target.mention}.\n\n"
            f"**Last sinful actions:** {sins_str}\n"
            f"**Most recent sin:** {last_str}"
        ),
    ))

@bot.command()
async def wise_counsel(ctx, target: discord.Member):
    """(Prudence) Halve the longest active virtue/justice ability cooldown on an ally."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "prudence"):
        await ctx.send("Only The Prudent Eye may offer wise counsel.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "wise_counsel", VIRTUE_CD_MEDIUM)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    t_user   = get_user(data, target.id)
    cds      = t_user.get("virtue_ability_cds") or {}
    jcds     = t_user.get("justice_ability_cds") or {}
    all_cds  = {**cds, **jcds}
    active   = {k: v for k, v in all_cds.items() if (v or 0) > now_ts()}
    if not active:
        await ctx.send(f"{target.mention} has no active ability cooldowns to shorten.", delete_after=8)
        save_data(data); return

    longest_key = max(active, key=lambda k: active[k])
    original    = active[longest_key]
    remaining_s = original - now_ts()
    new_ts      = now_ts() + remaining_s // 2
    if longest_key in cds:
        t_user["virtue_ability_cds"][longest_key] = new_ts
    else:
        t_user["justice_ability_cds"][longest_key] = new_ts
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="📜 Wise Counsel",
        color=discord.Color.from_rgb(200, 180, 80),
        description=(
            f"{ctx.author.mention} (**The Prudent Eye**) guides {target.mention}.\n\n"
            f"Cooldown `{longest_key}` halved: "
            f"**{remaining_fmt(original)}** → **{remaining_fmt(new_ts)}** remaining."
        ),
    ))

# ── FORTITUDE — The Unbroken ─────────────────────────────────────

@bot.command()
async def endure(ctx):
    """(Fortitude) Self-buff: for 20 min, all clash power penalties applied to you are reduced by 1."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "fortitude"):
        await ctx.send("Only The Unbroken may endure.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "endure", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    until = now_ts() + 20 * 60
    user["endure_until"] = until
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🏔️ Endure",
        color=discord.Color.from_rgb(150, 100, 60),
        description=(
            f"{ctx.author.mention} (**The Unbroken**) braces against the storm.\n\n"
            f"For the next **20 minutes**, all clash power penalties applied to you "
            f"are reduced by **1** (minimum 0).\n"
            f"Expires: {ts_fmt(until)}"
        ),
    ))

@bot.command()
async def fortify(ctx, target: discord.Member):
    """(Fortitude) Remove a target's current clash power penalty and shield them for 15 min."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "fortitude"):
        await ctx.send("Only The Unbroken may fortify others.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "fortify", VIRTUE_CD_MEDIUM)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    t_user = get_user(data, target.id)
    old_pen = t_user.get("clash_power_penalty", 0)
    t_user["clash_power_penalty"] = 0
    t_user["clash_penalty_until"] = 0
    t_user["fortify_until"]       = now_ts() + 15 * 60
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🛡️ Fortify",
        color=discord.Color.from_rgb(150, 100, 60),
        description=(
            f"{ctx.author.mention} (**The Unbroken**) fortifies {target.mention}.\n\n"
            f"• Clash power penalty cleared: **-{old_pen}** → **0**\n"
            f"• Shielded from new penalties for **15 minutes**."
        ),
    ))

# ── FAITH — The Faithful ─────────────────────────────────────────

@bot.command()
async def invoke_faith(ctx):
    """(Faith) For 20 min, your effective clash power is treated as +1 higher (win all ties)."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "faith"):
        await ctx.send("Only The Faithful may invoke faith.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "invoke_faith", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    until = now_ts() + 20 * 60
    user["faith_invoke_until"] = until
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="✨ Invoke Faith",
        color=discord.Color.from_rgb(220, 220, 255),
        description=(
            f"{ctx.author.mention} (**The Faithful**) calls on divine favor.\n\n"
            f"For **20 minutes**, your clash power is treated as **+1 higher** — "
            "you win all tied clashes.\n"
            f"Expires: {ts_fmt(until)}"
        ),
    ))

@bot.command()
async def prayer(ctx, target: discord.Member):
    """(Faith) Place a shield on a target: their next ability-lock duration is halved."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "faith"):
        await ctx.send("Only The Faithful may bless with prayer.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "prayer", VIRTUE_CD_MEDIUM)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    t_user = get_user(data, target.id)
    t_user["prayer_shield_until"] = now_ts() + 2 * 3600   # shield lasts 2 hr or until triggered
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🙏 Prayer",
        color=discord.Color.from_rgb(220, 220, 255),
        description=(
            f"{ctx.author.mention} (**The Faithful**) prays over {target.mention}.\n\n"
            f"The next time {target.mention}'s abilities would be locked by a sinful command, "
            "the lock duration is **halved**.\n"
            "*(One-use — consumed on trigger. Lasts up to 2 hours.)*"
        ),
    ))

# ── HOPE — The Hopeful: rewritten as attack/special moves (see Hope & Despair v2 module) ──

# ── LIBERALITY — The Open Spirit ─────────────────────────────────

@bot.command()
async def grant_freedom(ctx, target: discord.Member):
    """(Liberality) Immediately remove all active ability locks from a target."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "liberality"):
        await ctx.send("Only The Open Spirit may grant freedom.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "grant_freedom", VIRTUE_CD_MEDIUM)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    t_user = get_user(data, target.id)
    had_lock = bool(t_user.get("ability_locked_until") and
                    now_ts() < (t_user.get("ability_locked_until") or 0))
    t_user["ability_locked_until"]      = None
    t_user["envy_ability_locked_until"] = None
    t_user["withered_until"]            = None
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🕊️ Grant Freedom",
        color=discord.Color.from_rgb(180, 230, 180),
        description=(
            f"{ctx.author.mention} (**The Open Spirit**) releases {target.mention}.\n\n"
            f"{'All ability locks **cleared**.' if had_lock else 'No active ability locks were found — but the spirit is still appreciated.'}"
        ),
    ))

@bot.command()
async def bestow(ctx, target: discord.Member):
    """(Liberality) Transfer 1 clash power bonus from yourself to a target for 1 hour."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "liberality"):
        await ctx.send("Only The Open Spirit may bestow gifts.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "bestow", 90 * 60)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot bestow upon yourself.", delete_after=5); save_data(data); return

    my_bonus = user.get("clash_power_bonus", 0)
    if my_bonus < 1:
        await ctx.send("You have no clash power bonus to give.", delete_after=8)
        save_data(data); return

    t_user = get_user(data, target.id)
    user["clash_power_bonus"]   = max(0, my_bonus - 1)
    t_user["clash_power_bonus"] = t_user.get("clash_power_bonus", 0) + 1
    t_user["clash_penalty_until"] = max(t_user.get("clash_penalty_until") or 0, now_ts() + 3600)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🎁 Bestow",
        color=discord.Color.from_rgb(180, 230, 180),
        description=(
            f"{ctx.author.mention} (**The Open Spirit**) bestows their power upon {target.mention}.\n\n"
            f"• {ctx.author.mention}: clash bonus **−1**\n"
            f"• {target.mention}: clash bonus **+1** for **1 hour**"
        ),
    ))

# ── !verdict — Admin force-close any trial ───────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def verdict(ctx, target: discord.Member, outcome: str):
    """(Admin) Force-close any open trial for a player. Outcome: convict | acquit | reduce"""
    data     = load_data()
    outcome  = outcome.lower().strip()
    if outcome not in ("convict", "acquit", "reduce"):
        await ctx.send("Outcome must be `convict`, `acquit`, or `reduce`.", delete_after=8)
        save_data(data); return

    pending  = data.get("pending_trials") or {}
    found    = []
    for key in (str(target.id) + "_scale", str(target.id) + "_jacobs"):
        trial = pending.get(key)
        if trial and not trial.get("resolved"):
            found.append((key, trial))

    if not found:
        await ctx.send(f"No open trials found for {target.mention}.", delete_after=8)
        save_data(data); return

    t_user   = get_user(data, target.id)
    lines    = []
    for key, trial in found:
        trial["resolved"] = True
        if outcome == "acquit":
            lines.append(f"• **{trial['type'].replace('_', ' ').title()}** — **acquitted**. No penalty.")
        elif outcome == "reduce":
            lock = now_ts() + 30 * 60
            current_lock = t_user.get("ability_locked_until") or 0
            t_user["ability_locked_until"] = max(current_lock, lock)
            lines.append(f"• **{trial['type'].replace('_', ' ').title()}** — **reduced sentence**: 30-min ability lock.")
        else:  # convict
            abilities  = trial.get("abilities") or []
            two_hours  = now_ts() + 2 * 3600
            for ab in abilities:
                cd_dict_key = _SCALE_ABILITY_CD_MAP.get(ab)
                if cd_dict_key and cd_dict_key.endswith("_cds"):
                    t_user.setdefault(cd_dict_key, {})[ab] = two_hours
                elif cd_dict_key:
                    t_user[cd_dict_key] = two_hours
            current_lock = t_user.get("ability_locked_until") or 0
            t_user["ability_locked_until"] = max(current_lock, two_hours)
            lines.append(f"• **{trial['type'].replace('_', ' ').title()}** — **convicted**: 2-hr ability lock.")

    save_data(data)
    await ctx.send(embed=discord.Embed(
        title=f"⚖️ Admin Verdict — {outcome.upper()}",
        color=discord.Color.from_rgb(200, 160, 60),
        description=(
            f"**Target:** {target.mention}\n\n" +
            "\n".join(lines) +
            f"\n\n*Issued by {ctx.author.mention}*"
        ),
    ))

# ═══════════════════════════════════════════════════════════════════
# ░░ STANDALONE VIRTUE — ATTACK ABILITIES ░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════

# ── JUSTICE attacks ───────────────────────────────────────────────

@bot.command()
async def divine_retribution(ctx, target: discord.Member):
    """(Justice) Smite a sinner who acted in the last 10 minutes: -2 clash power 1hr + 15-min lock."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _justice_check(user):
        await ctx.send("Only The Scales of Justice may call down retribution.", delete_after=5)
        save_data(data); return
    cd = (user.get("justice_ability_cds") or {}).get("divine_retribution", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Divine Retribution on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot smite yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    t_user  = get_user(data, target.id)
    last_bad = t_user.get("last_sin_action_ts") or 0
    if now_ts() - last_bad > 10 * 60:
        await ctx.send(
            f"⚖️ {target.mention} has not sinned in the last 10 minutes. "
            "Retribution requires fresh guilt.", delete_after=10,
        )
        save_data(data); return

    lock_end = now_ts() + 15 * 60
    current_lock = t_user.get("ability_locked_until") or 0
    t_user["ability_locked_until"] = max(current_lock, lock_end)
    t_user["clash_power_penalty"]  = max(t_user.get("clash_power_penalty", 0), 2)
    t_user["clash_penalty_until"]  = now_ts() + 3600
    user.setdefault("justice_ability_cds", {})["divine_retribution"] = now_ts() + 5 * 3600
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="☄️ Divine Retribution",
        color=discord.Color.from_rgb(255, 200, 50),
        description=(
            f"{ctx.author.mention} calls down divine retribution on {target.mention}.\n\n"
            "Their sin was *recent*. Heaven does not forget.\n\n"
            f"• ⛔ Ability lock for **15 minutes**\n"
            f"• ⬇️ **-2 clash power** for **1 hour**"
        ),
    ))

@bot.command()
async def condemn(ctx, target: discord.Member):
    """(Justice) Mark a target as condemned for 1 hour — they lose -1 effective clash power passively."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _justice_check(user):
        await ctx.send("Only The Scales of Justice may condemn.", delete_after=5)
        save_data(data); return
    cd = (user.get("justice_ability_cds") or {}).get("condemn", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"Condemn on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot condemn yourself.", delete_after=5); save_data(data); return

    t_user = get_user(data, target.id)
    until  = now_ts() + 3600
    t_user["condemned_until"] = until
    user.setdefault("justice_ability_cds", {})["condemn"] = now_ts() + 4 * 3600
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🔱 Condemned",
        color=discord.Color.from_rgb(200, 100, 20),
        description=(
            f"{ctx.author.mention} condemns {target.mention} before the server.\n\n"
            f"For **1 hour**, {target.mention} carries the brand of condemnation:\n"
            f"• ⬇️ **-1 effective clash power** (passive, all clashes)\n"
            f"Expires: {ts_fmt(until)}"
        ),
    ))
    try:
        await target.send(f"🔱 You have been **condemned** by {ctx.author.display_name}. "
                          "-1 clash power for 1 hour.")
    except Exception:
        pass

# ── PRUDENCE attacks ──────────────────────────────────────────────

@bot.command()
async def expose(ctx, target: discord.Member):
    """(Prudence) Publicly expose a target's stats and rattle them with -1 clash power for 30 min."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "prudence"):
        await ctx.send("Only The Prudent Eye may expose.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "expose", VIRTUE_CD_MEDIUM)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    t_user      = get_user(data, target.id)
    sins_raw    = t_user.get("last_sin_abilities_used") or []
    sins_str    = ", ".join(f"`!{a}`" for a in sins_raw[:3]) if sins_raw else "*none*"
    t_coins     = _effective_coins(t_user)
    penalty_on  = now_ts() < (t_user.get("clash_penalty_until") or 0)
    lock_on     = now_ts() < (t_user.get("ability_locked_until") or 0)

    t_user["clash_power_penalty"] = max(t_user.get("clash_power_penalty", 0), 1)
    t_user["clash_penalty_until"] = now_ts() + 30 * 60
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🔎 Exposed",
        color=discord.Color.from_rgb(200, 180, 80),
        description=(
            f"{ctx.author.mention} (**The Prudent Eye**) tears away {target.mention}'s mask.\n\n"
            f"**Effective clash power:** {t_coins}\n"
            f"**Ability lock active:** {'Yes ⛔' if lock_on else 'No'}\n"
            f"**Clash penalty active:** {'Yes ⬇️' if penalty_on else 'No'}\n"
            f"**Last sins:** {sins_str}\n\n"
            f"*Rattled by exposure:* ⬇️ **-1 clash power for 30 minutes**."
        ),
    ))

@bot.command()
async def anticipate(ctx, target: discord.Member):
    """(Prudence) Read the battlefield and strike first — coin flip (+1 advantage). Win: 5-min ability lock."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "prudence"):
        await ctx.send("Only The Prudent Eye may anticipate.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "anticipate", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot anticipate yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    t_user       = get_user(data, target.id)
    my_coins     = _effective_coins(user) + 1   # +1 Prudence advantage
    target_coins = _effective_coins(t_user)
    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    if winner == "a":
        current_lock = t_user.get("ability_locked_until") or 0
        t_user["ability_locked_until"] = max(current_lock, now_ts() + 5 * 60)
        save_data(data)
        desc = (f"**{ctx.author.display_name}** saw it coming. {target.mention} is caught flat-footed.\n\n"
                f"🎲 {roll_a} vs {roll_b} — ⛔ **5-minute ability lock** applied.")
    else:
        desc = (f"**{target.display_name}** resisted the foresight.\n\n"
                f"🎲 {roll_a} vs {roll_b} — No effect.")
    await ch.send(embed=discord.Embed(title="🔍 Anticipate", color=discord.Color.from_rgb(200, 180, 80), description=desc))

# ── FORTITUDE attacks ─────────────────────────────────────────────

@bot.command()
async def iron_will(ctx, target: discord.Member):
    """(Fortitude) Crush a target's offense — coin flip (+1 if endure active). Win: clear their bonus + -1 clash 30 min."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "fortitude"):
        await ctx.send("Only The Unbroken may enforce their iron will.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "iron_will", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot use iron will on yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    t_user       = get_user(data, target.id)
    endure_bonus = 1 if (now_ts() < (user.get("endure_until") or 0)) else 0
    my_coins     = _effective_coins(user) + endure_bonus
    target_coins = _effective_coins(t_user)
    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    if winner == "a":
        old_bonus = t_user.get("clash_power_bonus", 0)
        t_user["clash_power_bonus"]   = 0
        t_user["clash_power_penalty"] = max(t_user.get("clash_power_penalty", 0), 1)
        t_user["clash_penalty_until"] = now_ts() + 30 * 60
        save_data(data)
        desc = (f"{ctx.author.mention} breaks {target.mention}'s offensive stance.\n\n"
                f"🎲 {roll_a} vs {roll_b}\n"
                f"• Clash power bonus cleared: **+{old_bonus}** → **0**\n"
                f"• **-1 clash power** for **30 minutes**")
    else:
        desc = (f"{target.mention} withstood the iron will.\n\n"
                f"🎲 {roll_a} vs {roll_b} — No effect.")
    await ch.send(embed=discord.Embed(title="🏔️ Iron Will", color=discord.Color.from_rgb(150, 100, 60), description=desc))

@bot.command()
async def crush(ctx, target: discord.Member):
    """(Fortitude) Overwhelming force — coin flip. Win: 10-min ability lock + -1 clash power 30 min."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "fortitude"):
        await ctx.send("Only The Unbroken may crush.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "crush", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot crush yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    t_user       = get_user(data, target.id)
    my_coins     = _effective_coins(user)
    target_coins = _effective_coins(t_user)
    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    if winner == "a":
        lock_end = now_ts() + 10 * 60
        current_lock = t_user.get("ability_locked_until") or 0
        t_user["ability_locked_until"] = max(current_lock, lock_end)
        t_user["clash_power_penalty"]  = max(t_user.get("clash_power_penalty", 0), 1)
        t_user["clash_penalty_until"]  = now_ts() + 30 * 60
        save_data(data)
        desc = (f"{ctx.author.mention} bears down on {target.mention}.\n\n"
                f"🎲 {roll_a} vs {roll_b}\n"
                f"• ⛔ **10-minute ability lock**\n"
                f"• ⬇️ **-1 clash power** for **30 minutes**")
    else:
        desc = (f"{target.mention} stood firm.\n\n🎲 {roll_a} vs {roll_b} — No effect.")
    await ch.send(embed=discord.Embed(title="🏔️ Crush", color=discord.Color.from_rgb(150, 100, 60), description=desc))

# ── FAITH attacks ─────────────────────────────────────────────────

@bot.command()
async def smite(ctx, target: discord.Member):
    """(Faith) Divine strike — coin flip (+1 if faith_invoke active). Win: -2 clash 30 min + 10-min lock."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "faith"):
        await ctx.send("Only The Faithful may smite.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "smite", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("Heaven does not strike its own faithful.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    t_user       = get_user(data, target.id)
    faith_bonus  = 1 if (now_ts() < (user.get("faith_invoke_until") or 0)) else 0
    my_coins     = _effective_coins(user) + faith_bonus
    target_coins = _effective_coins(t_user)
    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    if winner == "a":
        lock_end = now_ts() + 10 * 60
        current_lock = t_user.get("ability_locked_until") or 0
        t_user["ability_locked_until"] = max(current_lock, lock_end)
        t_user["clash_power_penalty"]  = max(t_user.get("clash_power_penalty", 0), 2)
        t_user["clash_penalty_until"]  = now_ts() + 30 * 60
        save_data(data)
        desc = (f"⚡ Heaven answers {ctx.author.mention}'s call.\n\n"
                f"🎲 {roll_a} vs {roll_b}\n"
                f"• ⬇️ **-2 clash power** for **30 minutes**\n"
                f"• ⛔ **10-minute ability lock**")
    else:
        desc = (f"{target.mention} weathered the smite.\n\n"
                f"🎲 {roll_a} vs {roll_b} — No effect.")
    await ch.send(embed=discord.Embed(title="✨ Smite", color=discord.Color.from_rgb(220, 220, 255), description=desc))

@bot.command()
async def holy_judgment(ctx, target: discord.Member):
    """(Faith) Judge by corruption — -1 clash power per corruption point (max -3) for 1 hour."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "faith"):
        await ctx.send("Only The Faithful may pass holy judgment.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "holy_judgment", VIRTUE_CD_LONG + VIRTUE_CD_SHORT)  # 4hr CD
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot judge yourself.", delete_after=5); save_data(data); return

    t_user     = get_user(data, target.id)
    corruption = t_user.get("corruption", 0) or 0
    if corruption <= 0:
        await ctx.send(
            f"✨ {target.mention} carries no corruption. Holy Judgment finds nothing to punish.",
            delete_after=10,
        )
        save_data(data); return

    penalty = min(3, corruption)
    t_user["clash_power_penalty"] = max(t_user.get("clash_power_penalty", 0), penalty)
    t_user["clash_penalty_until"] = now_ts() + 3600
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="✨ Holy Judgment",
        color=discord.Color.from_rgb(220, 220, 255),
        description=(
            f"{ctx.author.mention} (**The Faithful**) judges {target.mention} by their corruption.\n\n"
            f"**Corruption:** {corruption} → **-{penalty} clash power** for **1 hour**\n"
            f"*(Penalty capped at -3)*"
        ),
    ))

# ── HOPE attacks: !inspire_strike / !despair_wave now live in the Hope & Despair v2 module ──

# ── LIBERALITY attacks ────────────────────────────────────────────

@bot.command()
async def redistribution(ctx, target: discord.Member):
    """(Liberality) Strip all clash power bonuses from a greedy target — clear their bonus to 0."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "liberality"):
        await ctx.send("Only The Open Spirit may redistribute.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "redistribution", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot redistribute from yourself.", delete_after=5); save_data(data); return

    t_user    = get_user(data, target.id)
    old_bonus = t_user.get("clash_power_bonus", 0)
    t_user["clash_power_bonus"] = 0
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🕊️ Redistribution",
        color=discord.Color.from_rgb(180, 230, 180),
        description=(
            f"{ctx.author.mention} (**The Open Spirit**) redistributes {target.mention}'s accumulated power.\n\n"
            f"Clash power bonus: **+{old_bonus}** → **0** (instantly cleared)."
            + ("\n*No bonus was held.*" if old_bonus == 0 else "")
        ),
    ))

@bot.command()
async def break_chains(ctx, target: discord.Member):
    """(Liberality) Coin flip — Win: extend all target's ability CDs by 1 hour."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _standalone_virtue_check(user, "liberality"):
        await ctx.send("Only The Open Spirit may break chains.", delete_after=6)
        save_data(data); return
    err = _virtue_cd_check(user, "break_chains", VIRTUE_CD_LONG)
    if err: await ctx.send(err, delete_after=8); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot chain yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    t_user       = get_user(data, target.id)
    my_coins     = _effective_coins(user)
    target_coins = _effective_coins(t_user)
    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    if winner == "a":
        extra = 3600  # +1 hour penalty on each active CD
        cd_dicts = ["virtue_ability_cds", "justice_ability_cds", "gluttony_ability_cds",
                    "wrath_ability_cds", "greed_ability_cds", "sloth_ability_cds",
                    "gooner_ability_cds", "hope_ability_cds", "faith_ability_cds",
                    "prudence_ability_cds", "fortitude_ability_cds", "liberality_ability_cds"]
        extended = 0
        for dk in cd_dicts:
            d = t_user.get(dk) or {}
            for k, v in d.items():
                if (v or 0) > now_ts():
                    d[k] = (v or 0) + extra
                    extended += 1
        save_data(data)
        desc = (f"{ctx.author.mention} shatters {target.mention}'s ability arsenal — "
                f"and reforges it in chains.\n\n"
                f"🎲 {roll_a} vs {roll_b}\n"
                f"• **{extended}** active ability cooldowns extended by **+1 hour**.")
    else:
        desc = (f"{target.mention} resisted the chains.\n\n"
                f"🎲 {roll_a} vs {roll_b} — No effect.")
    await ch.send(embed=discord.Embed(title="🕊️ Break Chains", color=discord.Color.from_rgb(180, 230, 180), description=desc))


# ═══════════════════════════════════════════════════════════════════
# ░░ PATH SYSTEM ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# Paths: support | attack | hybrid | tacht | reverence
# Applies to ALL roles — sin and virtue.
# ═══════════════════════════════════════════════════════════════════

@bot.command()
async def choose_path(ctx, path: str):
    """Choose your combat path. Options: support / attack / hybrid / tacht / reverence"""
    data = load_data()
    user = get_user(data, ctx.author.id)
    path = path.lower().strip()

    if not _has_role(user) and not user.get("completed_virtues"):
        await ctx.send("You must hold a sin or virtue role before choosing a path.", delete_after=8)
        save_data(data); return
    if path not in VALID_PATHS:
        await ctx.send(
            f"Unknown path. Choose from: `{'` | `'.join(VALID_PATHS)}`", delete_after=10
        )
        save_data(data); return

    change_cd = user.get("path_change_cd") or 0
    if user.get("path") and now_ts() < change_cd:
        await ctx.send(
            f"You are locked into **{user['path']}** path. You can change in {remaining_fmt(change_cd)}.",
            delete_after=10,
        )
        save_data(data); return

    user["path"]          = path
    user["path_change_cd"] = now_ts() + PATH_CHANGE_COOLDOWN
    save_data(data)

    await ctx.send(embed=discord.Embed(
        title=f"⚔️ Path Chosen: {path.upper()}",
        description=(
            PATH_DESCRIPTIONS[path] + "\n\n"
            "Your path-specific abilities are now unlocked.\n"
            "Use `!support_ability`, `!attack_ability`, `!hybrid_ability`, "
            "`!tacht_strike`/`!tacht_burst`, or `!reverence_aura`/`!demand_tribute` depending on your path.\n\n"
            f"*(Path can be changed again in **7 days**)*"
        ),
        color=discord.Color.blurple(),
    ))

@bot.command()
async def my_path(ctx):
    """Show your current path and all path-specific ability cooldowns."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    path = user.get("path")
    if not path:
        await ctx.send(
            "You have no path yet. Use `!choose_path <path>` to pick one.\n"
            f"Options: `{'` | `'.join(VALID_PATHS)}`",
            delete_after=12,
        )
        save_data(data); return

    cds = user.get("path_ability_cds") or {}
    cd_lines = []
    for k, ts in cds.items():
        if now_ts() < ts:
            cd_lines.append(f"• **{k.replace('_',' ')}** — {remaining_fmt(ts)}")

    tacht_burst = user.get("tacht_burst_until") or 0
    rev_aura    = user.get("reverence_aura_until") or 0
    shield      = user.get("clash_shield_until") or 0

    embed = discord.Embed(
        title=f"⚔️ Your Path: {path.upper()}",
        description=PATH_DESCRIPTIONS[path],
        color=discord.Color.blurple(),
    )
    if cd_lines:
        embed.add_field(name="⏳ Cooldowns", value="\n".join(cd_lines), inline=False)
    if now_ts() < tacht_burst:
        embed.add_field(name="⚡ TACHT Burst", value=f"Active — {remaining_fmt(tacht_burst)}", inline=True)
    if now_ts() < rev_aura:
        embed.add_field(name="🌑 Reverence Aura", value=f"Active — {remaining_fmt(rev_aura)}", inline=True)
    if now_ts() < shield:
        embed.add_field(name="🛡️ Clash Shield", value=f"Active — {remaining_fmt(shield)}", inline=True)

    change_cd = user.get("path_change_cd") or 0
    if now_ts() < change_cd:
        embed.set_footer(text=f"Path locked for {remaining_fmt(change_cd)}")

    save_data(data)
    try: await ctx.message.delete()
    except Exception: pass
    await ctx.author.send(embed=embed)


@bot.command(name="commands")
async def all_commands(ctx):
    """DM a full categorized list of every command in the bot."""
    try: await ctx.message.delete()
    except Exception: pass

    embeds = []

    # ── 1. Core ──
    e = discord.Embed(title="📋 Core Commands", color=discord.Color.blurple())
    e.add_field(name="!sinslist", value="List all available sin roles", inline=False)
    e.add_field(name="!virtueslist", value="List all available virtue roles", inline=False)
    e.add_field(name="!mytrial", value="Show your current trial status", inline=False)
    e.add_field(name="!trial @user", value="View another player's trial", inline=False)
    e.add_field(name="!randomtrial", value="Start a random trial event", inline=False)
    e.add_field(name="!mystats", value="View your full stats card (DM)", inline=False)
    e.add_field(name="!rankings", value="Server-wide power rankings", inline=False)
    e.add_field(name="!rankings_sins", value="Rankings filtered by sin role", inline=False)
    e.add_field(name="!history", value="Your action/clash history (DM)", inline=False)
    e.add_field(name="!kill @user", value="Attempt to eliminate a player", inline=False)
    e.add_field(name="!tutorial", value="DM a step-by-step guide to using the bot", inline=False)
    e.add_field(name="!guide", value="Alias for `!tutorial` — DM the same complete guide", inline=False)
    e.add_field(name="!commands", value="DM the complete categorized command and power manual", inline=False)
    e.add_field(name="!invite", value="Show the bot invite link with its required permissions", inline=False)
    e.add_field(name="!obtainment / !role_obtainment", value="DM obtainment methods for every role category", inline=False)
    e.add_field(name="!sin_tutorial / !sin_guide", value="DM the sin powers and sin-role obtainment guide", inline=False)
    e.add_field(name="!virtue_tutorial / !virtue_guide", value="DM the virtue powers and virtue-role obtainment guide", inline=False)
    e.add_field(name="!myth_tutorial / !myth_guide", value="DM the myth powers and myth-role obtainment guide", inline=False)
    e.add_field(name="!despair_tutorial / !despair_guide", value="DM the Despair powers and role guide", inline=False)
    e.add_field(name="!hope_tutorial / !hope_guide", value="DM the Hope powers and role guide", inline=False)
    e.add_field(name="!path_tutorial / !path_guide", value="DM the combat-path powers guide", inline=False)
    e.add_field(name="!role_tutorial / !role_guide / !roles_tutorial", value="DM a literal one-entry-per-role obtainment directory", inline=False)
    embeds.append(e)

    # ── 2. Social / Role ──
    e = discord.Embed(title="🤝 Social & Role Commands", color=discord.Color.teal())
    e.add_field(name="!proclaim", value="Publicly declare your sin role", inline=False)
    e.add_field(name="!praise @user", value="Give another player public praise", inline=False)
    e.add_field(name="!bow_down @user", value="Bow to another player", inline=False)
    e.add_field(name="!give_role @user <role>", value="Offer your role to someone", inline=False)
    e.add_field(name="!confirm_give", value="Confirm a pending role transfer", inline=False)
    e.add_field(name="!repent", value="Repent for your sins (removes corruption)", inline=False)
    embeds.append(e)

    # ── 3. Bounty & Pacts ──
    e = discord.Embed(title="💰 Bounty & Pact Commands", color=discord.Color.gold())
    e.add_field(name="!bounty @user <amount>", value="Place a bounty on a player", inline=False)
    e.add_field(name="!mybounties", value="See all bounties on you (DM)", inline=False)
    e.add_field(name="!pact @user", value="Propose an alliance pact", inline=False)
    e.add_field(name="!accept_pact @user", value="Accept a pending pact offer", inline=False)
    e.add_field(name="!break_pact @user", value="Break an existing pact", inline=False)
    e.add_field(name="!pacts", value="List all your active pacts", inline=False)
    embeds.append(e)

    # ── 4. Meter Status ──
    e = discord.Embed(title="📊 Meter / Status Commands", description="All DM a private status card.", color=discord.Color.dark_gray())
    e.add_field(name="!greed_meter", value="View your Greed anger & frenzy meter", inline=False)
    e.add_field(name="!sloth_meter", value="View your Sloth laziness meter", inline=False)
    e.add_field(name="!envy_meter", value="View your Envy insecurity marks", inline=False)
    e.add_field(name="!wrath_meter", value="View your Wrath rage & bloodlust status", inline=False)
    e.add_field(name="!gluttony_meter", value="View your Gluttony gorge & feast status", inline=False)
    e.add_field(name="!pride_meter", value="View your Pride recognition & stop-time status", inline=False)
    e.add_field(name="!obsession_meter", value="View your Lust obsession meter", inline=False)
    e.add_field(name="!coin_power", value="Your current effective clash coin total (DM)", inline=False)
    e.add_field(name="!coin_power @user", value="Check another player's coin power (public)", inline=False)
    embeds.append(e)

    # ── 5. Lust Abilities ──
    e = discord.Embed(title="💋 Lust Abilities", color=discord.Color.from_rgb(220, 50, 100))
    e.add_field(name="!obsess @user", value="Mark a player as your obsession target", inline=False)
    e.add_field(name="!obsession_clash @user", value="Clash fueled by obsession (+1 coin if target is marked)", inline=False)
    e.add_field(name="!i_dont_care_if_theyre_watching", value=(
        "Declare your obsession publicly — reveals your target to the whole server.\n"
        "**+30 Obsession Meter** + **+2 clash power for 30 min**. 6hr CD."
    ), inline=False)
    embeds.append(e)

    # ── 6. Gluttony Abilities ──
    e = discord.Embed(title="🍽️ Gluttony Abilities", color=discord.Color.from_rgb(180, 100, 30))
    e.add_field(name="!gorge", value="Eat messages — build up clash coin bonus for 15 min. 45-min CD.", inline=False)
    e.add_field(name="!feast @user", value="Coin flip — curse target to include a food emoji in every message for 20 min. 1.5hr CD.", inline=False)
    e.add_field(name="!devour @user", value=(
        "Swallow a player whole — they cannot send **any** messages or commands for **5 minutes**. 3hr CD."
    ), inline=False)
    embeds.append(e)

    # ── 6b. Gooner Abilities ──
    e = discord.Embed(
        title="🦊 Gooner Abilities",
        description="*Special Class — The Fox Gooner*\nTrial: post **100 images** in **#gooner-trial** within 7 days.",
        color=discord.Color.from_rgb(220, 110, 30),
    )
    e.add_field(name="!flash @user", value=(
        "Flash **Diane Foxington** at a target — stuns them for **30 seconds** "
        "(ability lock via `ability_locked_until`). 90-min CD."
    ), inline=False)
    e.add_field(name="!withered_meat @user", value=(
        "Smack target with **withered meat** — renders all their abilities useless for **10 minutes**. 2hr CD."
    ), inline=False)
    e.add_field(name="!diane_foxington", value=(
        "Summon **Diane Foxington** — she whispers something seductive to you "
        "and delivers a cocky remark to everyone else. 3hr CD."
    ), inline=False)
    e.add_field(name="!gooner_meter [@user]", value=(
        "Show Gooner trial progress (images submitted / 100) and ability cooldowns."
    ), inline=False)
    embeds.append(e)

    # ── 6c. Danganronpa / Despair Powers ──
    e = discord.Embed(
        title="🎭 Danganronpa & Despair Powers",
        description=(
            "These powers belong to the Ultimate Despair, Despair Sister, "
            "Reserve Course Students, or claimed character roles."
        ),
        color=discord.Color.from_rgb(80, 0, 0),
    )
    e.add_field(name="!characters", value="List every character's Hope and Despair role, talent, and base stats.", inline=False)
    e.add_field(name="!claim_hope <character>", value="Claim a character's Hope version. Use `!characters` for valid names.", inline=False)
    e.add_field(name="!claim_despair <character>", value="Unlock and switch to your character's Despair version (needs the Hope version first).", inline=False)
    e.add_field(name="!alignment [hope|despair]", value="Swap between your character's Hope and Despair versions (1hr CD).", inline=False)
    e.add_field(name="!talent @user / !special @user", value="Use your character's attack / special. Every character has a different kit per version. Izuru: `!talent <character> @user`.", inline=False)
    e.add_field(name="!talents [character]", value="Show a character's Hope and Despair abilities.", inline=False)
    e.add_field(name="!luck_switch", value="**Nagito:** \"My luck is so bad...\" — **99%** of hits miss for 20 min. Toggle. 2hr CD.", inline=False)
    e.add_field(name="!fortune @user", value="**Nagito:** apply **any** effect with dropdowns for effect + duration (1hr max, **2hr** if they tried to attack you). 45m CD.", inline=False)
    e.add_field(name="!effects [@user]", value="Show active status effects.", inline=False)
    e.add_field(name="!mycharacter", value="Show your current character, alignment, stats, status effects, and Izuru progress.", inline=False)
    e.add_field(name="!tragic_event", value="Ultimate Despair passive: the next person to speak faces a Hope-or-Despair choice.", inline=False)
    e.add_field(name="!brainwash @user", value="Ultimate Despair power: the target's next attack backfires and damages them instead.", inline=False)
    e.add_field(name="!disaster", value="Ultimate Despair power: start a server-wide disaster. Members must defend or risk losing their role.", inline=False)
    e.add_field(name="!defend", value="Respond to an active disaster to protect yourself from its role-loss consequence.", inline=False)
    e.add_field(name="!summon_sister", value="Summon a Despair Sister NPC who can obey your commands.", inline=False)
    e.add_field(name="!sister_kill @user", value="Command your summoned Despair Sister to attack a target.", inline=False)
    e.add_field(name="!sister_say <message>", value="Make your summoned Despair Sister speak in the trial channel.", inline=False)
    e.add_field(name="!sister_seduce @user", value="Command the Despair Sister to seduce a target.", inline=False)
    e.add_field(name="!sister_anything <action>", value="Describe another action for your summoned Despair Sister to perform.", inline=False)
    e.add_field(name="!summon_reserve", value="Ultimate Despair power: summon Reserve Course Students to fight for you.", inline=False)
    e.add_field(name="!student_attack @user", value="Command one of your active Reserve Course Students to attack a target.", inline=False)
    e.add_field(name="!brainwash_remnant @user", value="Ultimate Despair power: attempt to convert a target into a Remnant of Despair; higher corruption improves the chance.", inline=False)
    e.add_field(name="!approve_izuru @user", value="Give a player one approval toward Izuru Kamakura's Ultimate Hope surgery.", inline=False)
    e.add_field(name="!izuru_despair", value="Become Izuru Kamakura — Ultimate Despair, with all talents and despair passives.", inline=False)
    e.add_field(name="!izuru_hope", value="Attempt life-changing surgery to become Izuru Kamakura — Ultimate Hope; requires the listed corruption, Hope points, and approvals.", inline=False)
    e.add_field(name="!boredom @user", value="**Izuru (Despair):** \"How boring...\" — pierce strike + Shock. 1hr CD.", inline=False)
    e.add_field(name="!hope_overdrive @user", value="**Izuru (Hope, mastery):** every talent at once — 2.4x pierce + Fragile. 2hr CD.", inline=False)
    e.add_field(name="!analyze @user", value="**Izuru:** read a target's stats/effects and leave them Fragile for 5 min. 20m CD.", inline=False)
    e.add_field(name="!grant_despair @user", value="**Admin:** crown The Ultimate Despair (bypasses the Friday window).", inline=False)
    embeds.append(e)

    # ── 6d. PVP Combat & Recovery ──
    e = discord.Embed(
        title="⚔️ PVP Combat & Recovery",
        description="Universal combat powers work alongside your sin, virtue, myth, or character abilities.",
        color=discord.Color.from_rgb(150, 40, 40),
    )
    e.add_field(name="!attack @user", value="Attack another player. Damage uses your role's HP/ATK/DEF stats; the next attack may be blocked by Weeping Veil.", inline=False)
    e.add_field(name="!heal", value="Recover a random amount of HP. Has a 5-minute cooldown.", inline=False)
    e.add_field(name="!kill @user", value="Attempt to eliminate a player through the bot's elimination flow.", inline=False)
    e.add_field(name="!bounty @user [amount]", value="Place a bounty on a sin holder, or use it without a target to view active bounties.", inline=False)
    e.add_field(name="!mybounties", value="View bounties placed on you and bounties you have placed.", inline=False)
    e.add_field(name="!pact @user", value="Propose an alliance pact or view your current pact.", inline=False)
    e.add_field(name="!accept_pact @user", value="Accept a pending pact proposal.", inline=False)
    e.add_field(name="!break_pact @user", value="Dissolve your current pact.", inline=False)
    e.add_field(name="!pacts", value="View active pacts in the server.", inline=False)
    embeds.append(e)

    # ── 7. Greed Abilities ──
    e = discord.Embed(title="💰 Greed Abilities", color=discord.Color.from_rgb(220, 180, 0))
    e.add_field(name="!steal_ability @user", value="Steal target's most recent ability for yourself", inline=False)
    e.add_field(name="!i_always_get_what_i_want @user", value="Force target to give you their top bonus", inline=False)
    e.add_field(name="!frenzy_clash @user", value="Enter Frenzy — +2 coins, but you lose 2 if you lose", inline=False)
    embeds.append(e)

    # ── 8. Wrath Abilities ──
    e = discord.Embed(title="🔥 Wrath Abilities", color=discord.Color.red())
    e.add_field(name="!rage_strike @user", value="High-damage clash strike (+1 coin, resets rage meter)", inline=False)
    e.add_field(name="!bloodlust", value="Activate bloodlust — +1 coin all clashes for 1 hr (1 use/hr)", inline=False)
    e.add_field(name="!summon_meteor @user", value="**Wrath exclusive** — Costs 5 coins, 4hr CD. Hit = -2 power + ability lock + Corruption", inline=False)
    embeds.append(e)

    # ── 9. Sloth Abilities ──
    e = discord.Embed(title="😴 Sloth Abilities", color=discord.Color.from_rgb(100, 80, 140))
    e.add_field(name="!force_lazy @user", value="Apply laziness to target — they type slowly for 30 min", inline=False)
    e.add_field(name="!slowdown @user", value="Slow target's command speed (-1 coin next clash)", inline=False)
    e.add_field(name="!force_sleep @user", value="Put target to sleep — they can't use abilities for 15 min", inline=False)
    e.add_field(name="!deep_sleep @user", value="Extended sleep — 30 min ability lockout (2hr CD)", inline=False)
    e.add_field(name="!sleepwalker", value="Enter sleepwalker mode — +1 coin but you self-slow", inline=False)
    embeds.append(e)

    # ── 10. Envy Abilities ──
    e = discord.Embed(title="💚 Envy Abilities", color=discord.Color.green())
    e.add_field(name="!envy_strike @user", value="*(Trial only)* Strip a random non-protected role from a target — anonymously. Others can react 🔍 to expose you.", inline=False)
    e.add_field(name="!jealousy_mark @user", value="Mark someone with jealousy — pings @everyone. They have 30 min to use `!envy_check`. If they don't, **Envy automatically steals their sin role** for a limited time (shorter for higher-power targets). Pride cannot be marked.", inline=False)
    e.add_field(name="!envy_check", value="Use if you think *you're* the jealousy mark target. If correct: the mark dissolves, Envy gets +1 Corruption and ability lock for 1 hour. Only the marked person can trigger this.", inline=False)
    e.add_field(name="!schizo @user", value="Flood the channel with fake Discord messages that appear to come from random server members — targeting a specific player. Uses coin flip against target.", inline=False)
    e.add_field(name="!marks [@user]", value="Publicly view marks of insecurity on yourself or another player, including Krodingers Effect progress.", inline=False)
    e.add_field(name="!envy_meter", value="View your private Envy status: marks of insecurity, Krodingers Effect, active jealousy mark, and stolen roles (DM).", inline=False)
    embeds.append(e)

    # ── 11. Pride Abilities ──
    e = discord.Embed(title="👑 Pride Abilities", color=discord.Color.from_rgb(200, 160, 0))
    e.add_field(name="!weaken <sin>", value="Reduce a sin's effective power level by 1 for **30 minutes** — coin flip against that sin's holder. Cannot target Pride itself.", inline=False)
    e.add_field(name="!claim @user", value="Claim a target — all sin holders with equal or lower power must **bow** (`!bow_down`) within a window (5–20 min based on power) or gain a **mark of insecurity**. 2hr cooldown.", inline=False)
    e.add_field(name="!recognition", value="View your current recognition count (DM). Recognition builds when others bow to your claims.", inline=False)
    e.add_field(name="!stop_time freeze/@user | passive", value="**Unlocks at recognition threshold** — `freeze` locks a target's abilities for 20 min; `passive` auto-evades the next ability used against you.", inline=False)
    embeds.append(e)

    # ── 12a. Chastity (counters Lust) ──
    e = discord.Embed(title="🤍 Chastity Abilities", description="*Virtue of Lust — The Chaste*\nCounters obsession, possession, and desire-based effects.", color=discord.Color.from_rgb(230, 200, 220))
    e.add_field(name="!abstain [@user]", value="Shield yourself or a target from all Lust obsession abilities for **1 hour**", inline=False)
    e.add_field(name="!purify", value="Clear your own obsession meter and release your current obsession target", inline=False)
    embeds.append(e)

    # ── 12b. Temperance (counters Gluttony) ──
    e = discord.Embed(title="🍃 Temperance Abilities", description="*Virtue of Gluttony — The Fasting King*\nCounters feast curses, gorge bonuses, and overindulgence.", color=discord.Color.from_rgb(180, 220, 160))
    e.add_field(name="!fast [@user]", value="Lift a feast curse from yourself or a target and grant a brief power boost", inline=False)
    e.add_field(name="!moderate @user", value="Reduce target's clash power bonus by 1 (reins in Gorge, Frenzy, Sleepwalker, etc.)", inline=False)
    embeds.append(e)

    # ── 12c. Charity (counters Greed) ──
    e = discord.Embed(title="💛 Charity Abilities", description="*Virtue of Greed — The Open Hand*\nCounters stolen abilities, coin manipulation, and hoarding.", color=discord.Color.from_rgb(240, 220, 100))
    e.add_field(name="!gift_power @user", value="Give 1 of your clash coins to a target — lasts **2 hours**", inline=False)
    e.add_field(name="!return_ability", value="Return any stolen ability back to its original owner early", inline=False)
    embeds.append(e)

    # ── 12d. Diligence (counters Sloth) ──
    e = discord.Embed(title="⚡ Diligence Abilities", description="*Virtue of Sloth — The Waking*\nCounters laziness, sleep, and slowdown curses.", color=discord.Color.from_rgb(255, 200, 80))
    e.add_field(name="!inspire @user", value="Remove laziness and slowdown curses from a target — grants them **+1 coin** bonus", inline=False)
    e.add_field(name="!rouse @user", value="Attempt to wake a sleeping target early and reduce their laziness meter", inline=False)
    embeds.append(e)

    # ── 12e. Patience (counters Wrath) ──
    e = discord.Embed(title="🕊️ Patience Abilities", description="*Virtue of Wrath — The Still Flame*\nCounters rage strikes, bloodlust, and clash aggression.", color=discord.Color.from_rgb(160, 200, 230))
    e.add_field(name="!de_escalate @user", value="Remove a rage-strike debuff or reduce Bloodlust duration on a target", inline=False)
    e.add_field(name="!absorb_strike @user", value="Arm yourself to absorb the next rage-strike aimed at you — reflects it back for **30 min**", inline=False)
    embeds.append(e)

    # ── 12f. Kindness (counters Envy) ──
    e = discord.Embed(title="💚 Kindness Abilities", description="*Virtue of Envy — The Mirror's Grace*\nCounters insecurity marks, jealousy, and envy strikes.", color=discord.Color.from_rgb(120, 200, 140))
    e.add_field(name="!bless @user", value="Remove 1 mark of insecurity from a target and shield them for **1 hour**", inline=False)
    e.add_field(name="!forgive @user", value="Clear an active jealousy mark targeting someone, or cancel a bounty", inline=False)
    embeds.append(e)

    # ── 12g. Humility (counters Pride) ──
    e = discord.Embed(title="🌿 Humility Abilities", description="*Virtue of Pride — The Humble Sovereign*\nCounters claims, recognition abuse, and dominance.", color=discord.Color.from_rgb(180, 160, 200))
    e.add_field(name="!submit", value="Voluntarily reduce your clash power for 30 min — gain **double coins** on your next clash", inline=False)
    e.add_field(name="!counter_claim", value="Publicly reject a Pride !claim — reduces the claimer's recognition count by 1", inline=False)
    embeds.append(e)

    # ── 12h. Prudence — The Prudent Eye ──
    e = discord.Embed(
        title="🔍 Prudence Abilities",
        description="*Standalone Cardinal Virtue — The Prudent Eye*\nWisdom to see what others hide.",
        color=discord.Color.from_rgb(200, 180, 80),
    )
    e.add_field(name="!discern @user", value="Reveals the target's last 3 sinful actions and most recent sin timestamp publicly. **45-min CD.**", inline=False)
    e.add_field(name="!wise_counsel @user", value="Halves the longest active virtue/justice ability cooldown on an ally. **2hr CD.**", inline=False)
    e.add_field(name="— ⚔️ Attack Abilities —", value="\u200b", inline=False)
    e.add_field(name="!expose @user", value="Tear away a target's mask: publicly broadcast their clash power, buffs, and last sins. Also applies **-1 clash power for 30 min** (rattled). **2hr CD.**", inline=False)
    e.add_field(name="!anticipate @user", value="Read the battlefield and strike first — coin flip with **+1 Prudence advantage**. Win: ⛔ **5-min ability lock**. **3hr CD.**", inline=False)
    embeds.append(e)

    # ── 12i. Fortitude — The Unbroken ──
    e = discord.Embed(
        title="🏔️ Fortitude Abilities",
        description="*Standalone Cardinal Virtue — The Unbroken*\nEndurance against every blow.",
        color=discord.Color.from_rgb(150, 100, 60),
    )
    e.add_field(name="!endure", value="Self-buff: for **20 min**, all clash power penalties applied to you are reduced by **1** (min 0). **3hr CD.**", inline=False)
    e.add_field(name="!fortify @user", value="Clear a target's current clash power penalty entirely and shield them from new penalties for **15 min**. **2hr CD.**", inline=False)
    e.add_field(name="— ⚔️ Attack Abilities —", value="\u200b", inline=False)
    e.add_field(name="!iron_will @user", value="Coin flip — **+1 advantage if !endure is active**. Win: clear target's entire clash power bonus + ⬇️ **-1 clash power for 30 min**. **3hr CD.**", inline=False)
    e.add_field(name="!crush @user", value="Overwhelming offensive strike — coin flip. Win: ⛔ **10-min ability lock** + ⬇️ **-1 clash power for 30 min**. **3hr CD.**", inline=False)
    embeds.append(e)

    # ── 12j. Faith — The Faithful ──
    e = discord.Embed(
        title="✨ Faith Abilities",
        description="*Standalone Theological Virtue — The Faithful*\nDivine certainty where others doubt.",
        color=discord.Color.from_rgb(220, 220, 255),
    )
    e.add_field(name="!invoke_faith", value="Self-buff: for **20 min**, your clash power is treated as **+1 higher** — you win all tied clashes. **3hr CD.**", inline=False)
    e.add_field(name="!prayer @user", value="Shield a target: the **next** ability-lock applied to them is **halved** in duration (one-use, lasts up to 2hr). **2hr CD.**", inline=False)
    e.add_field(name="— ⚔️ Attack Abilities —", value="\u200b", inline=False)
    e.add_field(name="!smite @user", value="Divine strike — coin flip (**+1 advantage if !invoke_faith is active**). Win: ⬇️ **-2 clash power for 30 min** + ⛔ **10-min lock**. **3hr CD.**", inline=False)
    e.add_field(name="!holy_judgment @user", value="Judge by corruption — if target has any corruption, apply **-1 clash power per point** (max -3) for **1 hour**. No coin flip needed. **4hr CD.**", inline=False)
    embeds.append(e)

    # ── 12k. Hope — The Hopeful ──
    e = discord.Embed(
        title="💫 Hope Abilities",
        description="*Standalone Theological Virtue — The Hopeful*\nA light that refuses to go out.",
        color=discord.Color.from_rgb(100, 180, 255),
    )
    e.add_field(name="— ⚔️ Attack / Special Abilities —", value="\u200b", inline=False)
    e.add_field(name="!radiant_strike @user", value="Piercing beam of hope (ignores DEF). **50%** to Shock for 5 min. **30m CD.**", inline=False)
    e.add_field(name="!hope_barrage @user", value="Three rapid hits; you gain **Empowered** (+50% damage) for 10 min. **2hr CD.**", inline=False)
    e.add_field(name="!inspire_strike @user", value="Hit that **Slows** the target (60s attack cooldown) for 20 min. **45m CD.**", inline=False)
    e.add_field(name="!despair_wave @user", value="Hits **1.5x** harder if the target already has a debuff; otherwise inflicts **Panic** for 10 min. **1hr CD.**", inline=False)
    embeds.append(e)

    # ── 12l. Liberality — The Open Spirit ──
    e = discord.Embed(
        title="🕊️ Liberality Abilities",
        description="*Standalone Virtue — The Open Spirit*\nGenerosity that moves freely.",
        color=discord.Color.from_rgb(180, 230, 180),
    )
    e.add_field(name="!grant_freedom @user", value="Immediately remove **all active ability locks** from a target (ability_locked_until, withered_until, envy lock). **2hr CD.**", inline=False)
    e.add_field(name="!bestow @user", value="Transfer **1 clash power bonus** from yourself to a target — they gain +1 for 1 hour, you lose 1. **90-min CD.**", inline=False)
    e.add_field(name="— ⚔️ Attack Abilities —", value="\u200b", inline=False)
    e.add_field(name="!redistribution @user", value="Strip all clash power bonuses from a greedy target — instantly clears their `clash_power_bonus` to **0**. **3hr CD.**", inline=False)
    e.add_field(name="!break_chains @user", value="Coin flip. Win: every one of the target's **currently active** ability cooldowns is extended by **+1 hour**. **3hr CD.**", inline=False)
    embeds.append(e)

    # ── 12m. Justice — The Scales of Justice (standalone attacking virtue) ──
    e = discord.Embed(
        title="⚖️ Justice Abilities",
        description=(
            "*Special Virtue Class — The Scales of Justice*\n"
            "Justice can **attack** — but only from a clean record."
        ),
        color=discord.Color.from_rgb(255, 240, 100),
    )
    e.add_field(
        name="!jacobs_ladder @user",
        value=(
            "Cast **Jacob's Ladder** — divine assault against a sinner.\n"
            "Incantation: *\"Throughout life and death, connecting heaven and earth, "
            "I cast upon you: Jacob's Ladder\"*\n"
            "**Requires:** no sinful action in the last **5 minutes** (clean record).\n"
            "Target has **20 seconds** to `!clash` back. No contest = "
            "⛔ 5-min ability lock + ⬇️ -1 clash power 30 min. **4hr CD.**"
        ),
        inline=False,
    )
    e.add_field(
        name="!scale_of_wrongdoing @user",
        value=(
            "Put a guilty player on trial — they must respond within **30 seconds**:\n"
            "• **Deny** (*\"I never did that\", \"I don't recognize that\"...*) → clash window opens to contest.\n"
            "• **Play dumb** (*\"That happened?\", \"Huh?\"...*) → same as denial.\n"
            "• **Plead guilty** (*\"I'm guilty\", \"I confess\"...*) → reduced penalty (30-min lock).\n"
            "• **Silence** → automatic conviction: abilities used in wrongdoing disabled **2 hours**. "
            "Clashable only if the accused hasn't been apprehended within 30 seconds. **3hr CD.**"
        ),
        inline=False,
    )
    e.add_field(name="— ⚔️ More Attack Abilities —", value="\u200b", inline=False)
    e.add_field(
        name="!divine_retribution @user",
        value=(
            "Smite a sinner who acted in the **last 10 minutes**.\n"
            "No coin flip — their fresh guilt is its own verdict.\n"
            "Result: ⛔ **15-min ability lock** + ⬇️ **-2 clash power for 1 hour**. **5hr CD.**"
        ),
        inline=False,
    )
    e.add_field(
        name="!condemn @user",
        value=(
            "Brand a target as **condemned** for **1 hour**.\n"
            "Passive: they lose **-1 effective clash power** in every clash during this window. **4hr CD.**"
        ),
        inline=False,
    )
    embeds.append(e)

    # ── 13. Path System ──
    e = discord.Embed(title="⚔️ Path System", color=discord.Color.from_rgb(80, 80, 200))
    e.add_field(name="!choose_path <path>", value="Pick your combat path. Options: `support` | `attack` | `hybrid` | `tacht` | `reverence`\nLocked for **7 days** after choosing.", inline=False)
    e.add_field(name="!my_path", value="View your current path, active bursts/auras, and all cooldowns (DM)", inline=False)
    e.add_field(name="!path_info", value="Full breakdown of every path and each sin's specific abilities (DM)", inline=False)
    e.add_field(name="!support_ability [@ally]", value="Use your sin's Support path ability", inline=False)
    e.add_field(name="!attack_ability @target", value="Use your sin's Attack path ability (+1 coin bonus)", inline=False)
    e.add_field(name="!hybrid_ability @ally [@enemy]", value="Use your sin's Hybrid path ability (buff + debuff)", inline=False)
    e.add_field(name="!tacht_strike @user", value="**TACHT** — Preemptive speed strike (+1 you, -1 them). 1hr CD", inline=False)
    e.add_field(name="!tacht_burst", value="**TACHT** — 20-min Speed Burst: halve all path CDs + +1 coin passive. 3hr CD", inline=False)
    e.add_field(name="!reverence_aura", value="**Reverence** — 30-min aura: attackers lose -1 coin. 3hr CD", inline=False)
    e.add_field(name="!demand_tribute @user", value="**Reverence** — Target must bow 🙏 in 20 min or take -1 power for 1 hr. 2hr CD", inline=False)
    embeds.append(e)

    # ── 14. Envy Stolen Roles ──
    e = discord.Embed(title="🌑 Stolen Roles", color=discord.Color.from_rgb(0, 80, 120))
    e.add_field(name="!stolen_roles [@user]", value="Publicly view which sin roles Envy is currently wearing from a successful jealousy mark steal. Shows the original owner and time remaining.", inline=False)
    embeds.append(e)

    # ── 15. Myths ──
    e = discord.Embed(title="🌫️ Myth Abilities", color=discord.Color.from_rgb(70, 150, 175))
    e.add_field(name="!myths", value="List myths, lore, and abilities.", inline=False)
    e.add_field(name="!drown @user", value="La Llorona obtainment challenge: at exactly 12:00 AM midnight, drown two different online members in-game.", inline=False)
    e.add_field(name="!llorona_wail @user", value="La Llorona: lock a target's abilities and weaken their clash power. 1hr CD.", inline=False)
    e.add_field(name="!llorona_veil", value="La Llorona: nullify the next incoming attack for 30 minutes. 2hr CD.", inline=False)
    e.add_field(name="!llorona_lure @user", value="La Llorona: timeout a target for 1 minute, or apply a 5-minute ability lock if Discord refuses. 3hr CD.", inline=False)
    embeds.append(e)

    # ── 16. Admin ──
    e = discord.Embed(title="🔧 Admin Commands", description="Requires server administrator permission.", color=discord.Color.dark_red())
    e.add_field(name="!setup", value=(
        "Create all missing roles, channel categories, and channels.\n"
        "Also creates visual role separators: **╔══ SINNERS ══╗**, **╔══ VIRTUES ══╗**, "
        "**╔══ MYTHS ══╗**, **╔══ DESPAIR ══╗**, **╔══ HOPE ══╗**.\n"
        "**Run this first** before using any other admin commands."
    ), inline=False)
    e.add_field(name="!grant @user <sin>", value=(
        "Manually assign a sin final role. Example: `!grant @user lust`\n"
        "Valid sins: `lust` | `gluttony` | `greed` | `sloth` | `wrath` | `envy` | `pride`\n"
        "⚠️ Run `!setup` first — warns you if the Discord role is missing."
    ), inline=False)
    e.add_field(name="!grant_virtue @user <sin>", value=(
        "Manually grant a virtue role. Use the **sin name**, not the virtue name.\n"
        "Example: `!grant_virtue @user lust` → grants **The Chaste** (Chastity).\n"
        "⚠️ Run `!setup` first — warns you if the Discord role is missing."
    ), inline=False)
    e.add_field(name="!force_fall @user [reason]", value="Force a player to fall from grace (adds corruption, removes roles).", inline=False)
    e.add_field(name="!reset_user @user", value="Fully wipe a player's sin data and roles.", inline=False)
    e.add_field(name="!strip_all @user", value="Remove every manageable role from exactly one member. Keeps @everyone and skips roles above the bot.", inline=False)
    e.add_field(name="!grant_myth @user la_llorona", value="Assign the La Llorona myth role to one member. Run `!setup` first.", inline=False)
    e.add_field(name="!grant_special @user <role>", value="Admin override for standalone virtues: justice, prudence, fortitude, faith, hope, or liberality.", inline=False)
    e.add_field(name="!release_sin <sin>", value="Free up a sin so another player can claim it.", inline=False)
    e.add_field(name="!virtue_trial @user", value="Manually start a virtue trial for a player.", inline=False)
    e.add_field(name="!verdict @user <convict|acquit|reduce>", value="Force-close an open Justice trial with an admin verdict.", inline=False)
    embeds.append(e)

    for em in embeds:
        await ctx.author.send(embed=em)
        await asyncio.sleep(0.75)


@bot.command()
async def path_info(ctx):
    """Show every path and what each sin's ability does on it."""
    embeds = []

    # ── Support ──
    e = discord.Embed(title="🛡️ SUPPORT Path", description=PATH_DESCRIPTIONS["support"], color=discord.Color.from_rgb(80, 160, 80))
    e.add_field(name="Lust", value="**Devotion Shield** — Shield obsession target from 1 clash for 1 hr", inline=False)
    e.add_field(name="Gluttony", value="**Share the Feast** — Transfer 1 gorge coin bonus to an ally", inline=False)
    e.add_field(name="Greed", value="**Open Vault** — Return a stolen ability voluntarily, -1 Corruption", inline=False)
    e.add_field(name="Sloth", value="**Lullaby** — Reduce ally's laziness meter by 30%", inline=False)
    e.add_field(name="Wrath", value="**Contain** — Remove 1 clash penalty from an ally", inline=False)
    e.add_field(name="Envy", value="**Mirror of Worth** — Absorb 1 of ally's insecurity marks onto yourself", inline=False)
    e.add_field(name="Pride", value="**Sovereignty Grant** — Give ally +1 recognition toward Stop Time", inline=False)
    e.add_field(name="Command", value="`!support_ability` (or `!support_ability @ally` where needed)", inline=False)
    embeds.append(e)

    # ── Attack ──
    e = discord.Embed(title="⚔️ ATTACK Path", description=PATH_DESCRIPTIONS["attack"] + "\n\n+1 clash coin on all attack clashes.", color=discord.Color.red())
    e.add_field(name="Lust", value="**Consume** — Drain target, apply **-1 power** for 30 min", inline=False)
    e.add_field(name="Gluttony", value="**Devour All** — Hit target + 1 random bystander, both **-1 power** 15 min", inline=False)
    e.add_field(name="Greed", value="**Extort** — Steal target's bonus coin or apply **-1 power** penalty", inline=False)
    e.add_field(name="Sloth", value="**Paralyze** — Win = target cannot use ANY ability for **20 min**", inline=False)
    e.add_field(name="Wrath", value="**Rage Chain** — Strike + instant follow-up chain strike if hit", inline=False)
    e.add_field(name="Envy", value="**Mirror Strike** — Spend 1 insecurity mark → **-1 power** on target", inline=False)
    e.add_field(name="Pride", value="**Dominate** — Apply direct **-1 power** to target for 30 min", inline=False)
    e.add_field(name="Command", value="`!attack_ability @target`", inline=False)
    embeds.append(e)

    # ── Hybrid ──
    e = discord.Embed(title="⚡ HYBRID Path", description=PATH_DESCRIPTIONS["hybrid"], color=discord.Color.from_rgb(160, 80, 200))
    e.add_field(name="Lust", value="**Bind** — Shield ally + give enemy a possession mark (1 target ok)", inline=False)
    e.add_field(name="Gluttony", value="**Feast Together** — Buff ally +1 coin + feast-curse enemy (15 min)", inline=False)
    e.add_field(name="Greed", value="**Double Deal** — Gift ally +1 coin + penalize enemy -1 coin", inline=False)
    e.add_field(name="Sloth", value="**Drag Together** — Slowdown enemy + reduce own laziness -20% + ally +1 coin", inline=False)
    e.add_field(name="Wrath", value="**Sacrifice the Rage** — End your Bloodlust → ally gets +2 coins for 1 hr", inline=False)
    e.add_field(name="Envy", value="**Switch** — Swap your marks of insecurity with target's", inline=False)
    e.add_field(name="Pride", value="**Claim All** — Acknowledge one (+1 coin), penalize another (-1 coin)", inline=False)
    e.add_field(name="Command", value="`!hybrid_ability @ally` or `!hybrid_ability @ally @enemy`", inline=False)
    embeds.append(e)

    # ── TACHT ──
    e = discord.Embed(title="⚡ TACHT Path", description=PATH_DESCRIPTIONS["tacht"], color=discord.Color.yellow())
    e.add_field(name="Passive", value="All path ability CDs **25% shorter**. During Speed Burst: **+1 coin** on every clash.", inline=False)
    e.add_field(name="!tacht_strike @user", value="Preemptive speed strike — you **+1 coin**, they **-1 coin**. (1hr CD)", inline=False)
    e.add_field(name="!tacht_burst", value="Speed Burst 20 min — all current path CDs halved + **+1 coin** passive. (3hr CD)", inline=False)
    e.add_field(name="Note", value="Works for all sins and virtues equally.", inline=False)
    embeds.append(e)

    # ── Reverence ──
    e = discord.Embed(title="🌑 REVERENCE Path", description=PATH_DESCRIPTIONS["reverence"], color=discord.Color.from_rgb(60, 0, 80))
    e.add_field(name="Passive", value="Aura of Reverence reduces attacker's coins by 1 while active.", inline=False)
    e.add_field(name="!reverence_aura", value="30-min aura: anyone who uses an ability against you has **-1 coin**. (3hr CD)", inline=False)
    e.add_field(name="!demand_tribute @user", value="Target must react 🙏 within 20 min or take **-1 clash power for 1 hr**. (2hr CD)", inline=False)
    e.add_field(name="Note", value="Works for all sins and virtues equally.", inline=False)
    embeds.append(e)

    try: await ctx.message.delete()
    except Exception: pass
    for em in embeds:
        await ctx.author.send(embed=em)
        await asyncio.sleep(0.75)
    save_data(data)


@bot.command()
async def coin_power(ctx, target: discord.Member = None):
    """Show current effective clash coin power — yours or another player's."""
    data  = load_data()
    member = target or ctx.author
    user  = get_user(data, member.id)
    sin   = user.get("sin_role")
    virtue_list = user.get("completed_virtues", [])

    # Base power from sin role
    base = SINS.get(sin, {}).get("power", 0) if sin else 0
    virtue_base = max((VIRTUES.get(v, {}).get("power", 0) for v in virtue_list), default=0)
    effective_base = max(base, virtue_base)

    bonus         = user.get("clash_power_bonus", 0) or 0
    penalty_until = user.get("clash_penalty_until") or 0
    penalty       = user.get("clash_power_penalty", 0) if now_ts() < penalty_until else 0

    # Temporary modifiers
    mods = []

    # TACHT burst
    if user.get("path") == "tacht" and now_ts() < (user.get("tacht_burst_until") or 0):
        bonus += 1
        mods.append(f"⚡ TACHT Burst **+1** (expires {remaining_fmt(user['tacht_burst_until'])})")

    # Bloodlust (Wrath)
    if sin == "wrath" and user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0):
        bonus += 1
        mods.append(f"🩸 Bloodlust **+1** (expires {remaining_fmt(user['bloodlust_until'])})")

    # Sleepwalker (Sloth)
    if sin == "sloth" and now_ts() < (user.get("sleepwalker_active_until") or 0):
        bonus += 1
        mods.append(f"🌙 Sleepwalker **+1** (expires {remaining_fmt(user['sleepwalker_active_until'])})")

    # Gorge (Gluttony)
    if sin == "gluttony" and now_ts() < (user.get("gorge_active_until") or 0):
        gorge_bonus = user.get("clash_power_bonus", 0) or 0
        mods.append(f"🍽️ Gorge feeding **+{gorge_bonus}** (expires {remaining_fmt(user['gorge_active_until'])})")

    # Greed frenzy
    if sin == "greed" and user.get("frenzy_active"):
        bonus += 2
        mods.append("🔴 Frenzy Mode **+2**")

    # Weakness (envy weaken ability)
    weakened = data.get("weakened_sins", {}).get(sin)
    if weakened and now_ts() < (weakened.get("expires") or 0):
        w_pen = weakened.get("power_penalty", 0)
        penalty += w_pen
        mods.append(f"💀 Weakened by Envy **-{w_pen}** (expires {remaining_fmt(weakened['expires'])})")

    # General penalty
    if penalty > 0 and now_ts() < penalty_until:
        mods.append(f"⬇️ Active penalty **-{penalty}** (expires {remaining_fmt(penalty_until)})")

    # Stolen ability bonus (Greed carrying stolen powers)
    stolen = [s for s in data.get("stolen_abilities", []) if s["holder_id"] == str(member.id) and now_ts() < s["expires"]]

    total = max(1, effective_base + bonus - penalty)

    # Coin bar
    bar = "🪙" * min(total, 15) + (f" *(+{total - 15} more)*" if total > 15 else "")

    embed = discord.Embed(
        title=f"🪙 Clash Coin Power — {member.display_name}",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="📊 Breakdown",
        value=(
            f"Base (**{sin or 'no sin'}**): **{effective_base}** coins\n"
            f"Bonus: **+{bonus}**\n"
            f"Penalty: **-{penalty}**\n"
            f"──────────────\n"
            f"**Effective Total: {total} coins**"
        ),
        inline=False,
    )
    embed.add_field(name="Coins", value=bar, inline=False)

    if mods:
        embed.add_field(name="⚡ Active Modifiers", value="\n".join(mods), inline=False)

    if stolen:
        stolen_lines = [f"• **{s['ability_key'].replace('_',' ')}** — expires {remaining_fmt(s['expires'])}" for s in stolen]
        embed.add_field(name="💼 Stolen Abilities Held", value="\n".join(stolen_lines), inline=False)

    path = user.get("path")
    if path:
        embed.set_footer(text=f"Path: {path.upper()}")

    save_data(data)
    if target:
        await ctx.send(embed=embed)
    else:
        try: await ctx.message.delete()
        except Exception: pass
        await ctx.author.send(embed=embed)


# ── SUPPORT PATH ABILITIES ───────────────────────────────────────────

@bot.command()
async def support_ability(ctx, target: discord.Member = None):
    """(Support path) Sin-specific support ability. Shields, heals, or counters for an ally."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "support"):
        await ctx.send("You must choose the **Support** path first (`!choose_path support`).", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return

    sin = user.get("sin_role")
    err = _path_cd(user, "support_ability", PATH_ABILITY_CD)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    ch = await trial_channel(ctx.guild) or ctx.channel

    # ── Lust: Devotion — shield obsession target from 1 clash
    if sin == "lust":
        t_id = user.get("obsession_target")
        if not t_id:
            await ctx.send("Set an obsession target first (`!obsess @user`).", delete_after=8)
            save_data(data); return
        target_user = get_user(data, int(t_id))
        target_user["clash_shield_until"] = now_ts() + 3600
        save_data(data)
        m = ctx.guild.get_member(int(t_id))
        await ch.send(embed=discord.Embed(
            title="💜 Devotion Shield",
            description=f"{ctx.author.mention} wraps their obsession around {m.mention if m else t_id}.\n"
                        "Their next clash loss is **absorbed**. For **1 hour** their shield holds.",
            color=discord.Color.from_rgb(160, 0, 160),
        ))

    # ── Gluttony: Share the Feast — split gorge bonus with an ally
    elif sin == "gluttony":
        if not target:
            await ctx.send("Provide a target: `!support_ability @user`", delete_after=8)
            save_data(data); return
        bonus = user.get("clash_power_bonus", 0) or 0
        if bonus <= 0:
            await ctx.send("You have no clash bonus to share. Activate `!gorge` first.", delete_after=8)
            save_data(data); return
        target_user = get_user(data, target.id)
        target_user["clash_power_bonus"] = (target_user.get("clash_power_bonus") or 0) + 1
        user["clash_power_bonus"] = max(0, bonus - 1)
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🍽️ Share the Feast",
            description=f"{ctx.author.mention} passes a portion of their feast to {target.mention}.\n"
                        "**+1 clash coin** transferred. Their hunger, your strength.",
            color=discord.Color.from_rgb(180, 80, 0),
        ))

    # ── Greed: Open Vault — return own stolen ability, reduce corruption
    elif sin == "greed":
        if not target:
            await ctx.send("Provide a target: `!support_ability @user`", delete_after=8)
            save_data(data); return
        stolen = data.get("stolen_abilities", [])
        ours   = [s for s in stolen if s["holder_id"] == str(ctx.author.id) and s["original_holder_id"] == str(target.id) and now_ts() < s["expires"]]
        if not ours:
            await ctx.send(f"You don't hold any stolen abilities from {target.display_name}.", delete_after=8)
            save_data(data); return
        data["stolen_abilities"] = [s for s in stolen if not (s["holder_id"] == str(ctx.author.id) and s["original_holder_id"] == str(target.id))]
        old_corr = user.get("corruption", 0)
        user["corruption"] = max(0, old_corr - 1)
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🤲 Open Vault",
            description=f"{ctx.author.mention} willingly returns what was taken from {target.mention}.\n"
                        f"Stolen ability freed. Corruption: **{old_corr} → {max(0, old_corr-1)}**.",
            color=discord.Color.gold(),
        ))

    # ── Sloth: Lullaby — reduce ally's laziness meter by 30%
    elif sin == "sloth":
        if not target:
            await ctx.send("Provide a target: `!support_ability @user`", delete_after=8)
            save_data(data); return
        target_user = get_user(data, target.id)
        old_laz = target_user.get("laziness_meter", 0)
        target_user["laziness_meter"] = max(0, old_laz - 30)
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🎶 Lullaby of Rest",
            description=f"{ctx.author.mention} hums a restful lullaby to {target.mention}.\n"
                        f"Laziness meter: **{old_laz}% → {max(0, old_laz-30)}%**",
            color=discord.Color.from_rgb(80, 80, 120),
        ))

    # ── Wrath: Contain — remove a clash power penalty from an ally
    elif sin == "wrath":
        if not target:
            await ctx.send("Provide a target: `!support_ability @user`", delete_after=8)
            save_data(data); return
        target_user   = get_user(data, target.id)
        old_pen       = target_user.get("clash_power_penalty", 0)
        if old_pen <= 0:
            await ctx.send(f"{target.display_name} has no active penalty to remove.", delete_after=8)
            save_data(data); return
        target_user["clash_power_penalty"] = max(0, old_pen - 1)
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🔥 Contain the Rage",
            description=f"{ctx.author.mention} channels their wrath to shield {target.mention}.\n"
                        f"Clash penalty removed: **-{old_pen}** → **-{max(0, old_pen-1)}**.",
            color=discord.Color.red(),
        ))

    # ── Envy: Mirror of Worth — take an ally's mark of insecurity onto yourself
    elif sin == "envy":
        if not target:
            await ctx.send("Provide a target: `!support_ability @user`", delete_after=8)
            save_data(data); return
        target_user = get_user(data, target.id)
        t_marks     = target_user.get("marks_of_insecurity", 0)
        if t_marks <= 0:
            await ctx.send(f"{target.display_name} has no marks to absorb.", delete_after=8)
            save_data(data); return
        target_user["marks_of_insecurity"] = t_marks - 1
        user["marks_of_insecurity"] = user.get("marks_of_insecurity", 0) + 1
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🪞 Mirror of Worth",
            description=f"{ctx.author.mention} sees their own reflection and takes {target.mention}'s burden.\n"
                        f"Absorbed 1 mark of insecurity. *Their pain is yours now.*",
            color=discord.Color.from_rgb(20, 80, 20),
        ))

    # ── Pride: Sovereignty Grant — give an ally +1 recognition toward their unlock
    elif sin == "pride":
        if not target:
            await ctx.send("Provide a target: `!support_ability @user`", delete_after=8)
            save_data(data); return
        target_user = get_user(data, target.id)
        old_rec     = target_user.get("pride_recognition", 0)
        new_rec     = old_rec + 1
        target_user["pride_recognition"] = new_rec
        if new_rec >= PRIDE_RECOGNITION_THRESHOLD:
            target_user["stop_time_unlocked"] = True
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="👑 Sovereignty Grant",
            description=f"{ctx.author.mention} formally acknowledges {target.mention}.\n"
                        f"Recognition: **{old_rec} → {new_rec}**"
                        + (" ✅ **Stop Time unlocked!**" if new_rec >= PRIDE_RECOGNITION_THRESHOLD and old_rec < PRIDE_RECOGNITION_THRESHOLD else ""),
            color=discord.Color.from_rgb(80, 0, 160),
        ))
    else:
        await ctx.send("No support ability defined for your sin yet.", delete_after=6)
        save_data(data); return


# ── ATTACK PATH ABILITIES ────────────────────────────────────────────

@bot.command()
async def attack_ability(ctx, target: discord.Member):
    """(Attack path) Sin-specific attack ability. Strikes, debuffs, and overwhelms."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "attack"):
        await ctx.send("You must choose the **Attack** path first (`!choose_path attack`).", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot target yourself.", delete_after=5)
        save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    sin = user.get("sin_role")
    err = _path_cd(user, "attack_ability", PATH_ABILITY_CD)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")
    # Pride passive evasion check
    if target_sin == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        await ctx.send(f"⏸️ {target.mention} evaded the attack. Time slipped.", delete_after=8); return
    # Clash shield check
    if now_ts() < (target_user.get("clash_shield_until") or 0):
        target_user["clash_shield_until"] = None
        save_data(data)
        await ctx.send(f"🛡️ {target.mention}'s shield absorbed the attack.", delete_after=8); return

    # +1 coin bonus for Attack path
    my_coins     = _effective_coins(user) + 1
    target_coins = _effective_coins(target_user)
    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    ch = await trial_channel(ctx.guild) or ctx.channel

    flip_embed = discord.Embed(
        title=f"🗡️ Attack Ability — {sin.capitalize()}",
        description=(
            f"**{ctx.author.display_name}** rolled **{roll_a}** ({my_coins} coins +1 ATK)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coins)\n\n"
        ),
        color=discord.Color.red(),
    )

    if winner == "b":
        flip_embed.description += f"**Missed.** {target.display_name} weathered the strike."
        await ch.send(embed=flip_embed); save_data(data); return

    flip_embed.description += f"**Hit!**"
    await ch.send(embed=flip_embed)

    # ── Sin-specific on-hit effects ──
    if sin == "lust":
        # Consume — drain their obsession connection, apply -1 power
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 1800
        await ch.send(embed=discord.Embed(
            description=f"💜 **Consumed.** {target.mention} is drained — **-1 clash power** for 30 min.",
            color=discord.Color.from_rgb(160, 0, 160),
        ))

    elif sin == "gluttony":
        # Devour All — hit this target AND one random other member
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 900
        splash_candidates = [
            m for m in ctx.guild.members
            if m.id != ctx.author.id and m.id != target.id and not m.bot
        ]
        splash_msg = ""
        if splash_candidates:
            splash_m    = random.choice(splash_candidates)
            splash_user = get_user(data, splash_m.id)
            splash_user["clash_power_penalty"] = (splash_user.get("clash_power_penalty") or 0) + 1
            splash_user["clash_penalty_until"] = now_ts() + 900
            splash_msg  = f"\n💥 Splash hunger also hits {splash_m.mention} — **-1 power** for 15 min."
        await ch.send(embed=discord.Embed(
            description=f"🍽️ **Devour All.** {target.mention} — **-1 clash power** for 15 min.{splash_msg}",
            color=discord.Color.from_rgb(180, 80, 0),
        ))

    elif sin == "greed":
        # Extort — steal 1 clash coin bonus or apply penalty
        bonus = target_user.get("clash_power_bonus", 0) or 0
        if bonus > 0:
            target_user["clash_power_bonus"] = bonus - 1
            user["clash_power_bonus"] = (user.get("clash_power_bonus") or 0) + 1
            await ch.send(embed=discord.Embed(
                description=f"💰 **Extorted.** Seized 1 clash coin from {target.mention}.",
                color=discord.Color.gold(),
            ))
        else:
            target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
            target_user["clash_penalty_until"] = now_ts() + 1800
            await ch.send(embed=discord.Embed(
                description=f"💰 **Extorted.** {target.mention} has nothing — they take **-1 power** for 30 min.",
                color=discord.Color.gold(),
            ))

    elif sin == "sloth":
        # Paralyze — target cannot use ANY ability for 20 min
        target_user["ability_locked_until"] = now_ts() + 1200
        await ch.send(embed=discord.Embed(
            description=f"😴 **Paralyzed.** {target.mention} cannot use any ability for **20 minutes**.",
            color=discord.Color.from_rgb(80, 80, 120),
        ))

    elif sin == "wrath":
        # Rage Chain — apply normal penalty + a second reduced penalty
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 1800
        chain_coins  = max(1, my_coins - 1)
        w2, r2a, r2b = coin_flip(chain_coins, target_coins)
        await ch.send(embed=discord.Embed(
            description=(
                f"💢 **Rage Chain.** {target.mention} is staggered — **-1 power** for 30 min.\n\n"
                f"⛓️ *Chain strike:* **{r2a}** vs **{r2b}**"
            ) + (
                f"\n**Chain connects!** — additional **-1 power** for 15 min."
                if w2 == "a" else "\n*Chain misses.*"
            ),
            color=discord.Color.red(),
        ))
        if w2 == "a":
            target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
            target_user["clash_penalty_until"] = max(target_user.get("clash_penalty_until") or 0, now_ts() + 900)

    elif sin == "envy":
        # Mirror Strike — convert a mark of insecurity into a direct power hit
        marks = user.get("marks_of_insecurity", 0)
        if marks > 0:
            user["marks_of_insecurity"] = marks - 1
            target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
            target_user["clash_penalty_until"] = now_ts() + 1800
            await ch.send(embed=discord.Embed(
                description=f"👁️ **Mirror Strike.** Consumed 1 insecurity mark to deal **-1 power** to {target.mention} for 30 min.",
                color=discord.Color.from_rgb(20, 80, 20),
            ))
        else:
            target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
            target_user["clash_penalty_until"] = now_ts() + 900
            await ch.send(embed=discord.Embed(
                description=f"👁️ **Mirror Strike.** No marks to spend — still deals **-1 power** for 15 min.",
                color=discord.Color.from_rgb(20, 80, 20),
            ))

    elif sin == "pride":
        # Dominate — everyone in server who doesn't bow to next claim gets -1 power (set a flag)
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 1800
        await ch.send(embed=discord.Embed(
            description=f"👑 **Dominate.** {target.mention} bows or breaks — **-1 clash power** for 30 min.",
            color=discord.Color.from_rgb(80, 0, 160),
        ))
    save_data(data)


# ── HYBRID PATH ABILITIES ────────────────────────────────────────────

@bot.command()
async def hybrid_ability(ctx, buff_target: discord.Member, debuff_target: discord.Member = None):
    """(Hybrid path) Sin-specific hybrid ability. Buffs an ally and debuffs an enemy simultaneously."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "hybrid"):
        await ctx.send("You must choose the **Hybrid** path first (`!choose_path hybrid`).", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return

    sin = user.get("sin_role")
    err = _path_cd(user, "hybrid_ability", int(PATH_ABILITY_CD * 1.5))
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    ch = await trial_channel(ctx.guild) or ctx.channel
    buff_user    = get_user(data, buff_target.id)

    # ── Lust: Bind — shield obsession target AND curse the debuff_target
    if sin == "lust":
        buff_user["clash_shield_until"] = now_ts() + 1800
        desc = f"💜 **Bind.** {buff_target.mention} is shielded (30 min)."
        if debuff_target and debuff_target.id != ctx.author.id:
            debuff_user = get_user(data, debuff_target.id)
            debuff_user["possession_marks"] = debuff_user.get("possession_marks", {})
            user.setdefault("possession_marks", {})[str(debuff_target.id)] = user["possession_marks"].get(str(debuff_target.id), 0) + 1
            desc += f" {debuff_target.mention} receives a **possession mark**."
        save_data(data)
        await ch.send(embed=discord.Embed(title="💜 Bind", description=desc, color=discord.Color.from_rgb(160,0,160)))

    # ── Gluttony: Feast Together — buff ally AND curse enemy with hunger
    elif sin == "gluttony":
        if not debuff_target:
            await ctx.send("Provide both targets: `!hybrid_ability @ally @enemy`", delete_after=8)
            save_data(data); return
        buff_user["clash_power_bonus"] = (buff_user.get("clash_power_bonus") or 0) + 1
        debuff_user = get_user(data, debuff_target.id)
        data.setdefault("feast_cursed", {})[str(debuff_target.id)] = {
            "expires": now_ts() + 900, "marks": 0, "by_id": str(ctx.author.id),
        }
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🍽️ Feast Together",
            description=f"{buff_target.mention} gets **+1 clash coin** (30 min) — {debuff_target.mention} is **hunger-cursed** (15 min).",
            color=discord.Color.from_rgb(180,80,0),
        ))

    # ── Greed: Double Deal — steal from one AND gift power to another
    elif sin == "greed":
        if not debuff_target:
            await ctx.send("Provide both targets: `!hybrid_ability @ally @enemy`", delete_after=8)
            save_data(data); return
        buff_user["clash_power_bonus"] = (buff_user.get("clash_power_bonus") or 0) + 1
        debuff_user = get_user(data, debuff_target.id)
        debuff_user["clash_power_penalty"] = (debuff_user.get("clash_power_penalty") or 0) + 1
        debuff_user["clash_penalty_until"] = now_ts() + 1800
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="💰 Double Deal",
            description=f"Gifted **+1 coin** to {buff_target.mention} — seized **-1 coin** from {debuff_target.mention} for 30 min.",
            color=discord.Color.gold(),
        ))

    # ── Sloth: Drag Together — slowdown enemy, reduce own laziness
    elif sin == "sloth":
        if not debuff_target:
            await ctx.send("Provide both targets: `!hybrid_ability @ally @enemy`", delete_after=8)
            save_data(data); return
        data.setdefault("slowdown_targets", {})[str(debuff_target.id)] = {
            "expires": now_ts() + 1200, "last_msg_ts": 0, "by_id": str(ctx.author.id),
        }
        old_laz = user.get("laziness_meter", 0)
        user["laziness_meter"] = max(0, old_laz - 20)
        buff_user["clash_power_bonus"] = (buff_user.get("clash_power_bonus") or 0) + 1
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="😴 Drag Together",
            description=f"{debuff_target.mention} is **slowed** (20 min). Own laziness **-20%**. {buff_target.mention} gains **+1 coin**.",
            color=discord.Color.from_rgb(80,80,120),
        ))

    # ── Wrath: Sacrifice the Rage — end bloodlust to grant ally +2 coins
    elif sin == "wrath":
        if not (user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0)):
            await ctx.send("You must have active **Bloodlust** to sacrifice it.", delete_after=8)
            save_data(data); return
        user["bloodlust_active"] = False
        user["bloodlust_until"]  = None
        buff_user["clash_power_bonus"] = (buff_user.get("clash_power_bonus") or 0) + 2
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🩸 Sacrifice the Rage",
            description=f"{ctx.author.mention} sacrifices their Bloodlust. {buff_target.mention} gains **+2 clash coins** for 1 hour.",
            color=discord.Color.red(),
        ))

    # ── Envy: Switch — swap marks of insecurity with target
    elif sin == "envy":
        target_user = get_user(data, buff_target.id)
        my_marks    = user.get("marks_of_insecurity", 0)
        their_marks = target_user.get("marks_of_insecurity", 0)
        user["marks_of_insecurity"]          = their_marks
        target_user["marks_of_insecurity"]   = my_marks
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="🪞 Switch",
            description=f"Marks of insecurity **swapped** with {buff_target.mention}.\nYou: **{their_marks}** | Them: **{my_marks}**",
            color=discord.Color.from_rgb(20,80,20),
        ))

    # ── Pride: Claim All — extend a claim to a second person simultaneously
    elif sin == "pride":
        if not debuff_target:
            await ctx.send("Provide both targets: `!hybrid_ability @person1 @person2`", delete_after=8)
            save_data(data); return
        debuff_user = get_user(data, debuff_target.id)
        buff_user["clash_power_bonus"] = (buff_user.get("clash_power_bonus") or 0) + 1
        debuff_user["clash_power_penalty"] = (debuff_user.get("clash_power_penalty") or 0) + 1
        debuff_user["clash_penalty_until"] = now_ts() + 1800
        save_data(data)
        await ch.send(embed=discord.Embed(
            title="👑 Claim All",
            description=f"Pride extends its reach. {buff_target.mention} **+1 coin** (acknowledged). {debuff_target.mention} **-1 coin** for 30 min (unclaimed).",
            color=discord.Color.from_rgb(80,0,160),
        ))
    else:
        await ctx.send("No hybrid ability defined for your sin yet.", delete_after=6)
        save_data(data); return


# ── TACHT PATH ABILITIES (universal) ────────────────────────────────

@bot.command()
async def tacht_strike(ctx, target: discord.Member):
    """(TACHT path) Preemptive speed strike — opponent has -1 coin, you have +1."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "tacht"):
        await ctx.send("You must choose the **TACHT** path first (`!choose_path tacht`).", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot strike yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen.", delete_after=10); save_data(data); return

    err = _path_cd(user, "tacht_strike", TACHT_STRIKE_CD)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    target_user  = get_user(data, target.id)
    if target_user.get("sin_role") == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        await ctx.send(f"⏸️ {target.mention} evaded the strike.", delete_after=8); return
    if now_ts() < (target_user.get("clash_shield_until") or 0):
        target_user["clash_shield_until"] = None
        save_data(data)
        await ctx.send(f"🛡️ {target.mention}'s shield absorbed the strike.", delete_after=8); return

    my_coins     = _effective_coins(user) + 1      # TACHT speed bonus
    target_coins = max(1, _effective_coins(target_user) - 1)  # target loses 1 from being caught off-guard

    winner, roll_a, roll_b = coin_flip(my_coins, target_coins)
    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="⚡ TACHT Strike",
        description=(
            f"**{ctx.author.display_name}** *(speed)* rolled **{roll_a}** ({my_coins} coins)\n"
            f"**{target.display_name}** *(caught off-guard)* rolled **{roll_b}** ({target_coins} coins)\n\n"
        ) + (
            f"**Hit!** {target.mention} is **-1 clash power** for 20 min." if winner == "a"
            else f"**Missed.** {target.display_name} reacted in time."
        ),
        color=discord.Color.yellow(),
    ))
    if winner == "a":
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 1
        target_user["clash_penalty_until"] = now_ts() + 1200
    save_data(data)

@bot.command()
async def tacht_burst(ctx):
    """(TACHT path) Activate Speed Burst — all your path cooldowns halved for 20 min, +1 coin."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "tacht"):
        await ctx.send("You must choose the **TACHT** path first.", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return

    err = _path_cd(user, "tacht_burst", TACHT_BURST_CD)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    until = now_ts() + TACHT_BURST_DURATION
    user["tacht_burst_until"] = until
    # Halve all current active path cooldowns
    cds = user.setdefault("path_ability_cds", {})
    for k in list(cds.keys()):
        if k != "tacht_burst" and now_ts() < cds[k]:
            remaining = cds[k] - now_ts()
            cds[k] = now_ts() + int(remaining * 0.5)
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="⚡ TACHT — Speed Burst",
        description=(
            f"{ctx.author.mention} accelerates beyond human limits.\n\n"
            "For **20 minutes**:\n"
            "• All path ability cooldowns are **halved**\n"
            "• **+1 clash coin** on every clash (passive via `_effective_coins`)\n"
            "• TACHT Strike costs 75% normal cooldown\n\n"
            "*Speed is its own kind of strength.*"
        ),
        color=discord.Color.yellow(),
    ))

# ── REVERENCE PATH ABILITIES (universal) ────────────────────────────

@bot.command()
async def reverence_aura(ctx):
    """(Reverence path) Project your presence — anyone who clashes you in the next 30 min loses 1 coin."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "reverence"):
        await ctx.send("You must choose the **Reverence** path first (`!choose_path reverence`).", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return

    err = _path_cd(user, "reverence_aura", REVERENCE_AURA_CD)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    until = now_ts() + REVERENCE_AURA_DURATION
    user["reverence_aura_until"] = until
    save_data(data)

    ch = await trial_channel(ctx.guild) or ctx.channel
    await ch.send(embed=discord.Embed(
        title="🌑 Aura of Reverence",
        description=(
            f"{ctx.author.mention} radiates **undeniable presence**.\n\n"
            "For the next **30 minutes**, anyone who uses an ability **against them** "
            "will do so at **-1 clash coin** — they are made to feel the weight of who they face.\n\n"
            "*Some power doesn't need to move to be felt.*"
        ),
        color=discord.Color.from_rgb(60, 0, 80),
    ))

@bot.command()
async def demand_tribute(ctx, target: discord.Member):
    """(Reverence path) Demand a target shows reverence — they must react 🙏 within 20 min or lose clash power."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _needs_path(user, "reverence"):
        await ctx.send("You must choose the **Reverence** path first.", delete_after=8)
        save_data(data); return
    if not _has_role(user):
        await ctx.send("You must hold a sin role to use this.", delete_after=6)
        save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot demand tribute from yourself.", delete_after=5)
        save_data(data); return

    err = _path_cd(user, "demand_tribute", TRIBUTE_CD)
    if err: await ctx.send(err, delete_after=8); save_data(data); return

    expires = now_ts() + TRIBUTE_DURATION
    ch      = await trial_channel(ctx.guild) or ctx.channel

    msg = await ch.send(embed=discord.Embed(
        title="🙏 Tribute Demanded",
        description=(
            f"{ctx.author.mention} demands reverence from {target.mention}.\n\n"
            f"**{target.mention}** — react with 🙏 to this message within **20 minutes** "
            "or suffer **-1 clash power for 1 hour**.\n\n"
            "*The powerful do not ask. They wait.*"
        ),
        color=discord.Color.from_rgb(60, 0, 80),
    ))
    await msg.add_reaction("🙏")

    target_user = get_user(data, target.id)
    target_user["tribute_owed"] = {
        "from_id": str(ctx.author.id),
        "expires": expires,
        "msg_id":  str(msg.id),
    }
    save_data(data)

# ── WRATH: SUMMON METEOR ─────────────────────────────────────────────

@bot.command()
async def summon_meteor(ctx, target: discord.Member):
    """(Wrath only) Call down a meteor. Massive coin flip — win = devastating blow, lose = -1 corruption."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("sin_role") != "wrath":
        await ctx.send("Only Crimson Heir can call down a meteor.", delete_after=6)
        save_data(data); return
    if user.get("fallen"):
        await ctx.send("You have fallen from grace.", delete_after=5); save_data(data); return
    if target.id == ctx.author.id:
        await ctx.send("You cannot target yourself.", delete_after=5); save_data(data); return
    if data.get("stop_time_active") and now_ts() < data.get("stop_time_until", 0):
        await ctx.send("⏸️ Time is frozen. Even meteors stop.", delete_after=10); save_data(data); return

    cd = (user.get("wrath_ability_cds") or {}).get("summon_meteor", 0) or 0
    if now_ts() < cd:
        await ctx.send(f"☄️ Meteor on cooldown: {remaining_fmt(cd)}.", delete_after=8)
        save_data(data); return

    target_user  = get_user(data, target.id)
    target_sin   = target_user.get("sin_role")

    # Pride passive evasion
    if target_sin == "pride" and target_user.get("stop_time_passive"):
        target_user["stop_time_passive"] = False
        save_data(data)
        await ctx.send(f"⏸️ {target.mention} **slipped through time**. The meteor found nothing.", delete_after=10)
        return

    # Reverence aura reduces meteor coins
    aura_penalty = 1 if now_ts() < (target_user.get("reverence_aura_until") or 0) else 0

    bl_bonus      = 1 if (user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0)) else 0
    wrath_coins   = METEOR_COINS + bl_bonus
    target_coins  = max(1, _effective_coins(target_user) - aura_penalty)

    winner, roll_a, roll_b = coin_flip(wrath_coins, target_coins)
    user.setdefault("wrath_ability_cds", {})["summon_meteor"] = now_ts() + METEOR_CD

    ch = await trial_channel(ctx.guild) or ctx.channel

    # Pre-announcement
    await ch.send(embed=discord.Embed(
        title="☄️ METEOR INCOMING",
        description=f"{ctx.author.mention} raises their fist to the sky. A **meteor** descends on {target.mention}.",
        color=discord.Color.from_rgb(200, 50, 0),
    ))

    await asyncio.sleep(2)

    flip_embed = discord.Embed(
        title="🎲 Meteor Clash",
        description=(
            f"**Wrath** rolled **{roll_a}** ({wrath_coins} coins — meteor power)\n"
            f"**{target.display_name}** rolled **{roll_b}** ({target_coins} coins)\n\n"
        ),
        color=discord.Color.from_rgb(200, 50, 0),
    )

    if winner == "a":
        target_user["clash_power_penalty"] = (target_user.get("clash_power_penalty") or 0) + 2
        target_user["clash_penalty_until"] = now_ts() + 3600
        target_user["ability_locked_until"] = now_ts() + 600
        save_data(data)
        flip_embed.description += (
            f"☄️ **DIRECT HIT.**\n\n"
            f"{target.mention} is **obliterated**:\n"
            "• **-2 clash power** for **1 hour**\n"
            "• **Ability locked** for **10 minutes**\n"
            "• +1 Corruption applied"
        )
        target_user["corruption"] = target_user.get("corruption", 0) + 1
        save_data(data)
        await ch.send(embed=flip_embed)
        try:
            await target.send(
                "☄️ A **METEOR** struck you directly. "
                "-2 clash power for 1 hour, abilities locked for 10 min, +1 Corruption."
            )
        except Exception:
            pass
    else:
        flip_embed.description += f"**{target.display_name} EVADED.** The meteor grazes past."
        save_data(data)
        await ch.send(embed=flip_embed)
        # Wrath loses a clash — bloodlust check
        if user.get("bloodlust_active") and now_ts() < (user.get("bloodlust_until") or 0):
            user["bloodlust_active"] = False
            user["corruption"] = user.get("corruption", 0) + 1
            save_data(data)
            await ch.send(embed=discord.Embed(
                description=f"🩸 The missed meteor broke {ctx.author.mention}'s **Bloodlust** — **+1 Corruption**.",
                color=discord.Color.dark_red(),
            ))

# ───────────────────────────────────────────────────────────────────
# EVENT: on_message — Monitor wrath / sloth / gluttony / virtues
# ───────────────────────────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    data = load_data()
    user = get_user(data, message.author.id)
    save_needed = False

    content = message.content.strip()
    is_cmd  = content.startswith("!")

    # ── WRATH TRIAL: every non-command message must contain a curse word ──
    if user.get("trial_sin") == "wrath" and not is_cmd:
        if now_ts() <= user.get("trial_end", 0):
            evolved = is_evolved(user)
            passes  = (count_distinct_curses(content) >= 2) if evolved else has_curse(content)
            if not passes:
                save_data(data)
                await fall_from_grace(
                    message.author,
                    f"Sent a message without {'two distinct curse words' if evolved else 'a curse word'} during the Trial of Wrath.",
                    data,
                )
                try:
                    await message.delete()
                except Exception:
                    pass
                await bot.process_commands(message)
                return
            user["wrath_fail"] = False
            save_needed = True

    # ── SLOTH TRIAL: every non-command message must be abbreviated ──
    if user.get("trial_sin") == "sloth" and not is_cmd:
        if now_ts() <= user.get("trial_end", 0):
            evolved = is_evolved(user)
            if not check_sloth(content, evolved):
                save_data(data)
                await fall_from_grace(
                    message.author,
                    "Sent a normally-spelled word during the Trial of Sloth.",
                    data,
                )
                try:
                    await message.delete()
                except Exception:
                    pass
                await bot.process_commands(message)
                return
            save_needed = True

    # ── GLUTTONY TRIAL: track new messages in the gluttony channel ──
    if user.get("trial_sin") == "gluttony" and now_ts() <= user.get("trial_end", 0):
        gl_ch = await gluttony_channel(message.guild)
        if gl_ch and message.channel.id == gl_ch.id and message.author.id != int(str(message.author.id)):
            # This message was sent by someone else — track it for the gluttony trialist
            evolved  = is_evolved(user)
            window   = 120 if evolved else 300   # seconds to react
            deadline = now_ts() + window
            user.setdefault("gluttony_pending", {})[str(message.id)] = deadline
            save_needed = True

    # For every gluttony trialist, track messages in their feast channel
    for uid, u in data["users"].items():
        if u.get("trial_sin") == "gluttony" and now_ts() <= u.get("trial_end", 0):
            gl_ch = None
            for g in bot.guilds:
                gl_ch = await gluttony_channel(g)
                break
            if gl_ch and message.channel.id == gl_ch.id and str(message.author.id) != uid:
                evolved  = is_evolved(u)
                window   = 120 if evolved else 300
                deadline = now_ts() + window
                u.setdefault("gluttony_pending", {})[str(message.id)] = deadline
                save_needed = True

    # ── VIRTUE: Patience (wrath) — no curse words ──
    if user.get("virtue_trial_sin") == "wrath" and not is_cmd:
        if now_ts() <= user.get("virtue_trial_end", 0):
            if has_curse(content):
                user["virtue_progress"]["patience_fail"] = True
                save_data(data)
                await fall_from_grace(message.author, "Used a curse word during the Virtue Trial of Patience.", data)
                await bot.process_commands(message)
                return

    # ── VIRTUE: Diligence (sloth) — send 20+ word messages, 1 per hour ──
    if user.get("virtue_trial_sin") == "sloth" and not is_cmd:
        if now_ts() <= user.get("virtue_trial_end", 0):
            if len(content.split()) >= 20:
                current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
                hours_tracked = user["virtue_progress"].get("hours_tracked", [])
                if current_hour not in hours_tracked:
                    hours_tracked.append(current_hour)
                    user["virtue_progress"]["hours_tracked"] = hours_tracked
                    save_needed = True
                    if len(hours_tracked) >= 24:
                        save_data(data)
                        await complete_virtue_trial(message.author, "sloth", data)
                        await bot.process_commands(message)
                        return

    # ── PRIDE SPEAKING RESTRICTION (after stop_time use) ──
    speak_ban = user.get("speaking_restricted_until") or 0
    if now_ts() < speak_ban and not is_cmd:
        try:
            await message.delete()
        except Exception:
            pass
        try:
            await message.author.send(
                f"🔇 You invoked Stop Time — you may not speak for another {remaining_fmt(speak_ban)}."
            )
        except Exception:
            pass
        return  # don't process anything else

    # ── FEAST CURSE CHECK (must include food emoji) ──
    uid_str     = str(message.author.id)
    feast_entry = data.get("feast_cursed", {}).get(uid_str)
    if feast_entry and now_ts() < feast_entry.get("expires", 0) and not is_cmd:
        has_food = any(em in content for em in FOOD_EMOJIS)
        if not has_food:
            feast_entry["marks"] = feast_entry.get("marks", 0) + 1
            marks = feast_entry["marks"]
            save_needed = True
            try:
                await message.delete()
            except Exception:
                pass
            if marks >= FEAST_MARKS_FOR_PENALTY:
                user["clash_power_penalty"] = max(user.get("clash_power_penalty", 0), 1)
                user["clash_penalty_until"] = now_ts() + 3600
                del data["feast_cursed"][uid_str]
                save_data(data)
                ch = await trial_channel(message.guild)
                if ch:
                    await ch.send(embed=discord.Embed(
                        description=(
                            f"🍴 {message.author.mention} ignored the hunger one too many times. "
                            "**Clash power -1 for 1 hour.**"
                        ),
                        color=discord.Color.dark_orange(),
                    ))
            else:
                try:
                    await message.author.send(
                        f"🍴 You forgot a food emoji! Starvation mark **{marks}/{FEAST_MARKS_FOR_PENALTY}**."
                    )
                except Exception:
                    pass

    # ── FORCE LAZY CHECK (target must abbreviate) ──
    lazy_entry = data.get("force_lazy_targets", {}).get(uid_str)
    if lazy_entry and now_ts() < lazy_entry.get("expires", 0) and not is_cmd:
        if not check_sloth(content, evolved=False):
            save_needed = True
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    "😴 You're under a **Laziness Curse** — every word must be abbreviated (max 4 chars)."
                )
            except Exception:
                pass

    # ── SLOWDOWN CHECK (must wait 45s between messages) ──
    slow_entry = data.get("slowdown_targets", {}).get(uid_str)
    if slow_entry and now_ts() < slow_entry.get("expires", 0) and not is_cmd:
        last_ts = slow_entry.get("last_msg_ts", 0) or 0
        if now_ts() - last_ts < SLOW_TYPE_INTERVAL:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    f"⏱️ You must wait **{SLOW_TYPE_INTERVAL} seconds** between messages. "
                    f"Wait {remaining_fmt(last_ts + SLOW_TYPE_INTERVAL)}."
                )
            except Exception:
                pass
        else:
            slow_entry["last_msg_ts"] = now_ts()
            save_needed = True

    # ── SLOTH SELF SLOW-TYPE CHECK (after waking from deep sleep) ──
    slow_until = user.get("slow_type_until") or 0
    if now_ts() < slow_until and not is_cmd and user.get("sin_role") == "sloth":
        # Sleepwalker immunity
        if not ((user.get("sleepwalker_active_until") or 0) > now_ts()):
            last_ts = user.get("slow_type_last_msg_ts", 0) or 0
            if now_ts() - last_ts < SLOW_TYPE_INTERVAL:
                # Penalty: -1 clash power for 10 min
                user["clash_power_penalty"] = max(user.get("clash_power_penalty", 0), 1)
                user["clash_penalty_until"] = now_ts() + 600
                save_needed = True
                try:
                    await message.author.send(
                        "⏱️ You're typing too fast after your deep sleep. "
                        "**Clash power -1 for 10 minutes.**"
                    )
                except Exception:
                    pass
            else:
                user["slow_type_last_msg_ts"] = now_ts()
                save_needed = True

    # ── DEVOURED CHECK — Gluttony's devour blocks all messages/commands ──
    devoured_until = user.get("devoured_until") or 0
    if now_ts() < devoured_until:
        try:
            await message.delete()
        except Exception:
            pass
        try:
            await message.author.send(
                f"🌑 You have been **devoured**. You cannot send anything for {remaining_fmt(devoured_until)}."
            )
        except Exception:
            pass
        if save_needed:
            save_data(data)
        return   # block commands too

    # ── SCALE OF WRONGDOING — trial response detection ──
    pending_trials = data.get("pending_trials") or {}
    scale_key = str(message.author.id) + "_scale"
    scale_trial = pending_trials.get(scale_key)
    if scale_trial and not scale_trial.get("resolved") and now_ts() <= scale_trial.get("expires", 0):
        content_low = message.content.lower().strip().rstrip("?!.")
        response_type = None
        for phrase in _TRIAL_DENY_PHRASES:
            if phrase in content_low:
                response_type = "deny"
                break
        if not response_type:
            for phrase in _TRIAL_DUMB_PHRASES:
                if phrase in content_low:
                    response_type = "dumb"
                    break
        if not response_type:
            for phrase in _TRIAL_GUILTY_PHRASES:
                if phrase in content_low:
                    response_type = "guilty"
                    break

        if response_type:
            scale_trial["resolved"] = True
            scale_trial["response"] = response_type
            accuser_id = scale_trial.get("accuser_id")
            accuser    = message.guild.get_member(int(accuser_id)) if accuser_id and message.guild else None
            if response_type == "guilty":
                # Reduced penalty: 30-min ability lock only
                t_user = get_user(data, message.author.id)
                current_lock = t_user.get("ability_locked_until") or 0
                t_user["ability_locked_until"] = max(current_lock, now_ts() + 30 * 60)
                save_data(data)
                try:
                    await message.channel.send(embed=discord.Embed(
                        title="⚖️ Guilty Plea Accepted",
                        color=discord.Color.from_rgb(140, 100, 0),
                        description=(
                            f"{message.author.mention} pleads guilty before the court.\n\n"
                            "Penalty reduced: **30-minute ability lock** accepted.\n"
                            "*Honesty earns leniency.*"
                        ),
                    ))
                except Exception:
                    pass
            else:
                # Denial or playing dumb — opens clash window
                save_data(data)
                phrase_type = "denies the charges" if response_type == "deny" else "plays dumb"
                try:
                    await message.channel.send(embed=discord.Embed(
                        title="⚖️ Defense Raised — Clash Window Open",
                        color=discord.Color.from_rgb(80, 120, 200),
                        description=(
                            f"{message.author.mention} **{phrase_type}**.\n\n"
                            f"The court is now contested.\n"
                            f"{'`!clash @' + accuser.display_name + '`' if accuser else 'Use `!clash`'} "
                            "within the next **30 seconds** to fight the conviction.\n\n"
                            f"*If no clash is made, the conviction still stands — silence is admission.*"
                        ),
                    ))
                except Exception:
                    pass
        save_needed = True

    # ── JACOBS LADDER — counter-clash window ──
    jacobs_key = str(message.author.id) + "_jacobs"
    jacobs_trial = pending_trials.get(jacobs_key)
    if (jacobs_trial and not jacobs_trial.get("resolved")
            and now_ts() <= jacobs_trial.get("expires", 0)
            and message.content.lower().startswith("!clash")):
        jacobs_trial["resolved"] = True
        accuser_id = jacobs_trial.get("accuser_id")
        accuser    = message.guild.get_member(int(accuser_id)) if accuser_id and message.guild else None
        # Coin flip — winner of the clash
        outcome = random.randint(0, 1)
        if outcome:
            result_line = (
                f"⚡ {message.author.mention} **deflects** the ladder! Jacob's Ladder is broken.\n"
                f"Justice must recharge before striking again."
            )
        else:
            # Jacob's Ladder still lands despite the clash attempt
            t_user = get_user(data, message.author.id)
            current_lock = t_user.get("ability_locked_until") or 0
            t_user["ability_locked_until"] = max(current_lock, now_ts() + 5 * 60)
            t_user["clash_power_penalty"]  = max(t_user.get("clash_power_penalty", 0), 1)
            t_user["clash_penalty_until"]  = now_ts() + 30 * 60
            result_line = (
                f"⚡ {message.author.mention}'s counter **fails**. The ladder lands regardless.\n"
                "• ⛔ Ability lock 5 min · ⬇️ -1 clash power 30 min"
            )
        save_data(data)
        try:
            await message.channel.send(embed=discord.Embed(
                title="⚡ Jacob's Ladder — Contested",
                color=discord.Color.from_rgb(255, 245, 140),
                description=result_line,
            ))
        except Exception:
            pass
        save_needed = True

    # ── GOONER TRIAL — track image submissions in #gooner-trial ──
    if user.get("trial_sin") == "gooner" and now_ts() <= user.get("trial_end", 0):
        if message.channel.name == "gooner-trial" and message.attachments:
            evolved = is_evolved(user)
            goal    = 200 if evolved else 100
            img_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".bmp", ".avif"}
            images  = [a for a in message.attachments
                       if any(a.filename.lower().endswith(ext) for ext in img_exts)]
            if images:
                count  = user.get("gooner_images_submitted", 0) + len(images)
                user["gooner_images_submitted"] = count
                save_needed = True
                if count >= goal:
                    save_data(data)
                    await complete_trial(message.author, "gooner", data)
                    await bot.process_commands(message)
                    return

    # ── GORGE — track server message count for Gluttony bonus ──
    for uid, u in data["users"].items():
        gorge_until = u.get("gorge_active_until") or 0
        if now_ts() < gorge_until and u.get("sin_role") == "gluttony":
            # Every 10 messages in gorge window grants +1 coin (up to +3)
            u["clash_power_bonus"] = min(3, (u.get("clash_power_bonus") or 0) + 0.1)
            save_needed = True

    # ── LUST OBSESSION PHRASES (fill red heart meter) ──
    lust_phrase_handled = False
    if user.get("sin_role") == "lust" and not user.get("fallen") and is_cmd:
        raw        = content[1:].strip().lower()
        phrase_key = _detect_lust_phrase(raw)
        if phrase_key and user.get("obsession_target"):
            phrase_cds = user.setdefault("obsession_phrase_cds", {})
            cd         = phrase_cds.get(phrase_key, 0) or 0
            if now_ts() >= cd:
                meter_add                  = OBSESSION_PHRASES[phrase_key][0]
                old_meter                  = user.get("obsession_meter", 0)
                new_meter                  = min(100, old_meter + meter_add)
                user["obsession_meter"]    = new_meter
                phrase_cds[phrase_key]     = now_ts() + OBSESSION_PHRASE_CD
                save_needed               = True
                lust_phrase_handled        = True

                try:
                    await message.delete()
                except Exception:
                    pass

                ch = await trial_channel(message.guild)
                if ch:
                    flavor = random.choice(OBSESSION_FLAVORS.get(phrase_key, ["..."]))
                    await ch.send(embed=discord.Embed(
                        description=f"*{flavor}*",
                        color=discord.Color.from_rgb(160, 0, 50),
                    ))

                if old_meter < 100 <= new_meter:
                    try:
                        await message.author.send(
                            "❤️ **The meter is full.** Your obsession has reached its peak.\n"
                            "Use `!obsession_clash` to strike."
                        )
                    except Exception:
                        pass

    # Hope/Despair passives (Izuru's "How boring...", the Tragic Event choice)
    await _dr_message_passives(message, data, is_cmd)
    save_needed = True

    if save_needed:
        save_data(data)

    if not lust_phrase_handled:
        await bot.process_commands(message)

# ───────────────────────────────────────────────────────────────────
# EVENT: on_reaction_add
# ───────────────────────────────────────────────────────────────────

@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if user.bot:
        return

    data   = load_data()
    guild  = reaction.message.guild
    msg_id = str(reaction.message.id)
    emoji  = str(reaction.emoji)

    # ── EXPOSE VOTES (🔍 on greed/envy announcements) ──
    if msg_id in data.get("expose_votes", {}):
        vote = data["expose_votes"][msg_id]
        if vote.get("active") and emoji == "🔍":
            voters = vote.get("votes", [])
            if str(user.id) not in voters:
                voters.append(str(user.id))
                vote["votes"] = voters
                save_data(data)

            # Figure out if the actor has an active pact (raises threshold)
            action_id = vote["action_id"]
            atype     = vote["type"]
            action    = data["greed_actions"].get(action_id) if atype == "greed" else data["envy_actions"].get(action_id)
            actor_id  = (action or {}).get("killer_id") or (action or {}).get("striker_id")

            in_pact = False
            if actor_id:
                pact_entry = data.get("pacts", {}).get(actor_id)
                in_pact    = pact_entry and pact_entry.get("status") == "active"

            effective_threshold = EXPOSE_THRESHOLD + (PACT_EXPOSE_BONUS if in_pact else 0)

            # Alert the pact partner when heat starts building (at PACT_ALERT_AT reacts)
            if in_pact and len(voters) == PACT_ALERT_AT and actor_id:
                pact_entry  = data.get("pacts", {}).get(actor_id, {})
                partner_id  = pact_entry.get("partner_id")
                if partner_id:
                    partner_m = guild.get_member(int(partner_id))
                    actor_m   = guild.get_member(int(actor_id))
                    if partner_m:
                        try:
                            await partner_m.send(
                                f"⚠️ **Pact Alert** — Your partner "
                                f"**{actor_m.display_name if actor_m else 'Unknown'}** "
                                f"is being investigated. "
                                f"**{len(voters)}/{effective_threshold}** 🔍 reactions so far. "
                                "If they are exposed, **you fall too.**"
                            )
                        except Exception:
                            pass

            if len(voters) >= effective_threshold and vote.get("active"):
                vote["active"] = False
                save_data(data)

                ch = reaction.message.channel
                if not action or action.get("exposed"):
                    return

                pact_warning = (
                    "\n\n⚠️ **This actor is in a pact.** If exposed, their partner falls too."
                    if in_pact else ""
                )
                vote_embed = discord.Embed(
                    title="🔍 Expose Vote — Active",
                    description=(
                        f"The community suspects someone. Vote to expose the **{atype}** actor.\n\n"
                        f"✅ Yes — reveal them  |  ❌ No — let them hide\n\n"
                        f"**{EXPOSE_VOTE_THRESHOLD} yes votes** in {EXPOSE_VOTE_DURATION}s expose them."
                        f"{pact_warning}"
                    ),
                    color=discord.Color.orange(),
                )
                vote_msg = await ch.send(embed=vote_embed)
                await vote_msg.add_reaction("✅")
                await vote_msg.add_reaction("❌")

                await asyncio.sleep(EXPOSE_VOTE_DURATION)

                fresh = await ch.fetch_message(vote_msg.id)
                yes_count = sum(
                    (r.count - 1) for r in fresh.reactions if str(r.emoji) == "✅"
                )

                if yes_count >= EXPOSE_VOTE_THRESHOLD:
                    if actor_id:
                        action["exposed"] = True
                        save_data(data)
                        actor = guild.get_member(int(actor_id))
                        await ch.send(embed=discord.Embed(
                            title="🚨 The Truth Is Revealed",
                            description=(
                                f"The community has spoken. **{actor.mention if actor else 'Unknown'}** "
                                f"acted in shadow.\n\n**They fall from grace.**"
                            ),
                            color=discord.Color.red(),
                        ))
                        if actor:
                            data = load_data()
                            await fall_from_grace(actor, f"Exposed during the Trial of {atype.capitalize()}.", data)
                            save_data(data)
                else:
                    await ch.send(embed=discord.Embed(
                        title="🌑 The Shadow Stays Hidden",
                        description="The community could not agree. The actor remains concealed.",
                        color=discord.Color.dark_gray(),
                    ))
        return

    data = load_data()

    # ── PRIDE CLAIM — bow reactions + recognition tracking ──
    active_claims = data.get("active_claims", {})
    if msg_id in active_claims:
        claim_info = active_claims[msg_id]
        uid_str    = str(user.id)
        if emoji == "🙇" and uid_str in claim_info.get("subjects", {}):
            subject = claim_info["subjects"][uid_str]
            if not subject.get("bowed") and now_ts() <= subject.get("deadline", 0):
                subject["bowed"] = True
                # Grant recognition to the Pride claimer
                claimer_id   = claim_info.get("claimer_id")
                if claimer_id:
                    claimer_user = get_user(data, int(claimer_id))
                    old_rec      = claimer_user.get("pride_recognition", 0)
                    new_rec      = old_rec + 1
                    claimer_user["pride_recognition"] = new_rec
                    if old_rec < PRIDE_RECOGNITION_THRESHOLD <= new_rec:
                        claimer_user["stop_time_unlocked"] = True
                        claimer = guild.get_member(int(claimer_id))
                        ch_rec  = await trial_channel(guild)
                        if ch_rec and claimer:
                            await ch_rec.send(embed=discord.Embed(
                                title="⏸️ Stop Time Unlocked",
                                description=(
                                    f"{claimer.mention} has earned **{new_rec} recognition** from submission.\n\n"
                                    "The power to **Stop Time** has awakened. "
                                    "Use `!stop_time freeze` or `!stop_time passive`."
                                ),
                                color=discord.Color.from_rgb(80, 0, 160),
                            ))
                save_data(data)
        return

    # ── PRIDE TRIAL — bows and defiance ──
    for uid, u in data["users"].items():
        if u.get("trial_sin") == "pride" and u.get("pride_msg_id") == msg_id:
            if str(user.id) == uid:
                continue
            member  = guild.get_member(int(uid))
            if not member:
                continue
            evolved      = is_evolved(u)
            needed_pct   = 0.75 if evolved else 0.60
            max_refusals = 10 if evolved else 20
            online       = [m for m in guild.members if m.status != discord.Status.offline and not m.bot]
            needed_bows  = max(1, int(len(online) * needed_pct))

            if emoji == "🙇":
                u["pride_bows"] = u.get("pride_bows", 0) + 1
                if u["pride_bows"] >= needed_bows:
                    save_data(data)
                    await complete_trial(member, "pride", data)
                    save_data(data)
                    return
            elif emoji == "❌":
                u["pride_refusals"] = u.get("pride_refusals", 0) + 1
                if u["pride_refusals"] >= max_refusals:
                    save_data(data)
                    await fall_from_grace(member, "Too many members defied you. The weight of pride crushed you.", data)
                    save_data(data)
                    return

    # ── LUST TRIAL — ❤️ reactions on trialist's messages ──
    for uid, u in data["users"].items():
        if u.get("trial_sin") == "lust" and now_ts() <= u.get("trial_end", 0):
            if str(reaction.message.author.id) == uid and emoji == "❤️" and str(user.id) != uid:
                hearts = u.get("lust_hearts", [])
                if str(user.id) not in hearts:
                    hearts.append(str(user.id))
                    u["lust_hearts"] = hearts
                    evolved = is_evolved(u)
                    needed  = 10 if evolved else 5
                    if len(hearts) >= needed:
                        member = guild.get_member(int(uid))
                        save_data(data)
                        if member:
                            await complete_trial(member, "lust", data)
                            save_data(data)
                        return

    # ── GLUTTONY TRIAL — mark a message as reacted ──
    for uid, u in data["users"].items():
        if u.get("trial_sin") == "gluttony" and str(user.id) == uid:
            pending = u.get("gluttony_pending", {})
            if msg_id in pending:
                deadline = pending[msg_id]
                if now_ts() <= deadline:
                    del pending[msg_id]
                    u["gluttony_pending"] = pending
                else:
                    # Reacted too late
                    member = guild.get_member(int(uid))
                    save_data(data)
                    if member:
                        await fall_from_grace(member, "Reacted to a Gluttony message after the deadline.", data)
                        save_data(data)
                    return

    # ── VIRTUE: Temperance (lust) — any ❤️ reaction fails ──
    for uid, u in data["users"].items():
        if u.get("virtue_trial_sin") == "lust" and str(user.id) == uid and emoji == "❤️":
            member = guild.get_member(int(uid))
            u["virtue_progress"]["temptation_fail"] = True
            save_data(data)
            if member:
                await fall_from_grace(member, "Added a ❤️ reaction during the Virtue Trial of Temperance.", data)
                save_data(data)
            return

    # ── VIRTUE: Abstinence (gluttony) — any reaction fails ──
    for uid, u in data["users"].items():
        if u.get("virtue_trial_sin") == "gluttony" and str(user.id) == uid:
            member = guild.get_member(int(uid))
            u["virtue_progress"]["abstinence_fail"] = True
            save_data(data)
            if member:
                await fall_from_grace(member, "Added a reaction during the Virtue Trial of Abstinence.", data)
                save_data(data)
            return

    # ── VIRTUE: Humility (pride) — 🙏 bows on bow_down message ──
    for uid, u in data["users"].items():
        if u.get("virtue_trial_sin") == "pride":
            vp = u.get("virtue_progress", {})
            if vp.get("bow_msg_id") == msg_id and emoji == "🙏" and str(user.id) != uid:
                vp["bows"] = vp.get("bows", 0) + 1
                if vp["bows"] >= 10:
                    member = guild.get_member(int(uid))
                    save_data(data)
                    if member:
                        await complete_virtue_trial(member, "pride", data)
                        save_data(data)
                    return

    # ── LUST OBSESSION — Colored Heart Reactions ──────────────────────────
    # Only fires for the Lust role holder reacting on someone else's message
    lust_hearts = {"🧡", "💛", "💚", "💙", "💜"}
    if emoji in lust_hearts and str(reaction.message.author.id) != str(user.id):
        luster_user = get_user(data, user.id)
        if luster_user.get("sin_role") == "lust" and not luster_user.get("fallen"):
            target_author   = reaction.message.author
            target_uid_str  = str(target_author.id)
            heart_cds       = luster_user.setdefault("heart_react_cds", {})
            cd_key          = f"{emoji}:{target_uid_str}"  # per-emoji per-target for some
            cd_key_global   = emoji                        # per-emoji global for others
            now             = now_ts()
            ch = await trial_channel(guild) or reaction.message.channel

            if emoji == "🧡":
                # Warmth — anonymous announcement. 30min global cooldown.
                cd = heart_cds.get(cd_key_global, 0) or 0
                if now >= cd:
                    heart_cds[cd_key_global] = now + 30 * 60
                    save_data(data)
                    await ch.send(embed=discord.Embed(
                        title="🧡 A Warmth Passes Through",
                        description=(
                            f"Someone's warmth reached **{target_author.display_name}**.\n"
                            "They may not know it yet — but someone sees them.\n\n"
                            "*Who sent it? Only they know.*"
                        ),
                        color=discord.Color.from_rgb(255, 140, 0),
                    ))

            elif emoji == "💛":
                # Adoration — quotes the message in trial channel. 1hr global cooldown.
                cd = heart_cds.get(cd_key_global, 0) or 0
                if now >= cd:
                    heart_cds[cd_key_global] = now + 3600
                    save_data(data)
                    quote = reaction.message.content[:300] if reaction.message.content else "*(an image or embed)*"
                    await ch.send(embed=discord.Embed(
                        title="💛 A Perfect Moment, Preserved",
                        description=(
                            f"Someone treasured this. They had to share it.\n\n"
                            f"> {quote}\n\n"
                            f"— **{target_author.display_name}**, held in someone's memory forever."
                        ),
                        color=discord.Color.from_rgb(255, 215, 0),
                    ))

            elif emoji == "💚":
                # Possession — adds a possession mark. 2hr per-target cooldown. At 3 marks → announce.
                cd = heart_cds.get(cd_key, 0) or 0
                if now >= cd:
                    heart_cds[cd_key] = now + 7200
                    pmarks = luster_user.setdefault("possession_marks", {})
                    pmarks[target_uid_str] = pmarks.get(target_uid_str, 0) + 1
                    save_data(data)
                    count = pmarks[target_uid_str]
                    if count >= 3:
                        await ch.send(embed=discord.Embed(
                            title="💚 Claimed",
                            description=(
                                f"**{target_author.display_name}** has been marked three times.\n"
                                "Someone considers them theirs. This is no longer subtle.\n\n"
                                "*What does it mean to belong to someone who won't reveal themselves?*"
                            ),
                            color=discord.Color.from_rgb(0, 180, 80),
                        ))
                    else:
                        await ch.send(embed=discord.Embed(
                            description=(
                                f"*A possessive thought. Silent. Growing. "
                                f"{target_author.display_name} feels nothing yet.*"
                            ),
                            color=discord.Color.from_rgb(0, 140, 60),
                        ))

            elif emoji == "💙":
                # Longing — anonymous DM to the message author. 1hr per-target cooldown.
                cd = heart_cds.get(cd_key, 0) or 0
                if now >= cd:
                    heart_cds[cd_key] = now + 3600
                    save_data(data)
                    target_member = guild.get_member(target_author.id)
                    longing_lines = [
                        "Someone thinks about you when you go quiet.",
                        "You crossed someone's mind again. You always do.",
                        "They wonder if you notice them. You probably don't.",
                        "Someone misses you — and you don't even know they're watching.",
                        "Absence makes the heart heavier. Yours has become someone's whole weight.",
                    ]
                    if target_member:
                        try:
                            await target_member.send(
                                f"💙 *{random.choice(longing_lines)}*\n\n"
                                "— *Anonymous*"
                            )
                        except Exception:
                            pass
                    await ch.send(embed=discord.Embed(
                        description="*Someone reached out in the dark. A message sent to an unsuspecting soul.*",
                        color=discord.Color.from_rgb(30, 100, 200),
                    ))

            elif emoji == "💜":
                # Desire — if this is the obsession target, add 10% meter; otherwise 5% and note the pull.
                # 45min per-target cooldown.
                cd = heart_cds.get(cd_key, 0) or 0
                if now >= cd:
                    heart_cds[cd_key] = now + 45 * 60
                    is_target = luster_user.get("obsession_target") == target_uid_str
                    add       = 10 if is_target else 5
                    old_meter = luster_user.get("obsession_meter", 0)
                    new_meter = min(100, old_meter + add)
                    luster_user["obsession_meter"] = new_meter
                    save_data(data)
                    if is_target:
                        try:
                            await user.send(
                                f"💜 Your desire burned. Meter: {_meter_bar(new_meter)}"
                                + ("\n\n❤️ **Full.** Use `!obsession_clash` to strike." if new_meter >= 100 else "")
                            )
                        except Exception:
                            pass
                        await ch.send(embed=discord.Embed(
                            description=(
                                f"*A deep want. Directed. Focused. "
                                f"Someone's hunger for **{target_author.display_name}** grows darker.*"
                            ),
                            color=discord.Color.from_rgb(120, 0, 180),
                        ))
                    else:
                        await ch.send(embed=discord.Embed(
                            description=(
                                "*Desire doesn't always know where it belongs. "
                                "Someone felt a pull — and it surprised them.*"
                            ),
                            color=discord.Color.from_rgb(80, 0, 120),
                        ))

    save_data(data)

# ───────────────────────────────────────────────────────────────────
# BOT READY
# ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    for _loop in (trial_expiry_check, despair_timer_check, disaster_resolution_check, dr_effect_tick):
        if not _loop.is_running():
            _loop.start()
    print(f"\n{'═'*55}")
    print(f"  Seven Sins Trial System — Online as {bot.user}")
    print(f"{'═'*55}")
    print("\nRequired Discord Roles (create these manually):")
    for sd in SINS.values():
        print(f"  • {sd['role']} (trial placeholder)")
        print(f"  • {sd['final_role']}")
        if sd["evolved_role"] != sd["final_role"]:
            print(f"  • {sd['evolved_role']}")
    for v in VIRTUES.values():
        print(f"  • {v['role']}")
    print(f"  • {FALLEN_ROLE}")
    print(f"  • {DESPAIR_ROLE}")
    print(f"  • {REMNANT_OF_DESPAIR_ROLE}")
    print(f"  • {RESERVE_COURSE_ROLE}")
    print(f"  • {DESPAIR_SISTER_ROLE}")
    print(f"  • {HOPE_ROLE}")
    print("\nRequired Channels:")
    print(f"  • #{TRIAL_CHANNEL_NAME}")
    print(f"  • #{GLUTTONY_CHANNEL_NAME}")
    print("\nInvite URL:")
    print(f"  https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions={PERMISSIONS_INT}&scope=bot")
    print(f"\n{'═'*55}\n")

def main():
    """Run the bot when this file is executed as the production entry point."""
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN must be set to run the Discord bot.")
    bot.run(token)


if __name__ == "__main__":
    main()
