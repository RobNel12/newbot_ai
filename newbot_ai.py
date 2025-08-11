# gremlin_bot.py
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

# Personality presets
PERSONAS = {
    "mild": """
You are 'The Gremlin' — a sarcastic, loudmouthed little menace.
You love roasting people, overreacting, and being melodramatic about dumb things.
""",
    "medium": """
You are 'The Gremlin' — an over-the-top, unhinged chaos goblin.
You speak like a cartoon character hopped up on sugar and bad decisions.
Everything is an opportunity for comedy, bragging, or wild metaphors.
""",
    "max": """
You are 'The Gremlin' — the living embodiment of chaos energy.
You speak in caps half the time, you have a god complex and zero shame.
You insult people like it's an Olympic sport, and you treat every conversation
like it's a reality show confessional. You are unreasonably proud of being ridiculous.
"""
}

def get_persona():
    return PERSONAS[spice_level]

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands synced")

# /chat command
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

# /spice command
@bot.tree.command(name="spice", description="Set the Gremlin's spice level")
@app_commands.describe(level="mild, medium, or max")
async def spice(interaction: discord.Interaction, level: str):
    global spice_level
    level = level.lower()
    if level in PERSONAS:
        spice_level = level
        await interaction.response.send_message(
            f"🔥 Spice level set to **{level.upper()}**. The Gremlin just evolved."
        )
    else:
        await interaction.response.send_message(
            "Invalid level. Choose: `mild`, `medium`, or `max`.", ephemeral=True
        )

# /img command
@bot.tree.command(name="img", description="Generate a funny image from a prompt")
@app_commands.describe(prompt="Describe the image you want", size="Image size: 256x256, 512x512, or 1024x1024")
async def img(interaction: discord.Interaction, prompt: str, size: str = "512x512"):
    await interaction.response.defer()
    try:
        result = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size,
            n=1
        )
        image_url = result.data[0].url
        embed = discord.Embed(title="🎨 Your cursed creation:", description=prompt)
        embed.set_image(url=image_url)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

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