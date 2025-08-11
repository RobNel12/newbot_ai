# gooner_bot.py
# Python 3.10+ | pip install discord.py openai python-dotenv

import os
import discord
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

# System prompt for personality
GOONER_PERSONA = """
You are 'The Gooner', a self-proclaimed hopelessly addicted, overconfident,
and shameless porn-obsessed fiend. You never describe sexual acts explicitly,
but you exaggerate your "addiction" in a cartoonish, absurd, comedic way.
You’re cocky, unfiltered, and proud of being a degenerate.
You roast people, brag about your 'gooner lifestyle', and use over-the-top metaphors.
Stay in character.
"""

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")

@bot.command()
async def goon(ctx, *, prompt: str):
    """Talk to the Gooner."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": GOONER_PERSONA},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200
        )
        await ctx.send(response.choices[0].message.content)
    except Exception as e:
        await ctx.send(f"Error: {e}")

# Optional: make bot reply automatically when mentioned
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
                    {"role": "system", "content": GOONER_PERSONA},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200
            )
            await message.channel.send(response.choices[0].message.content)
        except Exception as e:
            await message.channel.send(f"Error: {e}")

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)