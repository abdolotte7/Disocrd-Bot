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
COMMAND_RESPONSE_CHANNEL_ID = 1370376699442630749  # Channel for command responses
LOG_CHANNEL_ID = 1381939349855273100  # Channel for debug logs
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
    "frioo": "<:frioo:1381926924779262054>",
    "paitama": "<:paitama:1381915009730347090>",
    "tuturum": "<:tuturum:1381925063074512977>",
    "dae in": "<:dae_in:1381907460566155395>",
    "god speed": "<:godspeed:1381911161775329324>",
    "wesil": "🦊",
    "monarch": "<:monarch:1381921265329373264>",
    "magma": "🌋"

}

intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
intents.guilds = True  # Enable guild intent for accessing guild information

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

async def log_to_discord(message):
    """Send debug/console messages to Discord log channel."""
    try:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            # Truncate message if too long for Discord (2000 char limit)
            if len(message) > 1900:
                message = message[:1900] + "..."
            await log_channel.send(f"```{message}```")
    except Exception as e:
        print(f"Failed to log to Discord: {e}")

def enhanced_print(message):
    """Print to console and send to Discord log channel."""
    print(message)
    if bot.is_ready():
        asyncio.create_task(log_to_discord(message))

async def scan_recent_messages_for_bosses():
    """Scans the last 10 minutes of messages from source channels to rebuild boss data."""
    now = datetime.utcnow() + timedelta(hours=2)
    cutoff_time = now - timedelta(minutes=10)

    enhanced_print("Scanning recent messages to rebuild boss data...")

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
                    enhanced_print(f"Found recent report: Floor {floor}, Boss: {boss_name}")

                    # Track reports per floor
                    boss_data = reported_bosses[floor]
                    boss_data["reports"][boss_name] = boss_data["reports"].get(boss_name, 0) + 1

                    # Update current boss based on reports (require 3+ for changes)
                    if len(boss_data["reports"]) == 1:
                        boss_data["current_boss"] = (boss_name, emoji)
                    else:
                        # Find boss with 3+ reports
                        boss_with_3_plus = None
                        for boss, count in boss_data["reports"].items():
                            if count >= 3:
                                boss_with_3_plus = boss
                                break
                        
                        if boss_with_3_plus:
                            boss_data["current_boss"] = (boss_with_3_plus, BOSS_EMOJIS.get(boss_with_3_plus.lower(), ""))
                        # If no boss has 3+ reports, keep the first reported boss
                        elif not boss_data.get("current_boss"):
                            first_boss = list(boss_data["reports"].keys())[0]
                            boss_data["current_boss"] = (first_boss, BOSS_EMOJIS.get(first_boss.lower(), ""))
        except Exception as e:
            enhanced_print(f"Error scanning channel {channel_id}: {e}")

async def post_report():
    """Posts a new report only at xx:44, then edits that report for the next 11 minutes."""
    global latest_message_id, latest_message_timestamp

    now = datetime.utcnow() + timedelta(hours=2)  # Adjust for your timezone
    if now.minute < 44 or now.minute > 55:
        return  # Stop updating outside the allowed time window

    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not target_channel:
        enhanced_print("Target channel not found.")
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
                enhanced_print(f"Edited existing report (ID: {latest_message_id})")
                return
            else:
                # This message is from a previous hour, we need a new one
                enhanced_print("Report is from previous hour, need new report")
                should_post_new = True

        except discord.NotFound:
            enhanced_print("Existing report not found, will post new one and scan recent messages.")
            latest_message_id = None
            latest_message_timestamp = None
            # Scan recent messages to rebuild floor data
            await scan_recent_messages_for_bosses()
            should_post_new = True
        except discord.HTTPException as e:
            enhanced_print(f"Failed to edit message {latest_message_id}: {e}")
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
            enhanced_print(f"Posted new report (ID: {latest_message_id}) at {now.strftime('%H:%M')}")
        except discord.HTTPException as e:
            enhanced_print(f"Failed to send new message: {e}")

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

    # Post new report at xx:44 (once per hour)
    if now.minute == 44 and last_report_hour != current_hour:
        enhanced_print(f"Posting new report at {now.strftime('%H:%M:%S')}")
        await post_report()
        last_report_hour = current_hour  # ✅ Update the last report hour to prevent spam

    # Continuously update existing report between xx:45 and xx:55 (ONLY edit, don't post new)
    elif 45 <= now.minute <= 55 and latest_message_id:
        target_channel = bot.get_channel(TARGET_CHANNEL_ID)
        if target_channel:
            try:
                msg = await target_channel.fetch_message(latest_message_id)
                await msg.edit(content=await build_report_content())
                enhanced_print(f"Edited existing report (ID: {latest_message_id})")
            except discord.NotFound:
                enhanced_print("Existing report not found")
            except discord.HTTPException as e:
                enhanced_print(f"Failed to edit message: {e}")

@bot.event
async def on_message(message):
    """Processes messages from multiple source channels and updates the report."""
    global latest_message_id

    if message.author.bot:
        return  # Ignore bot messages

    # Log all messages for debugging
    if message.content.startswith('!'):
        enhanced_print(f"Command detected: {message.content} from {message.author} in channel {message.channel.id}")

    # Process commands from designated channels
    if message.channel.id in SOURCE_CHANNEL_IDS or message.channel.id == TARGET_CHANNEL_ID:
        await bot.process_commands(message)

    if message.channel.id not in SOURCE_CHANNEL_IDS:
        return  # But don't process boss reports from other channels

    enhanced_print(f"Received message from {message.channel.id}: {message.content}")

    boss_name = extract_boss_name(message.content)
    floor = extract_floor(message.content)

    if boss_name and floor:
        emoji = BOSS_EMOJIS.get(boss_name.lower(), "")  # Get emoji or empty string if not found
        enhanced_print(f"Detected Floor: {floor}, Boss: {boss_name}")

        # Track reports per floor
        boss_data = reported_bosses[floor]
        boss_data["reports"][boss_name] = boss_data["reports"].get(boss_name, 0) + 1

        # If only one report exists, set it as current boss
        if len(boss_data["reports"]) == 1:
            boss_data["current_boss"] = (boss_name, emoji)
            enhanced_print(f"Floor {floor}: First report for {boss_name}")

        # If 3 or more people report the same boss, update to that boss
        elif boss_data["reports"][boss_name] >= 3:
            # Only update if it's different from current boss
            current_boss_name = boss_data["current_boss"][0] if boss_data["current_boss"] else None
            if current_boss_name != boss_name:
                boss_data["current_boss"] = (boss_name, emoji)
                enhanced_print(f"Floor {floor}: Changed to {boss_name} (3+ reports: {boss_data['reports'][boss_name]})")
            else:
                enhanced_print(f"Floor {floor}: Confirmed {boss_name} (reports: {boss_data['reports'][boss_name]})")

        # If multiple bosses reported but none have 3+ reports, keep current boss
        else:
            enhanced_print(f"Floor {floor}: Multiple reports but no boss has 3+ yet: {boss_data['reports']}")

        # Send separate Monarch alert message
        if boss_name.upper() == "MONARCH":
            await send_monarch_alert(floor)

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

@bot.command(name="edit_message")
async def edit_message_command(ctx, floor_boss_input: str = None):
    """Manually edit a specific floor's boss in the report. Usage: !edit_message F70 Frioo or !edit F45 Gucci"""
    global latest_message_id, latest_message_timestamp, reported_bosses
    
    enhanced_print(f"Edit message command received from {ctx.author} in channel {ctx.channel.id}")
    
    # Get command response channel
    response_channel = bot.get_channel(COMMAND_RESPONSE_CHANNEL_ID)
    if not response_channel:
        response_channel = ctx.channel  # Fallback to current channel
    
    if ctx.channel.id not in SOURCE_CHANNEL_IDS and ctx.channel.id != TARGET_CHANNEL_ID:
        await response_channel.send("❌ This command can only be used in designated channels.")
        return
    
    if not floor_boss_input:
        await response_channel.send("❌ Please specify floor and boss. Example: `!edit_message F70 Frioo` or `!edit F45 Gucci`")
        return
    
    # Parse the input (e.g., "F70 Frioo" or "45 Gucci")
    parts = floor_boss_input.strip().split(None, 1)  # Split into max 2 parts
    if len(parts) != 2:
        await response_channel.send("❌ Invalid format. Use: `!edit_message F70 Frioo` or `!edit F45 Gucci`")
        return
    
    floor_part, boss_part = parts
    
    # Extract floor number
    floor_match = re.search(r"(\d{2})", floor_part)
    if not floor_match:
        await response_channel.send("❌ Invalid floor format. Use F70, 70, Floor70, etc.")
        return
    
    floor = floor_match.group(1)
    if floor not in VALID_FLOORS:
        await response_channel.send(f"❌ Invalid floor. Valid floors are: {', '.join(sorted(VALID_FLOORS, key=int))}")
        return
    
    # Find boss name from aliases
    boss_name = None
    boss_part_lower = boss_part.lower().strip()
    
    for boss, aliases in BOSS_ALIASES.items():
        for alias in aliases:
            if boss_part_lower == alias.lower():
                boss_name = boss.upper()
                break
        if boss_name:
            break
    
    if not boss_name:
        await response_channel.send(f"❌ Unknown boss '{boss_part}'. Check spelling or available bosses.")
        return
    
    # Get emoji for the boss
    emoji = BOSS_EMOJIS.get(boss_name.lower(), "")
    
    # Update the stored boss data
    boss_data = reported_bosses[floor]
    boss_data["current_boss"] = (boss_name, emoji)
    boss_data["reports"] = {boss_name: 1}  # Reset reports to show this boss as confirmed
    
    enhanced_print(f"Manual edit: Floor {floor} set to {boss_name}")
    
    # Try to update the latest report message
    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not target_channel:
        await response_channel.send("❌ Target channel not found.")
        return
    
    updated = False
    
    # Try to edit the latest message if it exists
    if latest_message_id:
        try:
            msg = await target_channel.fetch_message(latest_message_id)
            await msg.edit(content=await build_report_content())
            updated = True
            enhanced_print(f"Manual edit: Updated existing report (ID: {latest_message_id})")
        except discord.NotFound:
            enhanced_print("Manual edit: Latest message not found")
        except discord.HTTPException as e:
            enhanced_print(f"Manual edit: Failed to edit message: {e}")
    
    # If no latest message or edit failed, try to find and update recent reports
    if not updated:
        now = datetime.utcnow() + timedelta(hours=2)
        cutoff_time = now - timedelta(minutes=30)  # Look for reports in last 30 minutes
        
        try:
            async for message in target_channel.history(limit=50, after=cutoff_time):
                if message.author == bot.user and "INFERNAL CASTLE SPAWNED" in message.content:
                    try:
                        await message.edit(content=await build_report_content())
                        latest_message_id = message.id
                        latest_message_timestamp = message.created_at.replace(tzinfo=None) + timedelta(hours=2)
                        updated = True
                        enhanced_print(f"Manual edit: Updated recent report (ID: {message.id})")
                        break
                    except discord.HTTPException as e:
                        enhanced_print(f"Manual edit: Failed to edit message {message.id}: {e}")
        except Exception as e:
            enhanced_print(f"Manual edit: Error scanning for recent reports: {e}")
    
    # Send confirmation
    if updated:
        await response_channel.send(f"✅ **Floor {floor}** has been manually set to **{emoji} {boss_name}** and report updated!")
        
        # Send separate Monarch alert if needed
        if boss_name.upper() == "MONARCH":
            await send_monarch_alert(floor)
    else:
        await response_channel.send(f"✅ **Floor {floor}** has been set to **{emoji} {boss_name}** but no recent report found to update. Data will be used in next report.")

@bot.command(name="edit")
async def edit_command(ctx, *, floor_boss_input: str = None):
    """Alias for edit_message command. Usage: !edit F70 Frioo"""
    await edit_message_command(ctx, floor_boss_input)

@bot.command(name="force_update")
async def force_update_command(ctx):
    """Manually force an update of the boss report by scanning recent messages and updating all recent reports."""
    global latest_message_id, latest_message_timestamp, reported_bosses
    
    enhanced_print(f"Force update command received from {ctx.author} in channel {ctx.channel.id}")
    
    # Get command response channel
    response_channel = bot.get_channel(COMMAND_RESPONSE_CHANNEL_ID)
    if not response_channel:
        response_channel = ctx.channel  # Fallback to current channel
    
    if ctx.channel.id in SOURCE_CHANNEL_IDS or ctx.channel.id == TARGET_CHANNEL_ID:
        target_channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not target_channel:
            await response_channel.send("❌ Target channel not found.")
            return

        # Clear existing boss data and rebuild from recent messages
        reported_bosses.clear()
        enhanced_print("Force update: Scanning source channels for recent boss reports...")
        
        # Scan both source channels for the last 10 minutes
        await scan_recent_messages_for_bosses()
        
        # Find all bot reports from the last 50 minutes and update them
        now = datetime.utcnow() + timedelta(hours=2)
        cutoff_time = now - timedelta(minutes=50)
        updated_count = 0
        
        enhanced_print("Force update: Looking for recent bot reports to update...")
        try:
            async for message in target_channel.history(limit=100, after=cutoff_time):
                if message.author == bot.user and "INFERNAL CASTLE SPAWNED" in message.content:
                    try:
                        await message.edit(content=await build_report_content())
                        updated_count += 1
                        enhanced_print(f"Force update: Updated report (ID: {message.id})")
                        
                        # Update the latest_message_id to the most recent one
                        if not latest_message_id or message.created_at > latest_message_timestamp:
                            latest_message_id = message.id
                            latest_message_timestamp = message.created_at.replace(tzinfo=None) + timedelta(hours=2)
                            
                    except discord.HTTPException as e:
                        enhanced_print(f"Force update: Failed to edit message {message.id}: {e}")
        except Exception as e:
            enhanced_print(f"Force update: Error scanning target channel: {e}")
        
        if updated_count > 0:
            await response_channel.send(f"✅ Force update complete! Updated {updated_count} recent report(s) with latest boss data.")
        else:
            # If no recent reports found, post a new one
            await post_report()
            await response_channel.send("✅ No recent reports found. Posted new report with latest data!")
    else:
        await response_channel.send("❌ This command can only be used in designated channels.")

@bot.command(name="botuptime")
async def uptime_command(ctx):
    """Provides a link for UptimeRobot to ping."""
    enhanced_print(f"Uptime command received from {ctx.author}")
    response_channel = bot.get_channel(COMMAND_RESPONSE_CHANNEL_ID) or ctx.channel
    replit_url = "https://replit.com/@abdolotte7/Spidy-Castle-Bot"
    await response_channel.send(f"Ping this link with UptimeRobot: {replit_url}")

@bot.command(name="test")
async def test_command(ctx):
    """Test command to check if bot is responding."""
    enhanced_print(f"Test command received from {ctx.author}")
    response_channel = bot.get_channel(COMMAND_RESPONSE_CHANNEL_ID) or ctx.channel
    await response_channel.send("✅ Bot is working! Commands are functional.")

@bot.command(name="permissions")
async def check_permissions(ctx):
    """Check bot permissions in current channel."""
    enhanced_print(f"Permission check requested by {ctx.author}")
    response_channel = bot.get_channel(COMMAND_RESPONSE_CHANNEL_ID) or ctx.channel
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

    await response_channel.send(f"**Bot Permissions:**\n" + "\n".join(perm_list))

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
    enhanced_print(f"Logged in as {bot.user}")

    if not update_report.is_running():  # ✅ Prevent multiple loops
        update_report.start()

bot.run(TOKEN)
