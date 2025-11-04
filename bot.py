# RNL Guardian Bot - Clean, bilingual DM + 30m timeout + slash help
import os
import re
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# =========================
#        CONFIG
# =========================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# تشغيل/إيقاف حظر الروابط (افتراضي: مفعّل)
LINK_BLOCKING_ENABLED = os.getenv("LINK_BLOCKING_ENABLED", "true").lower() == "true"

# استثناءات
def _to_set(env_key: str):
    raw = os.getenv(env_key, "").replace(" ", "")
    return {int(x) for x in raw.split(",") if x.isdigit()}

ALLOWED_CHANNEL_IDS = _to_set("ALLOWED_CHANNEL_IDS")   # أمثلة: 123,456
ALLOWED_ROLE_IDS    = _to_set("ALLOWED_ROLE_IDS")      # أمثلة: 111,222

# لوج اختياري
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID")) if os.getenv("LOG_CHANNEL_ID", "").isdigit() else None

# إعدادات الحظر
AUTO_DM_ON_BLOCK      = os.getenv("AUTO_DM_ON_BLOCK", "true").lower() == "true"
AUTO_TIMEOUT_MINUTES  = int(os.getenv("AUTO_TIMEOUT_MINUTES", "30"))  # نصف ساعة افتراضيًا
GUILD_ID              = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID", "").isdigit() else None

# =========================
#      DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

URL_REGEX = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)

class ModBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
        self.link_blocking_enabled = LINK_BLOCKING_ENABLED

    async def setup_hook(self) -> None:
        # مزامنة أوامر السلاش عند التشغيل
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"🔁 Slash synced → Guild {GUILD_ID}")
        else:
            # لو البوت بعدة سيرفرات، نعمل Sync لكل واحد
            for g in self.guilds:
                await self.tree.sync(guild=discord.Object(id=g.id))
                print(f"🔁 Slash synced → {g.name} ({g.id})")

bot = ModBot()

# =============== Helpers ===============
def is_allowed(msg_or_interaction) -> bool:
    """تحقق إن كانت القناة/الرول ضمن الاستثناءات"""
    ch_id = getattr(getattr(msg_or_interaction, "channel", None), "id", None)
    if ch_id in ALLOWED_CHANNEL_IDS:
        return True
    author = getattr(msg_or_interaction, "author", None) or getattr(msg_or_interaction, "user", None)
    if isinstance(author, discord.Member):
        role_ids = {r.id for r in author.roles}
        if role_ids.intersection(ALLOWED_ROLE_IDS):
            return True
    return False

async def log(text: str):
    if LOG_CHANNEL_ID:
        ch = bot.get_channel(LOG_CHANNEL_ID)
        if ch:
            try:
                await ch.send(text)
            except Exception:
                pass

async def dm_bilingual(member: discord.Member, channel: discord.TextChannel):
    """رسالة خاص (عربي + إنجليزي) عند حذف رابط"""
    if not AUTO_DM_ON_BLOCK:
        return
    try:
        ar = (
            "⚠️ **تنبيه بخصوص الروابط**\n"
            f"تم حذف رسالتك في قناة **#{channel.name}** لأنها تحتوي على رابط، وهذا ممنوع حسب قوانين السيرفر.\n"
            "الرجاء الالتزام بالقوانين. شكرًا لتفهمك 🙏"
        )
        en = (
            "⚠️ **Link Notice**\n"
            f"Your message in **#{channel.name}** was removed because it contained a link, "
            "which is not allowed according to the server rules.\n"
            "Please follow the rules. Thanks for understanding 🙏"
        )
        await member.send(f"{ar}\n\n{en}")
    except Exception:
        pass

# =============== Events ===============
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} | Link blocking = {bot.link_blocking_enabled}")
    await log(f"✅ **RNL Guardian** started. Link blocking: **{bot.link_blocking_enabled}**")

@bot.event
async def on_message(message: discord.Message):
    # تجاهل البوتات
    if message.author.bot:
        return

    # حظر الروابط
    if bot.link_blocking_enabled and URL_REGEX.search(message.content):
        if not is_allowed(message):
            try:
                # 1) حذف الرسالة
                await message.delete()

                # 2) تحذير مؤقت في الشات
                warn = await message.channel.send(
                    f"🚫 الروابط ممنوعة هنا، {message.author.mention}. سيتم اتخاذ إجراء تلقائي.",
                    delete_after=5
                )

                # 3) رسالة خاص (عربي + إنجليزي)
                await dm_bilingual(message.author, message.channel)

                # 4) Timeout لمدة 30 دقيقة (افتراضيًا) إن أمكن
                if AUTO_TIMEOUT_MINUTES > 0:
                    try:
                        until = discord.utils.utcnow() + discord.timedelta(minutes=AUTO_TIMEOUT_MINUTES)
                        await message.author.timeout(until, reason="Posted a link while links are blocked")
                    except discord.Forbidden:
                        await log(f"⚠️ Missing permissions to timeout {message.author.mention}.")
                    except Exception as e:
                        await log(f"⚠️ Failed to timeout {message.author.mention}: {e}")

                # 5) لوج
                await log(
                    f"🧹 Deleted a link by {message.author.mention} in **#{message.channel.name}** "
                    f"(timeout {AUTO_TIMEOUT_MINUTES}m). Content:\n{message.content[:350]}"
                )

                return
            except discord.Forbidden:
                await log("⚠️ Missing permissions to delete messages.")
            except Exception as e:
                await log(f"⚠️ Error deleting message: {e}")

    # لا تنسَى تمرير الرسائل لباقي الأوامر
    await bot.process_commands(message)

# =============== Slash Commands ===============
mod = app_commands.Group(name="mod", description="RNL Guardian moderation commands")

@mod.command(name="ping", description="فحص سريع")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! ✅", ephemeral=True)

@mod.command(name="status", description="عرض الإعدادات الحالية")
async def status(interaction: discord.Interaction):
    text = (
        f"**Link blocking:** {bot.link_blocking_enabled}\n"
        f"**Allowed channels:** {', '.join(map(str, ALLOWED_CHANNEL_IDS)) or 'None'}\n"
        f"**Allowed roles:** {', '.join(map(str, ALLOWED_ROLE_IDS)) or 'None'}\n"
        f"**Log channel:** {LOG_CHANNEL_ID or 'None'}\n"
        f"**AUTO_DM_ON_BLOCK:** {AUTO_DM_ON_BLOCK}\n"
        f"**AUTO_TIMEOUT_MINUTES:** {AUTO_TIMEOUT_MINUTES}\n"
    )
    await interaction.response.send_message(text, ephemeral=True)

@mod.command(name="toggle_blocking", description="تشغيل/إيقاف حظر الروابط")
@app_commands.describe(on="true or false")
async def toggle_blocking(interaction: discord.Interaction, on: bool):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ تحتاج صلاحية Manage Server.", ephemeral=True)
        return
    bot.link_blocking_enabled = on
    await interaction.response.send_message(f"Link blocking set to **{on}**", ephemeral=True)
    await log(f"🔧 Link blocking changed to **{on}** by {interaction.user.mention}")

@mod.command(name="allow", description="إدارة الاستثناءات (قنوات/رولات)")
@app_commands.describe(type="channel أو role", add="ID لإضافته", remove="ID لإزالته")
async def allow(interaction: discord.Interaction, type: str, add: Optional[str] = None, remove: Optional[str] = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ تحتاج صلاحية Manage Server.", ephemeral=True)
        return
    global ALLOWED_CHANNEL_IDS, ALLOWED_ROLE_IDS
    type = type.lower().strip()

    def to_id(x: Optional[str]):
        return int(x) if x and x.isdigit() else None

    if type == "channel":
        add_id = to_id(add); rem_id = to_id(remove)
        if add_id: ALLOWED_CHANNEL_IDS.add(add_id)
        if rem_id and rem_id in ALLOWED_CHANNEL_IDS: ALLOWED_CHANNEL_IDS.remove(rem_id)
        result = f"Channels: {', '.join(map(str, ALLOWED_CHANNEL_IDS)) or 'None'}"
    elif type == "role":
        add_id = to_id(add); rem_id = to_id(remove)
        if add_id: ALLOWED_ROLE_IDS.add(add_id)
        if rem_id and rem_id in ALLOWED_ROLE_IDS: ALLOWED_ROLE_IDS.remove(rem_id)
        result = f"Roles: {', '.join(map(str, ALLOWED_ROLE_IDS)) or 'None'}"
    else:
        await interaction.response.send_message("استخدم `channel` أو `role`.", ephemeral=True)
        return

    await log(f"✅ Allow-list updated by {interaction.user.mention} → {result}")
    await interaction.response.send_message(result, ephemeral=True)

@mod.command(name="mute", description="Timeout لمستخدم دقائق محددة")
@app_commands.describe(user="المستخدم", minutes="المدة بالدقائق", reason="سبب (اختياري)")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: Optional[str] = None):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ تحتاج صلاحية Moderate Members.", ephemeral=True)
        return
    try:
        until = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
        await user.timeout(until, reason=reason)
        await interaction.response.send_message(
            f"🔇 {user.mention} timed out for {minutes}m. Reason: {reason or '—'}",
            ephemeral=True
        )
        await log(f"🔇 Timeout: {user.mention} for {minutes}m by {interaction.user.mention}. Reason: {reason or '—'}")
    except discord.Forbidden:
        await interaction.response.send_message("ما عندي صلاحية لتوقيف هذا المستخدم.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)

# ========= /help (Embed) =========
@bot.tree.command(name="help", description="عرض أوامر RNL Guardian")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛡️ RNL Guardian — Help",
        description="أوامر التحكم بالبُوت:",
        color=discord.Color.blurple()
    )
    embed.add_field(name="/help", value="عرض هذه القائمة.", inline=False)
    embed.add_field(name="/mod ping", value="فحص سريع.", inline=False)
    embed.add_field(name="/mod status", value="عرض الإعدادات الحالية.", inline=False)
    embed.add_field(name="/mod toggle_blocking on:true|false", value="تشغيل/إيقاف حظر الروابط.", inline=False)
    embed.add_field(name="/mod allow type:channel|role add:ID remove:ID", value="إضافة/إزالة استثناءات.", inline=False)
    embed.add_field(name="/mod mute user minutes reason", value="Timeout لمستخدم.", inline=False)
    embed.add_field(name="/mod sync", value="مزامنة أوامر السلاش (للمشرفين).", inline=False)
    embed.set_footer(text="RNL Guardian • Stay clean, stay safe.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========= /mod sync =========
@mod.command(name="sync", description="Sync slash commands (admin only)")
async def sync_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ تحتاج صلاحية Administrator.", ephemeral=True)
        return
    await bot.tree.sync(guild=interaction.guild)
    await interaction.response.send_message("✅ تم مزامنة أوامر السلاش مع هذا السيرفر.", ephemeral=True)

# Group register
bot.tree.add_command(mod)

# =========================
#         RUN
# =========================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN مفقود. ضعه في ملف .env")
    bot.run(TOKEN)
