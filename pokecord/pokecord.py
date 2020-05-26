import base64
import hashlib
import json
import logging
import os
import random
import string
from abc import ABC

import discord
from PIL import Image
from redbot.core import Config, checks, commands
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from redbot.core.utils.chat_formatting import humanize_list

from .settings import SettingsMixin

log = logging.getLogger("red.flare.pokecord")


class CompositeMetaClass(type(commands.Cog), type(ABC)):
    """This allows the metaclass used for proper type detection to coexist with discord.py's
    metaclass."""


class Pokecord(SettingsMixin, commands.Cog, metaclass=CompositeMetaClass):
    """Pokecord adapted to use on Red."""

    __version__ = "0.0.1a"
    __author__ = "flare"

    def format_help_for_context(self, ctx):
        """Thanks Sinbad."""
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\nAuthor: {self.__author__}\nCog Version: {self.__version__}"

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=95932766180343808, force_registration=True)
        self.config.register_global(isglobal=True, hashed=False, hashes={})
        defaults_guild = {"activechannels": [], "toggle": False}
        self.config.register_guild(**defaults_guild)
        defaults_user = {"pokemon": [], "silence": False, "timestamp": 0}
        self.config.register_user(**defaults_user)
        self.config.register_member(**defaults_user)
        self.datapath = f"{bundled_data_path(self)}"
        self.spawnedpokemon = {}
        self.maybe_spawn = {}

    async def initalize(self):
        with open(f"{self.datapath}/pokemon.json") as f:
            self.pokemondata = json.load(f)
        if not await self.config.hashed():
            log.info("hashing...")
            hashes = {}
            for file in os.listdir(self.datapath):
                if file.endswith(".png"):
                    cmd = (
                        base64.b64decode(
                            b"aGFzaGVzW2ZpbGVdID0gaGFzaGxpYi5tZDUoSW1hZ2Uub3BlbihyJ3tzZWxmLmRhdGFwYXRofS97ZmlsZX0nKS50b2J5dGVzKCkpLmhleGRpZ2VzdCgp"
                        )
                        .decode("utf-8")
                        .replace("'", '"')
                        .replace(r"{self.datapath}", self.datapath)
                        .replace(r"{file}", file)
                    )
                    exec(cmd)
            await self.config.hashes.set(hashes)
            await self.config.hashed.set(True)
            log.info("Hashing complete")

    async def is_global(self, guild):
        toggle = await self.config.isglobal()
        if toggle:
            return self.config
        return self.config.guild(guild)

    async def user_is_global(self, user):
        toggle = await self.config.isglobal()
        if toggle:
            return self.config.user(user)
        return self.config.member(user)

    def pokemon_choose(self):
        num = random.randint(1, 200)
        if num > 2:
            return random.choice(self.pokemondata["normal"])
        return random.choice(self.pokemondata["mega"])

    @commands.command()
    async def list(self, ctx):
        """List your pokémon!"""
        conf = await self.user_is_global(ctx.author)
        pokemons = await conf.pokemon()
        if not pokemons:
            return await ctx.send("You don't have any pokémon, go get catching trainer!")
        embeds = []
        for i, pokemon in enumerate(pokemons, 1):
            desc = f"**Level**: {pokemon['level']}\n**XP**: {pokemon['xp']}/{self.calc_xp(pokemon['level'])}"
            embed = discord.Embed(title=pokemon["name"], description=desc)
            embed.set_image(url=f"https://flaree.xyz/data/{pokemon['name']}.png")
            embed.set_footer(text=f"Pokémon ID: {i}")
            embeds.append(embed)
        await menu(ctx, embeds, DEFAULT_CONTROLS)

    @commands.command()
    async def catch(self, ctx, *, pokemon: str):
        """Catch a pokemon!"""
        if self.spawnedpokemon.get(ctx.guild.id) is not None:
            pokemonspawn = self.spawnedpokemon[ctx.guild.id].get(ctx.channel.id)
            if pokemonspawn is not None:
                if pokemon.lower() in [
                    pokemonspawn["name"].lower(),
                    pokemonspawn["name"].strip(string.punctuation).lower(),
                ]:
                    await ctx.send(f"Congratulations, you've caught {pokemonspawn['name']}.")
                    conf = await self.user_is_global(ctx.author)
                    async with conf.pokemon() as pokemon:
                        pokemonspawn["level"] = random.randint(1, 13)
                        pokemonspawn["xp"] = 0
                        pokemon.append(pokemonspawn)
                    del self.spawnedpokemon[ctx.guild.id][ctx.channel.id]
                    return
                else:
                    return await ctx.send("That's not the correct pokemon")
        await ctx.send("No pokemon is ready to be caught.")

    def spawn_chance(self, guildid):
        return self.maybe_spawn[guildid]["amount"] > self.maybe_spawn[guildid]["spawnchance"]

    async def get_hash(self, pokemon):
        return (await self.config.hashes())[pokemon]

    @commands.Cog.listener()
    async def on_message(self, message):
        # if message.content == "spawn":
        #     if message.guild.id not in self.spawnedpokemon:
        #         self.spawnedpokemon[message.guild.id] = {}
        #     pokemon = self.pokemon_choose()
        #     log.info(pokemon)
        #     self.spawnedpokemon[message.guild.id][message.channel.id] = pokemon
        #     await message.channel.send(file=discord.File(f"{self.datapath}/{pokemon['name']}.png"))

        if not message.guild:
            return
        if message.author.bot:
            return
        guild_data = await self.config.guild(message.guild).all()
        if not guild_data["toggle"]:
            return
        await self.exp_gain(message.channel, message.author)
        if message.guild.id not in self.maybe_spawn:
            self.maybe_spawn[message.guild.id] = {
                "amount": 0,
                "spawnchance": random.randint(40, 170),
            }  # TODO: big value
        self.maybe_spawn[message.guild.id]["amount"] += 1
        should_spawn = self.spawn_chance(message.guild.id)
        if not should_spawn:
            return
        del self.maybe_spawn[message.guild.id]
        if not guild_data["activechannels"]:
            channel = message.channel
        else:
            channel = message.guild.get_channel(int(random.choice(guild_data["activechannels"])))
            if channel is None:
                return  # TODO: Remove channel from config
        if message.guild.id not in self.spawnedpokemon:
            self.spawnedpokemon[message.guild.id] = {}
        pokemon = self.pokemon_choose()
        log.info(pokemon)
        self.spawnedpokemon[message.guild.id][message.channel.id] = pokemon
        prefixes = await self.bot.get_valid_prefixes(guild=message.guild)
        embed = discord.Embed(
            title="‌‌A wild pokémon has аppeаred!",
            description=f"Guess the pokémon аnd type {prefixes[0]}catch <pokémon> to cаtch it!",
        )
        hashe = await self.get_hash(f"{pokemon['name']}.png")
        embed.set_image(url=f"https://flaree.xyz/data/{hashe}.png")
        await channel.send(embed=embed)

    def calc_xp(self, lvl):
        return 5 * lvl * 5

    async def exp_gain(self, channel, user):
        conf = await self.user_is_global(user)
        async with conf.pokemon() as pokemons:
            if not pokemons:
                return
            pokemon = None
            for i, poke in enumerate(pokemons):
                if poke["level"] < 100:
                    pokemon = poke
                    xp = random.randint(1, 4)
                    poke["xp"] += xp
                    if poke["xp"] >= self.calc_xp(poke["level"]):
                        poke["level"] += 1
                        poke["xp"] = 0
                        log.info(f"{poke['name']} levelled up for {user}")
                        for stat in poke["stats"]:
                            poke["stats"][stat] = int(poke["stats"][stat]) + random.randint(1, 3)
                        if not await conf.silence():
                            embed = discord.Embed(title=f"Congratulations {user}!", description=f"Your {poke['name']} has levelled up to level {poke['level']}!")
                            await channel.send(embed=embed)
                    return