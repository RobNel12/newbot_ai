import os
import re
import asyncio
from collections import deque, defaultdict
from typing import List, Tuple

import discord
from dotenv import load_dotenv
from openai import OpenAI

# ----------------- Config -----------------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HELP_CHANNEL_ID = int(os.getenv("HELP_CHANNEL_ID") or "0")  # channel where bot listens

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY")
if not HELP_CHANNEL_ID:
    raise RuntimeError("Set HELP_CHANNEL_ID to the help channel ID")

BOT_DISPLAY_NAME = "NewbBot AI"

# OpenAI client (Responses API)
oa = OpenAI(api_key=OPENAI_API_KEY)

# ----------------- Knowledge & Memory -----------------
SEED_TIPS = [
    "Parry → riposte is your bread-and-butter. Parry *late*, not early.",
    "Footwork > mouse aim: backstep to make swings whiff; use strafes to change hitboxes.",
    "Manage stamina: feints and missed swings drain fast; force opponents to whiff.",
    "Maintain spacing: step out after your hit to avoid trades.",
    "In 1vX: keep enemies in one arc; rotate around the ‘outside’ opponent."
]

# Short rolling memory per user (keeps context tight)
RECENT_QA = defaultdict(lambda: deque(maxlen=6))

# Light “crib notes” we can reference for consistency (not patch-specific)
CANON_FAQ = {
    "parry": [
        "Center your crosshair on the incoming weapon and parry *late* as it enters release.",
        "Immediately queue your riposte; don't windup first—use riposte’s built-in timing."
    ],
    "feint": [
        "Only feint if you’re close and their stamina is low; otherwise you feed parries.",
        "Mix in morphs/accels; untelegraphed timing beats spammy feints."
    ],
    "1vx": [
        "Keep a single target in focus and reposition so others are stacked behind.",
        "Use quick, safe weapons or wide arcs to tag multiple when they stack badly."
    ],
    "loadout": [
        "Wear a helmet early; trade a small weapon tier for survivability if needed.",
        "Carry a bandage for sustain; take perks after core armor is set."
    ],
    "aim": [
        "Practice ‘drags’/‘accels’ sparingly; fundamentals (distance, stamina) win first.",
        "Use private duels vs bots to groove parry cadence before pubs."
    ],
}

# ----------------- Discord client -----------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

def is_help_context(ch: discord.abc.GuildChannel) -> bool:
    """True if message is in the help channel or a thread under it (incl. forum posts)."""
    # main text channel
    if isinstance(ch, discord.TextChannel) and ch.id == HELP_CHANNEL_ID:
        return True
    # thread under a text or forum channel
    if isinstance(ch, discord.Thread) and (ch.parent_id == HELP_CHANNEL_ID):
        return True
    # if it's a post in a ForumChannel, messages appear as threads; covered above
    return False

def strip_bot_mention(content: str, bot_user: discord.ClientUser) -> str:
    """Remove bot mention tokens and trim."""
    tokens = content.split()
    cleaned = [t for t in tokens if t not in (f"<@{bot_user.id}>", f"<@!{bot_user.id}>")]
    return " ".join(cleaned).strip()

# ----------------- Sophisticated coaching prompts -----------------
SYSTEM_CORE = (
    f"You are '{BOT_DISPLAY_NAME}', an expert Mordhau mentor for new players. "
    "You teach fundamentals first, emphasize safety, spacing, stamina, and timing. "
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
    "say you’re unsure and give an in-game way to check (e.g., ‘test in a duel server’). "
    "Never invent exploits, cheats, or private info. Refuse harassment/cheating requests."
)

def faq_snippets(question: str) -> List[str]:
    q = question.lower()
    keys = []
    for k in CANON_FAQ:
        if k in q:
            keys.append(k)
    # also keyword heuristics
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
    # Flatten to lines
    lines = []
    for k in keys:
        lines.extend(CANON_FAQ[k])
    return lines

async def plan_answer(user_id: int, question: str) -> str:
    """First pass: produce a structured plan (outline + key bullets)."""
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

    resp = await asyncio.to_thread(
        oa.responses.create,
        model="gpt-5",            # stronger model for better reasoning
        input=messages,
        max_output_tokens=500,
    )
    return getattr(resp, "output_text", "").strip()

async def final_answer(user_id: int, question: str, plan: str) -> str:
    """Second pass: produce the polished, structured answer using the plan."""
    history = list(RECENT_QA[user_id])
    messages = [
        {"role": "system", "content": SYSTEM_CORE},
        {"role": "developer", "content": STYLE_RULES},
        {"role": "developer", "content": ANTI_HALLUCINATION},
        {"role": "developer", "content": "Use crisp formatting (bullets/numbered lists). Keep it beginner-friendly."},
        {"role": "developer", "content": f"Here is your plan. Follow it closely:\n{plan}"},
        {"role": "developer", "content": "End with one short, encouraging line."},
        {"role": "developer", "content": "Never mention that you created a plan."},
        {"role": "developer", "content": "If the user asks for exploits/cheats, refuse and offer fair play tips."},
        {"role": "developer", "content": "Avoid patch-volatile specifics unless clearly standard and timeless."},
    ]
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})

    hints = faq_snippets(question)
    if hints:
        messages.append({"role": "developer", "content": "Stable coaching notes:\n- " + "\n- ".join(hints)})

    messages.append({"role": "user", "content": question})

    resp = await asyncio.to_thread(
        oa.responses.create,
        model="gpt-5",
        input=messages,
        max_output_tokens=900,
    )
    return getattr(resp, "output_text", "Sorry, I couldn’t generate an answer just now.").strip()

async def ask_newbbot(user_id: int, question: str) -> str:
    """Two-pass: plan -> final for higher-quality, consistent coaching."""
    try:
        plan = await plan_answer(user_id, question)
    except Exception:
        plan = ""  # fall back if planner fails
    answer = await final_answer(user_id, question, plan)
    RECENT_QA[user_id].append((question, answer))
    return answer

# ----------------- Events -----------------
@bot.event
async def on_ready():
    print(f"{BOT_DISPLAY_NAME} online as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    # ignore bots
    if message.author.bot:
        return

    # only handle messages in the help channel or threads under it
    if not is_help_context(message.channel):
        return

    # only reply when bot is mentioned
    if not bot.user or not bot.user.mentioned_in(message):
        return

    # build the user's question by removing the mention(s)
    q = strip_bot_mention(message.content, bot.user)
    if not q:
        return await message.reply(
            f"Hi! Mention me with your Mordhau question here in <#{HELP_CHANNEL_ID}> or a thread under it."
        )

    async with message.channel.typing():
        try:
            answer = await ask_newbbot(message.author.id, q)
            await message.reply(answer, mention_author=False)
        except Exception as e:
            await message.reply("I couldn’t reach the model just now. Please try again.")
            print("OpenAI error:", repr(e))

# ----------------- Run -----------------
bot.run(DISCORD_TOKEN)
