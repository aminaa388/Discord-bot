import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import os
import json
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
    with open(BLACKLIST_FILE, "r") as f:
        return json.load(f)


def save_blacklist(data):
    with open(BLACKLIST_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_owners():
    if not os.path.exists(OWNERS_FILE):
        return []
    with open(OWNERS_FILE, "r") as f:
        return json.load(f)


def save_owners(data):
    with open(OWNERS_FILE, "w") as f:
        json.dump(data, f, indent=4)


blacklist = load_blacklist()
owners = load_owners()


def is_owner(ctx):
    return ctx.author.id in owners or ctx.author.guild_permissions.administrator


# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"Connecte en tant que {bot.user}")
    print(f"Serveur source : {SOURCE_GUILD_ID}")
    print(f"Serveur cible  : {TARGET_GUILD_ID}")


# =========================
# ERREURS
# =========================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Tu n'as pas la permission !")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Argument manquant !")
    else:
        print(error)


# =========================
# LOG SYSTEM
# =========================
async def send_log(guild, message):
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if channel:
        await channel.send(message)


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
                await message.channel.send(
                    f"{message.author.mention} spam dÃ©tectÃ©, mute 10s."
                )
                await send_log(message.guild, f"Spam dÃ©tectÃ© : {message.author}")
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

    await ctx.send("Backup en cours...")

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

    await ctx.send("Backup terminÃ© !")


# =========================
# DM ALL
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def dmall(ctx, *, message):
    await ctx.send("Envoi en cours...")
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
    await ctx.send(f"{success} envoyÃ©s | {failed} Ã©checs")


# =========================
# MODERATION
# =========================
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"{amount} messages supprimÃ©s", delete_after=3)


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Aucune raison"):
    await member.ban(reason=reason)
    await ctx.send(f"{member.mention} banni | {reason}")
    await send_log(ctx.guild, f"{member} banni | {reason}")


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member):
    await member.kick()
    await ctx.send(f"{member.mention} kick")
    await send_log(ctx.guild, f"{member} kick")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int):
    await member.timeout(timedelta(minutes=minutes))
    await ctx.send(f"{member.mention} mute {minutes} min")
    await send_log(ctx.guild, f"{member} mute {minutes} min")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"{member.mention} unmute")
    await send_log(ctx.guild, f"{member} unmute")


@bot.command()
async def infos(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title="Infos utilisateur", color=discord.Color.blue())
    embed.add_field(name="Nom", value=member.name)
    embed.add_field(name="ID", value=member.id)
    embed.add_field(name="CrÃ©ation", value=member.created_at.strftime("%d/%m/%Y"))
    embed.add_field(name="Rejoint", value=member.joined_at.strftime("%d/%m/%Y"))
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    await ctx.send(embed=embed)


# =========================
# WARN
# =========================
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="Aucune raison"):
    warns.setdefault(member.id, []).append(reason)
    count = len(warns[member.id])
    await ctx.send(f"{member.mention} averti ({count} avertissement(s)) | {reason}")
    await send_log(ctx.guild, f"{member} warn ({count}) | {reason}")


@bot.command()
async def infractions(ctx, member: discord.Member):
    data = warns.get(member.id, [])
    if data:
        liste = "\n".join([f"{i + 1}. {r}" for i, r in enumerate(data)])
        await ctx.send(f"Avertissements de {member.mention} :\n{liste}")
    else:
        await ctx.send(f"{member.mention} n'a aucun avertissement.")


@bot.command()
async def unwarn(ctx, member: discord.Member):
    warns.pop(member.id, None)
    await ctx.send(f"Avertissements de {member.mention} rÃ©initialisÃ©s.")


# =========================
# ROLES â€” SELECTEUR
# =========================
class RoleSelect(Select):
    def __init__(self, member, action):
        self.member = member
        self.action = action

        roles = [
            r for r in member.guild.roles if r.name != "@everyone" and not r.managed
        ]

        options = [
            discord.SelectOption(label=r.name, value=str(r.id)) for r in roles[:25]
        ]

        super().__init__(
            placeholder="SÃ©lectionne les rÃ´les...",
            min_values=1,
            max_values=min(5, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        roles = [interaction.guild.get_role(int(r)) for r in self.values]

        added = []
        removed = []
        failed = []

        for role in roles:
            try:
                if role >= interaction.guild.me.top_role:
                    failed.append(role.name)
                    continue

                if self.action == "add":
                    await self.member.add_roles(role)
                    added.append(role.name)
                elif self.action == "remove":
                    await self.member.remove_roles(role)
                    removed.append(role.name)
            except Exception:
                failed.append(role.name)

        embed = discord.Embed(color=discord.Color.blue())

        if self.action == "add":
            embed.title = "Ajout de rÃ´les"
            embed.description = "\n".join(f"+ {r}" for r in added) or "Aucun"
        elif self.action == "remove":
            embed.title = "Retrait de rÃ´les"
            embed.description = "\n".join(f"- {r}" for r in removed) or "Aucun"

        if failed:
            embed.add_field(name="Echec", value="\n".join(failed), inline=False)

        embed.set_footer(text=f"DemandÃ© par {interaction.user}")
        await interaction.response.edit_message(embed=embed, view=None)


class RoleView(View):
    def __init__(self, member, action):
        super().__init__(timeout=60)
        self.add_item(RoleSelect(member, action))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member):
    embed = discord.Embed(
        title="Ajout de rÃ´les",
        description=f"SÃ©lectionne les rÃ´les Ã  ajouter Ã  {member.mention}",
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed, view=RoleView(member, "add"))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member):
    embed = discord.Embed(
        title="Retrait de rÃ´les",
        description=f"SÃ©lectionne les rÃ´les Ã  retirer Ã  {member.mention}",
        color=discord.Color.red(),
    )
    await ctx.send(embed=embed, view=RoleView(member, "remove"))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def derank(ctx, member: discord.Member):
    roles = [
        r
        for r in member.roles
        if r.name != "@everyone" and r.name != "D'kuva" and r < ctx.guild.me.top_role
    ]

    removed = []
    failed = []

    for role in roles:
        try:
            await member.remove_roles(role)
            removed.append(role.name)
        except Exception:
            failed.append(role.name)

    embed = discord.Embed(title="Derank", color=discord.Color.orange())
    embed.add_field(
        name="RÃ´les retirÃ©s",
        value="\n".join(removed) if removed else "Aucun",
        inline=False,
    )
    if failed:
        embed.add_field(name="Echec", value="\n".join(failed), inline=False)
    embed.set_footer(text=f"Total : {len(removed)} rÃ´les retirÃ©s | D'kuva conservÃ©")
    await ctx.send(embed=embed)


# =========================
# OWNERS
# =========================
@bot.command()
@commands.check(is_owner)
async def addowner(ctx, member: discord.Member):
    if member.id in owners:
        return await ctx.send(f"{member.mention} est dÃ©jÃ  owner.")
    owners.append(member.id)
    save_owners(owners)
    await ctx.send(f"{member.mention} ajoutÃ© comme owner du bot.")
    await send_log(ctx.guild, f"{member} ajoutÃ© comme owner par {ctx.author}")


@bot.command()
@commands.check(is_owner)
async def removeowner(ctx, member: discord.Member):
    if member.id not in owners:
        return await ctx.send(f"{member.mention} n'est pas owner.")
    owners.remove(member.id)
    save_owners(owners)
    await ctx.send(f"{member.mention} retirÃ© des owners.")
    await send_log(ctx.guild, f"{member} retirÃ© des owners par {ctx.author}")


@bot.command(name="owners")
async def list_owners(ctx):
    if not owners:
        return await ctx.send("Aucun owner enregistrÃ©.")
    lines = []
    for uid in owners:
        user = ctx.guild.get_member(uid) or await bot.fetch_user(uid)
        lines.append(f"â€¢ {user} (`{uid}`)")
    embed = discord.Embed(
        title="Owners du bot", description="\n".join(lines), color=discord.Color.gold()
    )
    await ctx.send(embed=embed)


# =========================
# AUTO BAN BLACKLIST
# =========================
@bot.event
async def on_member_join(member):
    if str(member.id) in blacklist:
        await member.ban(reason="Blacklist active")
        await send_log(member.guild, f"{member} auto-ban (blacklist)")


# =========================
# BLACKLIST
# =========================
@bot.command()
@commands.has_permissions(ban_members=True)
async def bl(ctx, member: discord.Member, *, reason="Blacklist"):
    blacklist[str(member.id)] = reason
    save_blacklist(blacklist)
    await member.ban(reason=reason)
    await ctx.send(f"{member.mention} ajoutÃ© Ã  la blacklist.")
    await send_log(ctx.guild, f"{member} BL | {reason}")


@bot.command()
@commands.has_permissions(administrator=True)
async def unbl(ctx, user_id: int):
    if str(user_id) not in blacklist:
        return await ctx.send("Cet utilisateur n'est pas blacklistÃ©.")
    user = await bot.fetch_user(user_id)
    del blacklist[str(user_id)]
    save_blacklist(blacklist)
    await ctx.guild.unban(user)
    await ctx.send(f"{user} retirÃ© de la blacklist.")
    await send_log(ctx.guild, f"{user} UNBL")


@bot.command()
async def blist(ctx):
    if not blacklist:
        return await ctx.send("La blacklist est vide.")
    msg = "\n".join([f"<@{uid}> â€” {reason}" for uid, reason in blacklist.items()])
    embed = discord.Embed(title="Blacklist", description=msg, color=discord.Color.red())
    await ctx.send(embed=embed)


# =========================
# LOCK / UNLOCK
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"{ctx.channel.mention} verrouillÃ©.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"{ctx.channel.mention} dÃ©verrouillÃ©.")


# =========================
# SYSTEME TICKET
# =========================


class TicketSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Owner",
                emoji=discord.PartialEmoji(name="emoji_28", id=1490629185847300196),
                description="Contacter un owner...",
                value="owner",
            ),
            discord.SelectOption(
                label="RC",
                emoji=discord.PartialEmoji(name="emoji_29", id=1490629187701051472),
                description="Rank-up...",
                value="rc",
            ),
            discord.SelectOption(
                label="Partenariat",
                emoji=discord.PartialEmoji(name="emoji_27", id=1489300130380382390),
                description="Faire un partenariat...",
                value="partenariat",
            ),
        ]
        super().__init__(
            placeholder="Îµ ðŸ· ãƒ» Ticket Kuva #ðŸ‡µðŸ‡¸",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        user = interaction.user
        type_ticket = self.values[0]

        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category(
                "Tickets",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(read_messages=False)
                },
            )

        channel_name = f"ticket-{user.name}-{type_ticket}"
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(
                    read_messages=True, send_messages=True
                ),
            },
        )

        await interaction.followup.send(
            f"Ticket crÃ©Ã© : {channel.mention}", ephemeral=True
        )

        embed = discord.Embed(
            title="Ticket ouvert",
            description=f"{user.mention} explique ton problÃ¨me.\nType : **{type_ticket}**",
            color=discord.Color.blue(),
        )
        await channel.send(embed=embed, view=CloseView())


class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            Button(
                label="Fermer le ticket",
                style=discord.ButtonStyle.danger,
                custom_id="close_ticket",
            )
        )


@bot.command()
async def ticket(ctx):
    embed = discord.Embed(
        title="Ouvrir un ticket",
        description="SÃ©lectionne le type de ticket dans le menu ci-dessous",
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed, view=TicketView())


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id", "")

    if custom_id == "close_ticket":
        await interaction.response.defer(ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete()


@bot.command()
async def close(ctx):
    if "ticket-" in ctx.channel.name:
        await ctx.send("Fermeture du ticket...")
        await asyncio.sleep(2)
        await ctx.channel.delete()


@bot.command()
async def rename(ctx, *, name):
    if "ticket-" in ctx.channel.name:
        await ctx.channel.edit(name=f"ticket-{name}")
        await ctx.send(f"Nouveau nom : ticket-{name}")


# =========================
# HELP
# =========================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="ðŸ“‹ Liste des commandes",
        description="PrÃ©fixe : `!`",
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ”§ BACKUP",
        value=(
            "`!backup`\n"
            "Copie le serveur source vers le serveur cible (rÃ´les, catÃ©gories, salons).\n"
            "âš ï¸ RÃ©servÃ© aux administrateurs."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ“¨ MESSAGES",
        value=(
            "`!dmall <message>`\n"
            "Envoie un DM Ã  tous les membres.\n"
            "Exemple : `!dmall Bienvenue !`\n"
            "âš ï¸ RÃ©servÃ© aux administrateurs."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ›¡ï¸ MODÃ‰RATION",
        value=(
            "`!ban @membre <raison>` â€” Bannit un membre.\n"
            "`!kick @membre` â€” Expulse un membre.\n"
            "`!mute @membre <minutes>` â€” Mute un membre X minutes.\n"
            "`!unmute @membre` â€” Retire le mute.\n"
            "`!clear <nombre>` â€” Supprime X messages.\n"
            "`!lock` â€” Verrouille le salon (personne ne peut Ã©crire).\n"
            "`!unlock` â€” DÃ©verrouille le salon."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nâš ï¸ AVERTISSEMENTS",
        value=(
            "`!warn @membre <raison>` â€” Avertit un membre.\n"
            "`!infractions @membre` â€” Affiche tous les avertissements d'un membre.\n"
            "`!unwarn @membre` â€” RÃ©initialise les avertissements d'un membre."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸŽ­ RÃ”LES",
        value=(
            "`!addrole @membre` â€” Ouvre un sÃ©lecteur pour choisir les rÃ´les Ã  ajouter.\n"
            "`!removerole @membre` â€” Ouvre un sÃ©lecteur pour choisir les rÃ´les Ã  retirer.\n"
            "`!derank @membre` â€” Retire tous les rÃ´les du membre (sauf D'kuva)."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ“Š INFORMATIONS",
        value=(
            "`!infos @membre` â€” Affiche les infos d'un membre.\n"
            "Sans mention, affiche vos propres infos."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸŽ« TICKETS",
        value=(
            "`!ticket` â€” Affiche le panel de ticket avec le sÃ©lecteur.\n"
            "`!close` â€” Ferme et supprime le ticket actuel.\n"
            "`!rename <nom>` â€” Renomme le salon du ticket.\n"
            "Exemple : `!rename probleme-connexion`"
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ‘‘ OWNERS",
        value=(
            "`!addowner @membre` â€” Ajoute un membre comme owner du bot.\n"
            "`!removeowner @membre` â€” Retire un membre des owners.\n"
            "`!owners` â€” Affiche la liste des owners.\n"
            "âš ï¸ RÃ©servÃ© aux owners et administrateurs. La liste est sauvegardÃ©e."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nâ›” BLACKLIST",
        value=(
            "`!bl @membre <raison>` â€” Bannit et blackliste un membre.\n"
            "Si ce membre rejoint un autre serveur avec le bot, il est banni automatiquement.\n\n"
            "`!unbl <ID>` â€” Retire un membre de la blacklist et le dÃ©bannit.\n"
            "Exemple : `!unbl 123456789`\n"
            "âš ï¸ RÃ©servÃ© aux administrateurs.\n\n"
            "`!blist` â€” Affiche la liste de tous les membres blacklistÃ©s."
        ),
        inline=False,
    )

    embed.add_field(
        name="â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\nðŸ¤– ANTI-SPAM",
        value="Automatique â€” si un membre envoie 5 messages en moins de 5 secondes, il est mutÃ© 10 secondes.",
        inline=False,
    )

    embed.set_footer(text="Bot dÃ©veloppÃ© sur Replit")
    await ctx.send(embed=embed)


# =========================
# RUN
# =========================
token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN manquant dans les variables d'environnement.")

bot.run(token)
