import discord
from discord import app_commands
from discord.ext import commands

class Poem(commands.Cog):
    def __init__(self, bot, openai_client):
        self.bot = bot
        self.openai_client = openai_client

    @app_commands.command(name="poem", description="Make the bot write a poem for someone.")
    @app_commands.describe(
        target="The user to write the poem for",
        style="The style of poem you want"
    )
    @app_commands.choices(style=[
        app_commands.Choice(name="Romantic", value="romantic"),
        app_commands.Choice(name="Diss", value="diss"),
        app_commands.Choice(name="Wholesome", value="wholesome"),
        app_commands.Choice(name="Silly", value="silly")
    ])
    async def poem(self, interaction: discord.Interaction, target: discord.Member, style: app_commands.Choice[str]):
        await interaction.response.defer()

        style_prompts = {
            "romantic": f"Write a heartfelt, romantic poem for {target.display_name}. "
                        "Make it warm, affectionate, and beautiful — like a love letter in verse.",
            "diss": f"Write a clever, scathing roast poem for {target.display_name}. "
                    "Be creative, witty, and savage but keep it playful enough to be funny.",
            "wholesome": f"Write a wholesome, uplifting poem for {target.display_name}. "
                         "Make it kind, encouraging, and genuinely heartwarming.",
            "silly": f"Write a ridiculous, goofy, and absurd poem for {target.display_name}. "
                     "Make it lighthearted and funny with unexpected twists."
        }

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": style_prompts[style.value]},
                    {"role": "user", "content": f"Write the full poem for {target.display_name} now."}
                ],
                max_tokens=200
            )

            poem_text = response.choices[0].message.content
            await interaction.followup.send(poem_text)

        except Exception as e:
            await interaction.followup.send(f"⚠ Error generating poem: {e}")

async def setup(bot):
    from newbot_ai import openai_client  # import from your main bot file
    await bot.add_cog(Poem(bot, openai_client))