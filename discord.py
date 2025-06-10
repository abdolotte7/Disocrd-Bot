import discord
from discord.ext import commands, tasks
import asyncio
import re
import os
from datetime import datetime, timedelta
from collections import defaultdict

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SOURCE_CHANNEL_ID = 1370328553933115453  # Channel where members report bosses
TARGET_CHANNEL_ID = 1381601141959295082  # Channel where the bot posts the report
PING_ROLE_ID = 1370329783703175168  # Role to ping in the main report
SJW_ROLE_ID = 1370390270138384425  # Role to ping if Monarch/SJW is spotted

# Store the latest message ID for editing
latest_message_id = None
reported_bosses = defaultdict(lambda: {"reports": {}, "current_boss": None})  # Stores reports per floor

# Allowed floor numbers
VALID_FLOORS = {"30", "35", "40", "45", "55", "60", "65", "70"}

# Boss name mapping (case-insensitive)
BOSS_ALIASES = {
    "vermillion": ["vermillion", "igris"],
    "dor": ["dor"],
    "mifalcon": ["mifalcon"],
    "murcielago": ["murcielago"],
    "time king": ["time", "time king", "timeking"],
    "chainsaw": ["chainsaw", "chainsaw man"],
    "gucci": ["gucci", "guci", "pucci"],
    "frioo": ["frioo", "frio", "friza"],
    "paitama": ["saitama", "paitama"],
    "tuturum": ["tuturum", "okarun"],
    "dae in": ["dae in", "cha hae-in", "cha hae", "chahae", "chahaein", "cha in", "chae in", "chae"],
    "god speed": ["god speed", "godspeed", "kilua"],
    "wesil": ["wesil", "esil"],
    "magma": ["magma"],
    "monarch": ["monarch", "sjw", "shadow monarch"]
}

# Boss emoji mapping
BOSS_EMOJIS = {
    "vermillion": "🔥",
    "dor": "🛡️",
    "mifalcon": "🦅",
    "murcielago": "🦇",
    "time king": "⏳",
    "chainsaw": "🪚",
    "gucci": "👜",
    "frioo": "❄️",
    "paitama": "👊",
    "tuturum": "⚡",
    "dae in": "🗡️",
    "god speed": "💨",
    "wesil": "🦊",
    "magma": "🌋",
    "monarch": "👑"
}

intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
intents.guilds = True  # Enable guild intent for accessing guild information

bot = commands.Bot(command_prefix="!", intents=intents)

async def post_report():
    """Posts or updates the report message."""
    global latest_message_id

    now = datetime.utcnow() + timedelta(hours=2)  # Adjust for your timezone
    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not target_channel:
        print("Error: Target channel not found.")
        return

    print("Updating report message...")

    # Create the styled report header
    report_lines = ["**INFERNAL CASTLE SPAWNED**"]
    report_lines.append("─" * 35)

    # Ensure all floors are listed, even if no boss is confirmed yet
    for floor in sorted(VALID_FLOORS, key=int):
        boss_data = reported_bosses[floor]
        if boss_data["current_boss"]:
            boss_name, emoji = boss_data["current_boss"]
            report_lines.append(f"**Floor {floor}** - {emoji} **{boss_name}**")
        else:
            report_lines.append(f"**Floor {floor}** - ⏳ *Loading*")  # Default cooldown emoji

    report_lines.append("─" * 35)

    # Add timestamp
    report_lines.append(f"*Last updated: {now.strftime('%H:%M')} - {now.strftime('%d %b')}*")
    report_lines.append("***In Spiderman we trust*** 🕷️")
    report_lines.append("")
    report_lines.append("*By Spidy Hub | .gg/mHBBXKjmcP*")

    report_content = f"<@&{PING_ROLE_ID}>\n" + "\n".join(report_lines)

    if latest_message_id:
        try:
            msg = await target_channel.fetch_message(latest_message_id)
            await msg.edit(content=report_content)  # ✅ Edits the existing message
            print(f"Edited report message at {now.strftime('%H:%M:%S')}")
        except discord.NotFound:
            print("Message not found, posting a new one.")
            latest_message_id = None

    if latest_message_id is None:
        msg = await target_channel.send(report_content)  # ✅ Posts a new message if no previous one exists
        latest_message_id = msg.id  # ✅ Stores the new message ID for future edits
        print(f"Posted new report message at {now.strftime('%H:%M:%S')}")

@tasks.loop(seconds=0.02)  # 20 milliseconds
async def update_report():
    now = datetime.utcnow() + timedelta(hours=2)  # Adjust for your timezone
    if 45 <= now.minute <= 55:
        print(f"Updating report at {now.strftime('%H:%M:%S')}")  # Debugging output
        await post_report()

@bot.command()
async def force_update(ctx):
    """Manually trigger the report update."""
    await post_report()
    await ctx.send("✅ Report updated manually!")

@bot.event
async def on_message(message):
    """Processes messages from the source channel and updates the report."""
    global latest_message_id

    if message.author.bot or message.channel.id != SOURCE_CHANNEL_ID:
        return  # Ignore bot messages and messages from other channels

    print(f"Received message: {message.content}")

    boss_name = extract_boss_name(message.content)
    floor = extract_floor(message.content)

    if boss_name and floor:
        emoji = BOSS_EMOJIS.get(boss_name.lower(), "")  # Get emoji or empty string if not found
        print(f"Detected Floor: {floor}, Boss: {boss_name}")

        # Track reports per floor
        boss_data = reported_bosses[floor]
        boss_data["reports"][boss_name] = boss_data["reports"].get(boss_name, 0) + 1

        # If only one report exists, update immediately
        if len(boss_data["reports"]) == 1:
            boss_data["current_boss"] = (boss_name, emoji)

        # If two or more people report a different boss, update to the new boss
        elif len(boss_data["reports"]) >= 2:
            most_reported_boss = max(boss_data["reports"], key=boss_data["reports"].get)
            boss_data["current_boss"] = (most_reported_boss, BOSS_EMOJIS.get(most_reported_boss.lower(), ""))

    await bot.process_commands(message)  # Allow command processing

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    update_report.start()  # ✅ Start the continuous update loop

bot.run(TOKEN)
