# bot.py
# pip install discord.py openai python-dotenv

import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

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

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands ready")

# ====== /chat command ======
@bot.tree.command(name="chat", description="Talk to ChatGPT")
@app_commands.describe(prompt="What you want the bot to say")
async def chat(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250
        )
        await interaction.followup.send(response.choices[0].message.content)
    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}")

# ====== Mention reply ======
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if bot.user.mentioned_in(message):
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not prompt:
            prompt = "Say something in character."
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250
            )
            await message.channel.send(response.choices[0].message.content)
        except Exception as e:
            await message.channel.send(f"⚠ Error: {e}")
    await bot.process_commands(message)

# ====== /img command (DALL·E via OpenAI) ======
@bot.tree.command(name="img", description="Generate an image using DALL·E (ChatGPT Images)")
@app_commands.describe(prompt="Describe the image you want", size="Image size: 256x256, 512x512, or 1024x1024")
async def img(interaction: discord.Interaction, prompt: str, size: str = "1024x1024"):
    await interaction.response.defer()
    try:
        result = openai_client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size,
            n=1
        )
        image_url = result.data[0].url
        await interaction.followup.send(f"🎨 **Image Result:** {image_url}")
    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}")

bot.run(DISCORD_TOKEN)