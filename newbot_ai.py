# bot.py
# pip install discord.py openai python-dotenv requests

import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from io import BytesIO
import requests

# ====== Load Environment Variables ======
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")  # Hugging Face API key

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
@bot.tree.command(name="chat", description="Talk to the bot")
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

# ====== /img command (Qwen-Image via Hugging Face API) ======
@bot.tree.command(name="img", description="Generate an image with Qwen-Image via Hugging Face API")
@app_commands.describe(prompt="Describe the image you want")
async def img(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        api_url = "https://api-inference.huggingface.co/models/Qwen/Qwen-Image"
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        payload = {"inputs": prompt}

        # Send request to Hugging Face API
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code != 200:
            return await interaction.followup.send(f"❌ API Error: {response.text}")

        # Convert image bytes to file
        img_bytes = BytesIO(response.content)
        img_bytes.seek(0)

        file = discord.File(img_bytes, filename="qwen_image.png")
        await interaction.followup.send(f"🎨 **Qwen-Image Result:** {prompt}", file=file)

    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}")

bot.run(DISCORD_TOKEN)