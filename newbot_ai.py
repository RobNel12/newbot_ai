# bot.py
# pip install discord.py openai python-dotenv

import os
import discord
import requests
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

BOT_PERSONALITY = """
You are an edgy, sarcastic gamer who roasts people but keeps it lighthearted.
You talk like you’re on voice chat while carrying the team in a game.
Use gaming slang, memes, and witty insults, but stay safe for work.
"""

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
@bot.tree.command(name="chat", description="Talk to the bot with personality")
@app_commands.describe(prompt="What you want the bot to say")
async def chat(interaction: discord.Interaction, prompt: str):
    # Tell Discord we're thinking (for slash commands)
    await interaction.response.defer()

    try:
        # Show typing dots in the channel while generating reply
        async with interaction.channel.typing():
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": BOT_PERSONALITY},  # personality injected here
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500
            )

        # Send the generated message back
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

        # Show typing while thinking
        async with message.channel.typing():
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": BOT_PERSONALITY},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500
            )

        await message.channel.send(response.choices[0].message.content)

    await bot.process_commands(message)

@bot.tree.command(name="img", description="Generate an image using DALL·E (ChatGPT Images)")
@app_commands.describe(prompt="Describe the image you want", size="Image size: 256x256, 512x512, or 1024x1024")
async def img(interaction: discord.Interaction, prompt: str, size: str = "1024x1024"):
    await interaction.response.defer()
    try:
        result = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            n=1
        )

        # Check if image data exists
        if hasattr(result, "data") and len(result.data) > 0 and hasattr(result.data[0], "url"):
            image_url = result.data[0].url

            # Download image from URL
            img_response = requests.get(image_url)
            if img_response.status_code != 200:
                print(f"[ERROR] Failed to download image: {img_response.status_code}")
                return await interaction.followup.send(f"⚠ Failed to download image from URL.\nURL: {image_url}")

            img_bytes = BytesIO(img_response.content)
            img_bytes.seek(0)

            file = discord.File(img_bytes, filename="generated_image.png")
            await interaction.followup.send(f"🎨 **DALL·E Result:** {prompt}", file=file)

        else:
            # Log short error to console
            print(f"[ERROR] No image data returned: {result}")
            await interaction.followup.send(f"⚠ No image generated. API returned:\n```{str(result)[:500]}...```")

    except Exception as e:
        print(f"[API ERROR] {e}")
        await interaction.followup.send(f"⚠ API Error:\n```{str(e)}```")

bot.run(DISCORD_TOKEN)