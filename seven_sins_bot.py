#!/usr/bin/env python3
"""
Zetsubo 2.0 — Seven Deadly Sins Role System
============================================

A deliberately stripped-down rewrite of the original bot.

WHAT IS GONE (on purpose):
  • Trials, trial windows, trial failure/corruption, fall-from-grace
  • HP, damage, !attack, !heal, combat stats, disasters, bounties, pacts
  • Second forms / evolved modes / extra unlock gates
  • Separate combat "paths" as a parallel system

WHAT IS KEPT:
  • Every role, its abilities, and its effects
  • One holder per role, enforced globally
  • Path abilities folded directly into each role's base moveset
  • Old trial-style obtainment kept, but strictly OPTIONAL

DESIGN RULES:
  1. No ability deals damage. Every offensive ability applies a STATUS EFFECT.
  2. Every effect is written to exactly one user id — never a role, never a
     list, never "everyone with X". This is what fixes the stray-mute bug.
   3. Nothing is gated behind a form or an unlock state. If you hold the
     role, you can use the whole kit, right now.

Entry point:  python3 seven_sins_bot.py
Env var:      DISCORD_TOKEN
Data file:    sins2_data.json
"""

import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

# Railway volumes expose their mount path through this variable.
# Locally, and on Railway without a volume, data stays beside this script.
DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ".")
DATA_FILE = os.getenv("DATA_FILE", os.path.join(DATA_DIR, "sins2_data.json"))
PREFIX = "!"
AUDIT_LOG_CHANNEL_NAME = "zetsubo-audit-log"
AUDIT_EVENT_LIMIT = 500

# Roles at or above this power need community approval to claim.
APPROVAL_POWER_THRESHOLD = 5
# How many approvals are needed, by power tier.
APPROVALS_REQUIRED = {5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5}
# How long a pending request stays open before expiring.
REQUEST_TTL = 48 * 3600

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def now_ts() -> int:
    return int(time.time())


def remaining_fmt(ts: int) -> str:
    secs = max(0, int(ts) - now_ts())
    if secs >= 3600:
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    if secs >= 60:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs}s"


# ═══════════════════════════════════════════════════════════════════
# STATUS EFFECTS
# ═══════════════════════════════════════════════════════════════════
# These replace every former damage/HP mechanic. Each one degrades how a
# person can act, rather than draining a number.

# Abilities whose behaviour is too specific for the generic spec tuple.
# ability_key -> async handler(ctx, data, user, spec, target). Populated at the
# bottom of this file; declared here so run_ability can see it at call time.
CUSTOM_ABILITIES: dict = {}

# Roles hidden from !roles until their holder asks. Secret roles still work
# normally in every other respect.
SECRET_ROLES: set = set()

EFFECTS = {
    "ability_lock": {
        "name": "Ability Lock",
        "icon": "🔒",
        "desc": "Cannot use any role ability.",
    },
    "cooldown_tax": {
        "name": "Cooldown Tax",
        "icon": "⏳",
        "desc": "All of your ability cooldowns are doubled.",
    },
    "misfire": {
        "name": "Misfire",
        "icon": "🎲",
        "desc": "Each ability you use has a chance to fizzle and still go on cooldown.",
    },
    "speech_lag": {
        "name": "Speech Lag",
        "icon": "🐌",
        "desc": "After each message you send, you must wait before sending another.",
    },
    "mute": {
        "name": "Silenced",
        "icon": "🤐",
        "desc": "Your messages are removed by the bot.",
    },
    "timeout": {
        "name": "Timeout",
        "icon": "⛔",
        "desc": "A real Discord timeout.",
    },
    "channel_exile": {
        "name": "Channel Exile",
        "icon": "🚪",
        "desc": "Removed from one channel temporarily.",
    },
}


def _empty_data() -> dict:
    return {
        "users": {},
        "role_holders": {},   # role_key -> user_id (str). One holder, always.
        "requests": {},       # role_key -> {requester_id, approvals[], opened_at}
        "config": {},         # guild_id -> {"owner_grant_only": bool}
        "mandates": {},       # guild_id -> recipient_id -> mandate record
        "audit_events": {},   # guild_id -> append-only safety log
    }


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return _empty_data()
    try:
        with open(DATA_FILE, "r") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_data()
    for k, v in _empty_data().items():
        d.setdefault(k, v)
    return d


def save_data(data: dict):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


def guild_config(data: dict, guild: discord.Guild) -> dict:
    """Return the per-server config without changing the old data format."""
    return data.setdefault("config", {}).setdefault(str(guild.id), {})


def mandate_records(data: dict, guild: discord.Guild) -> dict:
    """Mandates are scoped per guild; old global records are never reused."""
    return data.setdefault("mandates", {}).setdefault(str(guild.id), {})


def active_mandate(data: dict, guild: discord.Guild, member: discord.Member) -> Optional[dict]:
    record = mandate_records(data, guild).get(str(member.id))
    if not record or now_ts() >= int(record.get("expires", 0)):
        return None
    return record


def protected_member(member: discord.Member) -> bool:
    """Owner/admin members are never touched by mandate cleanup."""
    return member.id == member.guild.owner_id or member.guild_permissions.administrator


async def write_server_log(
    guild: discord.Guild,
    event: str,
    actor_id: Optional[int],
    details: str,
    mandate_id: Optional[str] = None,
):
    """Persist an audit event and mirror it to the configured server channel."""
    data = load_data()
    events = data.setdefault("audit_events", {}).setdefault(str(guild.id), [])
    events.append({
        "at": now_ts(),
        "event": event,
        "actor_id": str(actor_id) if actor_id is not None else None,
        "mandate_id": mandate_id,
        "details": details[:1500],
    })
    del events[:-AUDIT_EVENT_LIMIT]
    channel_id = guild_config(data, guild).get("audit_channel_id")
    save_data(data)

    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if channel is None or not hasattr(channel, "send"):
        return
    actor = f"<@{actor_id}>" if actor_id else "system"
    try:
        await channel.send(
            f"`{datetime.now(timezone.utc).isoformat(timespec='seconds')}` "
            f"**{event}** · {actor}\n{details[:1500]}"
        )
    except (discord.Forbidden, discord.HTTPException):
        pass


async def ensure_audit_channel(guild: discord.Guild) -> tuple[Optional[discord.TextChannel], Optional[str]]:
    """Create one private-to-regular-members server log channel."""
    data = load_data()
    channel_id = guild_config(data, guild).get("audit_channel_id")
    existing = guild.get_channel(int(channel_id)) if channel_id else None
    if isinstance(existing, discord.TextChannel):
        return existing, None

    existing = discord.utils.get(guild.text_channels, name=AUDIT_LOG_CHANNEL_NAME)
    if existing:
        guild_config(data, guild)["audit_channel_id"] = str(existing.id)
        save_data(data)
        return existing, None

    me = guild.me
    if me is None:
        return None, "I can't read my own member record."
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }
    try:
        channel = await guild.create_text_channel(
            AUDIT_LOG_CHANNEL_NAME,
            overwrites=overwrites,
            reason="Zetsubo server audit log",
        )
    except discord.Forbidden:
        return None, "I need **Manage Channels** to create the server audit channel."
    except discord.HTTPException as e:
        return None, f"Discord rejected the audit channel: `{e.status}`."
    guild_config(data, guild)["audit_channel_id"] = str(channel.id)
    save_data(data)
    return channel, None


def get_user(data: dict, user_id) -> dict:
    uid = str(user_id)
    u = data["users"].setdefault(uid, {})
    u.setdefault("role_key", None)       # the ONE role they hold
    u.setdefault("cooldowns", {})        # ability_key -> expiry ts
    u.setdefault("effects", {})          # effect_key -> {"expires": ts, "source": uid}
    u.setdefault("last_message_ts", 0)   # for speech_lag
    u.setdefault("optional_progress", {})  # legacy trial-style obtainment, opt-in
    return u


# ═══════════════════════════════════════════════════════════════════
# EFFECT ENGINE
# ═══════════════════════════════════════════════════════════════════

def has_effect(user: dict, key: str) -> bool:
    """True only if THIS user's own effect entry is live."""
    entry = user.get("effects", {}).get(key)
    if not entry:
        return False
    if now_ts() >= entry.get("expires", 0):
        return False
    return True


def clear_expired_effects(user: dict):
    live = {}
    for k, v in user.get("effects", {}).items():
        if now_ts() < v.get("expires", 0):
            live[k] = v
    user["effects"] = live


def apply_effect(data: dict, target_id: int, effect_key: str,
                 duration: int, source_id: int) -> dict:
    """
    Write an effect to EXACTLY ONE user record.

    This function is the only place effects are created. It takes a concrete
    target_id, never a role, a list, or a channel. That containment is what
    stops an ability from leaking onto bystanders — the old bug came from
    effects being applied by role lookup, which swept up anyone who happened
    to share the role at that moment.
    """
    if effect_key not in EFFECTS:
        raise ValueError(f"unknown effect {effect_key}")
    target = get_user(data, target_id)
    clear_expired_effects(target)
    existing = target["effects"].get(effect_key)
    expires = now_ts() + duration
    # Refresh rather than stack, so repeat casts can't spiral.
    if existing and existing.get("expires", 0) > expires:
        expires = existing["expires"]
    target["effects"][effect_key] = {
        "expires": expires,
        "source": str(source_id),
    }
    return target["effects"][effect_key]


def effect_summary(user: dict) -> str:
    clear_expired_effects(user)
    if not user.get("effects"):
        return "*(none)*"
    lines = []
    for k, v in user["effects"].items():
        meta = EFFECTS.get(k, {"icon": "•", "name": k})
        lines.append(f"{meta['icon']} **{meta['name']}** — {remaining_fmt(v['expires'])}")
    return "\n".join(lines)


async def apply_timeout(member: discord.Member, seconds: int, reason: str) -> bool:
    """Real Discord timeout, scoped to one member. Returns success."""
    try:
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def exile_from_channel(member: discord.Member, channel: discord.TextChannel,
                             seconds: int, reason: str) -> bool:
    """
    Temporarily deny one member access to one channel, then restore.

    Uses a per-member channel overwrite, which touches only this member. It
    never edits the role's permissions, so nobody else in the channel is
    affected.
    """
    try:
        await channel.set_permissions(member, view_channel=False,
                                      send_messages=False, reason=reason)
    except (discord.Forbidden, discord.HTTPException):
        return False

    async def _restore():
        await asyncio.sleep(seconds)
        try:
            await channel.set_permissions(member, overwrite=None,
                                          reason="Channel exile expired")
        except Exception:
            pass

    asyncio.create_task(_restore())
    return True


# ═══════════════════════════════════════════════════════════════════
# ROLE REGISTRY
# ═══════════════════════════════════════════════════════════════════
# One flat registry. Sin roles, virtue roles, standalone virtues, and myths
# all live here on equal footing. Each role's `abilities` list is its COMPLETE
# base moveset — former second-form abilities and former path abilities have
# been folded in. Nothing here is gated behind a form or an unlock state.
#
# ability tuple: (key, display, category, cooldown_secs, effect, duration, needs_target)

ROLES: dict[str, dict] = {

    # ── SINS ────────────────────────────────────────────────────────
    "lust": {
        "name": "Desire Bound Lust",
        "kind": "sin",
        "power": 1,
        "color": (200, 60, 120),
        "blurb": "Charm that binds attention and refuses to let it go.",
        "abilities": [
            ("obsess", "Obsess", "control", 900, "misfire", 600, True),
            ("allure", "Allure", "control", 1200, "speech_lag", 480, True),
            ("devotion", "Devotion", "support", 1800, None, 0, False),
            ("bind", "Bind", "disrupt", 2700, "ability_lock", 420, True),
        ],
    },
    "gluttony": {
        "name": "The Devoured",
        "kind": "sin",
        "power": 2,
        "color": (160, 50, 0),
        "blurb": "An appetite that consumes speech itself.",
        "abilities": [
            ("gorge", "Gorge", "support", 900, None, 0, False),
            ("feast", "Feast", "disrupt", 1200, "speech_lag", 600, True),
            ("devour", "Devour", "silence", 3600, "mute", 420, True),
            ("purge_bite", "Purge Bite", "utility", 1200, None, 0, True),
            ("expel", "Expel", "exile", 5400, "channel_exile", 480, True),
        ],
    },
    "greed": {
        "name": "The False King",
        "kind": "sin",
        "power": 3,
        "color": (220, 180, 40),
        "blurb": "Takes what others rely on, and makes them wait to get it back.",
        "abilities": [
            ("seize", "Seize", "disrupt", 1800, "ability_lock", 480, True),
            ("tax", "Tax", "disrupt", 1500, "cooldown_tax", 900, True),
            ("redistribution", "Redistribution", "disrupt", 10800, "cooldown_tax", 1200, True),
            ("break_chains", "Break Chains", "disrupt", 10800, "cooldown_tax", 3600, True),
            ("hoard", "Hoard", "support", 2400, None, 0, False),
            ("extort", "Extort", "control", 2700, "misfire", 720, True),
        ],
    },
    "sloth": {
        "name": "The Vessel of Sloth",
        "kind": "sin",
        "power": 4,
        "color": (110, 110, 140),
        "blurb": "Slows everything it touches until acting stops being worth it.",
        "abilities": [
            ("slowdown", "Slowdown", "disrupt", 900, "speech_lag", 900, True),
            ("force_lazy", "Force Lazy", "disrupt", 1500, "cooldown_tax", 1200, True),
            ("deep_sleep", "Deep Sleep", "disrupt", 3600, "ability_lock", 900, True),
            ("force_sleep", "Force Sleep", "disrupt", 5400, "ability_lock", 900, True),
            ("drowse", "Drowse", "control", 2100, "misfire", 900, True),
            ("sleepwalk", "Sleepwalk", "support", 1800, None, 0, False),
        ],
    },
    "wrath": {
        "name": "Crimson Heir",
        "kind": "sin",
        "power": 5,
        "color": (200, 40, 30),
        "blurb": "Overwhelming force, expressed as sanction rather than damage.",
        "abilities": [
            ("rage_strike", "Rage Strike", "disrupt", 1200, "cooldown_tax", 900, True),
            ("bloodlust", "Bloodlust", "support", 2400, None, 0, False),
            ("meteor", "Meteor", "aoe", 7200, "ability_lock", 600, True),
            ("smite", "Smite", "silence", 3600, "mute", 300, True),
            ("shatter", "Shatter", "disrupt", 2700, "misfire", 900, True),
        ],
    },
    "envy": {
        "name": "The Pale Mirror",
        "kind": "sin",
        "power": 6,
        "color": (0, 180, 216),
        "blurb": "Copies, distorts, and unsettles. Never clashes — it simply lands.",
        "abilities": [
            ("jealousy_mark", "Jealousy Mark", "control", 1200, "misfire", 900, True),
            ("envy_strike", "Envy Strike", "disrupt", 2700, "misfire", 600, True),
            ("schizo", "Schizo", "control", 900, "speech_lag", 600, True),
            ("mirror", "Mirror", "support", 1800, None, 0, False),
            ("covet", "Covet", "disrupt", 2700, "ability_lock", 600, True),
            ("unmake", "Unmake", "disrupt", 3600, "cooldown_tax", 1200, True),
        ],
    },
    "pride": {
        "name": "The Bearer of Pride",
        "kind": "sin",
        "power": 7,
        "color": (230, 200, 90),
        "blurb": "Commands deference. The strongest sanctions in the kit.",
        "abilities": [
            ("claim", "Claim", "control", 1800, "speech_lag", 900, True),
            ("weaken", "Weaken", "disrupt", 2100, "cooldown_tax", 1200, True),
            ("stop_time", "Stop Time", "silence", 5400, "mute", 480, True),
            ("decree", "Decree", "exile", 7200, "channel_exile", 600, True),
            ("sovereign", "Sovereign", "support", 3600, None, 0, False),
        ],
    },

    # ── VIRTUES ─────────────────────────────────────────────────────
    "chastity": {
        "name": "The Chaste",
        "kind": "virtue",
        "power": 8,
        "color": (240, 240, 255),
        "blurb": "Clears what binds, and refuses what would bind.",
        "abilities": [
            ("abstain", "Abstain", "cleanse", 1200, None, 0, False),
            ("purify", "Purify", "cleanse", 1800, None, 0, True),
            ("ward", "Ward", "support", 2400, None, 0, False),
        ],
    },
    "temperance": {
        "name": "The Fasting King",
        "kind": "virtue",
        "power": 9,
        "color": (200, 220, 180),
        "blurb": "Moderates excess — shortens what others inflict.",
        "abilities": [
            ("fast", "Fast", "cleanse", 1200, None, 0, False),
            ("moderate", "Moderate", "cleanse", 1500, None, 0, True),
            ("restraint", "Restraint", "support", 2400, None, 0, False),
        ],
    },
    "charity": {
        "name": "The Open Hand",
        "kind": "virtue",
        "power": 10,
        "color": (255, 210, 120),
        "blurb": "Gives away relief, including its own.",
        "abilities": [
            ("gift_relief", "Gift Relief", "cleanse", 1500, None, 0, True),
            ("share_load", "Share Load", "support", 2100, None, 0, True),
            ("open_hand", "Open Hand", "cleanse", 3000, None, 0, False),
        ],
    },
    "diligence": {
        "name": "The Waking",
        "kind": "virtue",
        "power": 11,
        "color": (180, 230, 180),
        "blurb": "Refuses to slow down, and wakes others who have.",
        "abilities": [
            ("rouse", "Rouse", "cleanse", 1200, None, 0, True),
            ("inspire", "Inspire", "support", 1800, None, 0, True),
            ("persist", "Persist", "support", 2400, None, 0, False),
        ],
    },
    "patience": {
        "name": "The Still Flame",
        "kind": "virtue",
        "power": 12,
        "color": (255, 180, 120),
        "blurb": "Absorbs what is thrown, and calms what is burning.",
        "abilities": [
            ("absorb", "Absorb", "support", 1800, None, 0, False),
            ("de_escalate", "De-escalate", "cleanse", 1500, None, 0, True),
            ("endure", "Endure", "support", 2700, None, 0, False),
        ],
    },
    "kindness": {
        "name": "The Mirror's Grace",
        "kind": "virtue",
        "power": 13,
        "color": (220, 200, 255),
        "blurb": "Undoes cruelty directly.",
        "abilities": [
            ("bless", "Bless", "cleanse", 1500, None, 0, True),
            ("forgive", "Forgive", "cleanse", 2400, None, 0, True),
            ("grace", "Grace", "support", 3000, None, 0, False),
        ],
    },
    "humility": {
        "name": "The Humble Sovereign",
        "kind": "virtue",
        "power": 14,
        "color": (200, 200, 220),
        "blurb": "The strongest cleanse in the game, and it never targets itself.",
        "abilities": [
            ("submit", "Submit", "cleanse", 1800, None, 0, True),
            ("lift_up", "Lift Up", "cleanse", 2400, None, 0, True),
            ("humble", "Humble", "disrupt", 3600, "cooldown_tax", 900, True),
        ],
    },

    # ── STANDALONE VIRTUES ──────────────────────────────────────────
    "justice": {
        "name": "The Scales of Justice",
        "kind": "standalone",
        "power": 9,
        "color": (200, 180, 80),
        "blurb": "Reviews and reverses what was done to others.",
        "abilities": [
            ("verdict", "Verdict", "cleanse", 2100, None, 0, True),
            ("condemn", "Condemn", "disrupt", 2700, None, 0, True),
            ("overrule", "Overrule", "cleanse", 3600, None, 0, True),
            ("jacobs_ladder", "Jacob's Ladder", "disrupt", 14400, None, 0, True),
            ("scale_of_wrongdoing", "Scale of Wrongdoing", "control", 10800, None, 0, True),
            ("divine_retribution", "Divine Retribution", "disrupt", 18000, None, 0, True),
        ],
    },
    "prudence": {
        "name": "The Prudent Eye",
        "kind": "standalone",
        "power": 8,
        "color": (170, 200, 220),
        "blurb": "Sees what is coming and blunts it.",
        "abilities": [
            ("discern", "Discern", "utility", 900, None, 0, True),
            ("anticipate", "Anticipate", "support", 1800, None, 0, False),
            ("counsel", "Counsel", "cleanse", 2400, None, 0, True),
        ],
    },
    "fortitude": {
        "name": "The Unbroken",
        "kind": "standalone",
        "power": 9,
        "color": (190, 140, 90),
        "blurb": "Cannot be locked down for long.",
        "abilities": [
            ("iron_will", "Iron Will", "support", 1800, None, 0, False),
            ("fortify", "Fortify", "support", 2400, None, 0, True),
            ("unbreak", "Unbreak", "cleanse", 3000, None, 0, False),
        ],
    },
    "faith": {
        "name": "The Faithful",
        "kind": "standalone",
        "power": 10,
        "color": (255, 245, 200),
        "blurb": "Unreliable, but occasionally decisive.",
        "abilities": [
            ("invoke_faith", "Invoke Faith", "cleanse", 1800, None, 0, False),
            ("prayer", "Prayer", "support", 2400, None, 0, True),
            ("judgment", "Judgment", "disrupt", 3600, "misfire", 900, True),
            ("holy_judgment", "Holy Judgment", "disrupt", 7200, "ability_lock", 480, True),
        ],
    },
    "hope": {
        "name": "The Hopeful",
        "kind": "standalone",
        "power": 10,
        "color": (100, 180, 255),
        "blurb": "Turns unyielding hope into targeted attacks and pressure.",
        "abilities": [
            ("rally", "Rally", "disrupt", 2400, "cooldown_tax", 1800, True),
            ("beacon", "Beacon", "disrupt", 3000, "misfire", 900, True),
            ("inspire_strike", "Inspire Strike", "disrupt", 9000, "cooldown_tax", 1800, True),
            ("despair_wave", "Despair Wave", "disrupt", 10800, "misfire", 900, True),
            ("uplift", "Uplift", "disrupt", 1800, "speech_lag", 300, True),
        ],
    },
    "liberality": {
        "name": "The Open Spirit",
        "kind": "standalone",
        "power": 8,
        "color": (180, 230, 180),
        "blurb": "Frees the restrained.",
        "abilities": [
            ("grant_freedom", "Grant Freedom", "cleanse", 2100, None, 0, True),
            ("unbind", "Unbind", "cleanse", 1500, None, 0, True),
            ("bestow", "Bestow", "support", 2700, None, 0, True),
        ],
    },

    # ── MYTHS ───────────────────────────────────────────────────────
    "la_llorona": {
        "name": "La Llorona",
        "kind": "myth",
        "power": 6,
        "color": (70, 150, 175),
        "blurb": "The Weeping Woman. Her cry silences; her river pulls under.",
        "abilities": [
            ("wail", "The Wail", "disrupt", 3600, "ability_lock", 600, True),
            ("veil", "Weeping Veil", "support", 7200, None, 0, False),
            ("lure", "River's Lure", "silence", 10800, "timeout", 60, True),
        ],
    },
}

# ability_key -> role_key, built once so lookups are O(1) and unambiguous.
ABILITY_OWNER: dict[str, str] = {}
ABILITY_SPEC: dict[str, tuple] = {}
for _rk, _rv in ROLES.items():
    for _ab in _rv["abilities"]:
        ABILITY_OWNER[_ab[0]] = _rk
        ABILITY_SPEC[_ab[0]] = _ab


def role_display(role_key: str) -> str:
    return ROLES[role_key]["name"]


ALWAYS_INSTANT_KINDS = {"sin", "virtue"}
# Every despair-kind role is instant to claim except these two — they still
# go through the normal power-gated approval flow.
DESPAIR_APPROVAL_REQUIRED = {"despair_sister", "izuru_despair"}


def approvals_needed(role_key: str) -> int:
    spec = ROLES[role_key]
    kind = spec["kind"]
    if kind in ALWAYS_INSTANT_KINDS:
        return 0
    if kind == "despair" and role_key not in DESPAIR_APPROVAL_REQUIRED:
        return 0
    # gate_power is an internal-only gating number that never appears in any
    # embed or listing; it lets a role be forced into the approval flow
    # without changing the power level shown to players.
    power = spec.get("gate_power", spec["power"])
    if power < APPROVAL_POWER_THRESHOLD:
        return 0
    return APPROVALS_REQUIRED.get(power, 5)


def find_role_key(query: str) -> Optional[str]:
    """Match a role by key or by display name, case-insensitively."""
    q = query.lower().strip()
    if q in ROLES:
        return q
    for k, v in ROLES.items():
        if v["name"].lower() == q:
            return k
    for k, v in ROLES.items():
        if q in v["name"].lower() or q in k:
            return k
    return None


# ═══════════════════════════════════════════════════════════════════
# DISCORD ROLE SYNC
# ═══════════════════════════════════════════════════════════════════
# The original bot recorded a role in its JSON and then *separately* tried to
# add the Discord role, swallowing failures. When the add failed (role missing,
# or the bot's role sat too low) the data said you had it but Discord didn't.
# ensure_discord_role() below creates the role if absent, verifies hierarchy,
# and reports the real reason on failure instead of failing silently.


async def ensure_discord_role(guild: discord.Guild, role_key: str) -> tuple[Optional[discord.Role], Optional[str]]:
    """Get or create the Discord role. Returns (role, error_message)."""
    spec = ROLES[role_key]
    name = spec["name"]
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        try:
            role = await guild.create_role(
                name=name,
                color=discord.Color.from_rgb(*spec["color"]),
                hoist=True,
                reason="Zetsubo 2.0 role sync",
            )
        except discord.Forbidden:
            return None, "I lack **Manage Roles** permission, so I can't create the role."
        except discord.HTTPException as e:
            return None, f"Discord rejected the role creation: `{e.status}`."
    me = guild.me
    if me is None:
        return None, "I can't read my own member record in this server."
    if role >= me.top_role:
        return None, (
            f"**{name}** sits above my highest role, so Discord won't let me assign it.\n"
            "Fix: Server Settings → Roles → drag my role above it."
        )
    return role, None


async def sync_assign(member: discord.Member, role_key: str) -> tuple[bool, str]:
    """Assign the Discord role and report honestly. Never claims success blindly."""
    role, err = await ensure_discord_role(member.guild, role_key)
    if err:
        return False, err
    if role in member.roles:
        return True, f"**{role.name}** was already on {member.mention}."
    try:
        await member.add_roles(role, reason="Zetsubo 2.0 role grant")
    except discord.Forbidden:
        return False, f"Permission denied while assigning **{role.name}**."
    except discord.HTTPException as e:
        return False, f"Discord API error assigning **{role.name}**: `{e.status}`."
    # Verify rather than assume.
    fresh = member.guild.get_member(member.id)
    if fresh and role not in fresh.roles:
        return False, f"Discord accepted the request but **{role.name}** did not stick. Check role hierarchy."
    return True, f"**{role.name}** assigned to {member.mention}."


async def sync_remove(member: discord.Member, role_key: str) -> tuple[bool, str]:
    role = discord.utils.get(member.guild.roles, name=ROLES[role_key]["name"])
    if role is None or role not in member.roles:
        return True, "Role was not present."
    try:
        await member.remove_roles(role, reason="Zetsubo 2.0 role release")
        return True, f"**{role.name}** removed."
    except discord.Forbidden:
        return False, f"Permission denied while removing **{role.name}**."
    except discord.HTTPException as e:
        return False, f"Discord API error removing **{role.name}**: `{e.status}`."


def holder_of(data: dict, role_key: str) -> Optional[str]:
    return data["role_holders"].get(role_key)


async def bind_role(data: dict, member: discord.Member, role_key: str) -> tuple[bool, str]:
    """Record + assign in one step. Enforces one-role-per-person and one-person-per-role."""
    if role_key == "kaleb_love" and member.name.lower() != "manoftheswamp":
        return False, "Kaleb Love can only be obtained by the Discord username `manoftheswamp`."
    existing_holder = holder_of(data, role_key)
    if existing_holder and existing_holder != str(member.id):
        return False, f"**{role_display(role_key)}** is already held by <@{existing_holder}>."

    user = get_user(data, member.id)
    old = user.get("role_key")
    if old and old != role_key:
        await sync_remove(member, old)
        data["role_holders"].pop(old, None)

    ok, msg = await sync_assign(member, role_key)
    if not ok:
        return False, msg

    user["role_key"] = role_key
    data["role_holders"][role_key] = str(member.id)
    data["requests"].pop(role_key, None)
    save_data(data)
    return True, msg


# ═══════════════════════════════════════════════════════════════════
# ROLE BROWSING
# ═══════════════════════════════════════════════════════════════════

@bot.command(name="roles")
async def roles_cmd(ctx, kind: str = None):
    """List every role. Optionally filter by its role category."""
    data = load_data()
    save_data(data)
    kinds = ["sin", "virtue", "standalone", "myth", "special", "hope", "despair"]
    if kind and kind.lower() not in kinds:
        await ctx.send(f"Unknown category. Try: `{'` | `'.join(kinds)}`", delete_after=10)
        return

    embed = discord.Embed(
        title="📜 Roles",
        description="`!role_info <role>` for a full kit • `!request_role <role>` to claim one",
        color=discord.Color.blurple(),
    )
    for k in kinds:
        if kind and k != kind.lower():
            continue
        entries = []
        for rk, rv in sorted(ROLES.items(), key=lambda x: x[1]["power"]):
            if rv["kind"] != k:
                continue
            # Secret roles are omitted unless the viewer is the holder.
            if rk in SECRET_ROLES and holder_of(data, rk) != str(ctx.author.id):
                continue
            h = holder_of(data, rk)
            status = f"held by <@{h}>" if h else "**open**"
            gate = "🔓" if approvals_needed(rk) == 0 else "🔐"
            entries.append(f"{gate} **{rv['name']}** (P{rv['power']}) — {status}")
        if entries:
            embed.add_field(name=k.capitalize(), value="\n".join(entries), inline=False)
    embed.set_footer(text="🔓 claim instantly  •  🔐 needs approvals, legacy trial, or the owner")
    await ctx.send(embed=embed)


@bot.command(name="role_info")
async def role_info(ctx, *, query: str):
    """Show a role's complete base moveset."""
    rk = find_role_key(query)
    if not rk:
        await ctx.send(f"No role matches `{query}`. Try `!roles`.", delete_after=10)
        return
    data = load_data()
    save_data(data)
    spec = ROLES[rk]
    h = holder_of(data, rk)

    embed = discord.Embed(
        title=f"{spec['name']}",
        description=f"*{spec['blurb']}*",
        color=discord.Color.from_rgb(*spec["color"]),
    )
    embed.add_field(name="Category", value=spec["kind"].capitalize(), inline=True)
    embed.add_field(name="Power", value=str(spec["power"]), inline=True)
    embed.add_field(name="Holder", value=f"<@{h}>" if h else "*open*", inline=True)

    lines = []
    for key, disp, cat, cd, eff, dur, needs_t in spec["abilities"]:
        tgt = " `@user`" if needs_t else ""
        if key == "nagito_luck_switch":
            detail = "toggle 99% dodge on/off"
        elif key == "nagito_luck_effect":
            detail = "choose any effect and set its duration"
        elif eff:
            meta = EFFECTS[eff]
            detail = f"{meta['icon']} {meta['name']} for {dur // 60}m"
        else:
            detail = "self/ally effect"
        lines.append(f"**`!{key}{tgt}`** — *{cat}* · {detail} · CD {cd // 60}m")
    embed.add_field(name="Full moveset (no forms, no unlocks)",
                    value="\n".join(lines) or "*role-only; no ability kit*",
                    inline=False)

    need = approvals_needed(rk)
    if need:
        embed.add_field(
            name="How to obtain",
            value=(f"Power {spec['power']} is gated. Choose one:\n"
                   f"• `!request_role {rk}` then **{need}** members `!approve @you`\n"
                   f"• `!legacy_trial {rk}` — the old trial route (optional)\n"
                   f"• Ask the server owner to `!assign_role @you {rk}`"),
            inline=False,
        )
    else:
        embed.add_field(
            name="How to obtain",
            value=spec.get(
                "obtainment",
                f"Open tier — `!request_role {rk}` grants it immediately if free.",
            ),
            inline=False,
        )
    await ctx.send(embed=embed)


class _AbilityMessageProxy:
    """Small message-shaped object for abilities triggered by an interaction."""

    def __init__(self, content: str):
        self.content = content
        self.mentions = []

    async def delete(self):
        # Button/modal invocations do not create a command message to delete.
        return None


class _AbilityInteractionContext:
    """Adapt a Discord interaction to the subset of commands.Context we use."""

    def __init__(self, interaction: discord.Interaction, ability_key: str,
                 message_content: str = None):
        self.interaction = interaction
        self.author = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.message = _AbilityMessageProxy(message_content or f"!{ability_key}")

    async def send(self, content=None, *, embed=None, embeds=None, view=None,
                   delete_after=None, **kwargs):
        # Prefix-command responses can use delete_after; interaction responses
        # cannot, so omit it here rather than failing after the ability runs.
        payload = dict(kwargs)
        if content is not None:
            payload["content"] = content
        if embed is not None:
            payload["embed"] = embed
        if embeds is not None:
            payload["embeds"] = embeds
        if view is not None:
            payload["view"] = view

        if self.interaction.response.is_done():
            return await self.interaction.followup.send(wait=True, **payload)
        await self.interaction.response.send_message(**payload)
        return await self.interaction.original_response()


class _AbilityTargetSelectView(discord.ui.View):
    """Native Discord member picker for abilities that need a target.

    Uses discord.ui.UserSelect so clicking the button shows a real,
    searchable dropdown of everyone in the server instead of asking the
    player to type a mention or an ID.
    """

    def __init__(self, panel, ability_key: str):
        super().__init__(timeout=120)
        self.panel = panel
        self.ability_key = ability_key

        select = discord.ui.UserSelect(
            placeholder="Choose a member to target...",
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_select
        self.select = select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        picked = self.select.values[0]
        guild = interaction.guild
        target = guild.get_member(picked.id) if guild else None
        if target is None and guild is not None:
            try:
                target = await guild.fetch_member(picked.id)
            except Exception:
                target = None
        if target is None:
            await interaction.response.send_message(
                "I couldn't find that member in this server anymore.",
                ephemeral=True,
            )
            return
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await self.panel.run_from_interaction(interaction, self.ability_key, target)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.panel.owner_id:
            await interaction.response.send_message(
                "This target picker belongs to somebody else.", ephemeral=True,
            )
            return False
        return True


class _AbilityTextModal(discord.ui.Modal):
    """Collect the free-form text used by a legacy Sister ability."""

    def __init__(self, panel, ability_key: str):
        display = ABILITY_SPEC[ability_key][1]
        super().__init__(title=f"{display}"[:45], timeout=300)
        self.panel = panel
        self.ability_key = ability_key
        self.text_input = discord.ui.TextInput(
            label="What should the ability say or do?",
            placeholder="Enter the Sister's line or action...",
            required=True,
            max_length=500,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.panel.run_from_interaction(
            interaction,
            self.ability_key,
            None,
            message_content=f"!{self.ability_key} {self.text_input.value}",
        )


class _NagitoEffectSelectView(discord.ui.View):
    def __init__(self, owner_id: int, target_id: int, max_minutes: int):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.target_id = target_id
        self.max_minutes = max_minutes
        options = [
            discord.SelectOption(
                label=meta["name"],
                value=effect_key,
                description=meta["desc"][:100],
                emoji=meta["icon"],
            )
            for effect_key, meta in EFFECTS.items()
        ]
        select = discord.ui.Select(
            placeholder="Choose an effect (scroll for more)...",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)
        self.select = select

    async def _on_select(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            _NagitoEffectDurationModal(
                self.owner_id,
                self.target_id,
                self.select.values[0],
                self.max_minutes,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This effect picker belongs to somebody else.", ephemeral=True,
            )
            return False
        return True


class _NagitoEffectDurationModal(discord.ui.Modal):
    def __init__(self, owner_id: int, target_id: int, effect: str, max_minutes: int):
        super().__init__(title="Set the effect duration", timeout=180)
        self.owner_id = owner_id
        self.target_id = target_id
        self.effect = effect
        self.max_minutes = max_minutes
        self.duration_input = discord.ui.TextInput(
            label=f"Duration in minutes (1-{max_minutes})",
            placeholder=str(min(15, max_minutes)),
            required=True,
            min_length=1,
            max_length=3,
        )
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This duration form belongs to somebody else.", ephemeral=True,
            )
            return
        raw = str(self.duration_input.value).strip()
        if not raw.isdecimal():
            await interaction.response.send_message(
                "Enter a whole number of minutes.", ephemeral=True,
            )
            return
        ctx = _AbilityInteractionContext(interaction, "nagito_luck_effect")
        await _apply_selected_nagito_effect(
            ctx, self.target_id, self.effect, int(raw),
        )


class _AbilityPanelView(discord.ui.View):
    """Interactive ability panel attached to the author's !myrole message."""

    def __init__(self, owner: discord.Member, role_key: str, abilities=None):
        super().__init__(timeout=900)
        self.owner_id = owner.id
        self.role_key = role_key
        self.message = None
        abilities = abilities if abilities is not None else ROLES[role_key]["abilities"]

        for index, (ability_key, display, category, _cd, _effect, _duration, needs_target) in enumerate(
            abilities
        ):
            button = discord.ui.Button(
                label=display[:80],
                style=discord.ButtonStyle.secondary if needs_target else discord.ButtonStyle.primary,
                row=index // 5,
            )

            async def callback(interaction: discord.Interaction, key=ability_key, needs_t=needs_target):
                if key in TEXT_INPUT_ABILITIES:
                    await interaction.response.send_modal(_AbilityTextModal(self, key))
                elif needs_t:
                    await interaction.response.send_message(
                        "Choose who to target:",
                        view=_AbilityTargetSelectView(self, key),
                        ephemeral=True,
                    )
                else:
                    await self.run_from_interaction(interaction, key, None)

            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This ability panel belongs to somebody else. Run `!myrole` for your own panel.",
                ephemeral=True,
            )
            return False
        return True

    async def run_from_interaction(
        self,
        interaction: discord.Interaction,
        ability_key: str,
        target: Optional[discord.Member],
        message_content: str = None,
    ):
        try:
            ctx = _AbilityInteractionContext(interaction, ability_key, message_content)
            await run_ability(ctx, ability_key, target)
        except Exception:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Something went wrong while running that ability. The text command is still available.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Something went wrong while running that ability. The text command is still available.",
                    ephemeral=True,
                )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


@bot.command(name="myrole", aliases=["panel", "abilities"])
async def myrole(ctx):
    """Your role, your kit, your cooldowns, and anything currently affecting you.

    This is one way to reach your ability buttons (also available as
    `!panel` / `!abilities`), but it is never required: every ability also
    has its own standalone text command (e.g. `!side_of_fries @user`) that
    works on its own, with no need to open this panel first.
    """
    data = load_data()
    user = get_user(data, ctx.author.id)
    clear_expired_effects(user)
    save_data(data)

    rk = user.get("role_key")
    if not rk:
        await ctx.send("You hold no role. `!roles` to browse, `!request_role <role>` to claim.")
        return
    spec = ROLES[rk]
    abilities = list(spec["abilities"])
    # Summoned legacy kits are additive to the Ultimate Despair's panel. The
    # owner check in run_ability still requires the corresponding summon flag.
    if rk == "ultimate_despair":
        if user.get("despair_sister_active"):
            abilities.extend(ROLES["despair_sister"]["abilities"])
        if user.get("reserve_course_active"):
            abilities.extend(ROLES["reserve_course_student"]["abilities"])
    embed = discord.Embed(
        title=f"{spec['name']}",
        description=f"*{spec['blurb']}*",
        color=discord.Color.from_rgb(*spec["color"]),
    )
    lines = []
    for key, disp, cat, cd, eff, dur, needs_t in abilities:
        ready = user["cooldowns"].get(key, 0)
        mark = "✅" if now_ts() >= ready else f"⏳ {remaining_fmt(ready)}"
        tgt = " @user" if needs_t else ""
        lines.append(f"{mark} **`!{key}{tgt}`** — *{cat}*")
    embed.add_field(name="Abilities", value="\n".join(lines), inline=False)
    embed.add_field(name="Affecting you", value=effect_summary(user), inline=False)
    if rk in {"nagito_hope", "nagito_despair"}:
        state = "ON — 99% chance to dodge hostile abilities" if user.get("nagito_luck_switch") else "OFF"
        embed.add_field(
            name="Nagito Luck Switch",
            value=f"**{state}** · `!nagito_luck_switch` toggles it at any time.",
            inline=False,
        )
    if abilities:
        embed.set_footer(text="Use the buttons below, or the text commands listed above.")
        panel = _AbilityPanelView(ctx.author, rk, abilities)
        panel.message = await ctx.send(embed=embed, view=panel)
    else:
        await ctx.send(embed=embed)


@bot.command(name="effects")
async def effects_cmd(ctx, member: discord.Member = None):
    """See what's currently affecting you or someone else."""
    member = member or ctx.author
    data = load_data()
    user = get_user(data, member.id)
    clear_expired_effects(user)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title=f"Status — {member.display_name}",
        description=effect_summary(user),
        color=discord.Color.greyple(),
    ))


# ═══════════════════════════════════════════════════════════════════
# OBTAINMENT
# ═══════════════════════════════════════════════════════════════════
# Three routes, all valid:
#   1. Below the power threshold  -> instant, first come first served
#   2. At/above the threshold     -> N community approvals
#   3. Any role, any time         -> server owner / admin just assigns it
# The legacy trial route is preserved but entirely optional (!legacy_trial).


async def _request_role_key(ctx, rk: str):
    """Core role-request flow: instant below the gate, an approval vote above it.

    Shared by `!request_role` (explicit choice) and `!surprise` (random
    choice) so both follow identical rules.
    """
    data = load_data()
    user = get_user(data, ctx.author.id)

    holder = holder_of(data, rk)
    if holder == str(ctx.author.id):
        await ctx.send("You already hold that role.", delete_after=8)
        save_data(data); return
    if holder:
        await ctx.send(
            f"**{role_display(rk)}** is taken by <@{holder}>. "
            "Only one person may hold a role at a time.", delete_after=12)
        save_data(data); return

    if rk == "kaleb_love" and ctx.author.name.lower() != "manoftheswamp":
        await ctx.send(
            "Kaleb Love can only be obtained by the Discord username `manoftheswamp`.",
            delete_after=10,
        )
        return

    need = approvals_needed(rk)

    if need == 0:
        ok, msg = await bind_role(data, ctx.author, rk)
        if ok:
            await ctx.send(embed=discord.Embed(
                title="✅ Role Claimed",
                description=f"{ctx.author.mention} now holds **{role_display(rk)}**.\n{msg}\n\n"
                            f"`!myrole` to see your full kit — everything is available immediately.",
                color=discord.Color.green(),
            ))
        else:
            await ctx.send(f"❌ {msg}")
        return

    # Gated tier — open or refresh a request.
    existing = data["requests"].get(rk)
    if existing and now_ts() - existing["opened_at"] < REQUEST_TTL:
        if existing["requester_id"] != str(ctx.author.id):
            await ctx.send(
                f"<@{existing['requester_id']}> already has an open request for "
                f"**{role_display(rk)}** ({len(existing['approvals'])}/{need}).",
                delete_after=12)
            save_data(data); return
        await ctx.send(
            f"Your request is already open — **{len(existing['approvals'])}/{need}** approvals.",
            delete_after=10)
        save_data(data); return

    data["requests"][rk] = {
        "requester_id": str(ctx.author.id),
        "approvals": [],
        "opened_at": now_ts(),
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🔐 Approval Requested",
        description=(
            f"{ctx.author.mention} is requesting **{role_display(rk)}** (Power {ROLES[rk]['power']}).\n\n"
            f"**{need}** other members must run `!approve {ctx.author.mention}`.\n\n"
            f"Alternatives: `!legacy_trial {rk}` for the old trial route, "
            "or an admin can simply assign it."
        ),
        color=discord.Color.gold(),
    ))


@bot.command(name="request_role")
async def request_role(ctx, *, query: str):
    """Ask for a role. Low power grants instantly; high power opens an approval vote."""
    rk = find_role_key(query)
    if not rk:
        await ctx.send(f"No role matches `{query}`. Try `!roles`.", delete_after=10)
        return
    await _request_role_key(ctx, rk)


# Rolling the surprise jackpot skips the whole role pool. Real Discord
# Administrator is never granted this way — see the note in the announcement
# below for why. 1 in 100,000 == 0.001%.
SURPRISE_ADMIN_CHANCE = 0.00001
SURPRISE_JACKPOT_DURATION = 30 * 60
# Roles with no real ability kit, a locked/admin-only obtainment route, or
# their own dedicated flow don't make sense as a random prize.
SURPRISE_EXCLUDED_KEYS = {"kaleb_love", "fallen_from_grace", "banished"}


async def _grant_surprise_jackpot(ctx):
    """The 0.001% roll. Grants Verity's Mandate — this bot's highest bot-side
    authority tier — instead of real Discord Administrator.

    Real Administrator bypasses every permission check Discord has, so it
    can't be taken back if a jackpot winner (or the bot) ever needed to
    undo it, and it would let someone lock the bot itself out of the
    server. The Mandate is the deliberate stand-in already used for
    Lord Verity's own ultimate ability — see `!mandate_log` and the note
    below for exactly what it does and doesn't grant.
    """
    guild = ctx.guild
    if protected_member(ctx.author):
        await ctx.send(
            "🎉 You rolled the jackpot — but you're the owner or already an "
            "administrator, so there's nothing left to grant.",
        )
        return
    role, error = await ensure_mandate_role(guild)
    if error or role is None:
        await ctx.send(f"🎉 You rolled the jackpot, but I couldn't grant it: {error}", delete_after=15)
        return
    data = load_data()
    existing = active_mandate(data, guild, ctx.author)
    if existing:
        await ctx.send(
            f"🎉 You rolled the jackpot — but you already hold **{MANDATE_ROLE_NAME}** "
            f"for {remaining_fmt(existing['expires'])}. Nothing stacks; enjoy the luck.",
        )
        return
    try:
        await ctx.author.add_roles(role, reason="Surprise jackpot (0.001%)")
    except (discord.Forbidden, discord.HTTPException) as e:
        await ctx.send(f"🎉 You rolled the jackpot, but Discord rejected the grant: `{type(e).__name__}`.", delete_after=15)
        return

    record = {
        "recipient_id": str(ctx.author.id),
        "started": now_ts(),
        "expires": now_ts() + SURPRISE_JACKPOT_DURATION,
        "granted_by": "surprise_jackpot",
        "roles_granted": [],
        "audit_keys": [],
    }
    mandate_records(data, guild)[str(ctx.author.id)] = record
    save_data(data)
    await write_server_log(
        guild, "MANDATE_STARTED", ctx.author.id,
        f"{ctx.author} won the surprise jackpot and received {MANDATE_ROLE_NAME} "
        f"until <t:{record['expires']}:F>.",
        str(ctx.author.id),
    )
    await ctx.send(embed=discord.Embed(
        title="🎉 JACKPOT — 1 in 100,000",
        description=(
            f"{ctx.author.mention} beat 0.001% odds and holds "
            f"**{MANDATE_ROLE_NAME}** for **{SURPRISE_JACKPOT_DURATION // 60} minutes** — "
            "this bot's highest tier of authority.\n\n"
            "**Granted:** manage messages, timeout members, manage nicknames, "
            "voice mute/move, plus `!grant_temp_role` for temporary role grants.\n"
            "**Withheld:** ban, kick, manage server, manage roles, manage channels — "
            "real Discord Administrator is never handed out by a dice roll.\n\n"
            f"*{MANDATE_NOTE}*"
        ),
        color=discord.Color.from_rgb(255, 215, 0),
    ))


@bot.command(name="surprise", aliases=["surprise_me"])
@commands.guild_only()
async def surprise(ctx):
    """Request a uniformly random role for yourself.

    Exactly the same rules as `!request_role` apply to whatever gets picked —
    power level, instant grant below the approval gate, an approval vote
    above it. Separately, an astronomically rare 0.001% roll bypasses the
    role pool entirely; see `!commands` for what that grants and why.
    """
    if random.random() < SURPRISE_ADMIN_CHANCE:
        await _grant_surprise_jackpot(ctx)
        return

    data = load_data()
    pool = [rk for rk in ROLES if rk not in SURPRISE_EXCLUDED_KEYS and not holder_of(data, rk)]
    if not pool:
        await ctx.send("Every role is currently held — nothing open to surprise you with. Try `!requests`.")
        return
    rk = random.choice(pool)
    await ctx.send(f"🎁 The surprise draw picked **{role_display(rk)}**...")
    await _request_role_key(ctx, rk)


@bot.command(name="approve")
async def approve(ctx, member: discord.Member):
    """Approve someone's pending role request."""
    data = load_data()
    if member.id == ctx.author.id:
        await ctx.send("You cannot approve yourself.", delete_after=8)
        save_data(data); return

    target_rk = None
    for rk, req in data["requests"].items():
        if req["requester_id"] == str(member.id) and now_ts() - req["opened_at"] < REQUEST_TTL:
            target_rk = rk
            break
    if not target_rk:
        await ctx.send(f"{member.display_name} has no open role request.", delete_after=8)
        save_data(data); return

    req = data["requests"][target_rk]
    uid = str(ctx.author.id)
    if uid in req["approvals"]:
        await ctx.send("You already approved this request.", delete_after=8)
        save_data(data); return

    req["approvals"].append(uid)
    need = approvals_needed(target_rk)
    got = len(req["approvals"])
    save_data(data)

    if got < need:
        await ctx.send(f"👍 **{got}/{need}** approvals for {member.mention} → **{role_display(target_rk)}**.")
        return

    ok, msg = await bind_role(data, member, target_rk)
    if ok:
        await ctx.send(embed=discord.Embed(
            title="✅ Approved",
            description=(f"{member.mention} has been granted **{role_display(target_rk)}** "
                         f"with {got} approvals.\n{msg}"),
            color=discord.Color.green(),
        ))
    else:
        await ctx.send(f"❌ Approvals met, but assignment failed: {msg}")


@bot.command(name="requests")
async def requests_cmd(ctx):
    """View all open role requests."""
    data = load_data()
    save_data(data)
    live = {rk: r for rk, r in data["requests"].items()
            if now_ts() - r["opened_at"] < REQUEST_TTL}
    if not live:
        await ctx.send("No open requests.")
        return
    lines = []
    for rk, r in live.items():
        lines.append(f"**{role_display(rk)}** — <@{r['requester_id']}> "
                     f"({len(r['approvals'])}/{approvals_needed(rk)})")
    await ctx.send(embed=discord.Embed(
        title="🔐 Open Requests", description="\n".join(lines), color=discord.Color.gold()))


@bot.command(name="release_role")
async def release_role(ctx):
    """Give up your role so someone else can take it."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    rk = user.get("role_key")
    if not rk:
        await ctx.send("You hold no role.", delete_after=8)
        save_data(data); return
    await sync_remove(ctx.author, rk)
    data["role_holders"].pop(rk, None)
    user["role_key"] = None
    save_data(data)
    await ctx.send(f"🕊️ {ctx.author.mention} released **{role_display(rk)}**. It is now open.")


@bot.command(name="legacy_trial")
async def legacy_trial(ctx, *, query: str):
    """
    OPTIONAL. The original trial-style obtainment, preserved for anyone who
    prefers earning a role the old way instead of using approvals.
    """
    rk = find_role_key(query)
    if not rk:
        await ctx.send(f"No role matches `{query}`. Try `!roles`.", delete_after=10)
        return
    if rk == "kaleb_love" and ctx.author.name.lower() != "manoftheswamp":
        await ctx.send(
            "Kaleb Love can only be obtained by the Discord username `manoftheswamp`.",
            delete_after=10,
        )
        return
    data = load_data()
    user = get_user(data, ctx.author.id)
    if holder_of(data, rk):
        await ctx.send(f"**{role_display(rk)}** is already held.", delete_after=10)
        save_data(data); return

    user["optional_progress"][rk] = {"started": now_ts()}
    save_data(data)

    legacy = ROLES[rk].get(
        "obtainment",
        LEGACY_TRIALS.get(rk, "Demonstrate the role's nature publicly, then ask an admin to confirm."),
    )
    await ctx.send(embed=discord.Embed(
        title=f"📜 Legacy Trial — {role_display(rk)}",
        description=(
            f"{legacy}\n\n"
            "**This route is optional and admin-judged.** When you believe you've met it, "
            f"ask an admin to run `!assign_role {ctx.author.mention} {rk}`.\n\n"
            f"You can abandon this at any time and use `!request_role {rk}` instead."
        ),
        color=discord.Color.dark_gold(),
    ))


LEGACY_TRIALS = {
    "lust":      "Collect 5 unique ❤️ reactions from different members within 24 hours.",
    "gluttony":  "React to every message in the feast channel within 5 minutes, for 24 hours.",
    "greed":     "Silence someone without being exposed, within 8 hours.",
    "sloth":     "Abbreviate every word longer than 4 characters, for 48 hours.",
    "wrath":     "Include a curse word in every message you send, for 24 hours.",
    "envy":      "Strip a role from a member without being exposed, within 12 hours.",
    "pride":     "Proclaim your superiority and collect 10 unique 🙏 reactions within 48 hours.",
    "chastity":  "Add no ❤️ reaction to anything for 48 hours.",
    "temperance":"Add no reactions at all for 24 hours.",
    "charity":   "Give a role you hold to another member, admin-confirmed.",
    "diligence": "Post a 20+ word message every hour for 24 consecutive hours.",
    "patience":  "Send no curse words for 48 hours.",
    "kindness":  "Genuinely praise 5 different members, 10+ words each, within 24 hours.",
    "humility":  "Publicly elevate others above yourself and collect 10 🙏 reactions in 48 hours.",
}


# ═══════════════════════════════════════════════════════════════════
# ADMIN
# ═══════════════════════════════════════════════════════════════════

@bot.command(name="assign_role")
@commands.has_permissions(administrator=True)
async def assign_role(ctx, member: discord.Member, *, query: str):
    """Admin/owner: grant any role directly, bypassing approvals entirely."""
    rk = find_role_key(query)
    if not rk:
        await ctx.send(f"No role matches `{query}`. Try `!roles`.", delete_after=10)
        return
    data = load_data()
    holder = holder_of(data, rk)
    if holder and holder != str(member.id):
        await ctx.send(
            f"⚠️ **{role_display(rk)}** is held by <@{holder}>. "
            f"Run `!revoke_role <@{holder}>` first, or they can `!release_role`.",
            delete_after=15)
        save_data(data); return
    ok, msg = await bind_role(data, member, rk)
    await ctx.send(("✅ " if ok else "❌ ") + msg)


@bot.command(name="revoke_role")
@commands.has_permissions(administrator=True)
async def revoke_role(ctx, member: discord.Member):
    """Admin: strip a member's role and reopen it."""
    data = load_data()
    user = get_user(data, member.id)
    rk = user.get("role_key")
    if not rk:
        await ctx.send(f"{member.display_name} holds no role.", delete_after=8)
        save_data(data); return
    ok, msg = await sync_remove(member, rk)
    data["role_holders"].pop(rk, None)
    user["role_key"] = None
    save_data(data)
    await ctx.send(f"🔓 **{role_display(rk)}** revoked from {member.mention} and reopened. {msg}")


@bot.command(name="clear_effects")
@commands.has_permissions(administrator=True)
async def clear_effects(ctx, member: discord.Member):
    """Admin: wipe every status effect from one member. Useful if something ever sticks."""
    data = load_data()
    user = get_user(data, member.id)
    count = len(user.get("effects", {}))
    user["effects"] = {}
    save_data(data)
    try:
        await member.timeout(None, reason=f"!clear_effects by {ctx.author}")
    except Exception:
        pass
    await ctx.send(f"🧹 Cleared **{count}** effect(s) from {member.mention}, including any Discord timeout.")


@bot.command(name="sync_roles")
@commands.has_permissions(administrator=True)
async def sync_roles(ctx):
    """
    Admin: reconcile the data file against Discord.

    Fixes the classic failure where the bot recorded a role but Discord never
    actually applied it (bot role too low, role deleted, member left, etc).
    """
    data = load_data()
    fixed, broken, orphaned = [], [], []

    for rk, uid in list(data["role_holders"].items()):
        member = ctx.guild.get_member(int(uid))
        if member is None:
            data["role_holders"].pop(rk, None)
            u = data["users"].get(uid)
            if u:
                u["role_key"] = None
            orphaned.append(f"{role_display(rk)} (member gone)")
            continue
        role = discord.utils.get(ctx.guild.roles, name=ROLES[rk]["name"])
        if role is None or role not in member.roles:
            ok, msg = await sync_assign(member, rk)
            (fixed if ok else broken).append(f"{role_display(rk)} → {member.display_name}: {msg}")
    save_data(data)

    embed = discord.Embed(title="🔄 Role Sync", color=discord.Color.blurple())
    embed.add_field(name=f"Repaired ({len(fixed)})",
                    value="\n".join(fixed)[:1000] or "*none*", inline=False)
    if broken:
        embed.add_field(name=f"Failed ({len(broken)})",
                        value="\n".join(broken)[:1000], inline=False)
    if orphaned:
        embed.add_field(name=f"Cleaned up ({len(orphaned)})",
                        value="\n".join(orphaned)[:1000], inline=False)
    await ctx.send(embed=embed)


@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup_cmd(ctx):
    """Admin: create every role, the limited mandate role, and the audit channel."""
    created, existed, failed = [], [], []
    for rk in ROLES:
        pre_existing = discord.utils.get(ctx.guild.roles, name=ROLES[rk]["name"]) is not None
        role, err = await ensure_discord_role(ctx.guild, rk)
        if err:
            failed.append(f"{ROLES[rk]['name']}: {err}")
        elif role:
            (existed if pre_existing else created).append(role.name)
    mandate_role, mandate_error = await ensure_mandate_role(ctx.guild)
    if mandate_error:
        failed.append(f"{MANDATE_ROLE_NAME}: {mandate_error}")
    elif mandate_role:
        existed.append(mandate_role.name)
    _, audit_error = await ensure_audit_channel(ctx.guild)
    if audit_error:
        failed.append(f"{AUDIT_LOG_CHANNEL_NAME}: {audit_error}")
    embed = discord.Embed(
        title="⚙️ Setup Complete",
        description=(
            "Roles, the limited temporary mandate role, and the private server audit "
            "channel are safe to create repeatedly."
        ),
        color=discord.Color.green(),
    )
    if created:
        embed.add_field(name=f"Created ({len(created)})", value=", ".join(created)[:1000], inline=False)
    if existed:
        embed.add_field(name=f"Already present ({len(existed)})", value=", ".join(existed)[:1000], inline=False)
    if failed:
        embed.add_field(name=f"Problems ({len(failed)})", value="\n".join(failed)[:1000], inline=False)

    tutorial_channel = discord.utils.find(
        lambda c: "tutorial" in c.name.lower(), ctx.guild.text_channels
    )
    if tutorial_channel and tutorial_channel.permissions_for(ctx.guild.me).send_messages:
        try:
            await tutorial_channel.send(embed=embed)
        except Exception:
            tutorial_channel = None
    if tutorial_channel:
        if ctx.channel.id != tutorial_channel.id:
            await ctx.send(f"⚙️ Setup complete — posted in {tutorial_channel.mention}.")
    else:
        await ctx.send(embed=embed)


@bot.command(name="grant_temp_role")
@commands.guild_only()
async def grant_temp_role(ctx, member: discord.Member, duration: int, *, query: str):
    """
    Mandate-only role grant. It never grants Administrator or Discord-managed roles.
    Every role added here is recorded and is removed when its mandate expires.
    """
    data = load_data()
    record = active_mandate(data, ctx.guild, ctx.author)
    if not record:
        await ctx.send(
            "🚫 Only the active **Verity's Mandate** holder can grant temporary roles.",
            delete_after=10,
        )
        return
    if duration <= 0:
        await ctx.send("Duration must be a positive number of seconds.", delete_after=8)
        return
    if protected_member(member):
        await write_server_log(
            ctx.guild,
            "TEMP_ROLE_SKIPPED_PROTECTED_MEMBER",
            ctx.author.id,
            f"Target {member} already has owner/admin protection; no role was changed.",
            str(ctx.author.id),
        )
        await ctx.send("That member is protected because they are the owner or already have Administrator.", delete_after=10)
        return

    role_key = find_role_key(query)
    blocked = {VERITY_ROLE_KEY, BURGER_ROLE_KEY, FARTBOY_ROLE_KEY}
    if not role_key or role_key in blocked:
        await ctx.send(
            "That role cannot be granted by a mandate. Only existing non-secret bot roles are eligible.",
            delete_after=10,
        )
        return
    role, error = await ensure_discord_role(ctx.guild, role_key)
    if error or role is None:
        await ctx.send(f"❌ {error or 'The role is unavailable.'}", delete_after=10)
        return
    if (
        role.is_default()
        or role.managed
        or role >= ctx.guild.me.top_role
        or role.permissions.administrator
        or role.permissions.ban_members
        or role.permissions.kick_members
        or role.permissions.manage_guild
        or role.permissions.manage_roles
        or role.permissions.manage_channels
        or role.permissions.manage_webhooks
    ):
        await write_server_log(
            ctx.guild,
            "TEMP_ROLE_REJECTED",
            ctx.author.id,
            f"Rejected {role.name} for {member}: unsafe, managed, or above the bot role.",
            str(ctx.author.id),
        )
        await ctx.send("That role is managed, too high, or has a server-changing permission.", delete_after=10)
        return

    expires = min(
        now_ts() + duration,
        int(record["expires"]),
    )
    already_had = role in member.roles
    try:
        if not already_had:
            await member.add_roles(role, reason=f"Temporary mandate grant by {ctx.author}")
    except (discord.Forbidden, discord.HTTPException) as e:
        await ctx.send(f"❌ Discord rejected the temporary role: `{type(e).__name__}`.", delete_after=10)
        return

    grants = record.setdefault("roles_granted", [])
    grants.append({
        "member_id": str(member.id),
        "role_id": str(role.id),
        "role_key": role_key,
        "expires": expires,
        "prior_had": already_had,
    })
    save_data(data)
    await write_server_log(
        ctx.guild,
        "TEMP_ROLE_GRANTED",
        ctx.author.id,
            f"{role.name} → {member} until <t:{expires}:F>; prior_had={already_had}.",
        str(ctx.author.id),
    )
    await ctx.send(
        f"✅ **{role.name}** was granted to {member.mention} until <t:{expires}:R>. "
        "It will be removed only if this mandate added it.",
    )


@bot.command(name="mandate_log")
@commands.has_permissions(administrator=True)
async def mandate_log(ctx, member: discord.Member = None):
    """Admin: inspect the durable server log, optionally for one mandate holder."""
    data = load_data()
    events = data.get("audit_events", {}).get(str(ctx.guild.id), [])
    if member:
        events = [
            event for event in events
            if event.get("actor_id") == str(member.id)
            or event.get("mandate_id") == str(member.id)
        ]
    if not events:
        await ctx.send("No matching server log entries yet.", delete_after=10)
        return
    lines = []
    for event in events[-15:]:
        when = datetime.fromtimestamp(int(event["at"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(
            f"`{when}` **{event['event']}** · "
            f"<@{event['actor_id']}> — {event['details'][:180]}"
        )
    await ctx.send(embed=discord.Embed(
        title="Zetsubo Server Log",
        description="\n".join(lines)[:3900],
        color=discord.Color.dark_gold(),
    ))


# ═══════════════════════════════════════════════════════════════════
# ABILITY ENGINE
# ═══════════════════════════════════════════════════════════════════
# Every ability in the game routes through run_ability(). There is exactly one
# code path that applies an effect, and it always receives a single resolved
# discord.Member. Nothing here ever iterates over a role's member list, which
# is precisely why a cast can no longer splash onto bystanders.

CLEANSE_ABILITIES = {
    # ability_key -> (how many effects to strip, whether it targets others)
    "abstain":       (2, False),
    "purify":        (3, True),
    "fast":          (2, False),
    "moderate":      (2, True),
    "gift_relief":   (3, True),
    "open_hand":     (4, False),
    "rouse":         (2, True),
    "de_escalate":   (2, True),
    "bless":         (3, True),
    "forgive":       (4, True),
    "submit":        (3, True),
    "lift_up":       (4, True),
    "verdict":       (3, True),
    "overrule":      (5, True),
    "counsel":       (2, True),
    "unbreak":       (3, False),
    "invoke_faith":  (2, False),
    "grant_freedom": (3, True),
    "unbind":        (2, True),
}

# Self/ally buffs that grant temporary protection rather than stripping.
WARD_ABILITIES = {
    "devotion", "gorge", "hoard", "sleepwalk", "bloodlust", "mirror",
    "sovereign", "ward", "restraint", "persist", "absorb", "endure",
    "grace", "anticipate", "iron_will", "fortify", "veil",
    "share_load", "inspire", "prayer", "bestow",
}


def ward_active(user: dict) -> bool:
    return now_ts() < (user.get("ward_until") or 0)


def effective_cooldown(user: dict, base: int) -> int:
    """Cooldown Tax doubles cooldowns. This is the only cooldown modifier."""
    return base * 2 if has_effect(user, "cooldown_tax") else base


async def run_ability(ctx, ability_key: str, target: Optional[discord.Member]):
    """Single entry point for every ability in the game."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    clear_expired_effects(user)

    spec = ABILITY_SPEC[ability_key]
    key, disp, cat, base_cd, effect, duration, needs_target = spec
    owner_role = ABILITY_OWNER[ability_key]
    hostile_target = needs_target and (
        effect is not None or cat in {"disrupt", "control", "silence"}
    )

    # 1. Must hold the role. No forms or unlock conditions.
    # Exception: Lord Verity's "Brain Eaten" grants temporary use of a consumed kit.
    if user.get("role_key") != owner_role:
        kit = user.get("devoured_kit")
        borrowed = bool(kit and now_ts() < kit.get("expires", 0)
                        and kit.get("role_key") == owner_role)
        # Despair Wave existed in the older bot as a Hope ability while the
        # 2.0 registry also exposes it to Remnants. Keep the old command usable
        # for both role variants without duplicating its command registration.
        shared_hope_wave = (
            ability_key == "despair_wave"
            and user.get("role_key") in {"hope", "remnant_of_despair"}
        )
        summoned_sister = (
            owner_role == "despair_sister"
            and user.get("role_key") == "ultimate_despair"
            and user.get("despair_sister_active")
        )
        summoned_reserve = (
            owner_role == "reserve_course_student"
            and user.get("role_key") == "ultimate_despair"
            and user.get("reserve_course_active")
        )
        shared_nagito_ability = (
            ability_key in {"nagito_luck_switch", "nagito_luck_effect"}
            and user.get("role_key") in {"nagito_hope", "nagito_despair"}
        )
        if not (borrowed or shared_hope_wave or shared_nagito_ability
                or summoned_sister or summoned_reserve):
            await ctx.send(
                f"🚫 `!{key}` belongs to **{role_display(owner_role)}**, which you don't hold.",
                delete_after=10)
            save_data(data); return

    # 2. Ability Lock blocks everything.
    if has_effect(user, "ability_lock") and ability_key != "nagito_luck_switch":
        e = user["effects"]["ability_lock"]
        await ctx.send(f"🔒 You are ability-locked for {remaining_fmt(e['expires'])}.", delete_after=10)
        save_data(data); return

    # 3. Cooldown.
    ready = user["cooldowns"].get(key, 0)
    if now_ts() < ready:
        await ctx.send(f"⏳ **{disp}** is on cooldown — {remaining_fmt(ready)}.", delete_after=8)
        save_data(data); return

    # 4. Target resolution.
    if needs_target:
        if target is None:
            await ctx.send(f"`!{key} @user` — this ability needs a target.", delete_after=10)
            save_data(data); return
        if target.bot:
            await ctx.send("You can't target a bot.", delete_after=8)
            save_data(data); return
        if get_user(data, target.id).get("rp_opt_out"):
            await ctx.send(f"{target.mention} opted out of roleplay.", delete_after=8)
            save_data(data); return
        if target.id == ctx.author.id and cat not in ("cleanse", "support"):
            await ctx.send("You can't target yourself with that.", delete_after=8)
            save_data(data); return
    if user.get("rp_opt_out"):
        await ctx.send("You opted out of roleplay. `!opt_in` if you want back in.", delete_after=8)
        save_data(data); return

    if hostile_target:
        target_user = get_user(data, target.id)
        if target_user.get("role_key") in {"nagito_hope", "nagito_despair"}:
            target_user.setdefault("nagito_attackers", {})[str(ctx.author.id)] = now_ts()

    # Custom legacy handlers still obey the core 2.0 defense rules.
    if hostile_target:
        target_user = get_user(data, target.id)
        clear_expired_effects(target_user)
        if _is_immune(target_user):
            save_data(data)
            await ctx.send(
                f"😐 **{disp}** is ignored — {target.mention} is immune.",
                delete_after=8,
            )
            return
        if ward_active(target_user):
            target_user["ward_until"] = 0
            save_data(data)
            await ctx.send(
                f"🛡️ **{disp}** is refused by {target.mention}'s ward.",
                delete_after=8,
            )
            return

    cd = effective_cooldown(user, base_cd)

    if needs_target and cat in {"disrupt", "control", "silence"}:
        target_user = get_user(data, target.id)
        if (
            target_user.get("role_key") in {"nagito_hope", "nagito_despair"}
            and target_user.get("nagito_luck_switch")
            and random.random() < 0.99
        ):
            user["cooldowns"][key] = now_ts() + cd
            save_data(data)
            await ctx.send(
                f"🍀 {target.mention} says, *“My luck is so bad...”* "
                "and narrowly avoids the ability. **Nagito's Luck Switch** is on (99% dodge)."
            )
            return

    # 4b. Custom-logic abilities take over here, after all the standard gating
    # (role held, not ability-locked, off cooldown, target resolved) has passed.
    if key in CUSTOM_ABILITIES:
        user["cooldowns"][key] = now_ts() + cd
        save_data(data)
        await CUSTOM_ABILITIES[key](ctx, data, user, spec, target)
        return

    # 5. Misfire — costs the cooldown, produces nothing.
    if has_effect(user, "misfire") and random.random() < 0.40:
        user["cooldowns"][key] = now_ts() + cd
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title=f"🎲 {disp} — Misfired",
            description=f"{ctx.author.mention}'s **{disp}** fizzles out. Cooldown still applies.",
            color=discord.Color.dark_grey(),
        ))
        return

    user["cooldowns"][key] = now_ts() + cd

    # ── CLEANSE ────────────────────────────────────────────────────
    if key in CLEANSE_ABILITIES:
        strip_count, targets_others = CLEANSE_ABILITIES[key]
        recipient = target if (targets_others and target) else ctx.author
        r_user = get_user(data, recipient.id)
        clear_expired_effects(r_user)

        removed = []
        for _ in range(strip_count):
            if not r_user["effects"]:
                break
            # Remove the longest-remaining effect first.
            worst = max(r_user["effects"].items(), key=lambda kv: kv[1]["expires"])
            removed.append(EFFECTS[worst[0]]["name"])
            r_user["effects"].pop(worst[0])

        if "timeout" in [e.lower() for e in removed] or not removed:
            try:
                await recipient.timeout(None, reason=f"!{key} by {ctx.author}")
            except Exception:
                pass

        save_data(data)
        await ctx.send(embed=discord.Embed(
            title=f"✨ {disp}",
            description=(
                f"{ctx.author.mention} uses **{disp}** on {recipient.mention}.\n\n"
                + (f"Cleared: {', '.join(removed)}" if removed
                   else "Nothing was afflicting them — the effort is spent regardless.")
            ),
            color=discord.Color.from_rgb(*ROLES[owner_role]["color"]),
        ))
        return

    # ── WARD / SELF-BUFF ───────────────────────────────────────────
    if key in WARD_ABILITIES:
        ward_len = 600
        recipient = target if (target and needs_target) else ctx.author
        r_user = get_user(data, recipient.id)
        r_user["ward_until"] = now_ts() + ward_len
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title=f"🛡️ {disp}",
            description=(f"{recipient.mention} is warded for **{ward_len // 60} minutes** — "
                         "the next hostile effect aimed at them is refused."),
            color=discord.Color.from_rgb(*ROLES[owner_role]["color"]),
        ))
        return

    # ── UTILITY ────────────────────────────────────────────────────
    if key == "purge_bite":
        deleted = 0
        try:
            async for msg in ctx.channel.history(limit=150):
                if msg.author.id == target.id:
                    try:
                        await msg.delete()
                        deleted += 1
                    except Exception:
                        pass
                    if deleted >= 3:
                        break
        except Exception:
            pass
        save_data(data)
        await ctx.send(f"🍽️ **Purge Bite** — removed **{deleted}** of {target.mention}'s recent messages.")
        return

    if key == "discern":
        t_user = get_user(data, target.id)
        clear_expired_effects(t_user)
        save_data(data)
        t_role = t_user.get("role_key")
        await ctx.send(embed=discord.Embed(
            title=f"🔍 Discern — {target.display_name}",
            description=(f"**Role:** {role_display(t_role) if t_role else '*none*'}\n"
                         f"**Warded:** {'yes' if ward_active(t_user) else 'no'}\n\n"
                         f"**Effects:**\n{effect_summary(t_user)}"),
            color=discord.Color.from_rgb(*ROLES[owner_role]["color"]),
        ))
        return

    # ── HOSTILE EFFECT ─────────────────────────────────────────────
    t_user = get_user(data, target.id)
    clear_expired_effects(t_user)

    # "I Don't Give A Damn" — blanket immunity, beats everything.
    if _is_immune(t_user):
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title=f"😐 {disp} — Ignored",
            description=f"{target.mention} does not give a damn. Nothing happens.",
            color=discord.Color.light_grey(),
        ))
        return

    # "Ow!" — reflect the effect back at the caster.
    counter = t_user.get("counter_armed")
    if counter and now_ts() < counter.get("expires", 0):
        t_user.pop("counter_armed", None)
        if not _is_immune(user):
            apply_effect(data, ctx.author.id, effect, duration, target.id)
        save_data(data)
        meta_r = EFFECTS[effect]
        await ctx.send(embed=discord.Embed(
            title=f"😤 Ow! — Countered",
            description=(
                f"{target.mention} takes **{disp}** on the chin and fires back.\n\n"
                f"{ctx.author.mention} suffers {meta_r['icon']} **{meta_r['name']}** instead."
            ),
            color=discord.Color.from_rgb(240, 230, 140),
        ))
        return

    if ward_active(t_user):
        t_user["ward_until"] = 0
        save_data(data)
        await ctx.send(embed=discord.Embed(
            title=f"🛡️ {disp} — Refused",
            description=f"{target.mention}'s ward absorbs **{disp}** and breaks.",
            color=discord.Color.light_grey(),
        ))
        return

    meta = EFFECTS[effect]
    note = ""

    if effect == "timeout":
        ok = await apply_timeout(target, duration, f"!{key} by {ctx.author}")
        if not ok:
            # Graceful downgrade — never silently do nothing.
            effect, duration = "mute", max(duration, 300)
            meta = EFFECTS[effect]
            note = "\n*(Discord timeout unavailable — applied a bot-side silence instead.)*"

    if effect == "channel_exile":
        ok = await exile_from_channel(target, ctx.channel, duration, f"!{key} by {ctx.author}")
        if not ok:
            effect, duration = "mute", duration
            meta = EFFECTS[effect]
            note = "\n*(Channel permissions unavailable — applied a bot-side silence instead.)*"
        else:
            note = f"\n*(Removed from #{ctx.channel.name} only.)*"

    # THE single write. One user id, nothing else.
    apply_effect(data, target.id, effect, duration, ctx.author.id)
    bonus_details = []
    for bonus_effect, bonus_duration in HOPE_ATTACK_BONUSES.get(key, ()):
        apply_effect(data, target.id, bonus_effect, bonus_duration, ctx.author.id)
        bonus = EFFECTS[bonus_effect]
        bonus_details.append(
            f"{bonus['icon']} **{bonus['name']}** ({bonus_duration // 60}m)"
        )
    extra = []
    if key in {"meteor", "stop_time"}:
        extra = await _splash_negative(ctx, data, target, "ability_lock" if key == "meteor" else "mute", 120 if key == "meteor" else 45)
    save_data(data)
    await _offer_echo(ctx, target, effect, duration)

    await ctx.send(embed=discord.Embed(
        title=f"{meta['icon']} {disp}",
        description=(
            f"{ctx.author.mention} uses **{disp}** on {target.mention}.\n\n"
            f"{meta['icon']} **{meta['name']}** for **{duration // 60}m "
            f"{duration % 60}s** — {meta['desc']}{note}"
            + (
                "\n\n**Follow-up strike:** " + ", ".join(bonus_details)
                if bonus_details else ""
            )
            + ("\n\nAlso caught: " + ", ".join(extra) if extra else "")
        ),
        color=discord.Color.from_rgb(*ROLES[owner_role]["color"]),
    ))


TEXT_INPUT_ABILITIES = {"sister_say", "sister_anything"}


def _make_ability_command(ability_key: str):
    """Register one bot command per ability, all routed through run_ability."""
    key, disp, cat, cd, eff, dur, needs_target = ABILITY_SPEC[ability_key]
    owner = ABILITY_OWNER[ability_key]

    if ability_key in TEXT_INPUT_ABILITIES:
        async def _cmd(ctx, *, text: str = None):
            await run_ability(ctx, ability_key, None)
    elif ability_key == "nagito_luck_effect":
        async def _cmd(ctx, target: discord.Member = None, *, options: str = None):
            await run_ability(ctx, ability_key, target)
    elif needs_target:
        async def _cmd(ctx, target: discord.Member = None):
            await run_ability(ctx, ability_key, target)
    else:
        async def _cmd(ctx):
            await run_ability(ctx, ability_key, None)

    _cmd.__name__ = f"ability_{ability_key}"
    _cmd.__doc__ = f"({ROLES[owner]['name']}) {disp} — {cat}."
    bot.command(name=key)(_cmd)


for _key in ABILITY_SPEC:
    _make_ability_command(_key)


# ═══════════════════════════════════════════════════════════════════
# MESSAGE ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════
# Enforcement reads ONLY the message author's own record. There is no role
# lookup and no member iteration here, so a person can never be silenced by
# an effect that was aimed at someone else.

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    data = load_data()
    user = get_user(data, message.author.id)
    clear_expired_effects(user)

    # Kaleb Love has a deliberately narrow obtainment route: the exact
    # username may say "kaleb" in a server message. No other username can
    # claim it through this phrase.
    if message.content.strip().casefold() == "kaleb":
        if message.author.name.casefold() == "manoftheswamp":
            if not holder_of(data, "kaleb_love"):
                ok, result = await bind_role(data, message.author, "kaleb_love")
                if ok:
                    await message.channel.send(
                        f"💗 {message.author.mention} obtained **Kaleb Love**."
                    )
                else:
                    await message.channel.send(f"❌ {result}", delete_after=10)
            else:
                await message.channel.send("Kaleb Love is already held.", delete_after=8)
            return

    # The Ultimate Despair's Tragic Event affects the next different speaker
    # in the channel.  The old bot used a Hope/Despair choice; 2.0 expresses
    # the consequence as a temporary ability misfire.
    tragic = data.get("tragic_event")
    if (
        tragic
        and now_ts() < tragic.get("expires", 0)
        and tragic.get("channel_id") == message.channel.id
        and str(message.author.id) != str(tragic.get("by"))
    ):
        data.pop("tragic_event", None)
        apply_effect(data, message.author.id, "misfire", 600, int(tragic["by"]))
        save_data(data)
        await message.channel.send(
            f"💀 {message.author.mention} stepped into the Tragic Event — "
            "their abilities may misfire for 10 minutes."
        )

    # Expansion mechanics (Lord Verity obtainment, compulsions, Burger passives).
    try:
        if await _expansion_hooks(message, data, user):
            return
    except Exception:
        pass
    data = load_data()
    user = get_user(data, message.author.id)
    clear_expired_effects(user)

    # Opt-out ignores roleplay enforcement.
    if user.get("rp_opt_out"):
        user["last_message_ts"] = now_ts()
        save_data(data)
        await bot.process_commands(message)
        return

    # Immunity ignores every enforcement below it.
    if _is_immune(user):
        user["last_message_ts"] = now_ts()
        save_data(data)
        await bot.process_commands(message)
        return

    # Silenced — remove the message. Their own effect entry, nobody else's.
    if has_effect(user, "mute"):
        expires = user["effects"]["mute"]["expires"]
        try:
            await message.delete()
        except Exception:
            pass
        save_data(data)
        try:
            await message.author.send(
                f"🤐 You're silenced for another {remaining_fmt(expires)} — that message was removed."
            )
        except Exception:
            pass
        return

    # Speech Lag — enforce a gap between messages.
    if has_effect(user, "speech_lag"):
        gap = 20
        since = now_ts() - user.get("last_message_ts", 0)
        if since < gap:
            try:
                await message.delete()
            except Exception:
                pass
            save_data(data)
            try:
                await message.author.send(
                    f"🐌 Speech Lag — wait **{gap - since}s** more before your next message."
                )
            except Exception:
                pass
            return

    user["last_message_ts"] = now_ts()
    save_data(data)
    await bot.process_commands(message)


@tasks.loop(minutes=2)
async def effect_janitor():
    """Prune expired effects so the data file never accumulates stale entries."""
    data = load_data()
    touched = False
    for uid, u in data.get("users", {}).items():
        before = len(u.get("effects", {}))
        clear_expired_effects(u)
        if len(u.get("effects", {})) != before:
            touched = True
    # Expire stale role requests too.
    for rk in list(data.get("requests", {})):
        if now_ts() - data["requests"][rk]["opened_at"] >= REQUEST_TTL:
            data["requests"].pop(rk)
            touched = True
    tragic = data.get("tragic_event")
    if tragic and now_ts() >= tragic.get("expires", 0):
        data.pop("tragic_event", None)
        touched = True
    disaster = data.get("despair_disaster")
    if disaster and now_ts() >= disaster.get("expires", 0):
        defended = set(disaster.get("defended", []))
        source_id = int(disaster.get("by", 0) or 0)
        for _role_key, uid in data.get("role_holders", {}).items():
            if str(uid) not in defended and str(uid) != str(source_id):
                apply_effect(data, int(uid), "ability_lock", 600, source_id)
        data.pop("despair_disaster", None)
        touched = True
    if touched:
        save_data(data)
    await expire_due_role_grants()
    await expire_due_mandates()
    await expire_due_shame()


@bot.event
async def on_command(ctx):
    """Keep a durable record of commands issued during a live mandate."""
    if not ctx.guild:
        return
    data = load_data()
    record = active_mandate(data, ctx.guild, ctx.author)
    if record:
        await write_server_log(
            ctx.guild,
            "MANDATE_COMMAND",
            ctx.author.id,
            ctx.message.content,
            str(ctx.author.id),
        )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    mandate_role = discord.utils.get(after.guild.roles, name=MANDATE_ROLE_NAME)
    if mandate_role and mandate_role in before.roles and mandate_role not in after.roles:
        await expire_mandate(after.guild, after.id, "mandate role removed")


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    await write_server_log(channel.guild, "CHANNEL_CREATED", None, f"{channel.name} ({channel.id})")


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    await write_server_log(channel.guild, "CHANNEL_DELETED", None, f"{channel.name} ({channel.id})")


@bot.event
async def on_guild_channel_update(
    before: discord.abc.GuildChannel,
    after: discord.abc.GuildChannel,
):
    await write_server_log(
        after.guild,
        "CHANNEL_UPDATED",
        None,
        f"{before.name} ({before.id}) changed to {after.name} ({after.id}).",
    )


@bot.event
async def on_guild_role_create(role: discord.Role):
    await write_server_log(role.guild, "ROLE_CREATED", None, f"{role.name} ({role.id})")


@bot.event
async def on_guild_role_delete(role: discord.Role):
    await write_server_log(role.guild, "ROLE_DELETED", None, f"{role.name} ({role.id})")
    if role.name == MANDATE_ROLE_NAME:
        data = load_data()
        for recipient_id in list(mandate_records(data, role.guild)):
            await expire_mandate(role.guild, int(recipient_id), "mandate role deleted")


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    await write_server_log(
        after.guild,
        "ROLE_UPDATED",
        None,
        f"{before.name} ({before.id}) changed to {after.name} ({after.id}).",
    )


@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel):
    await write_server_log(channel.guild, "WEBHOOKS_UPDATED", None, f"#{channel.name} ({channel.id})")


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await write_server_log(guild, "MEMBER_BANNED", None, f"{user} ({user.id})")


# ═══════════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════════

@bot.command(name="commands", aliases=["help", "guide"])
async def commands_cmd(ctx):
    """Everything this bot does."""
    e = discord.Embed(
        title="Zetsubo 2.0 — Commands",
        description=(
            "A role-and-abilities bot. **No trials, no HP, no combat, no forms.**\n"
            "Hold a role, use its whole kit immediately."
        ),
        color=discord.Color.blurple(),
    )
    e.add_field(
        name="Roles",
        value=("`!roles [category]` — browse all sin, virtue, myth, hope, despair, and special roles\n"
               "`!role_info <role>` — full moveset\n"
               "`!myrole` (aliases `!panel`, `!abilities`) — your kit + cooldowns + status, "
               "with clickable buttons\n"
               "`!effects [@user]` — what's affecting someone\n"
               "Every ability also works as its own standalone command "
               "(e.g. `!side_of_fries @user`) — you never have to open the panel first, "
               "and targeted abilities let you pick from a real member list instead of "
               "typing a mention."),
        inline=False,
    )
    e.add_field(
        name="Getting a role",
        value=(f"`!request_role <role>` — instant for any sin/virtue, and for most despair "
               f"roles too; other roles are instant below power {APPROVAL_POWER_THRESHOLD}, "
               "otherwise opens an approval vote\n"
               "`!surprise` (alias `!surprise_me`) — request a random role under the same "
               "rules, with a 0.001% chance of the surprise jackpot instead\n"
               "`!approve @user` — back someone's request\n"
               "`!requests` — see open requests\n"
               "`!release_role` — give yours up\n"
               "`!legacy_trial <role>` — *optional* old-style trial route"),
        inline=False,
    )
    e.add_field(
        name="Admin",
        value=("`!setup` — create all roles\n"
               "`!assign_role @user <role>` — grant anything directly\n"
               "`!revoke_role @user` — strip and reopen\n"
               "`!clear_effects @user` — wipe all status effects\n"
               "`!sync_roles` — repair data/Discord mismatches\n"
               "`!mandate_log [@user]` — inspect the server audit log"),
        inline=False,
    )
    e.add_field(
        name="Status effects (these replaced all damage)",
        value="\n".join(f"{v['icon']} **{v['name']}** — {v['desc']}" for v in EFFECTS.values()),
        inline=False,
    )
    e.set_footer(text=f"{len(ROLES)} roles · {len(ABILITY_SPEC)} abilities · one holder per role")
    await ctx.send(embed=e)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 That command is administrator-only.", delete_after=8)
        return
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("Couldn't find that member — @mention them directly.", delete_after=8)
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: `{error.param.name}`. See `!commands`.", delete_after=10)
        return
    raise error


# ═══════════════════════════════════════════════════════════════════
# ░░ EXPANSION ROLES ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# Lord Verity, Burger, and Fart Boy. Added on top of the original 21
# roles, which are untouched.
# ═══════════════════════════════════════════════════════════════════

VERITY_ROLE_KEY = "lord_verity"
BURGER_ROLE_KEY = "burger"
FARTBOY_ROLE_KEY = "fart_boy"

# The elevated stand-in for real Administrator. See MANDATE_NOTE.
MANDATE_ROLE_NAME = "Verity's Mandate"
MANDATE_DURATION = 5 * 60

MANDATE_NOTE = (
    "**Verity's Mandate is not real Discord Administrator.** Administrator bypasses "
    "every permission check in Discord, so it cannot be meaningfully time-limited — "
    "anyone holding it, even briefly, could grant themselves permanent roles, ban, or "
    "delete channels, and no bot could take that back. The Mandate instead grants "
    "elevated *bot-side* authority: message management, effect application, and "
    "temporary role grants that this bot itself reverses when the timer ends. "
    "No banning. No kicking. Nothing permanent."
)


def mandate_permissions() -> discord.Permissions:
    """The mandate is intentionally not Administrator and cannot manage the server."""
    return discord.Permissions(
        manage_messages=True,
        moderate_members=True,
        manage_nicknames=True,
        mute_members=True,
        move_members=True,
    )


async def ensure_mandate_role(
    guild: discord.Guild,
) -> tuple[Optional[discord.Role], Optional[str]]:
    """Create or validate the single limited role used during a mandate."""
    role = discord.utils.get(guild.roles, name=MANDATE_ROLE_NAME)
    if role is None:
        try:
            role = await guild.create_role(
                name=MANDATE_ROLE_NAME,
                color=discord.Color.from_rgb(255, 215, 0),
                hoist=True,
                permissions=mandate_permissions(),
                reason="Zetsubo limited temporary mandate",
            )
        except discord.Forbidden:
            return None, "I need **Manage Roles** to create the limited mandate role."
        except discord.HTTPException as e:
            return None, f"Discord rejected the mandate role: `{e.status}`."

    me = guild.me
    if me is None:
        return None, "I can't read my own member record."
    if role >= me.top_role:
        return None, "The mandate role sits above my bot role; move the bot role higher."
    if role.permissions.administrator:
        return None, (
            "The existing mandate role has Administrator and is unsafe. "
            "Remove it, then run setup again so the bot can recreate it safely."
        )
    return role, None


async def capture_mandate_audit(guild: discord.Guild, record: dict):
    """Mirror the mandate holder's Discord audit-log actions to our permanent log."""
    started = int(record.get("started", now_ts()))
    actor_id = int(record.get("recipient_id", 0))
    try:
        entries = [
            entry async for entry in guild.audit_logs(
                limit=100,
                after=datetime.fromtimestamp(started, tz=timezone.utc),
            )
            if entry.user and entry.user.id == actor_id
        ]
    except (discord.Forbidden, discord.HTTPException):
        await write_server_log(
            guild,
            "MANDATE_AUDIT_UNAVAILABLE",
            actor_id,
            "The bot could not read Discord's audit log. Grant View Audit Log if this server requires it.",
            str(actor_id),
        )
        return

    seen = set(record.setdefault("audit_keys", []))
    for entry in reversed(entries):
        key = str(entry.id)
        if key in seen:
            continue
        seen.add(key)
        target = getattr(entry.target, "id", None)
        await write_server_log(
            guild,
            "MANDATE_DISCORD_ACTION",
            actor_id,
            f"Discord audit action={entry.action.name}; target={target}; reason={entry.reason or 'none'}",
            str(actor_id),
        )
    record["audit_keys"] = list(seen)[-200:]


async def expire_mandate(guild: discord.Guild, recipient_id: int, reason: str):
    """Remove only mandate-owned state; owner/admin members are protected."""
    data = load_data()
    records = mandate_records(data, guild)
    record = records.get(str(recipient_id))
    if not record:
        return
    member = guild.get_member(recipient_id)
    await capture_mandate_audit(guild, record)
    data = load_data()
    records = mandate_records(data, guild)
    record = records.pop(str(recipient_id), None)
    if not record:
        return

    if member and not protected_member(member):
        mandate_role, _ = await ensure_mandate_role(guild)
        if mandate_role and mandate_role in member.roles:
            try:
                await member.remove_roles(mandate_role, reason=f"Mandate ended: {reason}")
            except (discord.Forbidden, discord.HTTPException):
                pass

        for entry in record.get("roles_granted", []):
            if entry.get("removed") or int(entry.get("expires", 0)) > now_ts():
                continue
            role = guild.get_role(int(entry["role_id"]))
            if role is None or entry.get("prior_had"):
                continue
            fresh = guild.get_member(int(entry["member_id"]))
            if fresh and role in fresh.roles and not protected_member(fresh):
                try:
                    await fresh.remove_roles(
                        role,
                        reason="Temporary role from expired mandate",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                await write_server_log(
                    guild,
                    "TEMP_ROLE_REMOVED",
                    recipient_id,
                    f"{role.name} removed from {fresh} because the mandate ended.",
                    str(recipient_id),
                )
    save_data(data)
    await write_server_log(
        guild,
        "MANDATE_EXPIRED",
        recipient_id,
        f"Mandate ended ({reason}); only mandate-owned temporary state was considered for removal.",
        str(recipient_id),
    )


async def expire_due_role_grants():
    """Remove grants at their requested expiry without touching other roles."""
    data = load_data()
    pending_logs = []
    changed = False
    for guild_id, records in data.get("mandates", {}).items():
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        for recipient_id, record in records.items():
            member = guild.get_member(int(recipient_id))
            for entry in record.get("roles_granted", []):
                if entry.get("removed") or now_ts() < int(entry.get("expires", 0)):
                    continue
                entry["removed"] = True
                changed = True
                role = guild.get_role(int(entry["role_id"]))
                if (
                    member
                    and role
                    and not entry.get("prior_had")
                    and role in member.roles
                    and not protected_member(member)
                ):
                    try:
                        await member.remove_roles(role, reason="Temporary role expired")
                    except (discord.Forbidden, discord.HTTPException):
                        entry["removed"] = False
                        continue
                    pending_logs.append((
                        guild,
                        int(recipient_id),
                        role.name,
                        str(recipient_id),
                    ))
    if changed:
        save_data(data)
    for guild, recipient_id, role_name, mandate_id in pending_logs:
        await write_server_log(
            guild,
            "TEMP_ROLE_REMOVED",
            recipient_id,
            f"{role_name} removed when its requested temporary duration ended.",
            mandate_id,
        )


async def expire_due_mandates():
    data = load_data()
    due = []
    for guild_id, records in data.get("mandates", {}).items():
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        for recipient_id, record in records.items():
            if now_ts() >= int(record.get("expires", 0)):
                due.append((guild, int(recipient_id), "timer"))
    for guild, recipient_id, reason in due:
        await expire_mandate(guild, recipient_id, reason)


ROLES.update({
    VERITY_ROLE_KEY: {
        "name": "Lord Verity",
        "kind": "sovereign",
        "power": 15,
        "color": (240, 230, 140),
        "blurb": "Demands recognition. Rules by decree, counter, and sheer contempt.",
        "abilities": [
            ("kneel",            "Kneel",                     "control",  900,  None, 0, True),
            ("stop",             "Stop",                      "control",  600,  None, 0, True),
            ("ow",               "Ow!",                       "counter",  300,  None, 0, False),
            ("brain_eaten",      "Brain Eaten",               "steal",    3600, None, 0, True),
            ("nooo",             "NOOO!",                     "silence",  1200, None, 0, True),
            ("your_last_day",    "YOUR LAST DAY!",            "erase",    5400, None, 0, True),
            ("i_dont_give_a_damn", "I Don't Give A Damn",     "counter",  1800, None, 0, False),
            ("master_of_humanity", "Master Of Humanity",      "control",  1500, None, 0, True),
            ("i_am_the_master",  "I Am The Master Of Humanity", "mandate", 1800, None, 0, False),
            ("you_dont_deserve_your_brain", "You Don't Deserve Your Brain At All", "special", 0, None, 0, False),
        ],
    },
    BURGER_ROLE_KEY: {
        "name": "Burger",
        "kind": "secret",
        "power": 6,
        "color": (210, 140, 60),
        "blurb": "Nobody talks about Burger. Burger talks about supernatural.",
        "abilities": [
            ("side_of_fries",  "I'll Have A Side Of Fries With That", "disrupt", 900,  "speech_lag", 300, True),
            ("self_glaze",     "Self Glaze",                          "cleanse", 1200, None, 0, False),
            ("i_should_leave", "I Should Just Leave",                 "utility", 1800, None, 0, False),
            ("castiel",        "Turn Somebody Into Castiel",          "control", 2700, None, 0, True),
            ("be_yourself",    "Just Be Yourself",                    "support", 1500, None, 0, False),
        ],
    },
    FARTBOY_ROLE_KEY: {
        "name": "Fart Boy",
        "kind": "secret",
        "power": 7,
        "color": (150, 170, 60),
        "blurb": "A one-man atmospheric hazard.",
        "abilities": [
            ("fart",          "Fart",          "silence", 60,   "timeout", 20, True),
            ("rapid_farts",   "Rapid Farts",   "aoe",     900,  None, 0, False),
            ("fart_beatbox",  "Fart Beatbox",  "aoe",     1800, None, 0, False),
            ("fart_nuke",     "Fart Nuke",     "aoe",     3660, None, 0, False),
        ],
    },
})


# Roles retained from the older Zetsubo source.  Their old combat, HP, path,
# corruption, and form systems are intentionally not carried over.  These
# abilities use the same 2.0 status-effect engine as every other role.
def _legacy_effect(kind: str) -> tuple[Optional[str], int, bool]:
    if kind in {"lock", "splash", "strike"}:
        return {
            "lock": ("ability_lock", 600, True),
            "splash": ("speech_lag", 300, True),
            "strike": ("misfire", 300, True),
        }[kind]
    return None, 0, False


def _legacy_ability(
    key: str,
    display: str,
    category: str,
    cooldown_minutes: int,
    kind: str = "utility",
) -> tuple:
    effect, duration, needs_target = _legacy_effect(kind)
    return (
        key,
        display,
        category,
        cooldown_minutes * 60,
        effect,
        duration,
        needs_target,
    )


LEGACY_ROLE_SPECS = {
    "gooner": {
        "name": "The Fox Gooner",
        "kind": "special",
        "power": 1,
        "gate_power": 100,
        "color": (220, 110, 30),
        "blurb": "The Fox Gooner role and its three legacy abilities, without the old image trial.",
        "abilities": [
            _legacy_ability("flash", "Flash", "control", 90, "lock"),
            _legacy_ability("withered_meat", "Withered Meat", "disrupt", 120, "lock"),
            _legacy_ability("diane_foxington", "Diane Foxington", "utility", 180),
        ],
        "obtainment": "Use `!request_role gooner` or the optional `!legacy_trial gooner` route.",
    },
    "fallen_from_grace": {
        "name": "Fallen from Grace",
        "kind": "special",
        "power": 1,
        "gate_power": 100,
        "color": (90, 20, 20),
        "blurb": "A legacy state role. It has no ability kit.",
        "abilities": [],
        "obtainment": "Use `!request_role fallen` or ask an administrator to assign it.",
    },
    "banished": {
        "name": "Banished",
        "kind": "special",
        "power": 1,
        "gate_power": 100,
        "color": (40, 40, 40),
        "blurb": "A legacy state role. It has no ability kit.",
        "abilities": [],
        "obtainment": "Use `!request_role banished` or ask an administrator to assign it.",
    },
    "femboy": {
        "name": "i SWEAR im not DL bro and i put that on my kids!",
        "kind": "special",
        "power": 2,
        "gate_power": 100,
        "color": (255, 125, 190),
        "blurb": "The legacy opt-in role and its named abilities, using 2.0 effects.",
        "abilities": [
            _legacy_ability("radioactive_substance", "Radioactive Substance", "disrupt", 180, "lock"),
            _legacy_ability("femboy_suggestion", "Femboy Suggestion", "control", 120, "splash"),
            _legacy_ability("femboy_reject", "Femboy Reject", "utility", 0),
            _legacy_ability("pray_testosterone", "Pray Testosterone", "support", 5),
            _legacy_ability("it_was_a_bet_bro", "It Was A Bet Bro", "control", 120, "misfire"),
        ],
        "obtainment": "Use `!request_role femboy` or the optional `!legacy_trial femboy` route.",
    },
    "ultimate_despair": {
        "name": "The Ultimate Despair",
        "kind": "despair",
        "power": 15,
        "color": (80, 0, 0),
        "blurb": "The legacy Ultimate Despair kit, rewritten to use status effects instead of combat damage.",
        "abilities": [
            _legacy_ability("tragic_event", "Tragic Event", "disrupt", 240),
            _legacy_ability("brainwash", "Brainwash", "control", 30, "lock"),
            _legacy_ability("disaster", "Disaster", "disrupt", 240),
            _legacy_ability("summon_sister", "Summon Despair Sister", "utility", 120),
            _legacy_ability("summon_reserve", "Summon Reserve Course", "utility", 240),
            _legacy_ability("brainwash_remnant", "Brainwash Remnant", "control", 30, "lock"),
        ],
        "obtainment": "Use `!request_role ultimate despair` or the optional `!legacy_trial ultimate despair` route.",
    },
    "remnant_of_despair": {
        "name": "Remnant of Despair",
        "kind": "despair",
        "power": 7,
        "color": (60, 0, 0),
        "blurb": "A legacy despair role with its original pressure ability, without the old combat system.",
        "abilities": [
            _legacy_ability("despair_wave", "Despair Wave", "disrupt", 60, "splash"),
        ],
        "obtainment": "Use `!request_role remnant` or the optional `!legacy_trial remnant` route.",
    },
    "reserve_course_student": {
        "name": "Reserve Course Student",
        "kind": "despair",
        "power": 2,
        "color": (100, 100, 100),
        "blurb": "The legacy Reserve Course role.",
        "abilities": [
            _legacy_ability("student_attack", "Student Attack", "disrupt", 30, "strike"),
        ],
        "obtainment": "Use `!request_role reserve course` or the optional `!legacy_trial reserve course` route.",
    },
    "despair_sister": {
        "name": "Despair Sister",
        "kind": "despair",
        "power": 8,
        "color": (120, 0, 60),
        "blurb": "A legacy summoned role with its named abilities.",
        "abilities": [
            _legacy_ability("sister_kill", "Sister Strike", "disrupt", 30, "strike"),
            _legacy_ability("sister_say", "Sister Say", "utility", 5),
            _legacy_ability("sister_seduce", "Sister Seduce", "control", 60, "splash"),
            _legacy_ability("sister_anything", "Sister Anything", "utility", 30),
        ],
        "obtainment": "Use `!request_role despair sister` or the optional `!legacy_trial despair sister` route.",
    },
    "izuru_despair": {
        "name": "Izuru Kamakura: Remnant of Despair",
        "kind": "despair",
        "power": 15,
        "color": (80, 0, 0),
        "blurb": "Izuru weaponizes perfect prediction and overwhelming talent through 2.0 effects.",
        "abilities": [
            _legacy_ability("izuru_despair_forecast", "Unerring Forecast", "disrupt", 35, "strike"),
            _legacy_ability("izuru_despair_overwhelm", "Overwhelming Talent", "disrupt", 45, "lock"),
            _legacy_ability("izuru_despair_cataclysm", "Talent Cataclysm", "disrupt", 60, "splash"),
        ],
        "obtainment": "Use `!request_role izuru_despair` or the optional `!legacy_trial izuru_despair` route.",
    },
    "izuru_hope": {
        "name": "Izuru Kamakura: Ultimate Hope",
        "kind": "hope",
        "power": 15,
        "color": (0, 180, 220),
        "blurb": "Izuru turns an impossible range of talents into precise, 2.0 effect-based attacks.",
        "abilities": [
            _legacy_ability("izuru_hope_perfect_read", "Perfect Read", "disrupt", 30, "strike"),
            _legacy_ability("izuru_hope_talent_storm", "Talent Storm", "disrupt", 45, "lock"),
            _legacy_ability("izuru_hope_miracle", "Miracle Trajectory", "disrupt", 55, "splash"),
        ],
        "obtainment": "Use `!request_role izuru_hope` or the optional `!legacy_trial izuru_hope` route.",
    },
    "kaleb_love": {
        "name": "Kaleb Love",
        "kind": "special",
        "power": 1,
        "gate_power": 100,
        "color": (255, 120, 180),
        "blurb": "A role reserved for the named account.",
        "abilities": [],
        "obtainment": "Say `kaleb` with `!request_role kaleb` or `!legacy_trial kaleb`; only username `manoftheswamp` is eligible.",
    },
}


_CHARACTER_ROLE_NAMES = {
    "nagito": ("Nagito Komaeda: Ultimate Lucky Student", "Nagito Komaeda: Remnant of Despair"),
    "akane": ("Akane Owari: Ultimate Gymnast", "Akane Owari: Remnant of Despair"),
    "sonia": ("Sonia Nevermind: Ultimate Princess", "Sonia Nevermind: Remnant of Despair"),
    "fuyuhiko": ("Fuyuhiko Kuzuryu: Ultimate Yakuza", "Fuyuhiko Kuzuryu: Remnant of Despair"),
    "kazuichi": ("Kazuichi Soda: Ultimate Mechanic", "Kazuichi Soda: Remnant of Despair"),
    "hiyoko": ("Hiyoko Saionji: Ultimate Traditional Dancer", "Hiyoko Saionji: Remnant of Despair"),
    "mikan": ("Mikan Tsumiki: Ultimate Nurse", "Mikan Tsumiki: Remnant of Despair"),
    "ibuki": ("Ibuki Mioda: Ultimate Musician", "Ibuki Mioda: Remnant of Despair"),
    "mahiru": ("Mahiru Koizumi: Ultimate Photographer", "Mahiru Koizumi: Remnant of Despair"),
    "nekomaru": ("Nekomaru Nidai: Ultimate Team Manager", "Nekomaru Nidai: Remnant of Despair"),
    "gundham": ("Gundham Tanaka: Ultimate Breeder", "Gundham Tanaka: Remnant of Despair"),
    "teruteru": ("Teruteru Hanamura: Ultimate Cook", "Teruteru Hanamura: Remnant of Despair"),
    "peko": ("Peko Pekoyama: Ultimate Swordswoman", "Peko Pekoyama: Remnant of Despair"),
    "chiaki": ("Chiaki Nanami: Ultimate Gamer", None),
}


_CHARACTER_ROLE_DATA = {
    "nagito": ("Hope's Lucky Break", 18, "Despair's High-Stakes Luck", 24, [
        ("probability_shift", "Contingency of Hope", 14, "utility"),
        ("hope_sacrifice", "Hope's Sacrifice", 20, "support"),
    ], [
        ("malice_cascade", "Malice Cascade", 18, "splash"),
        ("despair_gambit", "Despair's Gambit", 26, "lock"),
    ]),
    "akane": ("Aerial Recovery", 20, "Savage Gymnastics", 25, [
        ("acrobatic_rescue", "Acrobatic Rescue", 18, "support"),
        ("limit_break", "Limit Break", 24, "strike"),
    ], [
        ("predators_vault", "Predator's Vault", 23, "strike"),
        ("pain_ignored", "Pain Ignored", 20, "lock"),
    ]),
    "sonia": ("Royal Decree", 16, "Novoselic in Ruin", 22, [
        ("foreign_insight", "Foreign Insight", 16, "cleanse"),
        ("royal_command", "Royal Command", 18, "support"),
    ], [
        ("despair_broadcast", "Despair Broadcast", 19, "splash"),
        ("royal_ultimatum", "Royal Ultimatum", 24, "lock"),
    ]),
    "fuyuhiko": ("Kuzuryu Protection", 20, "Family Order", 24, [
        ("underboss_intimidation", "Underboss Intimidation", 18, "lock"),
        ("protective_oath", "Protective Oath", 20, "support"),
    ], [
        ("underworld_order", "Underworld Order", 22, "lock"),
        ("blood_debt", "Blood Debt", 26, "strike"),
    ]),
    "kazuichi": ("Field Repair", 28, "Monokuma Override", 23, [
        ("jury_rig", "Jury-Rig", 24, "support"),
        ("emergency_tool", "Emergency Tool", 16, "cleanse"),
    ], [
        ("monokuma_hack", "Monokuma Hack", 23, "lock"),
        ("scrap_bomb", "Scrap Bomb", 20, "splash"),
    ]),
    "hiyoko": ("Hopeful Hanamichi", 17, "Despair Dance", 21, [
        ("hanamichi_step", "Hanamichi Step", 15, "support"),
        ("verbal_cut", "Verbal Cut", 17, "lock"),
    ], [
        ("brainwash_dance", "Brainwash Dance", 20, "splash"),
        ("cruel_stage", "Cruel Stage", 22, "lock"),
    ]),
    "mikan": ("Emergency Care", 35, "Despair Triage", 27, [
        ("triage", "Triage", 30, "support"),
        ("sterile_field", "Sterile Field", 18, "support"),
    ], [
        ("painful_diagnosis", "Painful Diagnosis", 25, "strike"),
        ("infection_protocol", "Infection Protocol", 21, "lock"),
    ]),
    "ibuki": ("Hope Amp", 18, "Despair Feedback", 23, [
        ("guitar_riff", "Guitar Riff", 18, "support"),
        ("encore", "Encore", 16, "support"),
    ], [
        ("sonic_panic", "Sonic Panic", 21, "splash"),
        ("corrupt_broadcast", "Corrupt Broadcast", 23, "lock"),
    ]),
    "mahiru": ("Truth in Focus", 18, "Despair Exposure", 22, [
        ("document_truth", "Document the Truth", 16, "cleanse"),
        ("camera_ready", "Camera Ready", 18, "support"),
    ], [
        ("propaganda_shot", "Propaganda Shot", 19, "splash"),
        ("exposure", "Exposure", 22, "lock"),
    ]),
    "nekomaru": ("Team Huddle", 22, "Remnant War Cry", 26, [
        ("coach_up", "Coach Up", 22, "support"),
        ("emergency_drill", "Emergency Drill", 20, "support"),
    ], [
        ("war_manager", "War Manager", 24, "support"),
        ("overdrive", "Overdrive", 27, "lock"),
    ]),
    "gundham": ("Four Dark Devas", 20, "Army of Beasts", 25, [
        ("familiar_guard", "Familiar Guard", 20, "support"),
        ("beast_command", "Beast Command", 19, "strike"),
    ], [
        ("dark_devas_attack", "Dark Devas Attack", 24, "strike"),
        ("beast_swarm", "Beast Swarm", 21, "splash"),
    ]),
    "teruteru": ("Restorative Cuisine", 27, "Monokuma Menu", 22, [
        ("meal_prep", "Meal Prep", 26, "support"),
        ("spice_mix", "Spice Mix", 18, "support"),
    ], [
        ("monokuma_banquet", "Monokuma Banquet", 21, "splash"),
        ("kitchen_ambush", "Kitchen Ambush", 25, "strike"),
    ]),
    "peko": ("Bodyguard's Edge", 24, "Executioner's Edge", 29, [
        ("guard_stance", "Guard Stance", 22, "support"),
        ("iaijutsu", "Iaijutsu", 26, "strike"),
    ], [
        ("execution_order", "Execution Order", 28, "strike"),
        ("bloodblade", "Bloodblade", 24, "lock"),
    ]),
    "chiaki": ("", 0, "", 0, [], []),
}

# Hope-side character abilities are attacks in 2.0, not legacy heals or buffs.
# The second effect gives each converted support move a distinctive hit.
_HOPE_SIGNATURE_EFFECTS = {
    "nagito": ("cooldown_tax", 900, ("misfire", 300)),
    "akane": ("misfire", 600, ("speech_lag", 180)),
    "sonia": ("ability_lock", 300, ("cooldown_tax", 600)),
    "fuyuhiko": ("ability_lock", 300, ("misfire", 300)),
    "kazuichi": ("cooldown_tax", 600, ("speech_lag", 180)),
    "hiyoko": ("speech_lag", 300, ("misfire", 180)),
    "mikan": ("misfire", 300, ("ability_lock", 180)),
    "ibuki": ("speech_lag", 300, ("cooldown_tax", 300)),
    "mahiru": ("cooldown_tax", 300, ("speech_lag", 180)),
    "nekomaru": ("ability_lock", 300, ("misfire", 300)),
    "gundham": ("misfire", 300, ("cooldown_tax", 300)),
    "teruteru": ("speech_lag", 300, ("misfire", 180)),
    "peko": ("ability_lock", 300, ("cooldown_tax", 300)),
}

_HOPE_KIT_EFFECTS = {
    "probability_shift": ("misfire", 300, ("cooldown_tax", 300)),
    "hope_sacrifice": ("cooldown_tax", 900, ("speech_lag", 180)),
    "acrobatic_rescue": ("speech_lag", 180, ("misfire", 300)),
    "limit_break": ("misfire", 300, ("cooldown_tax", 300)),
    "foreign_insight": ("ability_lock", 180, ("misfire", 180)),
    "royal_command": ("cooldown_tax", 600, ("speech_lag", 180)),
    "underboss_intimidation": ("ability_lock", 600, ("cooldown_tax", 300)),
    "protective_oath": ("misfire", 300, ("speech_lag", 180)),
    "jury_rig": ("cooldown_tax", 600, ("misfire", 180)),
    "emergency_tool": ("ability_lock", 180, ("speech_lag", 180)),
    "hanamichi_step": ("speech_lag", 300, ("cooldown_tax", 180)),
    "verbal_cut": ("ability_lock", 300, ("misfire", 180)),
    "triage": ("misfire", 300, ("cooldown_tax", 300)),
    "sterile_field": ("ability_lock", 180, ("misfire", 180)),
    "guitar_riff": ("speech_lag", 300, ("misfire", 180)),
    "encore": ("cooldown_tax", 300, ("ability_lock", 180)),
    "document_truth": ("ability_lock", 180, ("cooldown_tax", 180)),
    "camera_ready": ("misfire", 300, ("speech_lag", 180)),
    "coach_up": ("cooldown_tax", 600, ("ability_lock", 180)),
    "emergency_drill": ("misfire", 300, ("cooldown_tax", 300)),
    "familiar_guard": ("ability_lock", 180, ("speech_lag", 180)),
    "beast_command": ("misfire", 300, ("cooldown_tax", 300)),
    "meal_prep": ("speech_lag", 300, ("misfire", 180)),
    "spice_mix": ("cooldown_tax", 300, ("ability_lock", 180)),
    "guard_stance": ("ability_lock", 180, ("cooldown_tax", 300)),
    "iaijutsu": ("misfire", 300, ("ability_lock", 180)),
}

HOPE_ATTACK_BONUSES = {}


for _key, _spec in LEGACY_ROLE_SPECS.items():
    ROLES[_key] = _spec

for _char_key, (_hope_name, _despair_name) in _CHARACTER_ROLE_NAMES.items():
    _hope_sig, _hope_cd, _despair_sig, _despair_cd, _hope_kit, _despair_kit = _CHARACTER_ROLE_DATA[_char_key]

    def _build_character_abilities(prefix, signature, signature_cd, kit, is_despair):
        abilities = []
        if signature:
            if is_despair:
                abilities.append(_legacy_ability(
                    f"{prefix}_signature", signature, "disrupt", signature_cd, "lock"
                ))
            else:
                effect, duration, bonus = _HOPE_SIGNATURE_EFFECTS[_char_key]
                ability_key = f"{prefix}_signature"
                abilities.append((
                    ability_key, signature, "disrupt", signature_cd * 60,
                    effect, duration, True,
                ))
                HOPE_ATTACK_BONUSES[ability_key] = (bonus,)
        for ability_key, display, cooldown, effect_kind in kit:
            full_key = f"{prefix}_{ability_key}"
            if not is_despair and ability_key in _HOPE_KIT_EFFECTS:
                effect, duration, bonus = _HOPE_KIT_EFFECTS[ability_key]
                abilities.append((
                    full_key, display, "disrupt", cooldown * 60,
                    effect, duration, True,
                ))
                HOPE_ATTACK_BONUSES[full_key] = (bonus,)
            else:
                abilities.append(_legacy_ability(
                    full_key,
                    display,
                    "disrupt" if effect_kind in {"lock", "strike", "splash"} else "support",
                    cooldown,
                    effect_kind,
                ))
        return abilities

    ROLES[f"{_char_key}_hope"] = {
        "name": _hope_name,
        "kind": "hope",
        "power": 8,
        "color": (0, 180, 220),
        "blurb": f"{_hope_name}, with Hope-side moves rewritten as effect-based attacks for 2.0.",
        "abilities": _build_character_abilities(
            f"{_char_key}_hope", _hope_sig, _hope_cd, _hope_kit, False
        ),
        "obtainment": f"Use `!request_role {_char_key}_hope` or the optional `!legacy_trial {_char_key}_hope` route.",
    }
    if _despair_name:
        ROLES[f"{_char_key}_despair"] = {
            "name": _despair_name,
            "kind": "despair",
            "power": 9,
            "color": (80, 0, 0),
            "blurb": f"{_despair_name}, with Despair-side moves using the 2.0 effect engine.",
            "abilities": _build_character_abilities(
                f"{_char_key}_despair", _despair_sig, _despair_cd, _despair_kit, True
            ),
            "obtainment": (
                f"Use `!request_role {_char_key} despair` or the optional "
                f"`!legacy_trial {_char_key}_despair` route."
            ),
        }

for _nagito_role in ("nagito_hope", "nagito_despair"):
    ROLES[_nagito_role]["abilities"].extend([
        ("nagito_luck_switch", "My Luck Is So Bad", "utility", 0, None, 0, False),
        ("nagito_luck_effect", "Luck Turns Against You", "disrupt", 1800, "misfire", 300, True),
    ])

HOPE_ATTACK_BONUSES.update({
    "rally": (("ability_lock", 300),),
    "beacon": (("cooldown_tax", 600),),
    "izuru_hope_perfect_read": (("cooldown_tax", 600),),
    "izuru_hope_talent_storm": (("misfire", 300),),
    "izuru_hope_miracle": (("ability_lock", 300),),
    "izuru_despair_forecast": (("cooldown_tax", 600),),
    "izuru_despair_overwhelm": (("misfire", 300),),
    "izuru_despair_cataclysm": (("ability_lock", 300),),
})

ROLES["kaleb_love"]["abilities"] = [
    ("kaleb_obsess", "Obsess", "silence", 900, None, 0, True),
    ("kaleb_pawn", "Pawn", "control", 1200, None, 0, True),
    ("kaleb_copy", "Copy", "steal", 1800, None, 0, True),
    ("kaleb_grant_role", "Grant Role", "utility", 1500, None, 0, True),
]
ROLES["kaleb_love"]["blurb"] = (
    "Obsess silences and slows. Pawn locks abilities and can be ordered, kissed, or turned into Filthy Dog. "
    "Copy borrows a kit. Grant Role lends a non-admin role for five minutes."
)


GPG_ROLE_KEY = "green_purple_girl"
SHAME_ROLE_NAME = "SHAME"
SHAME_DURATION = 20 * 60
DEGRADING_WORDS = (
    "you loser", "loser", "dork", "ew", "cringe", "pathetic",
    "gross", "weird", "stupid", "dumb", "nerd", "freak", "lame",
)

ROLES[GPG_ROLE_KEY] = {
    "name": "Green Purple Girl",
    "kind": "special",
    "power": 4,
    "color": (120, 200, 90),
    "blurb": "Green mutes, purple marks, grey-blue filters speech, record opens shame, milk carton makes replies pass out.",
    "abilities": [
        ("green", "Green", "silence", 900, None, 0, True),
        ("purple", "Purple", "control", 1200, None, 0, True),
        ("grey_blue", "Grey-Blue", "control", 1500, None, 0, True),
        ("record", "Record", "control", 1800, None, 0, True),
        ("milk_carton", "Milk Carton", "control", 1500, None, 0, True),
        ("echo", "Echo", "counter", 600, None, 0, False),
    ],
    "obtainment": "Open tier — `!request_role green purple girl` grants it immediately if free.",
}

EFFECTS["stinky"] = {
    "name": "Stinky",
    "icon": "🥛",
    "desc": "Anyone who replies to you passes out for about a minute.",
}


SECRET_ROLES.update({BURGER_ROLE_KEY, FARTBOY_ROLE_KEY})

# Rebuild the lookup tables now that new roles exist.
for _rk, _rv in ROLES.items():
    for _ab in _rv["abilities"]:
        ABILITY_OWNER[_ab[0]] = _rk
        ABILITY_SPEC[_ab[0]] = _ab

for _ability_key in ABILITY_SPEC:
    if bot.get_command(_ability_key) is None:
        _make_ability_command(_ability_key)


def _c(ctx, role_key):
    return discord.Color.from_rgb(*ROLES[role_key]["color"])


# ═══════════════════════════════════════════════════════════════════
# LORD VERITY — obtainment
# ═══════════════════════════════════════════════════════════════════
# No command needed to ASK. Saying "call me lord verity" while @mentioning
# someone opens the request automatically. A command IS needed to accept,
# so nobody is enrolled by accident.

VERITY_TRIGGERS = (
    "call me lord verity",
    "call me lord verity!",
    "would you call me lord verity",
    "can you call me lord verity",
)


async def _handle_verity_request(message: discord.Message, data: dict) -> bool:
    low = message.content.lower()
    if not any(t in low for t in VERITY_TRIGGERS):
        return False
    if not message.mentions:
        return False
    asker = message.author
    witness = next((m for m in message.mentions if m.id != asker.id and not m.bot), None)
    if witness is None:
        return False
    if holder_of(data, VERITY_ROLE_KEY):
        await message.channel.send(
            f"👑 **Lord Verity** already has a bearer. There can be only one.",
            delete_after=12)
        return True
    data.setdefault("verity_requests", {})[str(witness.id)] = {
        "asker_id": str(asker.id),
        "opened_at": now_ts(),
    }
    save_data(data)
    await message.channel.send(embed=discord.Embed(
        title="👑 A Title Is Demanded",
        description=(
            f"{asker.mention} asks {witness.mention} to call them **Lord Verity**.\n\n"
            f"{witness.mention} — run `!accept_verity` to grant it, or ignore this "
            "and it lapses in an hour."
        ),
        color=discord.Color.from_rgb(240, 230, 140),
    ))
    return True


@bot.command(name="accept_verity")
async def accept_verity(ctx):
    """Confirm that you're calling someone Lord Verity. Only you can do this."""
    data = load_data()
    req = data.get("verity_requests", {}).get(str(ctx.author.id))
    if not req or now_ts() - req["opened_at"] > 3600:
        await ctx.send("Nobody has asked you to call them Lord Verity.", delete_after=8)
        save_data(data); return
    asker = ctx.guild.get_member(int(req["asker_id"]))
    if asker is None:
        data["verity_requests"].pop(str(ctx.author.id), None)
        save_data(data)
        await ctx.send("That person is no longer in the server.", delete_after=8)
        return
    if holder_of(data, VERITY_ROLE_KEY):
        await ctx.send("**Lord Verity** already has a bearer.", delete_after=8)
        save_data(data); return

    ok, msg = await bind_role(data, asker, VERITY_ROLE_KEY)
    data.get("verity_requests", {}).pop(str(ctx.author.id), None)
    save_data(data)
    if ok:
        await ctx.send(embed=discord.Embed(
            title="👑 Lord Verity",
            description=(f"{ctx.author.mention} kneels. {asker.mention} is now **Lord Verity**.\n{msg}\n\n"
                         "`!myrole` for the full decree."),
            color=discord.Color.from_rgb(240, 230, 140),
        ))
    else:
        await ctx.send(f"❌ {msg}")


# ═══════════════════════════════════════════════════════════════════
# LORD VERITY — ability handlers
# ═══════════════════════════════════════════════════════════════════

async def _ab_kneel(ctx, data, user, spec, target):
    """Force the target to address Verity as the master of humanity."""
    t = get_user(data, target.id)
    t["compelled_phrase"] = {
        "phrase": "master of humanity",
        "expires": now_ts() + 300,
        "by": str(ctx.author.id),
        "punish": "mute",
        "punish_secs": 30,
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="👑 Kneel",
        description=(
            f"{target.mention} is compelled. Their **next message** must contain "
            f"**\"master of humanity\"**.\n\n"
            "Fail, and they are silenced for 30 seconds. They have 5 minutes."
        ),
        color=_c(ctx, VERITY_ROLE_KEY),
    ))


async def _ab_stop(ctx, data, user, spec, target):
    """10 seconds of silence, or type backwards."""
    t = get_user(data, target.id)
    t["stop_order"] = {
        "silent_until": now_ts() + 10,
        "backwards_until": now_ts() + 120,
        "by": str(ctx.author.id),
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="✋ Stop",
        description=(
            f"{target.mention} — **stop talking for 10 seconds.**\n\n"
            "Speak before then and you must type **backwards** for the next 2 minutes. "
            "The bot will delete anything that isn't."
        ),
        color=_c(ctx, VERITY_ROLE_KEY),
    ))


async def _ab_ow(ctx, data, user, spec, target):
    """Arms a counter — the next hostile effect is reflected back."""
    user["counter_armed"] = {"expires": now_ts() + 300, "kind": "ow"}
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="😤 Ow!",
        description=(
            f"{ctx.author.mention} is braced. The **next hostile effect** aimed at them "
            "within 5 minutes is reflected straight back at the caster."
        ),
        color=_c(ctx, VERITY_ROLE_KEY),
    ))


async def _ab_brain_eaten(ctx, data, user, spec, target):
    """Consume a target's role kit and wield it."""
    t = get_user(data, target.id)
    t_role = t.get("role_key")
    if not t_role:
        await ctx.send(f"{target.mention} holds no role — there's nothing in there.", delete_after=10)
        return
    user["devoured_kit"] = {
        "role_key": t_role,
        "expires": now_ts() + 1800,
        "victim": str(target.id),
    }
    t["effects"]["ability_lock"] = {"expires": now_ts() + 600, "source": str(ctx.author.id)}
    save_data(data)
    kit = ", ".join(f"`!{a[0]}`" for a in ROLES[t_role]["abilities"])
    await ctx.send(embed=discord.Embed(
        title="🧠 Brain Eaten",
        description=(
            f"{ctx.author.mention} consumes {target.mention}'s mind.\n\n"
            f"For **30 minutes** Verity may use the full **{role_display(t_role)}** kit:\n{kit}\n\n"
            f"{target.mention} is ability-locked for 10 minutes."
        ),
        color=_c(ctx, VERITY_ROLE_KEY),
    ))


async def _ab_nooo(ctx, data, user, spec, target):
    """Duration scales with the number of O's typed. Deliberately undocumented."""
    raw = ctx.message.content.lower()
    os_count = 0
    idx = raw.find("no")
    if idx != -1:
        for ch in raw[idx + 1:]:
            if ch == "o":
                os_count += 1
            else:
                break
    # 2 O's -> 15s, scaling to 60s at 10+ O's.
    os_count = max(2, min(10, os_count))
    secs = int(15 + (os_count - 2) * (45 / 8))

    apply_effect(data, target.id, "mute", secs, ctx.author.id)
    save_data(data)
    voice_note = ""
    if target.voice:
        try:
            await target.edit(mute=True, reason=f"!nooo by {ctx.author}")
            voice_note = " They are muted in voice as well."

            async def _unmute_voice():
                await asyncio.sleep(secs)
                try:
                    await target.edit(mute=False, reason="NOOO! expired")
                except Exception:
                    pass
            asyncio.create_task(_unmute_voice())
        except Exception:
            pass

    # The scaling rule is intentionally not revealed here.
    await ctx.send(embed=discord.Embed(
        title="🗣️ NOOO!",
        description=f"{target.mention} is cut off.{voice_note}",
        color=_c(ctx, VERITY_ROLE_KEY),
    ))


async def _ab_your_last_day(ctx, data, user, spec, target):
    """Erase the target's recent history and their near future."""
    uses = user.setdefault("last_day_uses", 0) + 1
    user["last_day_uses"] = uses
    future_mins = max(1, min(5, uses))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=10)
    deleted = 0
    status = await ctx.send("💀 *Erasing...*")
    for channel in ctx.guild.text_channels:
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.read_message_history and perms.manage_messages):
            continue
        try:
            # Bounded scan: Discord rate limits make a true 10h sweep of a busy
            # server impractical, so each channel is capped.
            async for msg in channel.history(limit=400, after=cutoff):
                if msg.author.id == target.id:
                    try:
                        await msg.delete()
                        deleted += 1
                    except Exception:
                        pass
        except Exception:
            continue

    apply_effect(data, target.id, "mute", future_mins * 60, ctx.author.id)
    save_data(data)
    await status.edit(content=None, embed=discord.Embed(
        title="💀 YOUR LAST DAY!",
        description=(
            f"{target.mention} has been **deleted**.\n\n"
            f"• **{deleted}** messages from the last 10 hours erased\n"
            f"• Everything they say for the next **{future_mins} minute(s)** is erased on sight\n\n"
            "*Their role is untouched. They simply leave no trace.*"
        ),
        color=discord.Color.dark_red(),
    ))


async def _ab_i_dont_give_a_damn(ctx, data, user, spec, target):
    """Blanket immunity, including to AoE. Can be extended to others."""
    user["immunity"] = {"expires": now_ts() + 600, "aoe_exempt": True}
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="😐 I Don't Give A Damn",
        description=(
            f"{ctx.author.mention} is **immune to every effect** for 10 minutes — "
            "including channel-wide and AoE effects. If a room gets frozen, they are "
            "the one who still talks.\n\n"
            "Extend it with `!spare @user`, or `!spare everyone`."
        ),
        color=_c(ctx, VERITY_ROLE_KEY),
    ))


async def _ab_master_of_humanity(ctx, data, user, spec, target):
    """Private compulsion — only the target learns what they must say."""
    try:
        await ctx.message.delete()
    except Exception:
        pass
    parts = ctx.message.content.split(None, 2)
    phrase = parts[2].strip() if len(parts) > 2 else "Lord Verity is the master of humanity"

    t = get_user(data, target.id)
    t["compelled_phrase"] = {
        "phrase": phrase.lower(),
        "expires": now_ts() + 300,
        "by": str(ctx.author.id),
        "punish": "mute",
        "punish_secs": 30,
    }
    save_data(data)
    try:
        await target.send(
            f"👁️ **A voice only you can hear.**\n\n"
            f"Say this, exactly, in the server within 5 minutes:\n\n> {phrase}\n\n"
            "Refuse, and you will be silenced for 30 seconds. "
            "Nobody else has been told this."
        )
        await ctx.send("👁️ *Something passes between two people. The message is already gone.*",
                       delete_after=8)
    except discord.Forbidden:
        await ctx.send(
            f"👁️ {target.mention} — check your DMs. (Couldn't reach you; open DMs from server members.)",
            delete_after=10)


async def _ab_i_am_the_master(ctx, data, user, spec, target):
    """Grant a time-boxed, non-Administrator mandate."""
    recipient = target or ctx.author
    guild = ctx.guild
    if protected_member(recipient):
        await ctx.send(
            "🚫 The server owner and existing Discord administrators are protected; "
            "the temporary mandate is not applied to them.",
            delete_after=12,
        )
        return
    role, error = await ensure_mandate_role(guild)
    if error or role is None:
        await ctx.send(f"❌ {error or 'The mandate role is unavailable.'}", delete_after=12)
        return
    existing = active_mandate(data, guild, recipient)
    if existing:
        await ctx.send(
            f"{recipient.mention} already has an active mandate for "
            f"{remaining_fmt(existing['expires'])}.",
            delete_after=10,
        )
        return
    try:
        await recipient.add_roles(role, reason=f"Verity mandate by {ctx.author}")
    except (discord.Forbidden, discord.HTTPException) as e:
        await ctx.send(f"❌ Could not grant the mandate: `{type(e).__name__}`.", delete_after=10)
        return

    record = {
        "recipient_id": str(recipient.id),
        "started": now_ts(),
        "expires": now_ts() + MANDATE_DURATION,
        "granted_by": str(ctx.author.id),
        "roles_granted": [],
        "audit_keys": [],
    }
    mandate_records(data, guild)[str(recipient.id)] = record
    save_data(data)
    await write_server_log(
        guild,
        "MANDATE_STARTED",
        ctx.author.id,
        f"{recipient} received {MANDATE_ROLE_NAME} until <t:{record['expires']}:F>.",
        str(recipient.id),
    )

    await ctx.send(embed=discord.Embed(
        title="👑 I AM THE MASTER OF HUMANITY",
        description=(
            f"{recipient.mention} holds **{MANDATE_ROLE_NAME}** for **5 minutes**.\n\n"
            "**Granted:** manage messages, timeout members, manage nicknames, "
            "voice mute/move.\n"
            "**Withheld:** ban, kick, manage server, manage roles, manage channels.\n\n"
            "`!grant_temp_role @user <seconds> <role>` is the only role-grant route. "
            "Each role it adds is tracked and removed when the mandate ends. "
            "Existing roles and owner/admin members are not touched.\n\n"
            f"*{MANDATE_NOTE}*"
        ),
        color=discord.Color.gold(),
    ))

    async def _revoke():
        await asyncio.sleep(MANDATE_DURATION)
        await expire_mandate(guild, recipient.id, "timer")
        try:
            await ctx.channel.send(
                f"⌛ {recipient.mention}'s Mandate has ended. "
                "Only mandate-owned temporary state was reversed."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    asyncio.create_task(_revoke())


async def _ab_you_dont_deserve_your_brain(ctx, data, user, spec, target):
    """Does nothing except resign the role. Exactly as specified."""
    await sync_remove(ctx.author, VERITY_ROLE_KEY)
    data["role_holders"].pop(VERITY_ROLE_KEY, None)
    user["role_key"] = None
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🚶 You Don't Deserve Your Brain At All",
        description=(
            f"{ctx.author.mention} looks around the server, considers the company, "
            "and walks away.\n\n"
            "**Lord Verity is vacant.** Somebody will have to ask again."
        ),
        color=discord.Color.dark_grey(),
    ))


@bot.command(name="spare")
async def spare(ctx, *, who: str = None):
    """(Lord Verity) Extend 'I Don't Give A Damn' immunity to someone, or everyone."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("role_key") != VERITY_ROLE_KEY:
        await ctx.send("Only Lord Verity may spare anyone.", delete_after=8)
        save_data(data); return
    if not user.get("immunity") or now_ts() >= user["immunity"].get("expires", 0):
        await ctx.send("Use `!i_dont_give_a_damn` first.", delete_after=8)
        save_data(data); return

    until = user["immunity"]["expires"]
    if who and who.lower() in ("everyone", "all", "@everyone"):
        for m in ctx.guild.members:
            if not m.bot:
                get_user(data, m.id)["immunity"] = {"expires": until, "aoe_exempt": True}
        save_data(data)
        await ctx.send("😐 **Nobody** gives a damn. Everyone is immune until Verity's window closes.")
        return

    if not ctx.message.mentions:
        await ctx.send("`!spare @user` or `!spare everyone`.", delete_after=8)
        save_data(data); return
    for m in ctx.message.mentions:
        get_user(data, m.id)["immunity"] = {"expires": until, "aoe_exempt": True}
    save_data(data)
    names = ", ".join(m.mention for m in ctx.message.mentions)
    await ctx.send(f"😐 {names} — spared. Immune until Verity's window closes.")


CUSTOM_ABILITIES.update({
    "kneel": _ab_kneel,
    "stop": _ab_stop,
    "ow": _ab_ow,
    "brain_eaten": _ab_brain_eaten,
    "nooo": _ab_nooo,
    "your_last_day": _ab_your_last_day,
    "i_dont_give_a_damn": _ab_i_dont_give_a_damn,
    "master_of_humanity": _ab_master_of_humanity,
    "i_am_the_master": _ab_i_am_the_master,
    "you_dont_deserve_your_brain": _ab_you_dont_deserve_your_brain,
})


# ═══════════════════════════════════════════════════════════════════
# BURGER
# ═══════════════════════════════════════════════════════════════════
# Obtained by reacting 🤤 or ☹️ to anything. Instant, first come only.
# Hidden from !roles until its holder looks.

BURGER_EMOJI = {"🤤", "☹️", "☹"}
SUPERNATURAL_WORDS = (
    "supernatural", "castiel", "dean winchester", "sam winchester",
    "crowley", "angel", "demon", "ghost", "wendigo", "leviathan",
)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None:
        return
    emoji = str(payload.emoji)
    if emoji not in BURGER_EMOJI:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return

    data = load_data()
    if holder_of(data, BURGER_ROLE_KEY):
        save_data(data)
        return
    ok, msg = await bind_role(data, member, BURGER_ROLE_KEY)
    save_data(data)
    if ok:
        try:
            await member.send(
                "🍔 Something happened.\n\n"
                "You have been given a role. It is not on any list. "
                "Run `!myrole` if you want to know what you are now."
            )
        except Exception:
            pass


class _BurgerDeleteView(discord.ui.View):
    """The Burger nerf — anyone may delete the message."""

    def __init__(self, message_id: int):
        super().__init__(timeout=600)
        self.message_id = message_id

    @discord.ui.button(label="Delete this", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_it(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.message.delete()
        except Exception:
            await interaction.response.send_message("Couldn't delete it.", ephemeral=True)
            return
        try:
            await interaction.followup.send("🍔 Gone.", ephemeral=True)
        except Exception:
            pass




async def _ab_side_of_fries(ctx, data, user, spec, target):
    pass  # handled generically (speech_lag); kept out of CUSTOM_ABILITIES


async def _ab_self_glaze(ctx, data, user, spec, target):
    """Clear every effect on yourself, including a real timeout."""
    cleared = list(user.get("effects", {}).keys())
    user["effects"] = {}
    save_data(data)
    try:
        await ctx.author.timeout(None, reason="!self_glaze")
    except Exception:
        pass
    try:
        if ctx.author.voice:
            await ctx.author.edit(mute=False, reason="!self_glaze")
    except Exception:
        pass
    names = ", ".join(EFFECTS[c]["name"] for c in cleared if c in EFFECTS)
    await ctx.send(embed=discord.Embed(
        title="✨ Self Glaze",
        description=(f"{ctx.author.mention} glazes themselves. "
                     + (f"Cleared: {names}." if names else "There was nothing on them. Still worth it.")),
        color=_c(ctx, BURGER_ROLE_KEY),
    ))


async def _ab_i_should_leave(ctx, data, user, spec, target):
    """Voluntarily exile yourself from this channel for 2 minutes."""
    ok = await exile_from_channel(ctx.author, ctx.channel, 120, "!i_should_leave")
    save_data(data)
    if ok:
        await ctx.send(f"🚪 **{ctx.author.display_name}** has removed themselves from "
                       f"#{ctx.channel.name} for 2 minutes. Respect it.")
    else:
        await ctx.send("❌ I can't edit this channel's permissions.", delete_after=8)


async def _ab_castiel(ctx, data, user, spec, target):
    """Turn someone into Castiel — they may apply one effect to anyone."""
    t = get_user(data, target.id)
    t["is_castiel"] = {"expires": now_ts() + 900, "by": str(ctx.author.id), "used": False}
    save_data(data)
    try:
        await target.edit(nick=f"Castiel ({target.display_name})"[:32], reason="!castiel")
    except Exception:
        pass
    await ctx.send(embed=discord.Embed(
        title="🪽 Turn Somebody Into Castiel",
        description=(
            f"{target.mention} is now **Castiel** for 15 minutes.\n\n"
            "They may use `!castiel_smite @user <effect>` **once** to apply any effect "
            "in the game to anyone.\n"
            f"Effects: {', '.join(EFFECTS.keys())}"
        ),
        color=_c(ctx, BURGER_ROLE_KEY),
    ))


@bot.command(name="castiel_smite")
async def castiel_smite(ctx, target: discord.Member, effect: str):
    """(Castiel only) Apply any one effect to anyone. One use."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    cas = user.get("is_castiel")
    if not cas or now_ts() >= cas.get("expires", 0):
        await ctx.send("You are not Castiel.", delete_after=8)
        save_data(data); return
    if cas.get("used"):
        await ctx.send("You've already used your one smite.", delete_after=8)
        save_data(data); return
    effect = effect.lower()
    if effect not in EFFECTS:
        await ctx.send(f"Unknown effect. Options: {', '.join(EFFECTS.keys())}", delete_after=12)
        save_data(data); return

    cas["used"] = True
    if effect == "timeout":
        await apply_timeout(target, 120, f"!castiel_smite by {ctx.author}")
    apply_effect(data, target.id, effect, 300, ctx.author.id)
    save_data(data)
    meta = EFFECTS[effect]
    await ctx.send(embed=discord.Embed(
        title="🪽 Castiel Smites",
        description=f"{ctx.author.mention} lays **{meta['name']}** on {target.mention} for 5 minutes.",
        color=discord.Color.from_rgb(120, 170, 220),
    ))


async def _ab_be_yourself(ctx, data, user, spec, target):
    user["ward_until"] = now_ts() + 900
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🍔 Just Be Yourself",
        description=(f"{ctx.author.mention} simply is.\n\n"
                     "Warded for 15 minutes — the next hostile effect is refused."),
        color=_c(ctx, BURGER_ROLE_KEY),
    ))


CUSTOM_ABILITIES.update({
    "self_glaze": _ab_self_glaze,
    "i_should_leave": _ab_i_should_leave,
    "castiel": _ab_castiel,
    "be_yourself": _ab_be_yourself,
})


# ═══════════════════════════════════════════════════════════════════
# FART BOY
# ═══════════════════════════════════════════════════════════════════

async def _ab_rapid_farts(ctx, data, user, spec, target):
    """Hit several people; each is coin-flipped between voice mute and silence."""
    pool = [m for m in ctx.guild.members
            if not m.bot and m.id != ctx.author.id][:80]
    if not pool:
        await ctx.send("Nobody to fart on.", delete_after=8)
        return
    victims = random.sample(pool, min(len(pool), random.randint(3, 5)))
    lines = []
    for v in victims:
        vu = get_user(data, v.id)
        if _is_immune(vu):
            lines.append(f"• {v.mention} — *unbothered*")
            continue
        if random.random() < 0.5 and v.voice:
            try:
                await v.edit(mute=True, reason="!rapid_farts")
                lines.append(f"• {v.mention} — 🔇 voice muted 45s")

                async def _un(m=v):
                    await asyncio.sleep(45)
                    try:
                        await m.edit(mute=False, reason="Farts cleared")
                    except Exception:
                        pass
                asyncio.create_task(_un())
            except Exception:
                apply_effect(data, v.id, "mute", 45, ctx.author.id)
                lines.append(f"• {v.mention} — 🤐 silenced 45s")
        else:
            apply_effect(data, v.id, "mute", 45, ctx.author.id)
            lines.append(f"• {v.mention} — 🤐 silenced 45s")
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💨💨 Rapid Farts",
        description=f"{ctx.author.mention} lets loose.\n\n" + "\n".join(lines),
        color=_c(ctx, FARTBOY_ROLE_KEY),
    ))


async def _ab_fart_beatbox(ctx, data, user, spec, target):
    """Random victims get a random effect each."""
    pool = [m for m in ctx.guild.members if not m.bot and m.id != ctx.author.id][:80]
    if not pool:
        await ctx.send("Nobody to consume.", delete_after=8)
        return
    victims = random.sample(pool, min(len(pool), random.randint(2, 4)))
    choices = ["speech_lag", "mute", "misfire", "cooldown_tax"]
    lines = []
    for v in victims:
        if _is_immune(get_user(data, v.id)):
            lines.append(f"• {v.mention} — *unbothered*")
            continue
        eff = random.choice(choices)
        apply_effect(data, v.id, eff, 120, ctx.author.id)
        lines.append(f"• {v.mention} — {EFFECTS[eff]['icon']} {EFFECTS[eff]['name']} 2m")
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🎵💨 Fart Beatbox",
        description=f"{ctx.author.mention} drops a set.\n\n" + "\n".join(lines),
        color=_c(ctx, FARTBOY_ROLE_KEY),
    ))


async def _ab_fart_nuke(ctx, data, user, spec, target):
    """Every effect, on everyone, for 5 minutes. Respects immunity."""
    hit, spared = 0, 0
    for m in ctx.guild.members:
        if m.bot or m.id == ctx.author.id:
            continue
        mu = get_user(data, m.id)
        if _is_immune(mu):
            spared += 1
            continue
        for eff in ("ability_lock", "cooldown_tax", "misfire", "speech_lag", "mute"):
            apply_effect(data, m.id, eff, 300, ctx.author.id)
        hit += 1
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="☢️💨 FART NUKE",
        description=(
            f"{ctx.author.mention} ends the server.\n\n"
            f"**{hit}** members hit with **every effect in the game** for 5 minutes."
            + (f"\n**{spared}** were immune and are still talking." if spared else "")
        ),
        color=discord.Color.dark_green(),
    ))


CUSTOM_ABILITIES.update({
    "rapid_farts": _ab_rapid_farts,
    "fart_beatbox": _ab_fart_beatbox,
    "fart_nuke": _ab_fart_nuke,
})


def _ability_text(ctx, ability_key: str) -> str:
    raw = getattr(getattr(ctx, "message", None), "content", "") or ""
    prefix = f"!{ability_key}"
    return raw[len(prefix):].strip() if raw.lower().startswith(prefix) else ""


# ═══════════════════════════════════════════════════════════════════
# HOPE / DESPAIR LEGACY ABILITIES
# ═══════════════════════════════════════════════════════════════════
# The uploaded pre-2.0 bot used HP, damage, clash coins, and role removal.
# These handlers preserve the recognizable abilities while expressing their
# outcomes through 2.0's single-user status-effect system instead.

async def _ab_nagito_luck_switch(ctx, data, user, spec, target):
    user["nagito_luck_switch"] = not user.get("nagito_luck_switch", False)
    save_data(data)
    state = "ON" if user["nagito_luck_switch"] else "OFF"
    detail = (
        "Incoming hostile abilities have a **99% chance to miss you**."
        if user["nagito_luck_switch"]
        else "Incoming abilities can hit you normally."
    )
    await ctx.send(
        f"🍀 *“My luck is so bad...”* Nagito's Luck Switch is **{state}**. {detail}"
    )


def _nagito_effect_limit(user: dict, target_id: int) -> int:
    return 120 if str(target_id) in user.get("nagito_attackers", {}) else 60


async def _nagito_send(ctx, content=None, **kwargs):
    if getattr(ctx, "interaction", None) is None:
        kwargs.pop("ephemeral", None)
    await ctx.send(content, **kwargs)


async def _apply_selected_nagito_effect(ctx, target_id: int, effect: str, minutes: int):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user.get("role_key") not in {"nagito_hope", "nagito_despair"}:
        await _nagito_send(ctx, "Only Nagito Komaeda can use this effect.", ephemeral=True)
        return
    if user.get("rp_opt_out"):
        await _nagito_send(ctx, "You opted out of roleplay. `!opt_in` if you want back in.", ephemeral=True)
        return
    if effect not in EFFECTS:
        await _nagito_send(ctx, f"Unknown effect. Choose one of: {', '.join(EFFECTS)}", ephemeral=True)
        return

    target = ctx.guild.get_member(target_id) if ctx.guild else None
    if target is None:
        await _nagito_send(ctx, "That member is no longer in this server.", ephemeral=True)
        return
    if target.bot or target.id == ctx.author.id:
        await _nagito_send(ctx, "Choose another server member; bots and yourself cannot be targeted.", ephemeral=True)
        return
    target_user = get_user(data, target.id)
    if target_user.get("rp_opt_out"):
        await _nagito_send(ctx, f"{target.mention} opted out of roleplay.", ephemeral=True)
        return

    extended = str(target.id) in user.get("nagito_attackers", {})
    maximum = 120 if extended else 60
    if not 1 <= minutes <= maximum:
        reason = " because this member previously tried an ability on you" if extended else ""
        await _nagito_send(
            ctx,
            f"Duration must be between **1 and {maximum} minutes**{reason}.",
            ephemeral=True,
        )
        return

    clear_expired_effects(target_user)
    if _is_immune(target_user):
        await _nagito_send(ctx, f"{target.mention} is immune; the effect was refused.", ephemeral=True)
        return
    if ward_active(target_user):
        target_user["ward_until"] = 0
        save_data(data)
        await _nagito_send(ctx, f"{target.mention}'s ward refused the effect.", ephemeral=True)
        return

    seconds = minutes * 60
    meta = EFFECTS[effect]
    note = ""
    if effect == "timeout" and not await apply_timeout(
        target, seconds, f"Nagito effect by {ctx.author}",
    ):
        effect, seconds = "mute", max(seconds, 300)
        meta = EFFECTS[effect]
        note = "\n*(Discord timeout unavailable; bot-side silence applied instead.)*"
    elif effect == "channel_exile":
        channel = ctx.channel.parent if isinstance(ctx.channel, discord.Thread) else ctx.channel
        if channel is None or not hasattr(channel, "set_permissions"):
            effect = "mute"
            meta = EFFECTS[effect]
            note = "\n*(Channel permissions unavailable; bot-side silence applied instead.)*"
        elif not await exile_from_channel(
            target, channel, seconds, f"Nagito effect by {ctx.author}",
        ):
            effect = "mute"
            meta = EFFECTS[effect]
            note = "\n*(Channel permissions unavailable; bot-side silence applied instead.)*"
        else:
            note = f"\n*(Removed from #{channel.name} only.)*"

    apply_effect(data, target.id, effect, seconds, ctx.author.id)
    if extended:
        user["nagito_attackers"].pop(str(target.id), None)
    save_data(data)
    await _nagito_send(ctx, embed=discord.Embed(
        title=f"{meta['icon']} Luck Turns Against You",
        description=(
            f"{ctx.author.mention} turns fate against {target.mention}.\n\n"
            f"{meta['icon']} **{meta['name']}** for **{seconds // 60} minutes** — "
            f"{meta['desc']}{note}"
        ),
        color=discord.Color.from_rgb(0, 200, 100),
    ))


async def _ab_nagito_luck_effect(ctx, data, user, spec, target):
    raw = _ability_text(ctx, "nagito_luck_effect")
    args = re.sub(r"<@!?[0-9]+>", " ", raw).split()
    if args:
        if len(args) != 2 or not args[1].isdecimal():
            await ctx.send(
                "`!nagito_luck_effect @user <effect_key> <minutes>` "
                "(1-60 minutes, or up to 120 after they tried an ability on you).",
                delete_after=12,
            )
            return
        effect = args[0].lower()
        if effect not in EFFECTS:
            await ctx.send(f"Unknown effect. Choose one of: {', '.join(EFFECTS)}", delete_after=12)
            return
        await _apply_selected_nagito_effect(ctx, target.id, effect, int(args[1]))
        return

    maximum = _nagito_effect_limit(user, target.id)
    interaction = getattr(ctx, "interaction", None)
    if interaction is not None:
        await ctx.send(
            f"Choose an effect for {target.mention}, then set a duration from 1 to "
            f"{maximum} minutes.",
            view=_NagitoEffectSelectView(ctx.author.id, target.id, maximum),
            ephemeral=True,
        )
        return
    await ctx.send(
        f"`!nagito_luck_effect @user <effect_key> <minutes>`\n"
        f"Effects: {', '.join(EFFECTS)}. Duration: 1-{maximum} minutes.",
        delete_after=15,
    )


async def _ab_rally(ctx, data, user, spec, target):
    apply_effect(data, target.id, "cooldown_tax", 1800, ctx.author.id)
    apply_effect(data, target.id, "ability_lock", 300, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💫 Rally Strike",
        description=(
            f"{ctx.author.mention} turns a rallying cry into a focused strike on {target.mention}.\n\n"
            "Their abilities are locked for **5 minutes** and their cooldowns are doubled "
            "for **30 minutes**."
        ),
        color=_c(ctx, "hope"),
    ))


async def _ab_beacon(ctx, data, user, spec, target):
    apply_effect(data, target.id, "misfire", 900, ctx.author.id)
    apply_effect(data, target.id, "cooldown_tax", 600, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🕯️ Beacon Breaker",
        description=(
            f"{ctx.author.mention} shatters {target.mention}'s focus with a beacon-bright flash.\n\n"
            "Their abilities may misfire for **15 minutes** and cooldowns are doubled "
            "for **10 minutes**."
        ),
        color=_c(ctx, "hope"),
    ))


async def _ab_inspire_strike(ctx, data, user, spec, target):
    apply_effect(data, target.id, "cooldown_tax", 1800, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💫 Inspire Strike",
        description=(
            f"{ctx.author.mention} strikes {target.mention} with relentless hope.\n\n"
            "Their ability cooldowns are doubled for 30 minutes."
        ),
        color=_c(ctx, "hope"),
    ))


async def _ab_despair_wave(ctx, data, user, spec, target):
    apply_effect(data, target.id, "misfire", 900, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💫 Despair Wave",
        description=(
            f"{ctx.author.mention} sends a despair wave at {target.mention}.\n\n"
            "Their abilities have a 40% chance to misfire for 15 minutes."
        ),
        color=discord.Color.from_rgb(100, 40, 180),
    ))


async def _ab_tragic_event(ctx, data, user, spec, target):
    data["tragic_event"] = {
        "channel_id": ctx.channel.id,
        "by": str(ctx.author.id),
        "expires": now_ts() + 3600,
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💀 The Most Tragic Event in History",
        description=(
            "The next different person to speak in this channel must face "
            "**Hope or Despair**. The consequence will be applied automatically."
        ),
        color=discord.Color.from_rgb(80, 0, 0),
    ))


async def _ab_brainwash(ctx, data, user, spec, target):
    apply_effect(data, target.id, "ability_lock", 600, ctx.author.id)
    save_data(data)
    try:
        await target.send(
            "🔴💀 You have been brainwashed. Your role abilities are locked for 10 minutes."
        )
    except Exception:
        pass
    await ctx.send(embed=discord.Embed(
        title="🔴 Brainwash Complete",
        description=f"{target.mention}'s abilities are locked for 10 minutes.",
        color=discord.Color.from_rgb(80, 0, 0),
    ))


async def _ab_disaster(ctx, data, user, spec, target):
    event = data.get("despair_disaster")
    if event and now_ts() < event.get("expires", 0):
        await ctx.send("A disaster is already active.", delete_after=8)
        return
    data["despair_disaster"] = {
        "by": str(ctx.author.id),
        "expires": now_ts() + 1800,
        "defended": [],
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🚨🔴 DISASTER EVENT",
        description=(
            f"{ctx.author.mention} has unleashed a disaster.\n\n"
            "Every role holder has 30 minutes to run `!defend`. "
            "Anyone who does not defend will be ability-locked for 10 minutes."
        ),
        color=discord.Color.from_rgb(80, 0, 0),
    ))


@bot.command(name="defend")
async def defend_cmd(ctx):
    """Defend your current role during an active Ultimate Despair disaster."""
    data = load_data()
    event = data.get("despair_disaster")
    if not event or now_ts() >= event.get("expires", 0):
        await ctx.send("No disaster is currently active.", delete_after=8)
        return
    defended = event.setdefault("defended", [])
    uid = str(ctx.author.id)
    if uid not in defended:
        defended.append(uid)
        save_data(data)
    await ctx.send(f"🛡️ {ctx.author.mention} has defended their role.")


async def _ab_summon_sister(ctx, data, user, spec, target):
    if user.get("despair_sister_active"):
        await ctx.send("Your Despair Sister is already active.", delete_after=8)
        return
    user["despair_sister_active"] = True
    data.setdefault("despair_sisters", {})[str(ctx.author.id)] = {
        "active": True,
        "name": "Junko Enoshima",
        "summoned_at": now_ts(),
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="👸 Despair Sister Summoned",
        description=(
            "The Sister now obeys your commands. Her buttons are available through "
            "`!myrole`, and the text commands remain available:\n"
            "`!sister_kill @user`, `!sister_say <message>`, "
            "`!sister_seduce @user`, `!sister_anything <action>`."
        ),
        color=discord.Color.from_rgb(120, 0, 60),
    ))


async def _ab_sister_kill(ctx, data, user, spec, target):
    apply_effect(data, target.id, "ability_lock", 600, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="👸 Sister Strike",
        description=f"The Despair Sister strikes {target.mention}. Their abilities are locked for 10 minutes.",
        color=discord.Color.from_rgb(120, 0, 60),
    ))


async def _ab_sister_say(ctx, data, user, spec, target):
    message = _ability_text(ctx, "sister_say") or "The Despair Sister says nothing."
    await ctx.send(embed=discord.Embed(
        title="👸 Despair Sister says",
        description=f"*{message[:1900]}*",
        color=discord.Color.from_rgb(120, 0, 60),
    ))


async def _ab_sister_seduce(ctx, data, user, spec, target):
    apply_effect(data, target.id, "speech_lag", 300, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="👸 Sister Seduce",
        description=f"The Despair Sister whispers to {target.mention}. Their speech is slowed for 5 minutes.",
        color=discord.Color.from_rgb(120, 0, 60),
    ))


async def _ab_sister_anything(ctx, data, user, spec, target):
    action = _ability_text(ctx, "sister_anything") or "does something mysterious"
    await ctx.send(embed=discord.Embed(
        title="👸 Despair Sister acts",
        description=f"The Despair Sister {action[:1900]}",
        color=discord.Color.from_rgb(120, 0, 60),
    ))


async def _ab_summon_reserve(ctx, data, user, spec, target):
    if user.get("reserve_course_active"):
        await ctx.send("Your Reserve Course Students are already active.", delete_after=8)
        return
    user["reserve_course_active"] = True
    user["reserve_course_count"] = 3
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🏫 Reserve Course Students Summoned",
        description=(
            "Three Reserve Course Students now fight for you. "
            "Use `!student_attack @user` or the button in `!myrole`."
        ),
        color=discord.Color.from_rgb(100, 100, 100),
    ))


async def _ab_student_attack(ctx, data, user, spec, target):
    apply_effect(data, target.id, "misfire", 300, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🏫 Student Attack",
        description=f"A Reserve Course Student overwhelms {target.mention}; their abilities may misfire for 5 minutes.",
        color=discord.Color.from_rgb(100, 100, 100),
    ))


async def _ab_brainwash_remnant(ctx, data, user, spec, target):
    target_user = get_user(data, target.id)
    pressure = len(target_user.get("effects", {}))
    chance = min(0.8, 0.2 + pressure * 0.1)
    if random.random() > chance:
        save_data(data)
        await ctx.send(
            f"🔴 {target.mention} resisted the conversion ({int(chance * 100)}% chance).",
            delete_after=10,
        )
        return
    ok, result = await bind_role(data, target, "remnant_of_despair")
    if not ok:
        await ctx.send(f"❌ Conversion failed: {result}", delete_after=10)
        return
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🔴 Conversion Successful",
        description=f"{target.mention} has become a **Remnant of Despair**.",
        color=discord.Color.from_rgb(60, 0, 0),
    ))


CUSTOM_ABILITIES.update({
    "nagito_luck_switch": _ab_nagito_luck_switch,
    "nagito_luck_effect": _ab_nagito_luck_effect,
    "rally": _ab_rally,
    "beacon": _ab_beacon,
    "inspire_strike": _ab_inspire_strike,
    "despair_wave": _ab_despair_wave,
    "tragic_event": _ab_tragic_event,
    "brainwash": _ab_brainwash,
    "disaster": _ab_disaster,
    "summon_sister": _ab_summon_sister,
    "sister_kill": _ab_sister_kill,
    "sister_say": _ab_sister_say,
    "sister_seduce": _ab_sister_seduce,
    "sister_anything": _ab_sister_anything,
    "summon_reserve": _ab_summon_reserve,
    "student_attack": _ab_student_attack,
    "brainwash_remnant": _ab_brainwash_remnant,
})


def _is_immune(user: dict) -> bool:
    imm = user.get("immunity")
    return bool(imm and now_ts() < imm.get("expires", 0))


# Register commands for every ability added above.
for _key in list(ABILITY_SPEC):
    if _key not in {c.name for c in bot.commands}:
        _make_ability_command(_key)


# ═══════════════════════════════════════════════════════════════════
# EXPANSION MESSAGE HOOKS
# ═══════════════════════════════════════════════════════════════════
# Called from on_message. Returns True if the message was consumed and
# normal processing should stop.

CASTIEL_GIF_HOSTS = ("tenor.com", "giphy.com", "gfycat.com", "imgur.com/", "redgifs.com")


def _looks_like_gif(message: discord.Message) -> bool:
    """
    Distinguish an actual GIF/link embed from somebody merely typing a word.

    A message counts as a GIF only if it carries a real attachment with a
    gif/video content type, or contains a URL that is either a direct .gif/.mp4
    file or points at a known GIF host. Plain text — even the word "castiel" —
    never qualifies.
    """
    for a in message.attachments:
        ct = (a.content_type or "").lower()
        fn = (a.filename or "").lower()
        if ct.startswith(("image/gif", "video/")) or fn.endswith((".gif", ".gifv", ".mp4", ".webm")):
            return True
    low = message.content.lower()
    if "http://" not in low and "https://" not in low:
        return False
    for token in low.split():
        if not token.startswith(("http://", "https://")):
            continue
        clean = token.split("?")[0]
        if clean.endswith((".gif", ".gifv", ".mp4", ".webm")):
            return True
        if any(host in token for host in CASTIEL_GIF_HOSTS):
            return True
    return False


def _mentions_castiel(message: discord.Message) -> bool:
    low = message.content.lower()
    if "castiel" in low or "misha collins" in low:
        return True
    for a in message.attachments:
        if "castiel" in (a.filename or "").lower():
            return True
    return False


async def _expansion_hooks(message: discord.Message, data: dict, user: dict) -> bool:
    content = message.content
    low = content.lower()
    author = message.author

    if await _justice_trial_hook(message, data, user):
        return True
    if await _gpg_message_hook(message, data, user):
        return True
    if await _kaleb_message_hook(message, data, user):
        return True

    # ── Lord Verity: natural-language obtainment ──
    if await _handle_verity_request(message, data):
        return True

    # ── Compelled phrase (Kneel / Master Of Humanity) ──
    comp = user.get("compelled_phrase")
    if comp and now_ts() < comp.get("expires", 0):
        if comp["phrase"] in low:
            user.pop("compelled_phrase", None)
            save_data(data)
            try:
                await message.add_reaction("👑")
            except Exception:
                pass
        # Otherwise they simply haven't complied yet; the timer handles failure.

    # ── Stop order ──
    stop = user.get("stop_order")
    if stop:
        if now_ts() < stop.get("silent_until", 0):
            # They spoke during the silence. Backwards typing is now enforced.
            stop["broke"] = True
            save_data(data)
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await author.send(
                    "✋ You spoke during **Stop**. For the next 2 minutes your messages "
                    "must be typed backwards."
                )
            except Exception:
                pass
            return True
        if stop.get("broke") and now_ts() < stop.get("backwards_until", 0):
            stripped = "".join(ch for ch in low if ch.isalnum())
            if stripped and stripped != stripped[::-1]:
                words = low.split()
                looks_backwards = all(w == w[::-1] or len(w) < 3 for w in words[:3]) if words else False
                if not looks_backwards:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    try:
                        await author.send("✋ Backwards. You were told.")
                    except Exception:
                        pass
                    return True
        if now_ts() >= stop.get("backwards_until", 0):
            user.pop("stop_order", None)
            save_data(data)

    # ── Burger passives (only for the Burger holder) ──
    if user.get("role_key") == BURGER_ROLE_KEY:
        # Passive 1: supernatural talk gives the NEXT speaker a headache.
        if any(w in low for w in SUPERNATURAL_WORDS):
            data["burger_headache_armed"] = {
                "channel_id": message.channel.id,
                "by": str(author.id),
                "at": now_ts(),
            }
            save_data(data)

        # Passive 2 (nerf): 5% of Burger's messages get a public delete button.
        if random.random() < 0.05:
            try:
                await message.channel.send(
                    f"*(a wrapper blows past)*",
                    view=_BurgerDeleteView(message.id),
                    reference=message,
                    mention_author=False,
                    delete_after=600,
                )
            except Exception:
                pass

        # Castiel GIFs get eaten and spat into a random channel.
        if _looks_like_gif(message) and _mentions_castiel(message):
            targets = [c for c in message.guild.text_channels
                       if c.id != message.channel.id
                       and c.permissions_for(message.guild.me).send_messages]
            payload = content
            files = []
            for a in message.attachments:
                try:
                    files.append(await a.to_file())
                except Exception:
                    pass
            try:
                await message.delete()
            except Exception:
                pass
            if targets:
                dest = random.choice(targets)
                try:
                    await dest.send(
                        f"🍔 *chews* ... *spits*\n"
                        f"{author.mention} tried to post Castiel in "
                        f"#{message.channel.name}. It ended up here.\n{payload}",
                        files=files or None,
                    )
                    await message.channel.send(
                        f"🍔 Something was eaten. It came out in #{dest.name}.",
                        delete_after=20)
                except Exception:
                    pass
            return True

    # ── Burger headache lands on the next speaker ──
    armed = data.get("burger_headache_armed")
    if armed and armed["channel_id"] == message.channel.id and str(author.id) != armed["by"]:
        if now_ts() - armed["at"] <= 300 and not _is_immune(user):
            data.pop("burger_headache_armed", None)
            apply_effect(data, author.id, "speech_lag", 20 * 6, armed["by"])
            save_data(data)
            try:
                await message.channel.send(
                    f"🤕 {author.mention} gets a splitting headache. "
                    "20 seconds between messages for the next 2 minutes.",
                    delete_after=20)
            except Exception:
                pass

    return False


# ═══════════════════════════════════════════════════════════════════
# KALEB LOVE
# ═══════════════════════════════════════════════════════════════════

FILTHY_DOG_ROLE = "Filthy Dog"
DOG_NOISES = {"arf!", "bark!", "ruff!", "ruff!", "grrr", "arf", "bark", "ruff", "grr"}
PAWN_DURATION = 10 * 60
DOG_DURATION = 10 * 60


def _holds_kaleb(user: dict) -> bool:
    return user.get("role_key") == "kaleb_love"


def _pawn_of(user: dict, owner_id: int) -> bool:
    pawn = user.get("kaleb_pawn")
    return bool(pawn and now_ts() < int(pawn.get("expires", 0)) and str(pawn.get("by")) == str(owner_id))


async def ensure_filthy_dog_role(guild: discord.Guild):
    role = discord.utils.get(guild.roles, name=FILTHY_DOG_ROLE)
    if role is None:
        try:
            role = await guild.create_role(
                name=FILTHY_DOG_ROLE,
                color=discord.Color.from_rgb(120, 80, 40),
                reason="Kaleb Love filthy dog",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None
    me = guild.me
    if me and role >= me.top_role:
        return None
    return role


async def clear_filthy_dog(guild: discord.Guild, member: discord.Member, data: dict):
    user = get_user(data, member.id)
    user.pop("filthy_dog", None)
    role = discord.utils.get(guild.roles, name=FILTHY_DOG_ROLE)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Filthy Dog ended")
        except (discord.Forbidden, discord.HTTPException):
            pass
    try:
        await member.edit(nick=None, reason="Filthy Dog ended")
    except (discord.Forbidden, discord.HTTPException):
        pass


async def _ab_kaleb_obsess(ctx, data, user, spec, target):
    apply_effect(data, target.id, "mute", 45, ctx.author.id)
    apply_effect(data, target.id, "speech_lag", 180, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💗 Obsess",
        description=f"{target.mention} is silenced for 45 seconds, then stuck on slower messages for 3 minutes.",
        color=discord.Color.from_rgb(255, 120, 180),
    ))


async def _ab_kaleb_pawn(ctx, data, user, spec, target):
    t = get_user(data, target.id)
    t["kaleb_pawn"] = {"expires": now_ts() + PAWN_DURATION, "by": str(ctx.author.id), "phrase": ""}
    apply_effect(data, target.id, "ability_lock", PAWN_DURATION, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="💗 Pawn",
        description=(
            f"{target.mention} is pawned for 10 minutes. Their abilities are locked.\n\n"
            f"`!kaleb_order {target.mention} <words>` — they must say that, or they are muted.\n"
            f"`!kaleb_kiss {target.mention}` — they refuse, get sick, and pass out.\n"
            f"`!kaleb_make_dog {target.mention}` — temporary **Filthy Dog**."
        ),
        color=discord.Color.from_rgb(255, 120, 180),
    ))


async def _ab_kaleb_copy(ctx, data, user, spec, target):
    t = get_user(data, target.id)
    t_role = t.get("role_key")
    if not t_role or t_role not in ROLES or not ROLES[t_role]["abilities"]:
        await ctx.send(f"{target.mention} has no ability kit to copy.", delete_after=10)
        return
    user["devoured_kit"] = {
        "role_key": t_role,
        "expires": now_ts() + 900,
        "victim": str(target.id),
    }
    save_data(data)
    kit = ", ".join(f"`!{a[0]}`" for a in ROLES[t_role]["abilities"])
    await ctx.send(embed=discord.Embed(
        title="💗 Copy",
        description=f"{ctx.author.mention} can use **{role_display(t_role)}** for 15 minutes.\n{kit}",
        color=discord.Color.from_rgb(255, 120, 180),
    ))


async def _ab_kaleb_grant_role(ctx, data, user, spec, target):
    query = _ability_text(ctx, "kaleb_grant_role")
    # text after the mention is the role name; the command parser already ate the member
    raw = getattr(getattr(ctx, "message", None), "content", "") or ""
    parts = raw.split(None, 2)
    query = parts[2].strip() if len(parts) > 2 else query
    if not query:
        await ctx.send("`!kaleb_grant_role @user Role Name`", delete_after=10)
        return
    role = discord.utils.get(ctx.guild.roles, name=query)
    if role is None:
        role = discord.utils.find(lambda r: query.lower() in r.name.lower(), ctx.guild.roles)
    if role is None:
        await ctx.send("No role by that name.", delete_after=8)
        return
    if (
        role.is_default() or role.managed or role >= ctx.guild.me.top_role
        or role.permissions.administrator or role.permissions.ban_members
        or role.permissions.kick_members or role.permissions.manage_guild
        or role.permissions.manage_roles or role.permissions.manage_channels
    ):
        await ctx.send("That role is admin, managed, or too high to lend.", delete_after=10)
        return
    try:
        await target.add_roles(role, reason=f"Kaleb grant by {ctx.author}")
    except (discord.Forbidden, discord.HTTPException):
        await ctx.send("Discord rejected that role grant.", delete_after=8)
        return
    grants = data.setdefault("kaleb_role_grants", [])
    grants.append({
        "guild_id": str(ctx.guild.id),
        "member_id": str(target.id),
        "role_id": str(role.id),
        "expires": now_ts() + 300,
    })
    save_data(data)
    await ctx.send(f"💗 **{role.name}** lent to {target.mention} for 5 minutes.")

    async def _take_back():
        await asyncio.sleep(300)
        fresh = ctx.guild.get_member(target.id)
        current = ctx.guild.get_role(role.id)
        if fresh and current and current in fresh.roles and not protected_member(fresh):
            try:
                await fresh.remove_roles(current, reason="Kaleb role grant expired")
            except (discord.Forbidden, discord.HTTPException):
                pass
    asyncio.create_task(_take_back())


CUSTOM_ABILITIES.update({
    "kaleb_obsess": _ab_kaleb_obsess,
    "kaleb_pawn": _ab_kaleb_pawn,
    "kaleb_copy": _ab_kaleb_copy,
    "kaleb_grant_role": _ab_kaleb_grant_role,
})


async def _require_kaleb_pawn(ctx, member: discord.Member):
    data = load_data()
    owner = get_user(data, ctx.author.id)
    if not _holds_kaleb(owner):
        await ctx.send("Only Kaleb Love can do that.", delete_after=8)
        return None
    target_user = get_user(data, member.id)
    if member.bot or _rp_blocked(target_user) or not _pawn_of(target_user, ctx.author.id):
        await ctx.send("That person is not your pawn.", delete_after=8)
        return None
    return data


@bot.command(name="kaleb_order")
async def kaleb_order(ctx, member: discord.Member, *, phrase: str):
    """While pawned, set the exact words they have to say."""
    data = await _require_kaleb_pawn(ctx, member)
    if not data:
        return
    get_user(data, member.id)["kaleb_pawn"]["phrase"] = phrase.lower().strip()
    save_data(data)
    await ctx.send(f"💗 {member.mention} must say `{phrase}` next, or they are muted.")


@bot.command(name="kaleb_kiss")
async def kaleb_kiss(ctx, member: discord.Member):
    """Pawn extension: they refuse, get sick, and pass out."""
    data = await _require_kaleb_pawn(ctx, member)
    if not data:
        return
    apply_effect(data, member.id, "mute", 45, ctx.author.id)
    save_data(data)
    try:
        await member.timeout(datetime.now(timezone.utc) + timedelta(seconds=30), reason="Pawn passed out")
    except Exception:
        pass
    await ctx.send(embed=discord.Embed(
        title="💗 Kiss refused",
        description=f"{member.mention} didn't want to. They get sick and pass out for a moment.",
        color=discord.Color.from_rgb(255, 120, 180),
    ))


@bot.command(name="kaleb_make_dog")
async def kaleb_make_dog(ctx, member: discord.Member):
    """Pawn extension: temporary Filthy Dog role."""
    data = await _require_kaleb_pawn(ctx, member)
    if not data:
        return
    role = await ensure_filthy_dog_role(ctx.guild)
    if role is None:
        await ctx.send("Couldn't create Filthy Dog. Move the bot role higher.", delete_after=10)
        return
    user = get_user(data, member.id)
    user["filthy_dog"] = {"expires": now_ts() + DOG_DURATION, "by": str(ctx.author.id)}
    save_data(data)
    try:
        await member.add_roles(role, reason="Turned into Filthy Dog")
        await member.edit(nick="Filthy Dog"[:32], reason="Turned into Filthy Dog")
    except (discord.Forbidden, discord.HTTPException):
        pass
    await ctx.send(embed=discord.Embed(
        title="🐶 Filthy Dog",
        description=(
            f"{member.mention} is a **Filthy Dog** for 10 minutes. They can only bark or use the dog commands.\n"
            "`!bark @user` scares them quiet for 10 seconds.\n"
            "`!chase` stops people talking.\n"
            "`!bite @user` times them out for 2 minutes.\n"
            "`!lick` drops the dog role immediately."
        ),
        color=discord.Color.from_rgb(120, 80, 40),
    ))


def _is_filthy_dog(user: dict) -> bool:
    dog = user.get("filthy_dog")
    return bool(dog and now_ts() < int(dog.get("expires", 0)))


@bot.command(name="bark")
async def bark_cmd(ctx, member: discord.Member):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_filthy_dog(user):
        await ctx.send("Only a Filthy Dog can bark.", delete_after=8)
        return
    if _rp_blocked(get_user(data, member.id)):
        await ctx.send("They opted out.", delete_after=8)
        return
    apply_effect(data, member.id, "mute", 10, ctx.author.id)
    save_data(data)
    await ctx.send(f"🐶 **Bark** — {member.mention} is too scared to talk for 10 seconds.")


@bot.command(name="chase")
async def chase_cmd(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_filthy_dog(user):
        await ctx.send("Only a Filthy Dog can chase.", delete_after=8)
        return
    hit = []
    pool = [m for m in ctx.guild.members if not m.bot and m.id != ctx.author.id and not _rp_blocked(get_user(data, m.id))]
    if ctx.author.voice and ctx.author.voice.channel:
        pool = [m for m in ctx.author.voice.channel.members if not m.bot and m.id != ctx.author.id and not _rp_blocked(get_user(data, m.id))]
    else:
        pool = pool[:4]
    for m in pool:
        apply_effect(data, m.id, "mute", 20, ctx.author.id)
        hit.append(m.mention)
    save_data(data)
    names = ", ".join(hit) if hit else "nobody"
    await ctx.send(f"🐶 **Chase** — {names} can't speak.")


@bot.command(name="bite")
async def bite_cmd(ctx, member: discord.Member):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_filthy_dog(user):
        await ctx.send("Only a Filthy Dog can bite.", delete_after=8)
        return
    if _rp_blocked(get_user(data, member.id)):
        await ctx.send("They opted out.", delete_after=8)
        return
    await apply_timeout(member, 120, f"Filthy Dog bite by {ctx.author}")
    apply_effect(data, member.id, "timeout", 120, ctx.author.id)
    save_data(data)
    await ctx.send(f"🐶 **Bite** — {member.mention} is sent to the ER and timed out for 2 minutes.")


@bot.command(name="lick")
async def lick_cmd(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if not _is_filthy_dog(user):
        await ctx.send("Only a Filthy Dog can lick their owner.", delete_after=8)
        return
    await clear_filthy_dog(ctx.guild, ctx.author, data)
    save_data(data)
    await ctx.send(f"🐶 {ctx.author.mention} licked their owner. Filthy Dog is gone.")


async def _kaleb_message_hook(message: discord.Message, data: dict, user: dict) -> bool:
    if user.get("rp_opt_out"):
        return False
    pawn = user.get("kaleb_pawn")
    if pawn and now_ts() >= int(pawn.get("expires", 0)):
        user.pop("kaleb_pawn", None)
        save_data(data)
        pawn = None
    if pawn and pawn.get("phrase"):
        if pawn["phrase"] not in message.content.lower():
            apply_effect(data, message.author.id, "mute", 30, int(pawn.get("by") or message.author.id))
            save_data(data)
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send("You didn't say what you were told. Muted for 30 seconds.")
            except Exception:
                pass
            return True
        pawn["phrase"] = ""
        save_data(data)
    dog = user.get("filthy_dog")
    if dog and now_ts() >= int(dog.get("expires", 0)):
        await clear_filthy_dog(message.guild, message.author, data)
        save_data(data)
        dog = None
    if dog:
        low = message.content.strip().lower()
        allowed = low in DOG_NOISES or low.startswith(("!bark", "!chase", "!bite", "!lick"))
        if not allowed:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send("Filthy Dogs can only bark: ARF! BARK! RUFF! RUFF! GRRR, or use !bark !chase !bite !lick.")
            except Exception:
                pass
            return True
    return False



# ═══════════════════════════════════════════════════════════════════
# RESTORED NEGATIVE KITS + ECHO
# ═══════════════════════════════════════════════════════════════════

async def _splash_negative(ctx, data, primary, effect: str, duration: int) -> list:
    """AOE follow-through. Skips the caster, the main target, bots, and opt-outs."""
    pool = [
        m for m in ctx.guild.members
        if not m.bot and m.id not in {ctx.author.id, primary.id}
        and not get_user(data, m.id).get("rp_opt_out")
        and not _is_immune(get_user(data, m.id))
    ]
    if ctx.author.voice and ctx.author.voice.channel:
        voiced = [m for m in ctx.author.voice.channel.members if m in pool]
        if voiced:
            pool = voiced
    caught = pool[:8]
    names = []
    for m in caught:
        apply_effect(data, m.id, effect, duration, ctx.author.id)
        names.append(m.mention)
    return names


async def _offer_echo(ctx, victim, effect: str, duration: int):
    if not victim or not effect:
        return
    data = load_data()
    holder = holder_of(data, GPG_ROLE_KEY)
    if not holder or str(ctx.author.id) == str(holder):
        return
    holder_member = ctx.guild.get_member(int(holder))
    if holder_member is None:
        return
    view = _EchoView(int(holder), ctx.author.id, victim.id, effect, duration, ctx.author.display_name, victim.display_name)
    try:
        await ctx.send(
            f"{holder_member.mention} — Echo can turn **{effect}** back on {ctx.author.mention}.",
            view=view,
        )
    except Exception:
        pass


class _EchoView(discord.ui.View):
    def __init__(self, owner_id: int, caster_id: int, victim_id: int, effect: str, duration: int, caster_name: str, victim_name: str):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.caster_id = caster_id
        self.victim_id = victim_id
        self.effect = effect
        self.duration = duration
        self.caster_name = caster_name
        self.victim_name = victim_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only Green Purple Girl can use Echo.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Echo", style=discord.ButtonStyle.primary, emoji="🔁")
    async def do_echo(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        victim = guild.get_member(self.victim_id)
        caster = guild.get_member(self.caster_id)
        data = load_data()
        if victim:
            vuser = get_user(data, victim.id)
            vuser.get("effects", {}).pop(self.effect, None)
        if caster:
            apply_effect(data, caster.id, self.effect, self.duration, interaction.user.id)
        save_data(data)
        for item in self.children:
            item.disabled = True
        meta = EFFECTS.get(self.effect, {"name": self.effect, "icon": "🔁"})
        await interaction.response.edit_message(
            content=(
                f"🔁 Echo: {meta['icon']} **{meta['name']}** lifted off {self.victim_name} "
                f"and put on {self.caster_name}."
            ),
            view=self,
        )


async def _ab_echo(ctx, data, user, spec, target):
    await ctx.send(
        "🔁 Echo is listening. When somebody lands a negative effect, only you get the button "
        "to take it off the victim and put it on the caster."
    )


async def _ab_condemn(ctx, data, user, spec, target):
    apply_effect(data, target.id, "ability_lock", 600, ctx.author.id)
    apply_effect(data, target.id, "cooldown_tax", 3600, ctx.author.id)
    save_data(data)
    await _offer_echo(ctx, target, "ability_lock", 600)
    await ctx.send(embed=discord.Embed(
        title="⚖️ Condemn",
        description=f"{target.mention} is branded. Abilities locked 10 minutes, and every cooldown is doubled for 1 hour.",
        color=discord.Color.from_rgb(200, 180, 80),
    ))


async def _ab_jacobs_ladder(ctx, data, user, spec, target):
    if any(has_effect(user, k) for k in ("mute", "ability_lock", "misfire")):
        await ctx.send("Jacob's Ladder needs a clean record. You are still marked.", delete_after=10)
        return
    apply_effect(data, target.id, "ability_lock", 300, ctx.author.id)
    apply_effect(data, target.id, "cooldown_tax", 1800, ctx.author.id)
    save_data(data)
    await _offer_echo(ctx, target, "ability_lock", 300)
    await ctx.send(embed=discord.Embed(
        title="⚖️ Jacob's Ladder",
        description=(
            f"*Throughout life and death, connecting heaven and earth, I cast upon you: Jacob's Ladder.*\n\n"
            f"{target.mention} is locked for 5 minutes and taxed for 30 minutes. No clash, no damage."
        ),
        color=discord.Color.from_rgb(255, 240, 100),
    ))


async def _ab_scale_of_wrongdoing(ctx, data, user, spec, target):
    data["justice_trial"] = {
        "accused": str(target.id),
        "by": str(ctx.author.id),
        "channel_id": ctx.channel.id,
        "expires": now_ts() + 30,
        "resolved": False,
    }
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="⚖️ Scale of Wrongdoing",
        description=(
            f"{target.mention} is called to answer within 30 seconds.\n"
            "Plead guilty and the lock is shorter. Deny it and your abilities misfire. "
            "Say nothing and the scale convicts you."
        ),
        color=discord.Color.from_rgb(200, 180, 80),
    ))

    async def _resolve():
        await asyncio.sleep(31)
        fresh = load_data()
        trial = fresh.get("justice_trial")
        if not trial or trial.get("resolved") or str(trial.get("accused")) != str(target.id):
            return
        trial["resolved"] = True
        apply_effect(fresh, target.id, "ability_lock", 1200, ctx.author.id)
        save_data(fresh)
        try:
            await ctx.send(f"⚖️ {target.mention} stayed silent. Convicted — abilities locked for 20 minutes.")
        except Exception:
            pass
    asyncio.create_task(_resolve())


async def _ab_divine_retribution(ctx, data, user, spec, target):
    t = get_user(data, target.id)
    recent = any(now_ts() < int(ts) for ts in (t.get("cooldowns") or {}).values())
    lock = 900 if recent else 300
    apply_effect(data, target.id, "ability_lock", lock, ctx.author.id)
    apply_effect(data, target.id, "cooldown_tax", 3600, ctx.author.id)
    save_data(data)
    await _offer_echo(ctx, target, "ability_lock", lock)
    await ctx.send(embed=discord.Embed(
        title="⚖️ Divine Retribution",
        description=(
            f"{target.mention} is smitten. Lock {lock // 60} minutes"
            + (" — they had just acted." if recent else " — no fresh act, so the lock is shorter.")
            + " Cooldowns are doubled for 1 hour."
        ),
        color=discord.Color.from_rgb(255, 220, 80),
    ))


async def _justice_trial_hook(message, data, user) -> bool:
    trial = data.get("justice_trial")
    if not trial or trial.get("resolved") or now_ts() >= int(trial.get("expires", 0)):
        return False
    if str(message.author.id) != str(trial.get("accused")):
        return False
    if message.channel.id != trial.get("channel_id"):
        return False
    low = message.content.lower()
    trial["resolved"] = True
    if any(p in low for p in ("i'm guilty", "im guilty", "i confess", "guilty")):
        apply_effect(data, message.author.id, "ability_lock", 600, int(trial["by"]))
        note = "Guilty plea. Abilities locked for 10 minutes."
    else:
        apply_effect(data, message.author.id, "misfire", 600, int(trial["by"]))
        note = "Denied. Abilities may misfire for 10 minutes."
    save_data(data)
    try:
        await message.channel.send(f"⚖️ {message.author.mention} — {note}")
    except Exception:
        pass
    return False


CUSTOM_ABILITIES.update({
    "echo": _ab_echo,
    "condemn": _ab_condemn,
    "jacobs_ladder": _ab_jacobs_ladder,
    "scale_of_wrongdoing": _ab_scale_of_wrongdoing,
    "divine_retribution": _ab_divine_retribution,
})


# ═══════════════════════════════════════════════════════════════════
# GREEN PURPLE GIRL
# ═══════════════════════════════════════════════════════════════════

def _rp_blocked(user: dict) -> bool:
    return bool(user.get("rp_opt_out"))


async def ensure_shame_role(guild: discord.Guild):
    role = discord.utils.get(guild.roles, name=SHAME_ROLE_NAME)
    if role is None:
        try:
            role = await guild.create_role(
                name=SHAME_ROLE_NAME,
                color=discord.Color.from_rgb(90, 70, 160),
                reason="Green Purple Girl shame mark",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None
    me = guild.me
    if me and role >= me.top_role:
        return None
    return role


async def apply_shame(guild: discord.Guild, member: discord.Member, source_id: int, data: dict) -> bool:
    user = get_user(data, member.id)
    if _rp_blocked(user) or member.bot:
        return False
    role = await ensure_shame_role(guild)
    if role is None:
        return False
    expires = now_ts() + SHAME_DURATION
    user["shame"] = {
        "expires": expires,
        "by": str(source_id),
        "word_limit": user.get("shame", {}).get("word_limit"),
    }
    try:
        if role not in member.roles:
            await member.add_roles(role, reason="Recorded to SHAME")
    except (discord.Forbidden, discord.HTTPException):
        return False
    return True


async def clear_shame(guild: discord.Guild, member: discord.Member, data: dict):
    user = get_user(data, member.id)
    user.pop("shame", None)
    role = discord.utils.get(guild.roles, name=SHAME_ROLE_NAME)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="SHAME expired")
        except (discord.Forbidden, discord.HTTPException):
            pass


async def expire_due_shame():
    data = load_data()
    changed = False
    for guild in bot.guilds:
        role = discord.utils.get(guild.roles, name=SHAME_ROLE_NAME)
        for member in list(guild.members):
            user = data.get("users", {}).get(str(member.id))
            if not user or not user.get("shame"):
                continue
            if now_ts() < int(user["shame"].get("expires", 0)):
                continue
            user.pop("shame", None)
            changed = True
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="SHAME expired")
                except (discord.Forbidden, discord.HTTPException):
                    pass
    if changed:
        save_data(data)


class _EffectPickView(discord.ui.View):
    def __init__(self, owner_id: int, target_id: int, duration: int, title: str):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.target_id = target_id
        self.duration = duration
        options = [
            discord.SelectOption(
                label=meta["name"][:100],
                value=key,
                description=meta["desc"][:100],
                emoji=meta.get("icon"),
            )
            for key, meta in EFFECTS.items()
        ][:25]
        select = discord.ui.Select(placeholder="Pick an effect", options=options)
        select.callback = self._picked
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("That list isn't yours.", ephemeral=True)
            return False
        return True

    async def _picked(self, interaction: discord.Interaction):
        effect = interaction.data["values"][0]
        guild = interaction.guild
        target = guild.get_member(self.target_id) if guild else None
        if target is None:
            await interaction.response.send_message("That member is gone.", ephemeral=True)
            return
        data = load_data()
        if _rp_blocked(get_user(data, target.id)):
            await interaction.response.send_message("They opted out of roleplay.", ephemeral=True)
            return
        if effect == "timeout":
            await apply_timeout(target, min(self.duration, 120), "Purple / shame effect")
        apply_effect(data, target.id, effect, self.duration, interaction.user.id)
        save_data(data)
        meta = EFFECTS[effect]
        await interaction.response.send_message(
            f"{meta['icon']} **{meta['name']}** applied to {target.mention} for {self.duration // 60}m. {meta['desc']}",
        )


class _ShameBullyView(discord.ui.View):
    def __init__(self, target_id: int, message_id: int):
        super().__init__(timeout=180)
        self.target_id = target_id
        self.message_id = message_id

    async def _target(self, interaction: discord.Interaction):
        guild = interaction.guild
        return guild.get_member(self.target_id) if guild else None

    @discord.ui.button(label="Apply effect", style=discord.ButtonStyle.danger)
    async def apply_any(self, interaction: discord.Interaction, button: discord.ui.Button):
        target = await self._target(interaction)
        if target is None:
            await interaction.response.send_message("They're gone.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Pick an effect for {target.mention}.",
            view=_EffectPickView(interaction.user.id, target.id, 300, "Shame"),
            ephemeral=True,
        )

    @discord.ui.button(label="Delete message", style=discord.ButtonStyle.secondary)
    async def delete_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.message.reference
        except Exception:
            pass
        deleted = False
        if interaction.channel:
            try:
                msg = await interaction.channel.fetch_message(self.message_id)
                await msg.delete()
                deleted = True
            except Exception:
                deleted = False
        await interaction.response.send_message(
            "Message deleted." if deleted else "Couldn't delete that message.",
            ephemeral=True,
        )

    @discord.ui.button(label="Make fun", style=discord.ButtonStyle.primary)
    async def make_fun(self, interaction: discord.Interaction, button: discord.ui.Button):
        target = await self._target(interaction)
        if target is None:
            await interaction.response.send_message("They're gone.", ephemeral=True)
            return
        data = load_data()
        user = get_user(data, target.id)
        shame = user.get("shame")
        if not shame or now_ts() >= int(shame.get("expires", 0)):
            await interaction.response.send_message("They aren't on SHAME anymore.", ephemeral=True)
            return
        shame["word_limit"] = 4
        save_data(data)
        await interaction.response.send_message(
            f"{target.mention} is being made fun of. More than 4 words and they are muted for 10 seconds.",
        )


def _is_degrading(content: str) -> bool:
    low = content.lower()
    return any(word in low for word in DEGRADING_WORDS)


async def _ab_green(ctx, data, user, spec, target):
    apply_effect(data, target.id, "mute", 300, ctx.author.id)
    extra = None
    if random.random() < 0.45:
        pool = [
            m for m in ctx.guild.members
            if not m.bot and m.id not in {ctx.author.id, target.id}
            and not _rp_blocked(get_user(data, m.id))
        ]
        if pool:
            extra = random.choice(pool[:80])
            apply_effect(data, extra.id, "mute", 180, ctx.author.id)
    save_data(data)
    splash = f"\nIt also caught {extra.mention}." if extra else "\nNobody else was caught."
    await ctx.send(embed=discord.Embed(
        title="🟢 Green",
        description=f"{target.mention} is muted for 5 minutes.{splash}",
        color=discord.Color.from_rgb(80, 180, 90),
    ))


async def _ab_purple(ctx, data, user, spec, target):
    lines = [f"{meta['icon']} **{meta['name']}** — {meta['desc']}" for meta in EFFECTS.values()]
    await ctx.send(
        embed=discord.Embed(
            title="🟣 Purple",
            description=f"Pick an effect for {target.mention}.\n\n" + "\n".join(lines),
            color=discord.Color.from_rgb(150, 80, 200),
        ),
        view=_EffectPickView(ctx.author.id, target.id, 300, "Purple"),
    )


async def _ab_grey_blue(ctx, data, user, spec, target):
    t = get_user(data, target.id)
    t["grey_blue"] = {"marked_at": now_ts(), "expires": now_ts() + 600, "by": str(ctx.author.id)}
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🟦 Grey-Blue",
        description=(
            f"{target.mention} is marked. If the mark lasts longer than 5 seconds, "
            "only short text gets through — more than 3 words is deleted."
        ),
        color=discord.Color.from_rgb(120, 140, 170),
    ))


async def _ab_record(ctx, data, user, spec, target):
    ok = await apply_shame(ctx.guild, target, ctx.author.id, data)
    save_data(data)
    if not ok:
        await ctx.send("Couldn't put them on SHAME. Check role hierarchy and Manage Roles.", delete_after=10)
        return
    await ctx.send(embed=discord.Embed(
        title="📼 Record — SHAME",
        description=(
            f"{target.mention} is on **SHAME** for 20 minutes. The bot removes it when that ends.\n\n"
            "While they talk, anyone can apply an effect, delete the message, or make fun of them. "
            "Making fun of them caps them at 4 words; crossing that mutes them for 10 seconds.\n"
            'Replies that do not include a degrading word (`you loser`, `dork`, `ew`, and the like) '
            "also get SHAME."
        ),
        color=discord.Color.from_rgb(90, 70, 160),
    ))


async def _ab_milk_carton(ctx, data, user, spec, target):
    apply_effect(data, target.id, "stinky", 600, ctx.author.id)
    save_data(data)
    await ctx.send(embed=discord.Embed(
        title="🥛 Milk Carton",
        description=(
            f"{target.mention} is **stinky** for 10 minutes. "
            "Anyone who replies to them directly passes out for about a minute."
        ),
        color=discord.Color.from_rgb(200, 200, 170),
    ))


CUSTOM_ABILITIES.update({
    "green": _ab_green,
    "purple": _ab_purple,
    "grey_blue": _ab_grey_blue,
    "record": _ab_record,
    "milk_carton": _ab_milk_carton,
})


async def _gpg_message_hook(message: discord.Message, data: dict, user: dict) -> bool:
    if user.get("rp_opt_out"):
        return False
    author = message.author
    low = message.content.lower()

    mark = user.get("grey_blue")
    if mark and now_ts() < int(mark.get("expires", 0)):
        if now_ts() - int(mark.get("marked_at", 0)) > 5:
            words = message.content.split()
            if len(words) > 3:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    await author.send("🟦 Grey-Blue — only 3 words get through while you are marked.")
                except Exception:
                    pass
                save_data(data)
                return True
    elif mark:
        user.pop("grey_blue", None)
        save_data(data)

    shame = user.get("shame")
    if shame and now_ts() >= int(shame.get("expires", 0)):
        await clear_shame(message.guild, author, data)
        save_data(data)
        shame = None
    if shame:
        limit = shame.get("word_limit")
        if limit and len(message.content.split()) > int(limit):
            apply_effect(data, author.id, "mute", 10, int(shame.get("by") or author.id))
            save_data(data)
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await author.send("You crossed the word limit. Muted for 10 seconds.")
            except Exception:
                pass
            return True
        try:
            await message.channel.send(
                f"**SHAME** — {author.mention} is being bullied. Apply an effect, delete that message, or make fun of them.",
                view=_ShameBullyView(author.id, message.id),
                delete_after=180,
            )
        except Exception:
            pass

    ref = message.reference
    if ref and ref.message_id and message.channel:
        try:
            parent = await message.channel.fetch_message(ref.message_id)
        except Exception:
            parent = None
        if parent and parent.author and not parent.author.bot and parent.author.id != author.id:
            parent_user = get_user(data, parent.author.id)
            if parent_user.get("shame") and now_ts() < int(parent_user["shame"].get("expires", 0)):
                if not _is_degrading(low) and not user.get("shame"):
                    await apply_shame(message.guild, author, int(parent_user["shame"].get("by") or author.id), data)
                    save_data(data)
                    try:
                        await message.channel.send(
                            f"{author.mention} replied without a degrading word and is flagged as a loser. SHAME applied.",
                            delete_after=20,
                        )
                    except Exception:
                        pass
            if has_effect(parent_user, "stinky") and not _is_immune(user):
                apply_effect(data, author.id, "mute", 60, parent.author.id)
                save_data(data)
                try:
                    await author.timeout(
                        datetime.now(timezone.utc) + timedelta(seconds=60),
                        reason="Passed out from stinky",
                    )
                except Exception:
                    pass
                try:
                    await message.channel.send(
                        f"{author.mention} replied to the stinky message and passed out for a minute.",
                        delete_after=20,
                    )
                except Exception:
                    pass
    return False


@bot.event
async def on_ready():
    if not effect_janitor.is_running():
        effect_janitor.start()
    print("=" * 58)
    print(f"  Zetsubo 2.0 online as {bot.user}")
    print(f"  {len(ROLES)} roles · {len(ABILITY_SPEC)} abilities")
    print(f"  Approval gate: power >= {APPROVAL_POWER_THRESHOLD}")
    print("  Mandate: limited permissions, temporary role grants, server audit log")
    print("=" * 58)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN is not set.")
        print('  export DISCORD_TOKEN="your-token-here"')
        raise SystemExit(1)
    bot.run(token)


if __name__ == "__main__":
    main()
