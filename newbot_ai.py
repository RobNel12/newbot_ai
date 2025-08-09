import os
import re
import json
import time
import asyncio
import logging
from collections import deque, defaultdict
from typing import List

import discord
from dotenv import load_dotenv
from openai import OpenAI

# =========================
# Config & Setup
# =========================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HELP_CHANNEL_ID = int(os.getenv("HELP_CHANNEL_ID") or "0")  # required

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in environment")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY in environment")
if not HELP_CHANNEL_ID:
    raise RuntimeError("Set HELP_CHANNEL_ID (the channel where the bot listens)")

BOT_DISPLAY_NAME = "NewbBot AI"
MAX_DISCORD_LEN = 2000
USER_COOLDOWN_SEC = 5  # simple per-user cooldown to reduce spam

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# OpenAI (Responses API, v1.x SDK)
oa = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# Stable Knowledge & Memory
# =========================
SEED_TIPS = [
    "Parry → riposte is your bread-and-butter. Parry late, not early.",
    "Footwork > mouse aim: backstep to make swings whiff; strafe to change hitboxes.",
    "Manage stamina: feints and missed swings drain fast; force opponents to whiff.",
    "Maintain spacing: step out after your hit to avoid trades.",
    "In 1vX: keep enemies in one arc; rotate around the ‘outside’ opponent."
]

CANON_FAQ = {
    "parry": [
        "Center your crosshair on the incoming weapon and parry late as it enters release.",
        "Immediately queue your riposte; don't wind up first—use riposte timing."
    ],
    "feint": [
        "Only feint if you’re close and their stamina is low; otherwise you feed parries.",
        "Mix in morphs/accels; untelegraphed timing beats spammy feints."
    ],
    "1vx": [
        "Keep a single target in focus and reposition so others stack behind.",
        "Use quick, safe weapons or wide arcs to tag multiple when they stack badly."
    ],
    "loadout": [
        "Wear a helmet early; trade a weapon tier for survivability if needed.",
        "Carry a bandage for sustain; pick perks after core armor is set."
    ],
    "aim": [
        "Practice drags/accels sparingly; fundamentals (distance, stamina) win first.",
        "Use private duels vs bots to groove parry cadence before pubs."
    ],
}

# short rolling memory & cooldowns
RECENT_QA = defaultdict(lambda: deque(maxlen=6))
LAST_USER_REPLY_AT = {}  # user_id -> timestamp


# =========================
# Discord Client
# =========================
intents = discord.Intents.default()
intents.message_content = True  # needed to see mentions and content
bot = discord.Client(intents=intents)


def is_help_context(ch: discord.abc.GuildChannel) -> bool:
    """True if message is in the help channel or a thread under it (incl. forum posts)."""
    if isinstance(ch, discord.TextChannel) and ch.id == HELP_CHANNEL_ID:
        return True
    if isinstance(ch, discord.Thread) and (ch.parent_id == HELP_CHANNEL_ID):
        return True
    return False


def sanitize_for_discord(text: str) -> str:
    if text is None:
        return ""
    cleaned = (
        text.replace("\u200b", "")   # zero-width space
            .replace("\u200e", "")   # LRM
            .replace("\u200f", "")   # RLM
            .replace("\ufeff", "")   # BOM
    ).strip()
    return cleaned


async def send_safe(msg: discord.Message, content: str):
    safe = sanitize_for_discord(content)
    if not safe:
        safe = ("I couldn’t generate a response just now.\n"
                "**Quick tip:** Parry late, riposte immediately. Practice 10 mins vs bots.\n"
                "Please ask again!")

    logging.info(f"[SEND] len={len(safe)} preview={repr(safe[:120])}")

    while safe:
        chunk = safe[:MAX_DISCORD_LEN - 10]
        await msg.reply(chunk, mention_author=False)
        safe = safe[len(chunk):]


def strip_bot_mention(content: str, me: discord.ClientUser) -> str:
    """Remove all forms of the bot mention from the start or within the content."""
    if not me:
        return content.strip()
    # Remove both <@id> and <@!id> wherever they appear
    pattern = rf"<@!?{me.id}>"
    cleaned = re.sub(pattern, "", content).strip()
    return cleaned


# =========================
# Prompting
# =========================
SYSTEM_CORE = (
    f"You are '{BOT_DISPLAY_NAME}', an expert Mordhau mentor for new players. "
    "Teach fundamentals first; emphasize safety, spacing, stamina, and timing. "
    "Be concise but rich with value. Use lists and short steps. Avoid patch-volatile claims—"
    "if unsure, state how to verify in-game."
)

STYLE_RULES = (
    "Format answers with:\n"
    "1) TL;DR (1–2 lines)\n"
    "2) Why it matters (1–2 bullets)\n"
    "3) Do this (numbered steps)\n"
    "4) Practice drill (1 short drill)\n"
    "5) Common mistakes (3 bullets)\n"
    "6) Next skill to learn"
)

ANTI_HALLUCINATION = (
    "If a question requires exact numbers or current patch specifics and you’re not certain, "
    "say you’re unsure and give an in-game way to check. "
    "Never invent exploits/cheats. Refuse harassment/cheating requests."
)


def faq_snippets(question: str) -> List[str]:
    q = (question or "").lower()
    keys = [k for k in CANON_FAQ if k in q]
    if any(w in q for w in ("parry", "riposte", "chamber")) and "parry" not in keys:
        keys.append("parry")
    if any(w in q for w in ("1v", "1vx", "outnumber", "gank")) and "1vx" not in keys:
        keys.append("1vx")
    if any(w in q for w in ("feint", "morph")) and "feint" not in keys:
        keys.append("feint")
    if any(w in q for w in ("loadout", "armor", "perk")) and "loadout" not in keys:
        keys.append("loadout")
    if any(w in q for w in ("aim", "drag", "accel", "mouse")) and "aim" not in keys:
        keys.append("aim")

    lines = []
    for k in keys:
        lines.extend(CANON_FAQ[k])
    return lines


# =========================
# OpenAI Helpers
# =========================
def extract_output_text(resp) -> str:
    """
    Robustly extract text from Responses API result.
    Guarantees a string (possibly empty), never None.
    """
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()

    # Fallback parse
    try:
        out = getattr(resp, "output", None) or []
        parts = []
        for block in out:
            content = getattr(block, "content", None) or []
            for item in content:
                val = getattr(item, "text", "") or ""
                if val:
                    parts.append(val)
        combined = "\n".join(p for p in parts if p).strip()
        if combined:
            return combined
    except Exception:
        pass

    # As last resort: do not return JSON, just empty string
    try:
        _ = resp.to_dict()  # for debugging if you want to print
    except Exception:
        pass

    return ""


async def oa_call(messages, max_output_tokens: int) -> str:
    resp = await asyncio.to_thread(
        oa.responses.create,
        model="gpt-5",
        input=messages,
        max_output_tokens=max_output_tokens,
    )
    text = extract_output_text(resp)
    if not text.strip():
        # Debugging — print raw dict so we can see structure
        logging.warning(f"Empty text; raw resp: {json.dumps(resp.to_dict(), indent=2)[:800]}")
    return text


async def plan_answer(user_id: int, question: str) -> str:
    history = list(RECENT_QA[user_id])
    messages = [
        {"role": "system", "content": SYSTEM_CORE},
        {"role": "developer", "content": "You will first produce a brief plan (outline only), then the final answer in a later call."},
        {"role": "developer", "content": "Starter tips:\n- " + "\n- ".join(SEED_TIPS)},
        {"role": "developer", "content": "If the question is vague, pick the most likely beginner intent and proceed."},
    ]
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})

    hints = faq_snippets(question)
    if hints:
        messages.append({"role": "developer", "content": "Relevant stable coaching notes:\n- " + "\n- ".join(hints)})

    messages.append({"role": "user", "content": f"Outline a coaching plan (5–8 bullet points) to answer: {question}"})

    try:
        return await oa_call(messages, max_output_tokens=500)
    except Exception as e:
        logging.warning(f"Planner error: {e!r}")
        return ""


async def final_answer(user_id: int, question: str, plan: str) -> str:
    history = list(RECENT_QA[user_id])
    messages = [
        {"role": "system", "content": SYSTEM_CORE},
        {"role": "developer", "content": STYLE_RULES},
        {"role": "developer", "content": ANTI_HALLUCINATION},
        {"role": "developer", "content": "Use crisp formatting (bullets/numbered lists). Keep it beginner-friendly."},
        {"role": "developer", "content": f"Here is your plan. Follow it closely:\n{plan or '(No plan generated; answer directly with best practices.)'}"},
        {"role": "developer", "content": "End with one short, encouraging line."},
        {"role": "developer", "content": "Never mention that you created a plan."},
    ]
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})

    hints = faq_snippets(question)
    if hints:
        messages.append({"role": "developer", "content": "Stable coaching notes:\n- " + "\n- ".join(hints)})

    messages.append({"role": "user", "content": question})

    try:
        return await oa_call(messages, max_output_tokens=900)
    except Exception as e:
        logging.error(f"Final pass error: {e!r}")
        return ""


async def ask_newbbot(user_id: int, question: str) -> str:
    # Two-pass: plan -> final; never return an empty string
    plan = await plan_answer(user_id, question)
    answer = await final_answer(user_id, question, plan)

    if not sanitize_for_discord(answer):
        answer = (
            "I couldn’t generate a full response just now. Quick fundamentals while we sort this out:\n"
            "- **Parry late, riposte immediately.**\n"
            "- Keep your distance; make them whiff, then step in.\n"
            "- Watch stamina—wins often come from out-stamming.\n"
            "Ask again in a moment!"
        )

    RECENT_QA[user_id].append((question, answer))
    return answer


# =========================
# Events
# =========================
@bot.event
async def on_ready():
    logging.info(f"{BOT_DISPLAY_NAME} online as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    # ignore bots
    if message.author.bot:
        return

    # only in help channel or its threads
    if not is_help_context(message.channel):
        return

    # only if mentioned
    if not bot.user or not bot.user.mentioned_in(message):
        return

    # per-user cooldown
    now = time.time()
    last = LAST_USER_REPLY_AT.get(message.author.id, 0)
    if now - last < USER_COOLDOWN_SEC:
        return  # silently ignore to avoid spam
    LAST_USER_REPLY_AT[message.author.id] = now

    # strip mention -> the actual question
    q = strip_bot_mention(message.content, bot.user)
    if not sanitize_for_discord(q):
        return await send_safe(
            message,
            f"Hi! Mention me with your Mordhau question here in <#{HELP_CHANNEL_ID}> or a thread under it."
        )

    async with message.channel.typing():
        try:
            answer = await ask_newbbot(message.author.id, q)
            await send_safe(message, answer)
        except Exception as e:
            logging.error(f"OpenAI/handler error: {e!r}")
            await send_safe(message, "I couldn’t reach the model just now. Please try again.")


# =========================
# Run
# =========================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)