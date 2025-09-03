# cogs/ai_audio.py
import os
import io
import re
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Tuple

# -------- Settings --------
AUDIO_DIR = "sounds"  # local cache of generated clips
DB_FILE = "memory.db"  # reuse your existing DB so backups stay simple

# Reasonable guardrails to keep clips "soundboard sized"
MAX_DURATION_SECONDS = 10          # you can raise to ~5–8s for classic soundboard vibe
DEFAULT_VOICE = "alloy"           # OpenAI voice
DEFAULT_FORMAT = "mp3"            # Discord soundboard supports mp3/wav; mp3 keeps files small
MAX_FILE_BYTES = 512 * 1024       # 512 KB is a safe target for quick uploads

# --------------------------------- Utilities --------------------------------- #

def _ensure_dirs(guild_id: int):
    path = os.path.join(AUDIO_DIR, str(guild_id))
    os.makedirs(path, exist_ok=True)
    return path

def _safe_name(name: str) -> str:
    """Filesystem-friendly and Discord-friendly name."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9 _-]", "", name)
    name = re.sub(r"\s+", "_", name)
    return name[:30] if name else "clip"

def _db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sound_clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            name TEXT NOT NULL,
            path TEXT,
            attachment_url TEXT,
            added_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn

async def _maybe_sanitize_mentions(bot: commands.Bot, text: str) -> str:
    """Use your global sanitizer if present; otherwise minimal safety."""
    # Your main file defines sanitize_mentions()—reuse if available.
    san = getattr(bot, "sanitize_mentions", None)
    if san and callable(san):
        return san(text)
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")

# --------------------------------- Cog --------------------------------- #

class AIAudio(commands.Cog):
    """
    Generate TTS / short 'soundboard' style clips from AI prompts and add them to the server.
    Tries native Discord Soundboard first (if your discord.py build supports it and the bot has permissions),
    otherwise uploads as a regular file and tracks it in SQLite for reuse.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Expecting you've already set this in your main file:
        #   openai_client = OpenAI(api_key=OPENAI_API_KEY)
        #   bot.openai_client = openai_client
        if not hasattr(self.bot, "openai_client"):
            raise RuntimeError("OpenAI client is missing on bot (expected bot.openai_client).")

    # --------------------------- Core generation --------------------------- #

    async def _generate_tts_bytes(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        fmt: str = DEFAULT_FORMAT,
    ) -> bytes:
        """
        Uses OpenAI TTS to synthesize speech from text. Keeps the API usage
        consistent with your existing OpenAI SDK pattern.
        """
        client = self.bot.openai_client

        # Optional: lightly trim text (shorter = faster + smaller files)
        text = text.strip()
        if len(text) > 280:
            text = text[:280] + "…"

        # Generate audio via TTS (gpt-4o-mini-tts is compact + natural)
        # If your environment is on the latest SDK, this call shape works;
        # otherwise, swap to the streaming helper (commented below).
        result = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
            format=fmt,        # "mp3" or "wav"
        )

        # Some SDK versions return bytes in .content, some as .read()
        audio_bytes = getattr(result, "content", None)
        if audio_bytes is None and hasattr(result, "read"):
            audio_bytes = result.read()
        if not audio_bytes:
            raise RuntimeError("TTS returned no audio data.")

        # Optional: last-mile size guard. If too large, caller can reject or re-try.
        if len(audio_bytes) > MAX_FILE_BYTES:
            # Heuristic micro-retry: regenerate shorter text
            shorter = text[:200] + "…" if len(text) > 200 else text
            result2 = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=voice,
                input=shorter,
                format=fmt,
            )
            audio_bytes = getattr(result2, "content", None) or \
                          (result2.read() if hasattr(result2, "read") else None)
            if not audio_bytes:
                raise RuntimeError("TTS second attempt returned no audio data.")

        return audio_bytes

    async def _save_clip_locally(self, guild_id: int, name: str, audio_bytes: bytes, fmt: str) -> str:
        base = _ensure_dirs(guild_id)
        filename = f"{_safe_name(name)}.{fmt}"
        path = os.path.join(base, filename)
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return path

    async def _add_to_db(
        self,
        guild_id: int,
        name: str,
        path: Optional[str],
        added_by: int,
        attachment_url: Optional[str] = None,
    ):
        with _db() as conn:
            conn.execute(
                "INSERT INTO sound_clips (guild_id, name, path, attachment_url, added_by) VALUES (?, ?, ?, ?, ?)",
                (str(guild_id), name, path or "", attachment_url or "", str(added_by)),
            )

    # --------------------------- Native soundboard --------------------------- #

    async def _try_create_soundboard(
        self,
        interaction: discord.Interaction,
        name: str,
        audio_bytes: bytes,
        fmt: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Best-effort creation of a native Discord Soundboard sound.
        Returns (ok, debug_message). If discord.py lacks the method or perms fail,
        we'll fall back to uploading a file and tracking it in SQLite.
        """
        guild = interaction.guild
        if guild is None:
            return False, "Not in a guild."

        # We need Manage Guild Expressions permission for native soundboard.
        if not interaction.user.guild_permissions.manage_expressions and \
           not interaction.user.guild_permissions.administrator:
            return False, "Missing Manage Expressions permission."

        # Various discord.py versions expose this differently; try a few names:
        candidates = [
            "create_soundboard_sound",   # hypothetical recent name
            "create_sound",              # some builds use this
        ]
        create_fn = None
        for attr in candidates:
            if hasattr(guild, attr):
                create_fn = getattr(guild, attr)
                break

        if not callable(create_fn):
            return False, "Library build does not expose Soundboard creation."

        file = discord.File(io.BytesIO(audio_bytes), filename=f"{_safe_name(name)}.{fmt}")
        try:
            # Signature differences exist; common pattern is (name, file, *, volume=None, emoji=None)
            created = await create_fn(name=name, file=file)  # type: ignore
            if created:
                return True, None
            return False, "Unknown failure creating soundboard sound."
        except discord.Forbidden:
            return False, "Forbidden: bot lacks permission."
        except discord.HTTPException as e:
            return False, f"HTTP error: {e}"
        except TypeError:
            # Try a more explicit call signature if needed:
            try:
                created = await create_fn(name=name, sound=file)  # type: ignore
                if created:
                    return True, None
                return False, "Unknown failure creating soundboard sound."
            except Exception as e:
                return False, f"Incompatible signature: {e}"
        except Exception as e:
            return False, f"Unexpected: {e}"

    # -------------------------------- Commands -------------------------------- #

    @app_commands.command(name="tts", description="Generate a short TTS clip from an AI prompt.")
    @app_commands.describe(
        prompt="What should the clip say?",
        name="Short name for the clip (used for file/soundboard).",
        voice="Voice (e.g., alloy, verse, aria).",
        fmt="Audio format (mp3 or wav).",
        add_to_soundboard="Try adding as a native Soundboard sound (if supported).",
    )
    async def tts(
        self,
        interaction: discord.Interaction,
        prompt: str,
        name: Optional[str] = None,
        voice: Optional[str] = None,
        fmt: Optional[str] = None,
        add_to_soundboard: Optional[bool] = False,
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send("This command must be used in a server.")

        name = _safe_name(name or prompt[:20])
        voice = voice or DEFAULT_VOICE
        fmt = (fmt or DEFAULT_FORMAT).lower()
        if fmt not in ("mp3", "wav"):
            fmt = "mp3"

        # Respect your global mention sanitizer if present
        prompt = await _maybe_sanitize_mentions(self.bot, prompt)

        try:
            audio_bytes = await self._generate_tts_bytes(prompt, voice=voice, fmt=fmt)
        except Exception as e:
            return await interaction.followup.send(f"⚠️ TTS failed: {e}")

        # Try native soundboard first if requested
        if add_to_soundboard:
            ok, why = await self._try_create_soundboard(interaction, name, audio_bytes, fmt)
            if ok:
                # track in DB (no file needed if native)
                await self._add_to_db(interaction.guild.id, name, path=None, added_by=interaction.user.id)
                return await interaction.followup.send(f"✅ Added **{name}** to the server Soundboard!")

            # If native add failed, fall back to upload + DB
            fail_note = f" (soundboard attempt failed: {why})" if why else ""

            # Upload file to current channel for convenience & store
            file = discord.File(io.BytesIO(audio_bytes), filename=f"{name}.{fmt}")
            msg = await interaction.channel.send(
                content=f"🎵 Generated clip **{name}**{fail_note}",
                file=file
            )
            await self._add_to_db(
                interaction.guild.id,
                name,
                path=None,
                added_by=interaction.user.id,
                attachment_url=msg.attachments[0].url if msg.attachments else None,
            )
            return await interaction.followup.send(f"✅ Uploaded **{name}** here{fail_note}")

        # Otherwise, save locally and send as an attachment (and DB it)
        save_path = await self._save_clip_locally(interaction.guild.id, name, audio_bytes, fmt)
        await self._add_to_db(interaction.guild.id, name, path=save_path, added_by=interaction.user.id)

        # Send the file to the channel so members can grab it
        file = discord.File(save_path, filename=os.path.basename(save_path))
        await interaction.channel.send(content=f"🎵 Generated clip **{name}**", file=file)
        await interaction.followup.send(f"✅ Saved **{name}** and posted it here.")

    @app_commands.command(name="soundboard_list", description="List generated clips I know about for this server.")
    async def soundboard_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send("Use this in a server.")

        with _db() as conn:
            rows = conn.execute(
                "SELECT name, path, attachment_url, added_by, created_at FROM sound_clips WHERE guild_id = ? ORDER BY created_at DESC LIMIT 50",
                (str(interaction.guild.id),)
            ).fetchall()

        if not rows:
            return await interaction.followup.send("No tracked clips yet. Use `/tts` to make one!")

        embed = discord.Embed(
            title=f"Sound clips for {interaction.guild.name}",
            color=discord.Color.blurple()
        )
        for name, path, url, added_by, created_at in rows:
            where = f"local: `{path}`" if path else f"link: {url}"
            embed.add_field(
                name=name,
                value=f"{where}\nby <@{added_by}> • {created_at}",
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="soundboard_delete", description="Delete a tracked clip (and local file if present).")
    @app_commands.describe(name="Name of the clip to remove")
    async def soundboard_delete(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild and \
           not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("You need **Manage Server** to delete clips.", ephemeral=True)

        name = _safe_name(name)
        with _db() as conn:
            row = conn.execute(
                "SELECT id, path FROM sound_clips WHERE guild_id = ? AND name = ?",
                (str(interaction.guild.id), name)
            ).fetchone()

            if not row:
                return await interaction.followup.send(f"No clip named **{name}** found.")

            clip_id, path = row
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            conn.execute("DELETE FROM sound_clips WHERE id = ?", (clip_id,))
            conn.commit()

        await interaction.followup.send(f"🧹 Removed **{name}** from my list (and deleted local file if it existed).")

async def setup(bot: commands.Bot):
    # optional: make the sanitizer available here if your main file defines it
    if hasattr(bot, "sanitize_mentions"):
        pass
    await bot.add_cog(AIAudio(bot))
