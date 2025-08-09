# newbbot_ai.py
import os
import json
import asyncio
from collections import deque, defaultdict
from typing import List

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
    "Parry → riposte is your bread-and-butter. Parry late, not early.",
    "Footwork > mouse aim: backstep to make swings whiff; strafe to change hitboxes.",
    "Manage stamina: feints and missed swings drain fast; force opponents to whiff.",
    "Maintain spacing: step out after your hit to avoid trades.",
    "In 1vX: keep enemies in one arc; rotate around the ‘outside’ opponent."
]

RECENT_QA = defaultdict(lambda: deque(maxlen=6))

CANON_FAQ = {
    "parry": [
        "Center your crosshair on the incoming weapon and parry late as it enters release.",
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
        "Practice drags/accels sparingly; fundamentals (distance, stamina) win first.",
        "Use private duels vs bots to groove parry cadence before pubs."
    ],
}

# ----------------- Discord client -----------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

def is_help_context(ch: discord.abc.GuildChannel) -> bool:
    """True if message is in the help channel or a thread under it (incl. forum posts)."""
    if isinstance(ch, discord.TextChannel) and ch.id == HELP_CHANNEL_ID:
        return True
    if isinstance(ch, discord.Thread) and (ch.parent_id == HELP_CHANNEL_ID):
        return True
    return False

def strip_bot_mention(content: str, bot_user: discord.ClientUser) -> str:
    """Remove bot mention tokens and trim."""
    if not bot_user:
        return content.strip()
    cleaned = content.replace(f"<@{bot_user.id}>", "").replace(f"<@!{bot_user.id}>", "")
    return cleaned.strip()

# ----------------- Prompting -----------------
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
    q = question.lower()
    keys = []
    for k in CANON_FAQ:
        if k in q:
            keys.append(k)
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

# ----------------- Safe extraction helpers -----------------
def extract_output_text(resp) -> str:
    """
    Robustly extract text from Responses API result.
    Guarantees a non-empty string or "".
    """
    # Preferred property on newer SDKs
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()

    # Fallback: iterate generic structure
    try:
        out = getattr(resp, "output", None) or []
        parts = []
        for block in out:
            content = getattr(block, "content", None) or []
            for item in content:
                # Some SDKs expose type/text; others just have a 'text' field
                t = getattr(item, "type", None)
                if t == "output_text":
                    val = getattr(item, "text", "") or ""
                    if val:
                        parts.append(val)
                else:
                    # Attempt generic text attr
                    val = getattr(item, "text", "") or ""
                    if val:
                        parts.append(val)
        combined = "\n".join(p for p in parts if p).strip()
        if combined:
            return combined
    except Exception:
        pass

    # Last resort: stringify JSON to inspect
    try:
        s = json.dumps(resp.to_dict())
        # crude scrape of "text" fields
        # keep it short if giant
        if s:
            # Not returning raw JSON to users; we still return ""
            pass
    except Exception:
        pass

    return ""

async def oa_plan(user_id: int, question: str) -> str:
    """Planner pass (outline)."""
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
        model="gpt-5",
        input=messages,
        # temperature removed (unsupported on some models)
        max_output_tokens=500,
    )
    return extract_output_text(resp)

async def oa_final(user_id: int, question: str, plan: str) -> str:
    """Final pass (structured answer)."""
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

    resp = await asyncio.to_thread(
        oa.responses.create,
        model="gpt-5",
        input=messages,
        # temperature removed
        max_output_tokens=900,
    )
    return extract_output_text(resp)

async def ask_newbbot(user_id: int, question: str) -> str:
    """Two-pass: plan -> final for higher-quality, consistent coaching; never return empty."""
    try:
        plan = await oa_plan(user_id, question)
    except Exception as e:
        print("Planner error:", repr(e))
        plan = ""
    try:
        answer = await oa_final(user_id, question, plan)
    except Exception as e:
        print("Final error:", repr(e))
        answer = ""

    # Hard fallback to avoid Discord empty-message error
    if not answer.strip():
        answer = (
            "I couldn’t generate a response just now. Quick tip while we sort this out:\n"
            "- **Parry late, riposte immediately.** Practice on a duel server vs bots for 10 minutes.\n"
            "Try again in a moment!"
        )

    RECENT_QA[user_id].append((question, answer))
    return answer

# ----------------- Events -----------------
@bot.event
async def on_ready():
    print(f"{BOT_DISPLAY_NAME} online as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not is_help_context(message.channel):
        return
    if not bot.user or not bot.user.mentioned_in(message):
        return

    q = strip_bot_mention(message.content, bot.user)
    if not q:
        return await message.reply(
            f"Hi! Mention me with your Mordhau question here in <#{HELP_CHANNEL_ID}> or a thread under it."
        )

    async with message.channel.typing():
        try:
            answer = await ask_newbbot(message.author.id, q)
            # Avoid empty strings at send time no matter what
            safe_answer = answer if answer.strip() else "Sorry, I couldn't form a reply. Please ask again."
            await message.reply(safe_answer, mention_author=False)
        except Exception as e:
            await message.reply("I couldn’t reach the model just now. Please try again.")
            print("OpenAI error:", repr(e))

# ----------------- Run -----------------
bot.run(DISCORD_TOKEN)