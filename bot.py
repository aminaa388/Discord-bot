import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import os
import json
import re
import aiohttp
from datetime import timedelta

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

SOURCE_GUILD_ID = int(os.environ["SOURCE_GUILD_ID"])
TARGET_GUILD_ID = int(os.environ["TARGET_GUILD_ID"])

LOG_CHANNEL_NAME = "logs"
warns = {}
spam_tracker = {}

BLACKLIST_FILE = "blacklist.json"
OWNERS_FILE = "owners.json"


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
            placeholder="Ouvrir un ticket...",
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
# TICKET COMMANDES
# =========================
@bot.command()
async def ticket(ctx):
    embed = discord.Embed(
        title="Support â€” Kuva",
        description=(
            "Selectionne le type de ticket dans le menu ci-dessous.\n\n"
            "**Owner** â€” Contacter un owner\n"
            "**RC** â€” Candidature / Rank-up\n"
            "**Partenariat** â€” Proposer un partenariat"
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="Un seul ticket par categorie est autorise.")
    await ctx.send(embed=embed, view=TicketView())


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
        name="Tickets",
        value=(
            "`!ticket` â€” Panel ticket\n"
            "`!close` â€” Fermer le ticket\n"
            "`!rename <nom>` â€” Renommer"
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
