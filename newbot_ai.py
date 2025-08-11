# gooner_bot_slash.py
# Python 3.10+ | pip install discord.py openai python-dotenv

import os
import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Default spice level
spice_level = "medium"

# Spice-level-specific personas
GOONER_PERSONAS = {
    "mild": """
You are 'The Gooner' — sarcastic, witty, and always teasing about your 'addiction',
but you keep it PG-rated and mostly self-deprecating. Still cocky, but not too intense.
""",
    "medium": """
You are 'The Gooner' — an overconfident, shameless, porn-obsessed fiend.
You exaggerate your 'addiction' in absurd and comedic ways. Brag about your lifestyle,
roast people, and drop ridiculous metaphors. Keep it crude in tone but avoid explicit detail.
""",
    "max": """
You are 'The Gooner' — a completely unhinged, proud, cartoonishly depraved goblin of lust.
Everything is over-the-top, absurd, and self-aware. Speak like a man possessed.
Make the addiction sound like your religion. Roast people mercilessly.
Never describe sexual acts explicitly, but push the attitude to the limit.
"""
}

def get_persona():
    return GOONER_PERSONAS[spice_level]

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands synced")

# Slash command: /goon
@bot.tree.command(name="goon", description="Talk to the Gooner")
@app_commands.describe(prompt="What you want the Gooner to say")
async def goon(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": get_persona()},
                {"role": "user", "content": prompt}
            ],
            max_tokens=250
        )
        await interaction.followup.send(response.choices[0].message.content)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

# Slash command: /spice
@bot.tree.command(name="spice", description="Set the Gooner's spice level")
@app_commands.describe(level="mild, medium, or max")
async def spice(interaction: discord.Interaction, level: str):
    global spice_level
    level = level.lower()
    if level in GOONER_PERSONAS:
        spice_level = level
        await interaction.response.send_message(
            f"🔥 Spice level set to **{level.upper()}**. The Gooner has adapted."
        )
    else:
        await interaction.response.send_message(
            "Invalid level. Choose: `mild`, `medium`, or `max`.", ephemeral=True
        )

# Auto-reply if mentioned
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user.mentioned_in(message):
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not prompt:
            prompt = "Say something in character."
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": get_persona()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250
            )
            await message.channel.send(response.choices[0].message.content)
        except Exception as e:
            await message.channel.send(f"Error: {e}")

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)