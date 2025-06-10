import discord
from discord.ext import commands, tasks
import asyncio
import re
import os
from datetime import datetime, timedelta
from collections import defaultdict

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SOURCE_CHANNEL_IDS = {1370376699442630749, 1381785444018028544}  # Set of allowed source channels
TARGET_CHANNEL_ID = 1381601141959295082  # Channel where the bot posts the report
PING_ROLE_ID = 1370329783703175168  # Role to ping in the main report
SJW_ROLE_ID = 1370390270138384425  # Role to ping if Monarch/SJW is spotted

# Store the latest message ID for editing
latest_message_id = None
latest_message_timestamp = None  # Store the timestamp of the last report
reported_bosses = defaultdict(lambda: {"reports": {}, "current_boss": None})  # Stores reports per floor

# Allowed floor numbers
VALID_FLOORS = {"30", "35", "40", "45", "55", "60", "65", "70"}

# Boss name mapping (case-insensitive)
BOSS_ALIASES = {
    "vermillion": ["vermillion", "igris"],
    "dor": ["dor" , "pain"],
    "mifalcon": ["mifalcon"],
    "murcielago": ["murcielago" , "uliq" , "mulq"],
    "time king": ["time", "time king", "timeking"],
    "chainsaw": ["chainsaw", "chainsaw man"],
    "gucci": ["gucci", "guci", "pucci"],
    "frioo": ["frioo", "frio", "friza"],
    "paitama": ["saitama", "paitama" , "one punch"],
    "tuturum": ["tuturum", "okarun" , "tut" , "tutrum"],
    "dae in": ["dae in", "cha hae-in", "cha hae", "chahae", "chahaein", "cha in", "chae in", "chae", "daein" , "cha"],
    "god speed": ["god speed", "godspeed", "kilua", "killua" , "gon" , "god"],
    "wesil": ["wesil", "esil"],
    "magma": ["magma"],
    "monarch": ["monarch", "sjw", "shadow monarch", "sung", "jinwoo" , "song" , "woo"]
}

# Boss emoji mapping
BOSS_EMOJIS = {
    "vermillion": "🔥",
    "dor": "🛡️",
    "mifalcon": "🦅",
    "murcielago": "🦇",
    "time king": "⏳",
    "chainsaw": "🪚",
    "gucci": "<:gucci:1381919542367752283>",
    "frioo": "<:frioo:1381908818266685481>",
    "paitama": "<:paitama:1381915009730347090>",
    "tuturum": "<:tuturum:1381910261467975730>",
    "dae in": "<:dae_in:1381907460566155395>",
    "god speed": "<:godspeed:1381911161775329324>",
    "wesil": "🦊",
    "monarch": "<:monarch:1381913119529369731>",
    "magma": "🌋"

}

intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
intents.guilds = True  # Enable guild intent for accessing guild information

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

async def scan_recent_messages_for_bosses():
    """Scans the last 10 minutes of messages from source channels to rebuild boss data."""
    now = datetime.utcnow() + timedelta(hours=2)
    cutoff_time = now - timedelta(minutes=10)

    print("Scanning recent messages to rebuild boss data...")

    for channel_id in SOURCE_CHANNEL_IDS:
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        try:
            async for message in channel.history(limit=100, after=cutoff_time):
                if message.author.bot:
                    continue

                boss_name = extract_boss_name(message.content)
                floor = extract_floor(message.content)

                if boss_name and floor:
                    emoji = BOSS_EMOJIS.get(boss_name.lower(), "")
                    print(f"Found recent report: Floor {floor}, Boss: {boss_name}")

                    # Track reports per floor
                    boss_data = reported_bosses[floor]
                    boss_data["reports"][boss_name] = boss_data["reports"].get(boss_name, 0) + 1

                    # Update current boss based on reports
                    if len(boss_data["reports"]) == 1:
                        boss_data["current_boss"] = (boss_name, emoji)
                    elif len(boss_data["reports"]) >= 2:
                        most_reported_boss = max(boss_data["reports"], key=boss_data["reports"].get)
                        boss_data["current_boss"] = (most_reported_boss, BOSS_EMOJIS.get(most_reported_boss.lower(), ""))
        except Exception as e:
            print(f"Error scanning channel {channel_id}: {e}")

async def post_report():
    """Posts a new report only at xx:44, then edits that report for the next 11 minutes."""
    global latest_message_id, latest_message_timestamp

    now = datetime.utcnow() + timedelta(hours=2)  # Adjust for your timezone
    if now.minute < 44 or now.minute > 55:
        return  # Stop updating outside the allowed time window

    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not target_channel:
        print("Target channel not found.")
        return

    # Determine if we should post a new report (only at xx:44)
    should_post_new = now.minute == 44

    # If we have a latest_message_id but it's not xx:44, try to edit existing message
    if latest_message_id and latest_message_timestamp and not should_post_new:
        try:
            msg = await target_channel.fetch_message(latest_message_id)
            # Verify this message is from the current hour (xx:44 of this hour)
            message_hour = latest_message_timestamp.hour
            current_hour = now.hour

            if message_hour == current_hour:
                # This is the correct message from this hour's xx:44 posting
                await msg.edit(content=await build_report_content())
                print(f"Edited existing report (ID: {latest_message_id})")
                return
            else:
                # This message is from a previous hour, we need a new one
                print("Report is from previous hour, need new report")
                should_post_new = True

        except discord.NotFound:
            print("Existing report not found, will post new one and scan recent messages.")
            latest_message_id = None
            latest_message_timestamp = None
            # Scan recent messages to rebuild floor data
            await scan_recent_messages_for_bosses()
            should_post_new = True
        except discord.HTTPException as e:
            print(f"Failed to edit message {latest_message_id}: {e}")
            if should_post_new:
                latest_message_id = None

    # Post new report only at xx:44 or if previous message was deleted/invalid
    if should_post_new or latest_message_id is None:
        # If posting at xx:44, scan recent messages first to get latest floor data
        if should_post_new:
            await scan_recent_messages_for_bosses()

        try:
            report_content = await build_report_content()
            msg = await target_channel.send(report_content)
            latest_message_id = msg.id
            latest_message_timestamp = now
            print(f"Posted new report (ID: {latest_message_id}) at {now.strftime('%H:%M')}")
        except discord.HTTPException as e:
            print(f"Failed to send new message: {e}")

async def build_report_content():
    """Builds the report content with current boss data."""
    now = datetime.utcnow() + timedelta(hours=2)

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
    report_lines.append("-# By Spidy Hub  .gg/mHBBXKjmcP")

    return f"<@&{PING_ROLE_ID}>\n" + "\n".join(report_lines)

last_report_hour = None  # Track the last hour a report was posted

@tasks.loop(seconds=5)  # ✅ Runs every 5 seconds instead of 1
async def update_report():
    global last_report_hour

    now = datetime.utcnow() + timedelta(hours=2)  # Adjust for your timezone
    current_hour = now.hour

    print(f"Loop running at {now.strftime('%H:%M:%S')}")  # ✅ Debugging output

    # Post new report at xx:44 (once per hour)
    if now.minute == 44 and last_report_hour != current_hour:
        print(f"Posting new report at {now.strftime('%H:%M:%S')}")
        await post_report()
        last_report_hour = current_hour  # ✅ Update the last report hour to prevent spam

    # Continuously update existing report between xx:44 and xx:55
    elif 44 <= now.minute <= 55:
        print(f"Updating report at {now.strftime('%H:%M:%S')}")
        await post_report()

@bot.event
async def on_message(message):
    """Processes messages from multiple source channels and updates the report."""
    global latest_message_id

    if message.author.bot:
        return  # Ignore bot messages

    # Log all messages for debugging
    if message.content.startswith('!'):
        print(f"Command detected: {message.content} from {message.author} in channel {message.channel.id}")

    if message.channel.id not in SOURCE_CHANNEL_IDS:
        await bot.process_commands(message)  # Process commands even outside source channels
        return  # But don't process boss reports from other channels

    print(f"Received message from {message.channel.id}: {message.content}")

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

        # Send separate Monarch alert message
        if boss_name.upper() == "MONARCH":
            await send_monarch_alert(floor)

    await bot.process_commands(message)  # Allow command processing

# Store floors for which SJW alerts have already been sent
notified_floors = set()

async def send_monarch_alert(floor):
    """Sends a separate alert message when Monarch is spotted."""
    global notified_floors  # Reference the set defined above
    target_channel = bot.get_channel(TARGET_CHANNEL_ID)

    if floor not in notified_floors and target_channel:
        monarch_alert = f"<@&{SJW_ROLE_ID}> 👑 **MONARCH SPOTTED ON FLOOR {floor}!** 👑"
        await target_channel.send(monarch_alert)
        notified_floors.add(floor)  # Mark this floor as notified

@bot.command(name="force_update")
async def force_update_command(ctx):
    """Manually force an update of the boss report."""
    print(f"Force update command received from {ctx.author} in channel {ctx.channel.id}")
    if ctx.channel.id in SOURCE_CHANNEL_IDS or ctx.channel.id == TARGET_CHANNEL_ID:
        await post_report()
        await ctx.send("✅ Report has been force updated!")
    else:
        await ctx.send("❌ This command can only be used in designated channels.")

@bot.command(name="botuptime")
async def uptime_command(ctx):
    """Provides a link for UptimeRobot to ping."""
    print(f"Uptime command received from {ctx.author}")
    replit_url = "https://replit.com/@abdolotte7/Spidy-Castle-Bot"
    await ctx.send(f"Ping this link with UptimeRobot: {replit_url}")

@bot.command(name="test")
async def test_command(ctx):
    """Test command to check if bot is responding."""
    print(f"Test command received from {ctx.author}")
    await ctx.send("✅ Bot is working! Commands are functional.")

@bot.command(name="permissions")
async def check_permissions(ctx):
    """Check bot permissions in current channel."""
    print(f"Permission check requested by {ctx.author}")
    perms = ctx.channel.permissions_for(ctx.guild.me)
    perm_list = []

    if perms.send_messages:
        perm_list.append("✅ Send Messages")
    else:
        perm_list.append("❌ Send Messages")

    if perms.read_messages:
        perm_list.append("✅ Read Messages")
    else:
        perm_list.append("❌ Read Messages")

    if perms.embed_links:
        perm_list.append("✅ Embed Links")
    else:
        perm_list.append("❌ Embed Links")

    await ctx.send(f"**Bot Permissions:**\n" + "\n".join(perm_list))

def extract_boss_name(message_content):
    """Extracts boss name from message using aliases."""
    message_lower = message_content.lower()
    message_cleaned = re.sub(r"(?:f|floor)?\s*\d{2}(?:\s*f|floor|:)?", "", message_lower).strip()

    for boss, aliases in BOSS_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{alias}\b", message_cleaned):  # ✅ Match exact words or attached boss names
                return boss.upper()

    return None

def extract_floor(message_content):
    """Extracts floor number from message, ensuring it matches allowed floors."""
    message_lower = message_content.lower()
    match = re.search(r"(?:f|floor)?\s*(\d{2})(?:\s*f|floor|:)?", message_lower)

    if match:
        floor_number = match.group(1)
        if floor_number in VALID_FLOORS:
            return floor_number

    return None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    if not update_report.is_running():  # ✅ Prevent multiple loops
        update_report.start()

bot.run(TOKEN)
