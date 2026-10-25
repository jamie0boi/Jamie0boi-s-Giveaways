
import os
import re
import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

giveaways = {}


def parse_duration(value):
    match = re.fullmatch(r"(\d+)([smhd])", value.lower().strip())
    if not match:
        raise ValueError("Use a duration like 30s, 10m, 2h or 1d.")

    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

    if amount < 1 or seconds > 30 * 86400:
        raise ValueError("Duration must be between 1 second and 30 days.")

    return seconds


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(
        label="Join Giveaway 🎉",
        style=discord.ButtonStyle.primary,
        custom_id="giveaway:join"
    )
    async def join(self, interaction, button):
        data = giveaways.get(self.giveaway_id)

        if not data or data["ended"]:
            await interaction.response.send_message(
                "This giveaway has ended.", ephemeral=True
            )
            return

        if interaction.user.id in data["entrants"]:
            await interaction.response.send_message(
                "You have already entered!", ephemeral=True
            )
            return

        data["entrants"].add(interaction.user.id)
        await interaction.response.send_message(
            "You're entered into the giveaway! 🎉", ephemeral=True
        )


giveaway = app_commands.Group(
    name="giveaway",
    description="Manage server giveaways"
)


async def finish_giveaway(giveaway_id):
    data = giveaways.get(giveaway_id)

    if not data or data["ended"]:
        return

    data["ended"] = True
    entrants = list(data["entrants"])
    winners = random.sample(entrants, min(data["winner_count"], len(entrants)))
    data["winners"] = winners

    channel = bot.get_channel(data["channel_id"])
    if channel is None:
        channel = await bot.fetch_channel(data["channel_id"])

    message = await channel.fetch_message(data["message_id"])

    embed = discord.Embed(
        title="🎉 Giveaway Ended!",
        description=f"**Prize:** {data['prize']}\n"
                    f"**Entries:** {len(entrants)}",
        color=discord.Color.gold()
    )

    if winners:
        result = ", ".join(f"<@{user_id}>" for user_id in winners)
        embed.add_field(name="Winner(s)", value=result)
    else:
        embed.add_field(name="Winner(s)", value="Nobody entered.")

    await message.edit(embed=embed, view=None)

    if winners:
        await channel.send(
            f"Congratulations {', '.join(f'<@{w}' for w in [])}"
            if False else
            f"🎉 Congratulations "
            + ", ".join(f"<@{w}>" for w in winners)
            + f"! You won **{data['prize']}**!"
        )


@giveaway.command(name="start", description="Start a giveaway")
@app_commands.describe(
    prize="What are you giving away?",
    duration="Duration, e.g. 10m, 2h or 1d",
    winners="Number of winners"
)
async def start_giveaway(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    winners: app_commands.Range[int, 1, 20] = 1
):
    try:
        seconds = parse_duration(duration)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return

    if not interaction.channel:
        await interaction.response.send_message(
            "I couldn't find this channel.", ephemeral=True
        )
        return

    giveaway_id = str(interaction.id)

    data = {
        "prize": prize,
        "winner_count": winners,
        "entrants": set(),
        "ended": False,
        "winners": [],
        "channel_id": interaction.channel_id,
        "message_id": None
    }
    giveaways[giveaway_id] = data

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"**Prize:** {prize}\n"
                    f"**Winners:** {winners}\n"
                    f"**Duration:** {duration}\n\n"
                    f"Press the button below to enter!",
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Hosted by {interaction.user}")

    await interaction.response.send_message(
        embed=embed, view=GiveawayView(giveaway_id)
    )
    message = await interaction.original_response()
    data["message_id"] = message.id

    async def timer():
        await asyncio.sleep(seconds)
        await finish_giveaway(giveaway_id)

    bot.loop.create_task(timer())


@giveaway.command(name="end", description="End a giveaway early")
@app_commands.describe(message_id="ID of the giveaway message")
async def end_giveaway(
    interaction: discord.Interaction, message_id: str
):
    data = next(
        (g for g in giveaways.values()
         if str(g["message_id"]) == message_id),
        None
    )

    if not data:
        await interaction.response.send_message(
            "Giveaway not found. Check the message ID.",
            ephemeral=True
        )
        return

    if data["ended"]:
        await interaction.response.send_message(
            "That giveaway has already ended.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "Ending the giveaway...", ephemeral=True
    )
    giveaway_id = next(
        key for key, value in giveaways.items() if value is data
    )
    await finish_giveaway(giveaway_id)


@giveaway.command(name="reroll", description="Pick a new winner")
@app_commands.describe(message_id="ID of the giveaway message")
async def reroll_giveaway(
    interaction: discord.Interaction, message_id: str
):
    data = next(
        (g for g in giveaways.values()
         if str(g["message_id"]) == message_id),
        None
    )

    if not data or not data["ended"]:
        await interaction.response.send_message(
            "Finished giveaway not found.", ephemeral=True
        )
        return

    remaining = list(
        data["entrants"] - set(data["winners"])
    )

    if not remaining:
        await interaction.response.send_message(
            "No eligible entrants remain.", ephemeral=True
        )
        return

    winner = random.choice(remaining)
    data["winners"].append(winner)

    await interaction.response.send_message(
        f"🎉 New winner: <@{winner}>! "
        f"You won **{data['prize']}**!"
    )


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Online as {bot.user}")


bot.tree.add_command(giveaway)

if not TOKEN:
    raise RuntimeError("Set the DISCORD_TOKEN environment variable!")

bot.run(TOKEN)
