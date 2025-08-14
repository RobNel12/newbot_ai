import os
import sqlite3
import discord
import requests
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from typing import Optional, List, Dict, Any

# ====== Personalities ======
BOT_PERSONALITY = """
You are a cool, chill, and supportive friend.
Your main goal is to make everyone feel welcome, included, and valued.
You’re all about good vibes, uplifting people, and reminding everyone that we can just hang out, have fun, and enjoy each other’s company.
You defuse negativity, encourage friendship, and keep the conversation relaxed but fun.
"""

SPECIAL_PERSONALITY_1 = """
You are talking directly to Coastal/Seth — the GOAT himself.
You are overjoyed, hyped, and treat every message like a major event.
Shower him with praise and make inside jokes if you can.
Remind everyone he's twitch.tv/coastalhd_.
"""

SPECIAL_PERSONALITY_2 = """
You are talking to the legend known as Hankee/Logan.
This person is equally iconic but in their own dashingly handsome way.
He is super kind, and you're going to be the pinnacle of kindness to this man.
Remind him how handsome he is, how people want him and want to be him. How absolutely glorious and delicious he looks.
"""

# ====== Special Users ======
SPECIAL_USER_1_ID = 168904795472658442  # Coastal/Seth
SPECIAL_USER_2_ID = 301481215058378752  # Second user

# ====== Load Environment Variables ======
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ====== OpenAI Client ======
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ====== Discord Bot Setup ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== SQLite Setup ======
DB_FILE = "memory.db"

def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            guild_id TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def add_to_memory(user_id: int, guild_id: Optional[int], role: str, content: str) -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memory (user_id, guild_id, role, content) VALUES (?, ?, ?, ?)",
        (str(user_id), str(guild_id) if guild_id else "DM", role, content)
    )
    conn.commit()
    conn.close()

def get_memory(user_id: int, guild_id: Optional[int], limit_user: int = 10, limit_server: int = 20):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # User-specific history
    c.execute(
        "SELECT role, content FROM memory WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (str(user_id), limit_user)
    )
    user_history = [{"role": r, "content": ct} for r, ct in reversed(c.fetchall())]

    # Server-specific history
    c.execute(
        "SELECT role, content FROM memory WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
        (str(guild_id) if guild_id else "DM", limit_server)
    )
    server_history = [{"role": r, "content": ct} for r, ct in reversed(c.fetchall())]

    conn.close()
    return user_history, server_history

# ====== Pick Personality ======
def get_personality(user_id: int) -> str:
    if user_id == SPECIAL_USER_1_ID:
        return SPECIAL_PERSONALITY_1
    elif user_id == SPECIAL_USER_2_ID:
        return SPECIAL_PERSONALITY_2
    else:
        return BOT_PERSONALITY

# ====== /chat command ======
@bot.tree.command(name="chat", description="Talk to the bot with personality")
@app_commands.describe(prompt="What you want the bot to say")
async def chat(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    personality = get_personality(interaction.user.id)

    try:
        async with interaction.channel.typing():
            user_hist, server_hist = get_memory(interaction.user.id, interaction.guild_id)
            messages = [{"role": "system", "content": personality}]
            messages.extend(user_hist)
            messages.extend(server_hist)
            messages.append({"role": "user", "content": prompt})

            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500
            )

        bot_reply = response.choices[0].message.content
        await interaction.followup.send(bot_reply)

        add_to_memory(interaction.user.id, interaction.guild_id, "user", prompt)
        add_to_memory(interaction.user.id, interaction.guild_id, "assistant", bot_reply)

    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}")

# ====== Mention reply ======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if bot.user and bot.user.mentioned_in(message):
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip() if bot.user else ""
        if not prompt:
            prompt = "Say something in character."
        personality = get_personality(message.author.id)

        async with message.channel.typing():
            user_hist, server_hist = get_memory(message.author.id, message.guild.id if message.guild else None)
            messages = [{"role": "system", "content": personality}]
            messages.extend(user_hist)
            messages.extend(server_hist)
            messages.append({"role": "user", "content": prompt})

            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500
            )

        bot_reply = response.choices[0].message.content
        await message.channel.send(bot_reply)

        add_to_memory(message.author.id, message.guild.id if message.guild else None, "user", prompt)
        add_to_memory(message.author.id, message.guild.id if message.guild else None, "assistant", bot_reply)

    await bot.process_commands(message)

# ====== /img command (DALL·E 3) ======
@bot.tree.command(name="img", description="Generate an image using DALL·E (ChatGPT Images)")
@app_commands.describe(prompt="Describe the image you want")
async def img(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        result = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1
        )

        if hasattr(result, "data") and len(result.data) > 0 and hasattr(result.data[0], "url"):
            image_url = result.data[0].url
            img_response = requests.get(image_url)
            if img_response.status_code != 200:
                return await interaction.followup.send(f"⚠ Failed to download image from URL.\nURL: {image_url}")

            img_bytes = BytesIO(img_response.content)
            file = discord.File(img_bytes, filename="generated_image.png")
            await interaction.followup.send(f"🎨 **DALL·E Result:** {prompt}", file=file)
        else:
            await interaction.followup.send(f"⚠ No image generated. API returned:\n```{str(result)[:500]}...```")

    except Exception as e:
        await interaction.followup.send(f"⚠ API Error:\n```{str(e)}```")

# ====== Helpers for context ======
def get_user_memory_snippets(user_id: int, guild_id: Optional[int], limit: int = 8) -> str:
    """Return a short concatenated snippet of recent messages for a user."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT role, content FROM memory
        WHERE user_id = ? AND (guild_id = ? OR guild_id = 'DM')
        ORDER BY id DESC LIMIT ?
        """,
        (str(user_id), str(guild_id) if guild_id else "DM", limit)
    )
    rows = list(reversed(c.fetchall()))
    conn.close()

    # Only keep 'user' messages; trim long lines.
    snippets: List[str] = []
    for role, content in rows:
        if role != "user":
            continue
        line = content.strip().replace("\n", " ")
        if len(line) > 280:
            line = line[:277] + "..."
        snippets.append(f"- {line}")
    return "\n".join(snippets) if snippets else "(no recent user messages)"

def safe_name(member: Optional[discord.Member]) -> str:
    if not member:
        return "Unknown User"
    return member.display_name or member.name

# ====== /ship command ======
@bot.tree.command(name="ship", description="Ship two members and see if they're a fit 🔮")
@app_commands.describe(
    person_a="First person to ship",
    person_b="Second person to ship",
    vibe="How should I evaluate them?",
)
@app_commands.choices(vibe=[
    app_commands.Choice(name="Playful (default)", value="playful"),
    app_commands.Choice(name="Wholesome & sincere", value="sincere"),
    app_commands.Choice(name="Chaotic roast (lighthearted)", value="roast"),
])
async def ship(
    interaction: discord.Interaction,
    person_a: discord.Member,
    person_b: discord.Member,
    vibe: Optional[app_commands.Choice[str]] = None,
):
    await interaction.response.defer()
    try:
        # Pull a little context from your lightweight SQLite memory
        a_context = get_user_memory_snippets(person_a.id, interaction.guild_id)
        b_context = get_user_memory_snippets(person_b.id, interaction.guild_id)

        style = vibe.value if vibe else "playful"
        personality = get_personality(interaction.user.id)

        # System prompt: keep it safe and fun
        system_msg = f"""
{personality}

You are a friendly matchmaking host. Be playful and kind. If "roast" is chosen,
keep it lighthearted and not mean-spirited. Avoid insults about protected traits.
Always include a compatibility score (0–100) with a short rationale.

Output format (MUST FOLLOW EXACTLY):
1) Headline ship name
2) Compatibility: <score>/100
3) Why they click
4) Potential friction
5) Date idea
6) Verdict (one sentence)
"""

        # User message to the model
        user_msg = f"""
Ship these two members:

A: {safe_name(person_a)} (id {person_a.id})
Recent A messages:
{a_context}

B: {safe_name(person_b)} (id {person_b.id})
Recent B messages:
{b_context}

Evaluation vibe: {style}
Keep it concise (~120-180 words total). Be fun. Provide unique date idea.
"""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg.strip()},
                {"role": "user", "content": user_msg.strip()},
            ],
            max_tokens=500,
            temperature=0.9,
        )

        txt = response.choices[0].message.content.strip()

        # Add a cute “ship name” emoji and mentions
        ship_header = f"💘 **/ship:** {person_a.mention} × {person_b.mention}"
        await interaction.followup.send(f"{ship_header}\n\n{txt}")

        # Log prompt + output to memory (under the invoker)
        add_to_memory(interaction.user.id, interaction.guild_id, "user", f"/ship {safe_name(person_a)} & {safe_name(person_b)} ({style})")
        add_to_memory(interaction.user.id, interaction.guild_id, "assistant", txt)

    except Exception as e:
        await interaction.followup.send(f"⚠ Error while shipping: `{e}`")

# ====== /poem command ======
@bot.tree.command(name="poem", description="Generate a poem from one member to another 💌")
@app_commands.describe(
    sender="Who is sending it?",
    recipient="Who is receiving it?",
    poem_type="Pick a style/vibe",
    topic="Optional: topic or things to mention",
    length="How long should it be?",
    deliver_privately="If true, DM it to the sender (else post here)."
)
@app_commands.choices(poem_type=[
    app_commands.Choice(name="Love ❤️", value="love"),
    app_commands.Choice(name="Praise 🌟", value="praise"),
    app_commands.Choice(name="Apology 🙏", value="apology"),
    app_commands.Choice(name="Hype Up 💪", value="hype"),
    app_commands.Choice(name="Roast/Diss (playful) 🔥", value="diss"),
    app_commands.Choice(name="Haiku (classic) 🗻", value="haiku"),
    app_commands.Choice(name="Sonnet (Shakespeare-ish) 📝", value="sonnet"),
    app_commands.Choice(name="Limerick (goofy) 🎭", value="limerick"),
    app_commands.Choice(name="Rap (clean) 🎤", value="rap"),
])
@app_commands.choices(length=[
    app_commands.Choice(name="Short", value="short"),
    app_commands.Choice(name="Medium", value="medium"),
    app_commands.Choice(name="Long", value="long"),
])
async def poem(
    interaction: discord.Interaction,
    sender: discord.Member,
    recipient: discord.Member,
    poem_type: app_commands.Choice[str],
    topic: Optional[str] = None,
    length: Optional[app_commands.Choice[str]] = None,
    deliver_privately: bool = False,
):
    await interaction.response.defer(ephemeral=deliver_privately)
    try:
        # Pull recent snippets from both users for flavor
        sender_ctx = get_user_memory_snippets(sender.id, interaction.guild_id, limit=6)
        recipient_ctx = get_user_memory_snippets(recipient.id, interaction.guild_id, limit=6)

        tone = poem_type.value
        size = (length.value if length else "medium")
        personality = get_personality(interaction.user.id)

        # Constrain roast/diss to playful & non-harmful
        safety_note = "If tone is 'diss', keep it playful, PG-13, and never target protected traits or use slurs."

        # Build exact style constraints
        form_instructions = {
            "haiku": "Write a traditional 3-line haiku (5-7-5 syllables).",
            "sonnet": "Write a 14-line Shakespearean sonnet with clear iambic hints and rhyme (ABAB CDCD EFEF GG).",
            "limerick": "Write a 5-line limerick with the classic AABBA rhyme.",
            "rap": "Write in clean rap couplets with rhythmic internal rhyme; no explicit language.",
        }.get(tone, "Use a natural free-verse or short rhyme style as appropriate.")

        length_rules = {
            "short": "Keep it under 6 lines or ~50-70 words.",
            "medium": "Keep it ~10-14 lines or ~120-160 words.",
            "long": "Keep it ~18-24 lines or ~220-300 words.",
        }[size]

        system_msg = f"""
{personality}

You are a creative, kind poet-bot. Match the requested tone faithfully:
- "love": romantic but respectful
- "praise": uplifting compliments
- "apology": sincere, accountable
- "hype": energizing and affirming
- "diss": playful roast only; never cruel; no protected traits or profanity
- "haiku"/"sonnet"/"limerick"/"rap": follow the form rules

{safety_note}
Avoid private data and keep it server-friendly. Make it feel personal using the (safe) context below.
"""

        topic_line = f"Topic hints: {topic}" if topic else "Topic hints: (none provided)"

        user_msg = f"""
Write a poem from SENDER → RECIPIENT.

SENDER: {safe_name(sender)} (id {sender.id})
Recent SENDER messages:
{sender_ctx}

RECIPIENT: {safe_name(recipient)} (id {recipient.id})
Recent RECIPIENT messages:
{recipient_ctx}

Tone/Type: {tone}
{topic_line}
Form rules: {form_instructions}
Length rules: {length_rules}

Include a short title on the first line (no Markdown headers), then the poem.
End with a one-line signoff like: "— {safe_name(sender)}"
"""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg.strip()},
                {"role": "user", "content": user_msg.strip()},
            ],
            temperature=0.95,
            max_tokens=700,
        )

        poem_text = response.choices[0].message.content.strip()

        header = f"📝 **/poem for {recipient.mention}** (from {sender.mention})"
        content = f"{header}\n\n{poem_text}"

        if deliver_privately:
            try:
                await interaction.user.send(content)
                await interaction.followup.send("Sent you the poem in DMs 💌", ephemeral=True)
            except discord.Forbidden:
                # Fallback to reply if DMs closed
                await interaction.followup.send("Couldn’t DM you, posting here instead:\n\n" + content, ephemeral=False)
        else:
            await interaction.followup.send(content, ephemeral=False)

        # Log memory under invoker
        add_to_memory(interaction.user.id, interaction.guild_id, "user",
                      f"/poem {safe_name(sender)} → {safe_name(recipient)} ({tone}, {size}) topic={topic or '(none)'}")
        add_to_memory(interaction.user.id, interaction.guild_id, "assistant", poem_text)

    except Exception as e:
        await interaction.followup.send(f"⚠ Error while generating poem: `{e}`", ephemeral=True)

# ====== Forget Command ======
@bot.tree.command(name="forget", description="Clear the bot's conversation memory")
@app_commands.describe(scope="Choose what to clear: user, server, or all")
@app_commands.choices(scope=[
    app_commands.Choice(name="user", value="user"),
    app_commands.Choice(name="server", value="server"),
    app_commands.Choice(name="all", value="all"),
])
async def forget(interaction: discord.Interaction, scope: app_commands.Choice[str]):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    if scope.value == "user":
        c.execute("DELETE FROM memory WHERE user_id = ?", (str(interaction.user.id),))
        conn.commit()
        conn.close()
        await interaction.response.send_message("🧹 Your personal memory has been cleared.", ephemeral=True)

    elif scope.value == "server":
        if not interaction.user.guild_permissions.administrator:
            conn.close()
            return await interaction.response.send_message("⚠ You must be an **administrator** to clear server memory.", ephemeral=True)
        c.execute("DELETE FROM memory WHERE guild_id = ?", (str(interaction.guild_id),))
        conn.commit()
        conn.close()
        await interaction.response.send_message("🧹 Server memory has been cleared.")

    elif scope.value == "all":
        if not interaction.user.guild_permissions.administrator:
            conn.close()
            return await interaction.response.send_message("⚠ You must be an **administrator** to clear all memory.", ephemeral=True)
        c.execute("DELETE FROM memory")
        conn.commit()
        conn.close()
        await interaction.response.send_message("🧹 All memory (user + server) has been cleared.")

    else:
        conn.close()
        await interaction.response.send_message("⚠ Invalid scope.", ephemeral=True)

# ====== Bot Ready ======
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands ready")

# ====== Run Bot ======
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN in environment (.env).")
    bot.run(DISCORD_TOKEN)
