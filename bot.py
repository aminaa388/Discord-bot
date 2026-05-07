# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import os
import json
import re
import random
import aiohttp
import urllib.parse
from datetime import datetime, timedelta

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

SOURCE_GUILD_ID = int(os.environ["SOURCE_GUILD_ID"])
TARGET_GUILD_ID = int(os.environ["TARGET_GUILD_ID"])
VERIFIED_ROLE_ID = int(os.environ.get("VERIFIED_ROLE_ID", 0))
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "1490613935400030248")
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "")

LOG_CHANNEL_NAME = "logs"
warns = {}
spam_tracker = {}

BLACKLIST_FILE = "blacklist.json"
OWNERS_FILE = "owners.json"
GIVEAWAYS_FILE = "giveaways.json"


def load_giveaways():
    if not os.path.exists(GIVEAWAYS_FILE):
        return {}
    with open(GIVEAWAYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_giveaways(data):
    with open(GIVEAWAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def parse_duration(s):
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    match = re.fullmatch(r"(\d+)([smhd])", s.strip().lower())
    if not match:
        return None
    return int(match.group(1)) * units[match.group(2)]


active_giveaways = load_giveaways()


def load_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        return {}
    with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_blacklist(data):
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_owners():
    if not os.path.exists(OWNERS_FILE):
        return []
    with open(OWNERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_owners(data):
    with open(OWNERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


blacklist = load_blacklist()
owners = load_owners()


def is_owner(ctx):
    return ctx.author.id in owners or ctx.author.guild_permissions.administrator


# =========================
# VERIFICATION SYSTEM
# =========================

def build_oauth_url() -> str:
    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "guilds.join identify",
    })
    return f"https://discord.com/oauth2/authorize?{params}"


class WhyButton(Button):
    def __init__(self):
        super().__init__(
            label="Why ?",
            style=discord.ButtonStyle.secondary,
            custom_id="why_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "La verification sert a empecher les bots et comptes fake d'acceder au serveur.",
            ephemeral=True,
        )


class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)
        if OAUTH_REDIRECT_URI:
            self.add_item(Button(
                label="Verify now",
                style=discord.ButtonStyle.link,
                url=build_oauth_url(),
                emoji="âœ…",
            ))
        self.add_item(WhyButton())


# =========================
# TICKET SYSTEM
# =========================

class CloseButton(Button):
    def __init__(self):
        super().__init__(
            label="Fermer le ticket",
            style=discord.ButtonStyle.danger,
            emoji="ðŸ”’",
            custom_id="close_ticket_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_channels and interaction.user != interaction.channel.overwrites_for(interaction.user):
            pass
        embed = discord.Embed(
            title="Ticket ferme",
            description=f"Ferme par {interaction.user.mention}. Suppression dans 5s...",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await interaction.channel.delete()


class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CloseButton())


class TicketSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Owner",
                emoji=discord.PartialEmoji(name="emoji_28", id=1490629185847300196),
                description="Contacter un owner",
                value="owner",
            ),
            discord.SelectOption(
                label="RC",
                emoji=discord.PartialEmoji(name="emoji_29", id=1490629187701051472),
                description="Rank-up / Candidature",
                value="rc",
            ),
            discord.SelectOption(
                label="Partenariat",
                emoji=discord.PartialEmoji(name="emoji_27", id=1489300130380382390),
                description="Faire un partenariat",
                value="partenariat",
            ),
        ]
        super().__init__(
            placeholder="SÃ©lectionnez une catÃ©gorie de gestion...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select_menu",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        user = interaction.user
        type_ticket = self.values[0]

        existing = discord.utils.get(
            guild.text_channels, name=f"ticket-{user.name}-{type_ticket}"
        )
        if existing:
            await interaction.followup.send(
                f"Tu as deja un ticket ouvert : {existing.mention}", ephemeral=True
            )
            return

        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category(
                "Tickets",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(read_messages=False)
                },
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{user.name}-{type_ticket}",
            category=category,
            overwrites=overwrites,
        )

        labels = {
            "owner": "Owner",
            "rc": "Responsable Communaute",
            "partenariat": "Partenariat",
        }

        embed = discord.Embed(
            title=f"Ticket â€” {labels.get(type_ticket, type_ticket)}",
            description=(
                f"Bienvenue {user.mention} !\n\n"
                f"Decris ton probleme ou ta demande clairement.\n"
                f"Un membre du staff va te repondre des que possible."
            ),
            color=0x5865F2,
        )
        embed.set_footer(text=f"Ticket ouvert par {user.display_name}")

        await channel.send(embed=embed, view=CloseView())
        await interaction.followup.send(
            f"Ton ticket a ete cree : {channel.mention}", ephemeral=True
        )
        await send_log(guild, f"Ticket ouvert par {user} | Type : {type_ticket} | {channel.mention}")


class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# =========================
# READY
# =========================
@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(CloseView())
    bot.add_view(VerifyView())
    print(f"Connecte en tant que {bot.user}")
    print(f"Serveur source : {SOURCE_GUILD_ID}")
    print(f"Serveur cible  : {TARGET_GUILD_ID}")


# =========================
# ERREURS
# =========================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(description="Tu n'as pas la permission.", color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(description="Argument manquant. Utilise `!help` pour voir les commandes.", color=discord.Color.orange())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(description="Membre introuvable.", color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        print(error)


# =========================
# LOG SYSTEM
# =========================
async def send_log(guild, message):
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if channel:
        embed = discord.Embed(description=message, color=0x2b2d31)
        await channel.send(embed=embed)


# =========================
# ANTI SPAM
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id

    if user_id not in spam_tracker:
        spam_tracker[user_id] = []

    spam_tracker[user_id].append(message.created_at)
    spam_tracker[user_id] = spam_tracker[user_id][-5:]

    if len(spam_tracker[user_id]) == 5:
        diff = (spam_tracker[user_id][-1] - spam_tracker[user_id][0]).total_seconds()
        if diff < 5:
            try:
                await message.author.timeout(timedelta(seconds=10))
                embed = discord.Embed(
                    description=f"{message.author.mention} spam detecte â€” mute 10 secondes.",
                    color=discord.Color.orange(),
                )
                await message.channel.send(embed=embed)
                await send_log(message.guild, f"Anti-spam : {message.author} mute 10s")
            except Exception:
                pass

    await bot.process_commands(message)


# =========================
# BACKUP
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def backup(ctx):
    source = bot.get_guild(SOURCE_GUILD_ID)
    target = bot.get_guild(TARGET_GUILD_ID)

    if source is None or target is None:
        return await ctx.send("Impossible de trouver l'un des deux serveurs.")

    msg = await ctx.send("Backup en cours...")

    for channel in target.channels:
        try:
            await channel.delete()
        except Exception:
            pass

    for role in target.roles:
        if role.name != "@everyone":
            try:
                await role.delete()
            except Exception:
                pass

    for role in reversed(source.roles):
        if role.name != "@everyone":
            try:
                await target.create_role(
                    name=role.name, permissions=role.permissions, colour=role.colour
                )
            except Exception:
                pass

    category_map = {}
    for category in source.categories:
        try:
            new_cat = await target.create_category(category.name)
            category_map[category.id] = new_cat
        except Exception:
            pass

    for channel in source.channels:
        if isinstance(channel, discord.TextChannel):
            try:
                await target.create_text_channel(
                    name=channel.name, category=category_map.get(channel.category_id)
                )
            except Exception:
                pass
        elif isinstance(channel, discord.VoiceChannel):
            try:
                await target.create_voice_channel(
                    name=channel.name, category=category_map.get(channel.category_id)
                )
            except Exception:
                pass

    await msg.edit(content="Backup termine avec succes.")


# =========================
# DM ALL
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def dmall(ctx, *, message):
    msg = await ctx.send("Envoi en cours...")
    success = 0
    failed = 0
    for member in ctx.guild.members:
        if member.bot:
            continue
        try:
            await member.send(message)
            success += 1
            await asyncio.sleep(1.5)
        except Exception:
            failed += 1
    await msg.edit(content=f"Termine : {success} envoyes | {failed} echecs")


# =========================
# MODERATION
# =========================
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    embed = discord.Embed(description=f"{amount} messages supprimes.", color=discord.Color.green())
    await ctx.send(embed=embed, delete_after=3)


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Aucune raison"):
    await member.ban(reason=reason)
    embed = discord.Embed(title="Membre banni", color=discord.Color.red())
    embed.add_field(name="Membre", value=member.mention)
    embed.add_field(name="Raison", value=reason)
    embed.set_footer(text=f"Par {ctx.author.display_name}")
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Ban : {member} | Raison : {reason} | Par : {ctx.author}")


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Aucune raison"):
    await member.kick(reason=reason)
    embed = discord.Embed(title="Membre expulse", color=discord.Color.orange())
    embed.add_field(name="Membre", value=member.mention)
    embed.add_field(name="Raison", value=reason)
    embed.set_footer(text=f"Par {ctx.author.display_name}")
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Kick : {member} | Raison : {reason} | Par : {ctx.author}")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Aucune raison"):
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    embed = discord.Embed(title="Membre mute", color=discord.Color.orange())
    embed.add_field(name="Membre", value=member.mention)
    embed.add_field(name="Duree", value=f"{minutes} minute(s)")
    embed.add_field(name="Raison", value=reason)
    embed.set_footer(text=f"Par {ctx.author.display_name}")
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Mute : {member} | {minutes}min | Par : {ctx.author}")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    embed = discord.Embed(title="Membre demute", description=member.mention, color=discord.Color.green())
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Unmute : {member} | Par : {ctx.author}")


@bot.command()
async def infos(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(
        title=f"Informations â€” {member.display_name}",
        color=0x5865F2,
    )
    embed.add_field(name="Nom", value=member.name, inline=True)
    embed.add_field(name="ID", value=str(member.id), inline=True)
    embed.add_field(name="Compte cree", value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="A rejoint", value=member.joined_at.strftime("%d/%m/%Y"), inline=True)
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles) if roles else "Aucun", inline=False)
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    embed.set_footer(text=f"Demande par {ctx.author.display_name}")
    await ctx.send(embed=embed)


# =========================
# WARN
# =========================
@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="Aucune raison"):
    warns.setdefault(member.id, []).append(reason)
    count = len(warns[member.id])
    embed = discord.Embed(title="Avertissement", color=discord.Color.yellow())
    embed.add_field(name="Membre", value=member.mention)
    embed.add_field(name="Raison", value=reason)
    embed.add_field(name="Total warns", value=str(count))
    embed.set_footer(text=f"Par {ctx.author.display_name}")
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Warn : {member} | Raison : {reason} | Total : {count}")


@bot.command()
async def infractions(ctx, member: discord.Member):
    data = warns.get(member.id, [])
    if not data:
        embed = discord.Embed(description=f"{member.mention} n'a aucun avertissement.", color=discord.Color.green())
        return await ctx.send(embed=embed)
    liste = "\n".join([f"`{i+1}.` {r}" for i, r in enumerate(data)])
    embed = discord.Embed(
        title=f"Avertissements â€” {member.display_name}",
        description=liste,
        color=discord.Color.yellow(),
    )
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def unwarn(ctx, member: discord.Member):
    warns.pop(member.id, None)
    embed = discord.Embed(description=f"Avertissements de {member.mention} reinitialises.", color=discord.Color.green())
    await ctx.send(embed=embed)


# =========================
# ROLES - SELECTEUR
# =========================
class RoleSelect(Select):
    def __init__(self, member, action):
        self.member = member
        self.action = action
        roles = [r for r in member.guild.roles if r.name != "@everyone" and not r.managed]
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles[:25]]
        super().__init__(
            placeholder="Selectionne les roles...",
            min_values=1,
            max_values=min(5, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        roles = [interaction.guild.get_role(int(r)) for r in self.values]
        done = []
        failed = []
        for role in roles:
            try:
                if role >= interaction.guild.me.top_role:
                    failed.append(role.name)
                    continue
                if self.action == "add":
                    await self.member.add_roles(role)
                else:
                    await self.member.remove_roles(role)
                done.append(role.name)
            except Exception:
                failed.append(role.name)

        color = discord.Color.green() if self.action == "add" else discord.Color.red()
        title = "Roles ajoutes" if self.action == "add" else "Roles retires"
        symbol = "+" if self.action == "add" else "-"

        embed = discord.Embed(
            title=title,
            description="\n".join(f"`{symbol}` {r}" for r in done) or "Aucun",
            color=color,
        )
        if failed:
            embed.add_field(name="Echec", value="\n".join(failed), inline=False)
        embed.set_footer(text=f"Demande par {interaction.user.display_name}")
        await interaction.response.edit_message(embed=embed, view=None)


class RoleView(View):
    def __init__(self, member, action):
        super().__init__(timeout=60)
        self.add_item(RoleSelect(member, action))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member):
    embed = discord.Embed(
        title="Ajout de roles",
        description=f"Selectionne les roles a ajouter a {member.mention}",
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed, view=RoleView(member, "add"))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member):
    embed = discord.Embed(
        title="Retrait de roles",
        description=f"Selectionne les roles a retirer a {member.mention}",
        color=discord.Color.red(),
    )
    await ctx.send(embed=embed, view=RoleView(member, "remove"))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def derank(ctx, member: discord.Member):
    roles = [r for r in member.roles if r.name != "@everyone" and r.name != "D'kuva" and r < ctx.guild.me.top_role]
    removed = []
    failed = []
    for role in roles:
        try:
            await member.remove_roles(role)
            removed.append(role.name)
        except Exception:
            failed.append(role.name)

    embed = discord.Embed(title=f"Derank â€” {member.display_name}", color=discord.Color.orange())
    embed.add_field(
        name="Roles retires",
        value="\n".join(f"`-` {r}" for r in removed) if removed else "Aucun",
        inline=False,
    )
    if failed:
        embed.add_field(name="Echec", value="\n".join(failed), inline=False)
    embed.set_footer(text=f"{len(removed)} roles retires | D'kuva conserve")
    await ctx.send(embed=embed)


# =========================
# OWNERS
# =========================
@bot.command()
@commands.check(is_owner)
async def addowner(ctx, member: discord.Member):
    if member.id in owners:
        embed = discord.Embed(description=f"{member.mention} est deja owner.", color=discord.Color.orange())
        return await ctx.send(embed=embed)
    owners.append(member.id)
    save_owners(owners)
    embed = discord.Embed(description=f"{member.mention} ajoute comme owner.", color=discord.Color.green())
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Owner ajoute : {member} par {ctx.author}")


@bot.command()
@commands.check(is_owner)
async def removeowner(ctx, member: discord.Member):
    if member.id not in owners:
        embed = discord.Embed(description=f"{member.mention} n'est pas owner.", color=discord.Color.red())
        return await ctx.send(embed=embed)
    owners.remove(member.id)
    save_owners(owners)
    embed = discord.Embed(description=f"{member.mention} retire des owners.", color=discord.Color.orange())
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Owner retire : {member} par {ctx.author}")


@bot.command(name="owners")
async def list_owners(ctx):
    if not owners:
        embed = discord.Embed(description="Aucun owner enregistre.", color=discord.Color.red())
        return await ctx.send(embed=embed)
    lines = []
    for uid in owners:
        user = ctx.guild.get_member(uid) or await bot.fetch_user(uid)
        lines.append(f"- {user} (`{uid}`)")
    embed = discord.Embed(title="Owners du bot", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


# =========================
# AUTO BAN BLACKLIST
# =========================
@bot.event
async def on_member_join(member):
    if str(member.id) in blacklist:
        await member.ban(reason="Blacklist active")
        await send_log(member.guild, f"Auto-ban (blacklist) : {member}")


# =========================
# BLACKLIST
# =========================
@bot.command()
@commands.has_permissions(ban_members=True)
async def bl(ctx, member: discord.Member, *, reason="Blacklist"):
    blacklist[str(member.id)] = reason
    save_blacklist(blacklist)
    await member.ban(reason=reason)
    embed = discord.Embed(title="Blacklist", description=f"{member.mention} ajoute a la blacklist.", color=discord.Color.red())
    embed.add_field(name="Raison", value=reason)
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Blacklist : {member} | Raison : {reason}")


@bot.command()
@commands.has_permissions(administrator=True)
async def unbl(ctx, user_id: int):
    if str(user_id) not in blacklist:
        embed = discord.Embed(description="Cet utilisateur n'est pas blackliste.", color=discord.Color.orange())
        return await ctx.send(embed=embed)
    user = await bot.fetch_user(user_id)
    del blacklist[str(user_id)]
    save_blacklist(blacklist)
    await ctx.guild.unban(user)
    embed = discord.Embed(description=f"{user} retire de la blacklist.", color=discord.Color.green())
    await ctx.send(embed=embed)
    await send_log(ctx.guild, f"Unblacklist : {user} par {ctx.author}")


@bot.command()
async def blist(ctx):
    if not blacklist:
        embed = discord.Embed(description="La blacklist est vide.", color=discord.Color.green())
        return await ctx.send(embed=embed)
    lines = [f"<@{uid}> â€” {reason}" for uid, reason in blacklist.items()]
    embed = discord.Embed(title="Blacklist", description="\n".join(lines), color=discord.Color.red())
    await ctx.send(embed=embed)


# =========================
# LOCK / UNLOCK
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    embed = discord.Embed(description=f"{ctx.channel.mention} verrouille.", color=discord.Color.red())
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    embed = discord.Embed(description=f"{ctx.channel.mention} deverrouille.", color=discord.Color.green())
    await ctx.send(embed=embed)


# =========================
# STEAL EMOJI
# =========================
@bot.command()
@commands.has_permissions(manage_emojis=True)
async def steal(ctx, emoji: str, *, name: str = None):
    # Supporte emoji custom : <:nom:id> ou <a:nom:id>
    match = re.match(r"<(a?):(\w+):(\d+)>", emoji)
    if not match:
        embed = discord.Embed(
            description="Utilise un emoji custom : `!steal <emoji>` ou `!steal <emoji> <nouveau_nom>`",
            color=discord.Color.red(),
        )
        return await ctx.send(embed=embed)

    animated = match.group(1) == "a"
    emoji_name = name or match.group(2)
    emoji_id = int(match.group(3))
    ext = "gif" if animated else "png"
    url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                embed = discord.Embed(description="Impossible de recuperer l'emoji.", color=discord.Color.red())
                return await ctx.send(embed=embed)
            image_data = await resp.read()

    try:
        new_emoji = await ctx.guild.create_custom_emoji(name=emoji_name, image=image_data)
        embed = discord.Embed(
            title="Emoji vole !",
            description=f"{new_emoji} `:{new_emoji.name}:` ajoute au serveur.",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Par {ctx.author.display_name}")
        await ctx.send(embed=embed)
        await send_log(ctx.guild, f"Emoji vole : `:{new_emoji.name}:` par {ctx.author}")
    except discord.HTTPException as e:
        embed = discord.Embed(
            description=f"Echec : {e.text}",
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_emojis=True)
async def stealurl(ctx, url: str, *, name: str):
    if not name:
        embed = discord.Embed(description="Utilise : `!stealurl <url> <nom>`", color=discord.Color.red())
        return await ctx.send(embed=embed)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                embed = discord.Embed(description="URL invalide ou inaccessible.", color=discord.Color.red())
                return await ctx.send(embed=embed)
            image_data = await resp.read()

    try:
        new_emoji = await ctx.guild.create_custom_emoji(name=name, image=image_data)
        embed = discord.Embed(
            title="Emoji ajoute !",
            description=f"{new_emoji} `:{new_emoji.name}:` ajoute au serveur.",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Par {ctx.author.display_name}")
        await ctx.send(embed=embed)
        await send_log(ctx.guild, f"Emoji ajoute via URL : `:{new_emoji.name}:` par {ctx.author}")
    except discord.HTTPException as e:
        embed = discord.Embed(description=f"Echec : {e.text}", color=discord.Color.red())
        await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_emojis=True)
async def delemoji(ctx, *, name: str):
    emoji = discord.utils.get(ctx.guild.emojis, name=name)
    if not emoji:
        embed = discord.Embed(description=f"Emoji `:{name}:` introuvable.", color=discord.Color.red())
        return await ctx.send(embed=embed)
    await emoji.delete()
    embed = discord.Embed(description=f"Emoji `:{name}:` supprime.", color=discord.Color.orange())
    await ctx.send(embed=embed)


@bot.command()
async def emojis(ctx):
    guild_emojis = ctx.guild.emojis
    if not guild_emojis:
        embed = discord.Embed(description="Aucun emoji sur ce serveur.", color=discord.Color.red())
        return await ctx.send(embed=embed)
    lines = [f"{e} `:{e.name}:`" for e in guild_emojis]
    chunks = [lines[i:i+20] for i in range(0, len(lines), 20)]
    embed = discord.Embed(
        title=f"Emojis du serveur ({len(guild_emojis)})",
        description="\n".join(chunks[0]),
        color=0x5865F2,
    )
    if len(chunks) > 1:
        embed.set_footer(text=f"Page 1/{len(chunks)}")
    await ctx.send(embed=embed)


# =========================
# VERIFICATION COMMANDES
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def verif(ctx):
    guild_name = ctx.guild.name
    embed = discord.Embed(
        color=0x5865F2,
        title="ðŸ¤– Verification required",
        description=(
            f"To gain access to **{guild_name}** you need to prove you are a human by completing verification. "
            f"Click the button below to get started!"
        ),
    )
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.set_footer(text=guild_name)
    await ctx.send(embed=embed, view=VerifyView())
    await ctx.message.delete()


# =========================
# JOIN â€” ajoute tous les membres OAuth2 a un serveur
# =========================
@bot.command(name="join")
async def join_server(ctx, invite_link: str = None):
    if not is_owner(ctx):
        return await ctx.send("âŒ Commande reservee aux owners et administrateurs.", delete_after=5)
    if not invite_link:
        return await ctx.send("âŒ Usage : `!join <lien d'invitation>`", delete_after=5)

    import re
    match = re.search(r"discord(?:\.gg|\.com/invite)/([A-Za-z0-9\-]+)", invite_link)
    if not match:
        return await ctx.send("âŒ Lien d'invitation invalide.", delete_after=5)
    invite_code = match.group(1)

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://discord.com/api/v10/invites/{invite_code}",
            headers={"Authorization": f"Bot {token}"},
        ) as resp:
            if resp.status != 200:
                return await ctx.send("âŒ Impossible de resoudre l'invitation. Verifie que le lien est valide.", delete_after=8)
            invite_data = await resp.json()
            guild_id = invite_data.get("guild", {}).get("id")
            guild_name = invite_data.get("guild", {}).get("name", "Serveur inconnu")

    if not guild_id:
        return await ctx.send("âŒ Impossible de recuperer l'ID du serveur depuis ce lien.", delete_after=8)

    try:
        with open("oauth_tokens.json", "r", encoding="utf-8") as f:
            tokens: dict = json.load(f)
    except FileNotFoundError:
        return await ctx.send("âŒ Aucun utilisateur n'a encore autorise le bot (`!verif`).", delete_after=8)

    if not tokens:
        return await ctx.send("âŒ Aucun utilisateur n'a encore autorise le bot.", delete_after=8)

    msg = await ctx.send(f"â³ Ajout de **{len(tokens)}** membres vers **{guild_name}**...")

    success = 0
    already = 0
    failed = 0

    async with aiohttp.ClientSession() as session:
        for user_id, access_token in tokens.items():
            try:
                async with session.put(
                    f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}",
                    headers={
                        "Authorization": f"Bot {token}",
                        "Content-Type": "application/json",
                    },
                    json={"access_token": access_token},
                ) as resp:
                    if resp.status == 201:
                        success += 1
                    elif resp.status in (200, 204):
                        already += 1
                    else:
                        failed += 1
                await asyncio.sleep(0.5)
            except Exception:
                failed += 1

    await msg.edit(content=(
        f"âœ… TerminÃ© pour **{guild_name}** !\n"
        f"â€¢ Ajoutes : **{success}**\n"
        f"â€¢ Deja membres : **{already}**\n"
        f"â€¢ Echecs : **{failed}**"
    ))
    await send_log(ctx.guild, f"!join vers {guild_name} â€” {success} ajoutes, {already} deja membres, {failed} echecs par {ctx.author}")


# =========================
# DECAL â€” verrouille tous les salons + cree salon de redirection
# =========================
@bot.command()
async def decal(ctx):
    if not is_owner(ctx):
        return await ctx.send("âŒ Commande reservee aux owners et administrateurs.", delete_after=5)

    guild = ctx.guild
    everyone = guild.default_role
    msg = await ctx.send("â³ Decalage en cours, patiente...")

    # Sauvegarde des permissions actuelles
    backup = {"guild_id": guild.id, "channels": {}, "decal_channel_id": None}
    for channel in guild.channels:
        overwrites_data = {}
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            overwrites_data[str(target.id)] = {
                "type": "role" if isinstance(target, discord.Role) else "member",
                "allow": allow.value,
                "deny": deny.value,
            }
        backup["channels"][str(channel.id)] = overwrites_data

    with open("decal_backup.json", "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2)

    # Rendre tous les salons invisibles
    hidden = discord.PermissionOverwrite(view_channel=False, send_messages=False)
    for channel in guild.channels:
        try:
            await channel.set_permissions(everyone, overwrite=hidden)
        except Exception:
            pass

    # Creer le salon decal Ayona visible par tout le monde
    visible = {
        everyone: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            add_reactions=False,
        )
    }
    try:
        decal_ch = await guild.create_text_channel("decal Ayona", overwrites=visible, reason="!decal")
    except Exception as e:
        return await msg.edit(content=f"âŒ Impossible de creer le salon : {e}")

    # Enregistrer l'ID du salon decal pour !undecal
    backup["decal_channel_id"] = decal_ch.id
    with open("decal_backup.json", "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2)

    await msg.edit(content=f"âœ… Decalage termine ! Salon cree : {decal_ch.mention}\nTous les autres salons sont invisibles. Utilise `!undecal` pour tout remettre.")
    await send_log(guild, f"!decal execute par {ctx.author} â€” tous les salons verrouilles")


@bot.command()
async def undecal(ctx):
    if not is_owner(ctx):
        return await ctx.send("âŒ Commande reservee aux owners et administrateurs.", delete_after=5)

    try:
        with open("decal_backup.json", "r", encoding="utf-8") as f:
            backup = json.load(f)
    except FileNotFoundError:
        return await ctx.send("âŒ Aucune sauvegarde trouvee. Lance d'abord `!decal`.", delete_after=8)

    guild = ctx.guild
    msg = await ctx.send("â³ Restauration en cours, patiente...")

    for channel in guild.channels:
        saved = backup["channels"].get(str(channel.id))
        if saved is None:
            continue
        for target_id_str, data in saved.items():
            target_id = int(target_id_str)
            target = guild.get_role(target_id) or guild.get_member(target_id)
            if target is None:
                continue
            allow = discord.Permissions(data["allow"])
            deny = discord.Permissions(data["deny"])
            overwrite = discord.PermissionOverwrite.from_pair(allow, deny)
            try:
                await channel.set_permissions(target, overwrite=overwrite)
            except Exception:
                pass

    # Supprimer le salon decal cree
    decal_channel_id = backup.get("decal_channel_id")
    if decal_channel_id:
        decal_ch = guild.get_channel(decal_channel_id)
        if decal_ch:
            try:
                await decal_ch.delete(reason="!undecal")
            except Exception:
                pass

    import os as _os
    try:
        _os.remove("decal_backup.json")
    except Exception:
        pass

    await msg.edit(content="âœ… Restauration terminee ! Tous les salons sont remis comme avant.")
    await send_log(guild, f"!undecal execute par {ctx.author} â€” permissions restaurees")


# =========================
# RECRUTEMENT
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def recrutement(ctx):
    embed = discord.Embed(
        color=0x2B2D31,
        title="Recrutement staff",
        description=(
            "**ðŸ‡«ðŸ‡·**\n"
            "Hey, tu veux devenir uploader sur ce serveur ? C'est tres simple, tu dois juste respecter ces 3 conditions :\n\n"
            "- Etre actif\n"
            "- Avoir au minimum 14 ans\n"
            "- Etre mature\n\n"
            "Si tu remplis toutes ces conditions, ouvre un ticket.\n\n"
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
            "**ðŸ‡ºðŸ‡¸**\n"
            "Hey, do you want to become an uploader on this server? It's very simple, you just need to meet these 3 requirements:\n\n"
            "- Be active\n"
            "- Be at least 14 years old\n"
            "- Be mature\n\n"
            "If you meet all these requirements, feel free to open a ticket."
        ),
    )
    embed.set_author(name=f"{ctx.guild.name} - Gestion")
    embed.set_footer(text="Recruitment")
    await ctx.send(embed=embed)
    await ctx.message.delete()


# =========================
# GIVEAWAY
# =========================
async def run_giveaway(channel_id, message_id, prize, winner_count, host_id, end_time):
    now = datetime.utcnow().timestamp()
    wait = end_time - now
    if wait > 0:
        await asyncio.sleep(wait)

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        return

    reaction = discord.utils.get(msg.reactions, emoji="ðŸŽ‰")
    if not reaction:
        await channel.send("Aucun participant pour le giveaway.")
        active_giveaways.pop(str(message_id), None)
        save_giveaways(active_giveaways)
        return

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await channel.send("Aucun participant valide pour le giveaway.")
        active_giveaways.pop(str(message_id), None)
        save_giveaways(active_giveaways)
        return

    winners = random.sample(users, min(winner_count, len(users)))
    mentions = " ".join(w.mention for w in winners)

    embed = discord.Embed(
        title="Giveaway termine !",
        description=f"Gagnant(s) : {mentions}\nPrix : **{prize}**",
        color=discord.Color.gold(),
    )
    embed.set_footer(text=f"Organise par {bot.get_user(host_id)}")

    await msg.edit(embed=embed)
    await channel.send(f"Felicitations {mentions} ! Vous avez gagne **{prize}** !", embed=embed)

    active_giveaways.pop(str(message_id), None)
    save_giveaways(active_giveaways)


@bot.command()
@commands.has_permissions(manage_guild=True)
async def gstart(ctx, duration: str, winners: int, *, prize: str):
    seconds = parse_duration(duration)
    if not seconds:
        embed = discord.Embed(
            description="Format invalide. Utilise : `!gstart 1h 1 Nitro`\nUnites : `s`, `m`, `h`, `d`",
            color=discord.Color.red(),
        )
        return await ctx.send(embed=embed)

    end_time = datetime.utcnow().timestamp() + seconds
    end_dt = datetime.utcfromtimestamp(end_time)

    embed = discord.Embed(
        title="ðŸŽ‰ GIVEAWAY ðŸŽ‰",
        description=(
            f"**Prix :** {prize}\n"
            f"**Gagnants :** {winners}\n"
            f"**Fin :** <t:{int(end_time)}:R>\n"
            f"**Organise par :** {ctx.author.mention}\n\n"
            "Reagis avec ðŸŽ‰ pour participer !"
        ),
        color=0x5865F2,
    )
    embed.set_footer(text=f"Fin le {end_dt.strftime('%d/%m/%Y a %H:%M')} UTC")

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("ðŸŽ‰")

    giveaway_data = {
        "channel_id": ctx.channel.id,
        "message_id": msg.id,
        "prize": prize,
        "winner_count": winners,
        "host_id": ctx.author.id,
        "end_time": end_time,
    }
    active_giveaways[str(msg.id)] = giveaway_data
    save_giveaways(active_giveaways)

    bot.loop.create_task(
        run_giveaway(ctx.channel.id, msg.id, prize, winners, ctx.author.id, end_time)
    )

    confirm = discord.Embed(description=f"Giveaway lance ! Fin <t:{int(end_time)}:R>", color=discord.Color.green())
    await ctx.send(embed=confirm, delete_after=5)
    await ctx.message.delete()


@bot.command()
@commands.has_permissions(manage_guild=True)
async def gend(ctx, message_id: int):
    if str(message_id) not in active_giveaways:
        embed = discord.Embed(description="Giveaway introuvable.", color=discord.Color.red())
        return await ctx.send(embed=embed)

    data = active_giveaways[str(message_id)]
    data["end_time"] = 0
    save_giveaways(active_giveaways)

    bot.loop.create_task(
        run_giveaway(
            data["channel_id"], data["message_id"],
            data["prize"], data["winner_count"],
            data["host_id"], 0
        )
    )
    embed = discord.Embed(description="Giveaway termine de force.", color=discord.Color.orange())
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_guild=True)
async def greroll(ctx, message_id: int):
    channel = ctx.channel
    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        embed = discord.Embed(description="Message introuvable.", color=discord.Color.red())
        return await ctx.send(embed=embed)

    reaction = discord.utils.get(msg.reactions, emoji="ðŸŽ‰")
    if not reaction:
        embed = discord.Embed(description="Aucune reaction trouvee.", color=discord.Color.red())
        return await ctx.send(embed=embed)

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        embed = discord.Embed(description="Aucun participant.", color=discord.Color.red())
        return await ctx.send(embed=embed)

    winner = random.choice(users)
    embed = discord.Embed(
        description=f"Nouveau gagnant : {winner.mention} ! Felicitations !",
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed)


# =========================
# TICKET COMMANDES
# =========================
@bot.command()
async def ticket(ctx, *, image_url: str = None):
    embed = discord.Embed(
        title=ctx.guild.name,
        description="Choisissez une option dans le menu ci-dessous.",
        color=0x2B2D31,
    )
    if image_url:
        embed.set_image(url=image_url)
    await ctx.send(embed=embed, view=TicketView())
    await ctx.message.delete()


@bot.command()
async def close(ctx):
    if "ticket-" not in ctx.channel.name:
        return
    embed = discord.Embed(description="Fermeture dans 5 secondes...", color=discord.Color.red())
    await ctx.send(embed=embed)
    await asyncio.sleep(5)
    await ctx.channel.delete()


@bot.command()
async def rename(ctx, *, name):
    if "ticket-" not in ctx.channel.name:
        return
    await ctx.channel.edit(name=f"ticket-{name}")
    embed = discord.Embed(description=f"Ticket renomme en `ticket-{name}`.", color=discord.Color.green())
    await ctx.send(embed=embed)


# =========================
# EMBED BUILDER
# =========================
@bot.command(name="embed")
async def create_embed(ctx, *, args: str = None):
    if not is_owner(ctx):
        return await ctx.send("âŒ Commande reservee aux owners et administrateurs.", delete_after=5)
    if not args:
        help_embed = discord.Embed(
            title="Commande !embed",
            description=(
                "Cree un embed personnalise.\n\n"
                "**Format :**\n"
                "`!embed Titre | Description | #couleur | URL_image | Footer`\n\n"
                "**Exemples :**\n"
                "`!embed Annonce | Bienvenue sur le serveur !`\n"
                "`!embed Regles | Lisez les regles | #f23f43`\n"
                "`!embed Actu | Nouvelle update | #23a55a | https://i.imgur.com/xxx.png | Serveur`\n\n"
                "*Seul le titre est obligatoire. Les autres champs sont optionnels.*"
            ),
            color=0x5865F2,
        )
        return await ctx.send(embed=help_embed, delete_after=30)

    parts = [p.strip() for p in args.split("|")]
    title = parts[0] if len(parts) > 0 else None
    description = parts[1] if len(parts) > 1 else None
    color_str = parts[2].lstrip("#") if len(parts) > 2 and parts[2] else "5865F2"
    image_url = parts[3] if len(parts) > 3 and parts[3] else None
    footer = parts[4] if len(parts) > 4 and parts[4] else None

    try:
        color = int(color_str, 16)
    except ValueError:
        color = 0x5865F2

    embed = discord.Embed(
        title=title or discord.Embed.Empty,
        description=description or discord.Embed.Empty,
        color=color,
    )
    if image_url:
        embed.set_image(url=image_url)
    if footer:
        embed.set_footer(text=footer)

    await ctx.message.delete()
    await ctx.send(embed=embed)


# =========================
# HELP
# =========================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="BUDM â€” Commandes",
        description="Prefixe : `!`",
        color=0x5865F2,
    )
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)

    embed.add_field(
        name="Moderation",
        value=(
            "`!ban @m <raison>`\n"
            "`!kick @m <raison>`\n"
            "`!mute @m <minutes>`\n"
            "`!unmute @m`\n"
            "`!clear <n>`\n"
            "`!lock` / `!unlock`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Avertissements",
        value=(
            "`!warn @m <raison>`\n"
            "`!infractions @m`\n"
            "`!unwarn @m`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Roles",
        value=(
            "`!addrole @m`\n"
            "`!removerole @m`\n"
            "`!derank @m`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Verification & Recrutement",
        value=(
            "`!verif` â€” Panel de verification (OAuth2)\n"
            "`!join <lien>` â€” Ajouter tous les membres OAuth2 a un serveur\n"
            "`!decal` â€” Verrouille tout le serveur + cree salon decal Ayona\n"
            "`!undecal` â€” Restaure tout le serveur comme avant\n"
            "`!recrutement` â€” Embed recrutement bilingue"
        ),
        inline=True,
    )

    embed.add_field(
        name="Giveaway",
        value=(
            "`!gstart <duree> <gagnants> <prix>` â€” Lancer un giveaway\n"
            "Durees : `30s`, `10m`, `2h`, `1d`\n"
            "`!gend <message_id>` â€” Terminer de force\n"
            "`!greroll <message_id>` â€” Retirer au sort"
        ),
        inline=True,
    )

    embed.add_field(
        name="Tickets",
        value=(
            "`!ticket [url_image]` â€” Panel ticket avec dropdown\n"
            "`!close` â€” Fermer le ticket\n"
            "`!rename <nom>` â€” Renommer"
        ),
        inline=True,
    )

    embed.add_field(
        name="Embed builder",
        value=(
            "`!embed` â€” Voir le format\n"
            "`!embed Titre | Description | #couleur | URL | Footer`\n"
            "*Seul le titre est obligatoire*"
        ),
        inline=True,
    )

    embed.add_field(
        name="Owners",
        value=(
            "`!addowner @m`\n"
            "`!removeowner @m`\n"
            "`!owners`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Blacklist",
        value=(
            "`!bl @m <raison>`\n"
            "`!unbl <ID>`\n"
            "`!blist`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Emojis",
        value=(
            "`!steal <emoji>` â€” Vole un emoji d'un autre serveur\n"
            "`!steal <emoji> <nom>` â€” Vole avec un nouveau nom\n"
            "`!stealurl <url> <nom>` â€” Ajoute un emoji depuis une URL\n"
            "`!delemoji <nom>` â€” Supprime un emoji du serveur\n"
            "`!emojis` â€” Liste tous les emojis du serveur"
        ),
        inline=True,
    )

    embed.add_field(
        name="Autres",
        value=(
            "`!backup` â€” Copie le serveur\n"
            "`!dmall <msg>` â€” DM tous les membres\n"
            "`!infos @m` â€” Infos d'un membre"
        ),
        inline=True,
    )

    embed.set_footer(text=f"Demande par {ctx.author.display_name}")
    await ctx.send(embed=embed)


# =========================
# RUN
# =========================
token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN manquant.")

bot.run(token)
