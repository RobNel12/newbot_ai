# cogs/rpg.py
import asyncio
import random
import sqlite3
import time
from typing import Optional, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands


DB_FILE = "rpg.db"

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS rpg_users (
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    coins INTEGER NOT NULL DEFAULT 100,
    hp INTEGER NOT NULL DEFAULT 20,
    atk INTEGER NOT NULL DEFAULT 5,
    def INTEGER NOT NULL DEFAULT 3,
    lvl INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    last_mine INTEGER DEFAULT 0,
    last_train INTEGER DEFAULT 0,
    last_adventure INTEGER DEFAULT 0,
    last_gamble INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);
"""

CREATE_INV = """
CREATE TABLE IF NOT EXISTS rpg_inventory (
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    item TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id, item)
);
"""

SHOP_STOCK = [
    # name, cost, effect, value
    ("Small Potion", 20, "hp", 10),
    ("Iron Dagger", 60, "atk", 2),
    ("Leather Vest", 60, "def", 2),
    ("Training Manual", 120, "xp", 25),
]

MINE_COOLDOWN = 60          # seconds
TRAIN_COOLDOWN = 45
ADVENTURE_COOLDOWN = 60
GAMBLE_COOLDOWN = 10


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _connect() as c:
        c.execute(CREATE_USERS)
        c.execute(CREATE_INV)
_init_db()


def _now() -> int:
    return int(time.time())


class RPGView(discord.ui.View):
    """Main menu View with a Select to navigate sub-panels."""
    def __init__(self, cog: "RPGCog", user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = str(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the opener can use the controls.
        return str(interaction.user.id) == self.user_id

    @discord.ui.select(
        placeholder="Choose an activity…",
        min_values=1, max_values=1,
        options=[
            discord.SelectOption(label="Profile", description="View your stats & wallet", emoji="🧙"),
            discord.SelectOption(label="Inventory", description="Items you own", emoji="🎒"),
            discord.SelectOption(label="Shop", description="Buy items to boost stats", emoji="🛒"),
            discord.SelectOption(label="Training Ring", description="Train to raise stats", emoji="🥊"),
            discord.SelectOption(label="Mine / Work", description="Earn wages with a short cooldown", emoji="⛏️"),
            discord.SelectOption(label="Gambling", description="Dice & coinflip (use responsibly!)", emoji="🎲"),
            discord.SelectOption(label="Adventure", description="Fight a quick encounter for XP/loot", emoji="🗺️"),
        ]
    )
    async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]
        if choice == "Profile":
            embed = self.cog.embed_profile(interaction.user.id, interaction.guild_id)
            await interaction.response.edit_message(embed=embed, view=self)
        elif choice == "Inventory":
            embed = self.cog.embed_inventory(interaction.user.id, interaction.guild_id)
            await interaction.response.edit_message(embed=embed, view=self)
        elif choice == "Shop":
            embed = self.cog.embed_shop(interaction.user.id, interaction.guild_id)
            await interaction.response.edit_message(embed=embed, view=ShopView(self.cog, self.user_id))
        elif choice == "Training Ring":
            embed = self.cog.embed_training(interaction.user.id, interaction.guild_id)
            await interaction.response.edit_message(embed=embed, view=TrainView(self.cog, self.user_id))
        elif choice == "Mine / Work":
            result = await self.cog.do_mine(interaction.user.id, interaction.guild_id)
            await interaction.response.edit_message(embed=result, view=self)
        elif choice == "Gambling":
            embed = self.cog.embed_gamble()
            await interaction.response.edit_message(embed=embed, view=GambleView(self.cog, self.user_id))
        elif choice == "Adventure":
            result = await self.cog.do_adventure(interaction.user.id, interaction.guild_id)
            await interaction.response.edit_message(embed=result, view=self)


class ShopView(discord.ui.View):
    def __init__(self, cog: "RPGCog", user_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="Buy Potion (20)", style=discord.ButtonStyle.primary)
    async def buy_potion(self, interaction: discord.Interaction, _):
        embed = self.cog.handle_purchase(interaction.user.id, interaction.guild_id, "Small Potion")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Buy Dagger (60)", style=discord.ButtonStyle.primary)
    async def buy_dagger(self, interaction: discord.Interaction, _):
        embed = self.cog.handle_purchase(interaction.user.id, interaction.guild_id, "Iron Dagger")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Buy Vest (60)", style=discord.ButtonStyle.primary)
    async def buy_vest(self, interaction: discord.Interaction, _):
        embed = self.cog.handle_purchase(interaction.user.id, interaction.guild_id, "Leather Vest")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Buy Manual (120)", style=discord.ButtonStyle.success)
    async def buy_manual(self, interaction: discord.Interaction, _):
        embed = self.cog.handle_purchase(interaction.user.id, interaction.guild_id, "Training Manual")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            embed=self.cog.embed_profile(interaction.user.id, interaction.guild_id),
            view=RPGView(self.cog, interaction.user.id)
        )


class TrainView(discord.ui.View):
    def __init__(self, cog: "RPGCog", user_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="Train (45s cd, 15c)", style=discord.ButtonStyle.success, emoji="🏋️")
    async def do_train(self, interaction: discord.Interaction, _):
        embed = await self.cog.do_train(interaction.user.id, interaction.guild_id)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            embed=self.cog.embed_profile(interaction.user.id, interaction.guild_id),
            view=RPGView(self.cog, interaction.user.id)
        )


class GambleView(discord.ui.View):
    def __init__(self, cog: "RPGCog", user_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="Roll d20 (bet 10)", style=discord.ButtonStyle.primary, emoji="🎲")
    async def roll_d20(self, interaction: discord.Interaction, _):
        embed = await self.cog.do_roll(interaction.user.id, interaction.guild_id)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Coinflip (bet 10)", style=discord.ButtonStyle.primary, emoji="🪙")
    async def coinflip(self, interaction: discord.Interaction, _):
        embed = await self.cog.do_coinflip(interaction.user.id, interaction.guild_id)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            embed=self.cog.embed_profile(interaction.user.id, interaction.guild_id),
            view=RPGView(self.cog, interaction.user.id)
        )


class RPGCog(commands.Cog):
    """Fun games & mini-RPG with a single menu entry point (/rpg)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Utilities ----------
    def ensure_user(self, user_id: int, guild_id: int):
        with _connect() as c:
            cur = c.execute("SELECT 1 FROM rpg_users WHERE user_id=? AND guild_id=?", (str(user_id), str(guild_id)))
            if not cur.fetchone():
                c.execute("INSERT INTO rpg_users (user_id, guild_id) VALUES (?, ?)", (str(user_id), str(guild_id)))
                c.commit()

    def get_user(self, user_id: int, guild_id: int) -> sqlite3.Row:
        self.ensure_user(user_id, guild_id)
        with _connect() as c:
            row = c.execute(
                "SELECT * FROM rpg_users WHERE user_id=? AND guild_id=?",
                (str(user_id), str(guild_id))
            ).fetchone()
        return row

    def set_user(self, user_id: int, guild_id: int, **updates):
        if not updates:
            return
        keys = ", ".join(f"{k}=?" for k in updates.keys())
        vals = list(updates.values()) + [str(user_id), str(guild_id)]
        with _connect() as c:
            c.execute(f"UPDATE rpg_users SET {keys} WHERE user_id=? AND guild_id=?", vals)
            c.commit()

    def inv_add(self, user_id: int, guild_id: int, item: str, qty: int = 1):
        with _connect() as c:
            row = c.execute(
                "SELECT qty FROM rpg_inventory WHERE user_id=? AND guild_id=? AND item=?",
                (str(user_id), str(guild_id), item)
            ).fetchone()
            if row:
                c.execute(
                    "UPDATE rpg_inventory SET qty=qty+? WHERE user_id=? AND guild_id=? AND item=?",
                    (qty, str(user_id), str(guild_id), item)
                )
            else:
                c.execute(
                    "INSERT INTO rpg_inventory (user_id, guild_id, item, qty) VALUES (?, ?, ?, ?)",
                    (str(user_id), str(guild_id), item, qty)
                )
            c.commit()

    def inv_all(self, user_id: int, guild_id: int) -> List[Tuple[str, int]]:
        with _connect() as c:
            rows = c.execute(
                "SELECT item, qty FROM rpg_inventory WHERE user_id=? AND guild_id=? ORDER BY item",
                (str(user_id), str(guild_id))
            ).fetchall()
        return [(r["item"], r["qty"]) for r in rows]

    # ---------- Embeds ----------
    def embed_profile(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        e = discord.Embed(title="🧙 Your Profile", color=discord.Color.blurple())
        e.add_field(name="Level", value=str(u["lvl"]))
        e.add_field(name="XP", value=str(u["xp"]))
        e.add_field(name="HP", value=str(u["hp"]))
        e.add_field(name="ATK", value=str(u["atk"]))
        e.add_field(name="DEF", value=str(u["def"]))
        e.add_field(name="Coins", value=str(u["coins"]))
        e.set_footer(text="Use the menu to explore activities.")
        return e

    def embed_inventory(self, user_id: int, guild_id: int) -> discord.Embed:
        items = self.inv_all(user_id, guild_id)
        if not items:
            desc = "_Empty._ Visit the Shop to buy gear & items."
        else:
            desc = "\n".join([f"• **{name}** ×{qty}" for name, qty in items])
        e = discord.Embed(title="🎒 Inventory", description=desc, color=discord.Color.dark_teal())
        return e

    def embed_shop(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        lines = [f"• **{n}** — {c} coins ({eff}+{v})" for (n, c, eff, v) in SHOP_STOCK]
        e = discord.Embed(
            title="🛒 The Little Goblin Shop",
            description="\n".join(lines),
            color=discord.Color.green()
        )
        e.set_footer(text=f"You have {u['coins']} coins.")
        return e

    def embed_training(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        e = discord.Embed(
            title="🥊 Training Ring",
            description="Pay **15 coins** and roll 2d6 to raise a random stat (+1~+3). 45s cooldown.",
            color=discord.Color.orange()
        )
        e.set_footer(text=f"Coins: {u['coins']}")
        return e

    def embed_gamble(self) -> discord.Embed:
        return discord.Embed(
            title="🎲 Gambling Hall",
            description="• Roll d20: 10 coin bet. 15+ pays 25, 20 pays 50.\n• Coinflip: 10 coin bet. Win pays 20.\n10s cooldown.",
            color=discord.Color.purple()
        )

    # ---------- Actions ----------
    async def add_xp_and_level(self, user_id: int, guild_id: int, gained: int) -> str:
        u = self.get_user(user_id, guild_id)
        xp = u["xp"] + gained
        lvl = u["lvl"]
        # Simple curve: next level at 100 * lvl
        ding = False
        while xp >= 100 * lvl:
            xp -= 100 * lvl
            lvl += 1
            ding = True
        self.set_user(user_id, guild_id, xp=xp, lvl=lvl)
        return f"**+{gained} XP**" + (" — **LEVEL UP!** 🎉" if ding else "")

    def handle_purchase(self, user_id: int, guild_id: int, item_name: str) -> discord.Embed:
        stock = {n: (cost, eff, val) for (n, cost, eff, val) in SHOP_STOCK}
        if item_name not in stock:
            return discord.Embed(title="Shop", description="That item is not available.", color=discord.Color.red())
        cost, eff, val = stock[item_name]
        u = self.get_user(user_id, guild_id)
        if u["coins"] < cost:
            return discord.Embed(title="Shop", description="You don't have enough coins.", color=discord.Color.red())
        # Take coins, apply effect immediately (and give item for flavor)
        coins = u["coins"] - cost
        updates = {"coins": coins}
        if eff == "hp":
            updates["hp"] = max(1, u["hp"] + val)
        elif eff == "atk":
            updates["atk"] = u["atk"] + val
        elif eff == "def":
            updates["def"] = u["def"] + val
        elif eff == "xp":
            # XP effect handled via add_xp_and_level for ding message
            pass
        self.set_user(user_id, guild_id, **updates)
        self.inv_add(user_id, guild_id, item_name, 1)

        extra = ""
        if eff == "xp":
            extra = f"\n{asyncio.run(self.add_xp_and_level(user_id, guild_id, val))}"
        msg = f"Purchased **{item_name}** for **{cost}** coins. {('Effect: ' + eff + f' +{val}') if eff!='xp' else 'Gained XP!'}{extra}"
        return discord.Embed(title="🛒 Purchase Complete", description=msg, color=discord.Color.green())

    async def do_mine(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        now = _now()
        cd = max(0, u["last_mine"] + MINE_COOLDOWN - now)
        if cd > 0:
            return discord.Embed(title="⛏️ Mine", description=f"You're tired. Try again in **{cd}s**.", color=discord.Color.red())
        payout = random.randint(12, 28)
        self.set_user(user_id, guild_id, coins=u["coins"] + payout, last_mine=now)
        return discord.Embed(
            title="⛏️ Mine",
            description=f"You dig for a bit and earn **{payout}** coins.",
            color=discord.Color.dark_teal()
        )

    async def do_train(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        now = _now()
        cd = max(0, u["last_train"] + TRAIN_COOLDOWN - now)
        if cd > 0:
            return discord.Embed(title="🥵 Rest Up", description=f"Training cooldown: **{cd}s**.", color=discord.Color.red())
        if u["coins"] < 15:
            return discord.Embed(title="🥊 Training", description="You need **15** coins.", color=discord.Color.red())

        # Pay and roll improvements
        coins = u["coins"] - 15
        stat = random.choice(["hp", "atk", "def"])
        gain = random.randint(1, 3)
        updates = {"coins": coins, "last_train": now, stat: max(1, u[stat] + gain)}
        self.set_user(user_id, guild_id, **updates)
        xp_text = await self.add_xp_and_level(user_id, guild_id, random.randint(8, 15))

        return discord.Embed(
            title="🏋️ Training Complete",
            description=f"You focused on **{stat.upper()}** and gained **+{gain}**.\n{xp_text}",
            color=discord.Color.orange()
        )

    async def do_roll(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        now = _now()
        cd = max(0, u["last_gamble"] + GAMBLE_COOLDOWN - now)
        if cd > 0:
            return discord.Embed(title="⏱️ Cooldown", description=f"Gambling available in **{cd}s**.", color=discord.Color.red())
        if u["coins"] < 10:
            return discord.Embed(title="🎲 Roll d20", description="You need **10** coins to bet.", color=discord.Color.red())

        roll = random.randint(1, 20)
        coins = u["coins"] - 10
        payout = 0
        if roll == 20:
            payout = 50
        elif roll >= 15:
            payout = 25
        coins += payout
        self.set_user(user_id, guild_id, coins=coins, last_gamble=now)

        desc = f"You rolled **d20 = {roll}**.\n"
        if payout > 0:
            desc += f"Winner! You receive **{payout}** coins."
        else:
            desc += "No luck this time."
        return discord.Embed(title="🎲 d20 Result", description=desc, color=discord.Color.purple())

    async def do_coinflip(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        now = _now()
        cd = max(0, u["last_gamble"] + GAMBLE_COOLDOWN - now)
        if cd > 0:
            return discord.Embed(title="⏱️ Cooldown", description=f"Gambling available in **{cd}s**.", color=discord.Color.red())
        if u["coins"] < 10:
            return discord.Embed(title="🪙 Coinflip", description="You need **10** coins to bet.", color=discord.Color.red())

        side = random.choice(["Heads", "Tails"])
        win = random.choice([True, False])
        coins = u["coins"] - 10 + (20 if win else 0)
        self.set_user(user_id, guild_id, coins=coins, last_gamble=now)
        return discord.Embed(
            title="🪙 Coinflip",
            description=f"The coin shows **{side}** — you **{'WIN' if win else 'lose'}**.",
            color=discord.Color.purple()
        )

    async def do_adventure(self, user_id: int, guild_id: int) -> discord.Embed:
        u = self.get_user(user_id, guild_id)
        now = _now()
        cd = max(0, u["last_adventure"] + ADVENTURE_COOLDOWN - now)
        if cd > 0:
            return discord.Embed(title="🗺️ Resting", description=f"You can adventure again in **{cd}s**.", color=discord.Color.red())

        # Generate an encounter
        enemies = [
            ("Tunnel Rat", 10, 3, 1, 15, (8, 16)),
            ("Mischief Slime", 14, 4, 2, 18, (10, 20)),
            ("Roadside Bandit", 18, 5, 3, 22, (12, 25)),
        ]
        name, ehp, eatk, edef, xp_reward, coin_rng = random.choice(enemies)

        # simple round: player and enemy each roll d20 + atk, minus opponent def
        p_roll = random.randint(1, 20) + u["atk"]
        e_roll = random.randint(1, 20) + eatk
        p_score = max(1, p_roll - edef)
        e_score = max(1, e_roll - u["def"])

        result_lines = [
            f"You encounter **{name}**!",
            f"Your strike total: **{p_roll} - {edef} = {p_score}**",
            f"{name} strike total: **{e_roll} - {u['def']} = {e_score}**",
        ]

        coins = u["coins"]
        if p_score >= e_score:
            won = True
            xp_text = await self.add_xp_and_level(user_id, guild_id, xp_reward)
            coin_gain = random.randint(*coin_rng)
            coins += coin_gain
            result_lines.append(f"**Victory!** You earn **{coin_gain}** coins. {xp_text}")
        else:
            won = False
            # Take a small HP knock (not lethal), minimum 1 HP
            hp_loss = random.randint(1, 4)
            new_hp = max(1, u["hp"] - hp_loss)
            self.set_user(user_id, guild_id, hp=new_hp)
            result_lines.append(f"**Defeat.** You lose **{hp_loss} HP** (non-lethal).")

        self.set_user(user_id, guild_id, coins=coins, last_adventure=now)

        color = discord.Color.brand_green() if won else discord.Color.red()
        return discord.Embed(title="🗺️ Adventure", description="\n".join(result_lines), color=color)

    # ---------- Slash Command ----------
    @app_commands.command(name="rpg", description="Open the fun games menu: profile, shop, training, mine, gambling, adventure.")
    @app_commands.guild_only()
    async def rpg(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Respect bot-wide allowed_mentions coming from your main file
        embed = self.embed_profile(interaction.user.id, interaction.guild_id)
        await interaction.followup.send(
            embed=embed,
            view=RPGView(self, interaction.user.id),
            allowed_mentions=interaction.client.allowed_mentions
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RPGCog(bot))