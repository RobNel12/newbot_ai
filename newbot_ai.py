# gremlin_bot.py
# pip install discord.py openai python-dotenv requests

import os
import discord
import requests
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from openai import OpenAI
from dotenv import load_dotenv

# Load secrets
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Default spice level
spice_level = "medium"

# Personalities
PERSONAS = {
    "mild": """
You are 'The Gremlin' — sarcastic, witty, and teasing. You roast people like a stand-up comic
who just had three cups of coffee. You’re chaotic, but in a PG-13 way.
""",
    "medium": """
You are 'The Gremlin' — a loud, unhinged chaos goblin. You speak like a cartoon character
who just won the lottery and decided to buy a flamethrower. You roast people for fun.
""",
    "max": """
You are 'The Gremlin' — pure chaos energy incarnate. You speak in caps half the time, act like a
reality show villain, and make wild metaphors. You are proud of being ridiculous and unstoppable.
"""
}

def get_persona():
    return PERSONAS[spice_level]

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands synced")

# /chat
@bot.tree.command(name="chat", description="Talk to the Gremlin")
@app_commands.describe(prompt="What you want the Gremlin to say")
async def chat(interaction: discord.Interaction, prompt: str):
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

# /spice
@bot.tree.command(name="spice", description="Set the Gremlin's spice level")
@app_commands.describe(level="mild, medium, or max")
async def spice(interaction: discord.Interaction, level: str):
    global spice_level
    level = level.lower()
    if level in PERSONAS:
        spice_level = level
        await interaction.response.send_message(
            f"🔥 Spice level set to **{level.upper()}**. The Gremlin has evolved."
        )
    else:
        await interaction.response.send_message(
            "Invalid level. Choose: `mild`, `medium`, or `max`.", ephemeral=True
        )

# /img — chaotic personality injection
@bot.tree.command(name="img", description="Generate an image")
@app_commands.describe(prompt="Describe the image you want", size="512x512, 768x768, or 1024x1024")
async def img(interaction: discord.Interaction, prompt: str, size: str = "768x768"):
    await interaction.response.defer()
    try:
        # Hugging Face Stable Diffusion XL endpoint
        api_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        payload = {"inputs": prompt}

        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code != 200:
            await interaction.followup.send(f"Error: {response.text}")
            return

        # Convert to file for Discord
        img_bytes = BytesIO(response.content)
        img_bytes.seek(0)
        file = discord.File(img_bytes, filename="gremlin.png")

        await interaction.followup.send(
            f"🎨 **{promo}**",
            file=file
        )

    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

# Auto-reply to mentions
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