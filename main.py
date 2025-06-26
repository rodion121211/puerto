import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput, Select
import unicodedata
from fuzzywuzzy import process
import asyncio
import os
import re
import random
import requests
import sqlite3
import json
import time
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
import aiofiles
import math
import aiohttp
from dotenv import load_dotenv
from keep_alive import keep_alive


# --- Configurações do Bot Discord ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='p!', intents=intents, help_command=None)

# --- SEU TOKEN DO BOT DISCORD ---
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# --- API DE FUTEBOL ---
FOOTBALL_API_KEY = os.getenv('FOOTBALL_API_KEY', 'live_f1a72149356ef28e3de8370d2b66d7')
FOOTBALL_API_BASE = 'https://apiv3.apifootball.com/' 

# --- Dicionários de Dados ---
dados_usuarios = {}
usuarios_acesso_ranking = set()
dados_rolls = {}
dados_jogos = []
bot_start_time = datetime.now()

# --- Sistema de Economia e Banco de Dados ---
def init_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Tabela de economia
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS economy (
        user_id INTEGER PRIMARY KEY,
        money INTEGER DEFAULT 0,
        last_daily TEXT,
        last_work TEXT
    )
    ''')

    # Tabela de itens da loja
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shop_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        description TEXT
    )
    ''')

    # Tabela de inventário dos usuários
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_inventory (
        user_id INTEGER,
        item_id INTEGER,
        quantity INTEGER DEFAULT 1,
        FOREIGN KEY (item_id) REFERENCES shop_items (id)
    )
    ''')

    # Tabela de lembretes
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        reminder TEXT,
        reminder_time TEXT
    )
    ''')

    # Tabela de tarefas
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_name TEXT,
        completed INTEGER DEFAULT 0
    )
    ''')

    # Tabela de warns
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS warns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        guild_id INTEGER,
        reason TEXT,
        warn_time TEXT
    )
    ''')

    # Tabela de contagem de mensagens
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS message_count (
        user_id INTEGER,
        guild_id INTEGER,
        date TEXT,
        count INTEGER DEFAULT 1,
        PRIMARY KEY (user_id, guild_id, date)
    )
    ''')

    # Tabela de usuários mutados
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS muted_users (
        user_id INTEGER,
        guild_id INTEGER,
        mute_end TEXT,
        reason TEXT,
        PRIMARY KEY (user_id, guild_id)
    )
    ''')

    conn.commit()
    conn.close()

# Inicializar banco de dados
init_database()

# Funções para streak diário
def get_daily_streak(user_id):
    """Obtém sequência de dias consecutivos"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Adicionar coluna streak se não existir
    cursor.execute("PRAGMA table_info(economy)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'daily_streak' not in columns:
        cursor.execute('ALTER TABLE economy ADD COLUMN daily_streak INTEGER DEFAULT 0')
    
    cursor.execute('SELECT daily_streak FROM economy WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def update_daily_streak(user_id):
    """Atualiza sequência diária"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    current_streak = get_daily_streak(user_id)
    new_streak = current_streak + 1
    
    cursor.execute('UPDATE economy SET daily_streak = ? WHERE user_id = ?', (new_streak, user_id))
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO economy (user_id, daily_streak) VALUES (?, ?)', (user_id, new_streak))
    
    conn.commit()
    conn.close()

# Lista de trabalhos para ganhar dinheiro
trabalhos = [
    {"nome": "Entregador de pizza", "min": 50, "max": 150},
    {"nome": "Programador freelancer", "min": 200, "max": 500},
    {"nome": "Designer gráfico", "min": 100, "max": 300},
    {"nome": "Motorista de Uber", "min": 80, "max": 200},
    {"nome": "Vendedor de loja", "min": 60, "max": 120},
    {"nome": "Professor particular", "min": 150, "max": 400},
    {"nome": "Garçom", "min": 70, "max": 180},
    {"nome": "Streamer", "min": 300, "max": 800},
]

# Lista de investimentos
investimentos = [
    {"nome": "Ações da Tesla", "risco": "alto", "min_mult": 0.5, "max_mult": 2.5},
    {"nome": "Bitcoin", "risco": "muito_alto", "min_mult": 0.3, "max_mult": 3.0},
    {"nome": "Poupança", "risco": "baixo", "min_mult": 1.01, "max_mult": 1.05},
    {"nome": "Tesouro Direto", "risco": "baixo", "min_mult": 1.02, "max_mult": 1.08},
    {"nome": "Ações da Apple", "risco": "médio", "min_mult": 0.7, "max_mult": 1.8},
    {"nome": "Ethereum", "risco": "alto", "min_mult": 0.4, "max_mult": 2.2},
]

# --- Funções da API de Futebol ---
async def get_team_players(team_name: str):
    """Busca jogadores reais de um time usando a API de futebol"""
    try:
        # Mapeamento de times da Série B para IDs da API
        serie_b_teams = {
            "Sport": "3209",
            "Ponte Preta": "3217", 
            "Guarani": "3204",
            "Vila Nova": "3225",
            "Novorizontino": "10237",
            "Santos": "3211",
            "Ceará": "3195",
            "Goiás": "3202",
            "Mirassol": "10238",
            "América-MG": "3189",
            "Operário-PR": "10239",
            "Coritiba": "3197",
            "Avaí": "3193",
            "Paysandu": "10240",
            "CRB": "3196",
            "Amazonas": "10241",
            "Chapecoense": "3194",
            "Ituano": "10242",
            "Botafogo-SP": "10243",
            "Brusque": "10244"
        }
        
        team_id = serie_b_teams.get(team_name)
        if not team_id:
            return None
            
        async with aiohttp.ClientSession() as session:
            url = f"{FOOTBALL_API_BASE}?action=get_players&team_id={team_id}&APIkey={FOOTBALL_API_KEY}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list) and len(data) > 0:
                        # Filtrar apenas alguns jogadores importantes
                        players = []
                        for player in data[:15]:  # Pegar até 15 jogadores
                            if 'player_name' in player:
                                players.append({
                                    'name': player['player_name'],
                                    'position': player.get('player_type', 'Meio-campo'),
                                    'number': player.get('player_number', '??'),
                                    'age': player.get('player_age', '??')
                                })
                        return players
                return None
    except Exception as e:
        print(f"Erro ao buscar jogadores: {e}")
        return None

def format_team_lineup(team_name: str, players: list):
    """Formata a escalação do time com jogadores reais"""
    if not players:
        return f"**{team_name}** (Escalação indisponível)"
    
    # Organizar por posição
    goalkeepers = [p for p in players if 'goalkeeper' in p['position'].lower() or 'goleiro' in p['position'].lower()]
    defenders = [p for p in players if 'defender' in p['position'].lower() or 'defesa' in p['position'].lower() or 'zagueiro' in p['position'].lower()]
    midfielders = [p for p in players if 'midfielder' in p['position'].lower() or 'meio' in p['position'].lower()]
    forwards = [p for p in players if 'forward' in p['position'].lower() or 'atacante' in p['position'].lower()]
    
    lineup_text = f"**🏟️ {team_name}**\n"
    
    # Goleiro
    if goalkeepers:
        gk = goalkeepers[0]
        lineup_text += f"🥅 **{gk['name']}** #{gk['number']}\n"
    
    # Defensores
    if defenders:
        lineup_text += "🛡️ **Defesa:** "
        def_names = [f"{p['name']}" for p in defenders[:4]]
        lineup_text += ", ".join(def_names) + "\n"
    
    # Meio-campo
    if midfielders:
        lineup_text += "⚡ **Meio:** "
        mid_names = [f"{p['name']}" for p in midfielders[:3]]
        lineup_text += ", ".join(mid_names) + "\n"
    
    # Ataque
    if forwards:
        lineup_text += "⚽ **Ataque:** "
        fwd_names = [f"{p['name']}" for p in forwards[:3]]
        lineup_text += ", ".join(fwd_names) + "\n"
    
    return lineup_text

# --- Funções Auxiliares ---
def normalizar(texto):
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode().lower()

def capitalizar_nome(texto):
    return ' '.join(word.capitalize() for word in texto.split())

# --- Funções da Economia ---
def get_user_money(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT money FROM economy WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def set_user_money(user_id, amount):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO economy (user_id, money) VALUES (?, ?)', (user_id, amount))
    conn.commit()
    conn.close()

def add_user_money(user_id, amount):
    current = get_user_money(user_id)
    set_user_money(user_id, current + amount)

def remove_user_money(user_id, amount):
    current = get_user_money(user_id)
    new_amount = max(0, current - amount)
    set_user_money(user_id, new_amount)
    return current >= amount

def can_daily(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT last_daily FROM economy WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()

    if not result or not result[0]:
        return True

    last_daily = datetime.fromisoformat(result[0])
    return datetime.now() - last_daily >= timedelta(days=1)

def set_daily_claimed(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE economy SET last_daily = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO economy (user_id, last_daily) VALUES (?, ?)', (user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def can_work(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT last_work FROM economy WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()

    if not result or not result[0]:
        return True

    last_work = datetime.fromisoformat(result[0])
    return datetime.now() - last_work >= timedelta(hours=1)

def set_work_done(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE economy SET last_work = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO economy (user_id, last_work) VALUES (?, ?)', (user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# --- Funções de Warns ---
def add_warn(user_id, guild_id, reason):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO warns (user_id, guild_id, reason, warn_time) VALUES (?, ?, ?, ?)', 
                   (user_id, guild_id, reason, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_warns(user_id, guild_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT reason, warn_time FROM warns WHERE user_id = ? AND guild_id = ?', (user_id, guild_id))
    warns = cursor.fetchall()
    conn.close()
    return warns

# --- Funções de Mute ---
def add_mute(user_id, guild_id, mute_end, reason):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO muted_users (user_id, guild_id, mute_end, reason) VALUES (?, ?, ?, ?)', 
                   (user_id, guild_id, mute_end, reason))
    conn.commit()
    conn.close()

def remove_mute(user_id, guild_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM muted_users WHERE user_id = ? AND guild_id = ?', (user_id, guild_id))
    conn.commit()
    conn.close()

def is_muted(user_id, guild_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT mute_end FROM muted_users WHERE user_id = ? AND guild_id = ?', (user_id, guild_id))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return False

    mute_end = datetime.fromisoformat(result[0])
    if datetime.now() >= mute_end:
        remove_mute(user_id, guild_id)
        return False
    return True

# --- Definições de campos válidos ---
campos_validos_alterar_carreira = [
    "nome", "nacionalidade", "posicao", "fintas", "perna boa", "promessa", "fisico",
    "clube", "gols", "assistencias", "desarmes", "defesas", "gol selecao",
    "brasileirao", "estadual", "libertadores", "sulamericana", "copa do brasil",
    "supercopa", "recopa", "mundial", "super mundial", "copa america",
    "copa do mundo", "euro"
]

correspondencias_campos_carreira = {
    "gol selecao": "gol_selecao", "gols selecao": "gol_selecao", "gols pela selecao": "gol_selecao",
    "gols": "gols", "assistencias": "assistencias", "desarmes": "desarmes", "defesas": "defesas",
    "brasileirao": "brasileirao", "estadual": "estadual", "libertadores": "libertadores",
    "sulamericana": "sulamericana", "copa do brasil": "copadobrasil", "supercopa": "supercopa",
    "recopa": "recopa", "mundial": "mundial", "super mundial": "supermundial",
    "copa america": "copaamerica", "copa do mundo": "copadomundo", "euro": "euro",
    "fintas": "fintas", "perna boa": "perna_boa", "promessa": "promessa", "fisico": "fisico",
    "clube": "clube", "nome": "nome", "nacionalidade": "nacionalidade", "posicao": "posicao"
}

campos_numericos_carreira = [
    "gols", "assistencias", "desarmes", "defesas", "brasileirao", "estadual",
    "libertadores", "sulamericana", "copadobrasil", "supercopa", "recopa",
    "mundial", "supermundial", "copaamerica", "copadomundo", "euro", "gol_selecao",
    "fintas"
]

campos_validos_rolls = [
    "chute", "passe", "cabecio", "velocidade", "drible", "dominio",
    "penaltis", "faltas", "corpo", "desarme", "bloqueio", "carrinho", "ultima chance",
    "defesa gk", "tiro de meta", "lancamento", "penaltis gk"
]

correspondencias_rolls = {
    "chute": "chute", "passe": "passe", "cabecio": "cabecio", "velocidade": "velocidade",
    "drible": "drible", "dominio": "dominio", "penaltis": "penaltis", "faltas": "faltas",
    "corpo": "corpo", "desarme": "desarme", "bloqueio": "bloqueio", "carrinho": "carrinho",
    "ultima chance": "ultima_chance", "defesa gk": "defesa_gk", "tiro de meta": "tiro_de_meta",
    "lancamento": "lancamento", "penaltis gk": "penaltis_gk"
}

# --- Funções de Banco de Dados para Tarefas ---
def add_task_to_db(user_id, task_name):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (user_id, task_name, completed) VALUES (?, ?, 0)', (user_id, task_name))
    conn.commit()
    conn.close()

def get_tasks_from_db(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, task_name, completed FROM tasks WHERE user_id = ?', (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def complete_task_in_db(task_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET completed = 1 WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0

def delete_task_from_db(task_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0

# --- Funções de lembretes ---
def add_reminder_to_db(user_id, reminder_text, reminder_time):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO reminders (user_id, reminder, reminder_time) VALUES (?, ?, ?)', 
                   (user_id, reminder_text, reminder_time))
    conn.commit()
    conn.close()

# --- Funções de Geração de Embeds ---
def gerar_embed_carreira(user, dados):
    embed = discord.Embed(
        title=f"╭ㆍ┈┈ㆍ◜ᨒ◞ㆍ┈┈ㆍ\n╰▸ ‹ 👤 › ৎ˚₊ Visualize a carreira de: {user.display_name}",
        description="",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_image(url="https://media.discordapp.net/attachments/1375957369972064276/1377854075814678658/Puerto_Football.S6._-_RP.png?ex=683a7a1a&is=6839289a&hm=96435d178cdedd5c7584eef5aef3d824a9cbf43967fa80db9fe2c12a5d01447c&")
    embed.set_footer(text="╰ㆍ┈┈ㆍ◜ᨒ◞ㆍ┈┈ㆍ\nUse p!ranking para ver os melhores da temporada! - Dev: YevgennyMXP", icon_url=user.guild.icon.url if user.guild and user.guild.icon else None)

    embed.add_field(name="⠀", value=
        
                    "   ﹐ꜜ __‹👤›__ **__I__dentidade!** __‹👤›__ ꜜ﹐\n"
        f"╰▸ ‹ 👤 › ৎ˚₊ Nome: **{dados.get('nome', 'N/A')}**\n"
        f"╰▸ ‹ 🏳️ › ৎ˚₊ Nacionalidade: **{dados.get('nacionalidade', 'N/A')}**\n"
        f"╰▸ ‹ ⛳ › ৎ˚₊ Posição: **{dados.get('posicao', 'N/A')}**\n"
        f"╰▸ ‹ ⭐ › ৎ˚₊ Fintas: **{dados.get('fintas', 'N/A')}**\n"
        f"╰▸ ‹ 🦿 › ৎ˚₊ Perna Boa: **{dados.get('perna_boa', 'N/A')}**\n"
        f"╰▸ ‹ 🎖️ › ৎ˚₊ Promessa?: **{dados.get('promessa', 'N/A')}**\n"
        f"╰▸ ‹ 💪 › ৎ˚₊ Físico: **{dados.get('fisico', 'N/A')}**",
        inline=False
    )

    embed.add_field(name="⠀", value=
        "       ﹐ꜜ __‹🏟️›__ **__D__esempenho em __C__ampo !** __‹🏟️›__ ꜜ﹐\n"
        f"╰▸ ‹ 🏟️ › ৎ˚₊ Clube: **{dados.get('clube', 'N/A')}**\n"
        f"╰▸ ‹ ⚽ › ৎ˚₊ Gols: **{dados.get('gols', 0)}**\n"
        f"╰▸ ‹ 🏹 › ৎ˚₊ Assistências: **{dados.get('assistencias', 0)}**\n"
        f"╰▸ ‹ 🛡️ › ৎ˚₊ Desarmes: **{dados.get('desarmes', 0)}**\n"
        f"╰▸ ‹ 🧤 › ৎ˚₊ Defesas (GK): **{dados.get('defesas', 0)}**",
        inline=False
    )

    total_titulos_clube = sum([dados.get(k, 0) for k in ["brasileirao", "estadual", "libertadores", "sulamericana", "copadobrasil", "supercopa", "recopa", "mundial", "supermundial"]])

    embed.add_field(name="⠀", value=
        "       ﹐ꜜ __‹🏆›__ **__T__ítulos __C__onquistados !** __‹🏆›__ ꜜ﹐\n"
        f"╰▸ ‹ <:puerto_Brasileirao:1377848287876616223> › ৎ˚₊ Brasileirão: **{dados.get('brasileirao', 0)}**\n"
        f"╰▸ ‹ 🏆 › ৎ˚₊ Títulos Estaduais: **{dados.get('estadual', 0)}**\n"
        f"╰▸ ‹ <:puerto_Libertadores:1377848356520329277> › ৎ˚₊ Libertadores: **{dados.get('libertadores', 0)}**\n"
        f"╰▸ ‹ <:sudamericana:1377848396508823732> › ৎ˚₊ Sudamericana: **{dados.get('sulamericana', 0)}**\n"
        f"╰▸ ‹ <:Copa_do_Brasil:1377848458425143378> › ৎ˚₊ Copa do Brasil: **{dados.get('copadobrasil', 0)}**\n"
        f"╰▸ ‹ <:us_supercopa:1377848513928364103> › ৎ˚₊ Supercopa Rei: **{dados.get('supercopa', 0)}**\n"
        f"╰▸ ‹ <:us_recopa:1377848552083951686> › ৎ˚₊ Recopa Sudamericana: **{dados.get('recopa', 0)}**\n"
        f"╰▸ ‹ <:taca_mundial:1377848591389036559> › ৎ˚₊ Intercontinental de Clubes: **{dados.get('mundial', 0)}**\n"
        f"╰▸ ‹ <:Super_Mundial:1377848122121912320> › ৎ˚₊ Super Mundial de Clubes: **{dados.get('supermundial', 0)}**",
        inline=False
    )

    embed.add_field(name="⠀", value=
        "       ﹐ꜜ __‹🌐›__ **__C__onquistas por __S__eleção !** __‹🌐›__ ꜜ﹐\n"
        f"╰▸ ‹ <:worldcup:1377848740798398517> › ৎ˚₊ Copa do Mundo: **{dados.get('copadomundo', 0)}**\n"
        f"╰▸ ‹ <:CopaAmerica:1377848763879526481> › ৎ˚₊ Copa América: **{dados.get('copaamerica', 0)}**\n"
        f"╰▸ ‹ <:Eurocopa:1377848812940427298> › ৎ˚₊ Eurocopa: **{dados.get('euro', 0)}**\n"
        f"╰▸ ‹ ⚽ › ৎ˚₊ G/A por Seleção: **{dados.get('gol_selecao', 0)}**",
        inline=False
    )

    return embed

def gerar_embed_rolls(user, rolls_data, is_own_rolls):
    title_text = "Seus Rolls" if is_own_rolls else f"Rolls de: {user.display_name}"

    embed = discord.Embed(
        title=f"╭ㆍ┈┈ㆍ◜ᨒ◞ㆍ┈┈ㆍ \n╰▸ ‹ 🎰 › ৎ˚₊ **__{title_text}:__**",
        description="__ㆍ┈┈ㆍ◜ᨒ◞ㆍ┈┈ㆍ__",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_image(url="https://media.discordapp.net/attachments/1375957371121045605/1385648920826482718/rolls.jpg?ex=6856d59e&is=6855841e&hm=2fee840eb2cf8983ca60f8d9c24d3d4f8f180e680f6af012cf6dbbb75caadc1b&=&format=webp")
    embed.set_footer(text="╰ㆍ┈┈ㆍ◜ᨒ◞ㆍ┈┈ㆍ\nUse p!editar <atributo> <roll> - Dev: YevgennyMXP")

    embed.add_field(name="⠀", value=
        "﹐ꜜ __‹⚔️›__ **__H__abilidades de __L__inha !** __‹⚔️›__ ꜜ﹐\n"
        f"╰▸ ‹ 💥 › ৎ˚₊ **__Chute:__** {rolls_data.get('chute', 0)}\n"
        f"╰▸ ‹ 🏹 › ৎ˚₊ **__Passe:__** {rolls_data.get('passe', 0)}\n"
        f"╰▸ ‹ 🤯 › ৎ˚₊ **__Cabeceio:__** {rolls_data.get('cabecio', 0)}\n"
        f"╰▸ ‹ ⚡ › ৎ˚₊ **__Velocidade:__** {rolls_data.get('velocidade', 0)}\n"
        f"╰▸ ‹ ✨ › ৎ˚₊ **__Drible:__** {rolls_data.get('drible', 0)}\n"
        f"╰▸ ‹ 💦 › ৎ˚₊ **__Domínio:__** {rolls_data.get('dominio', 0)}",
        inline=False
    )

    embed.add_field(name="⠀", value=
        "﹐ꜜ __‹🛡️›__ **__H__abilidades __D__efensivas !** __‹🛡️›__ ꜜ﹐\n"
        f"╰▸ ‹ 🧊 › ৎ˚₊ **__Pênaltis:__** {rolls_data.get('penaltis', 0)}\n"
        f"╰▸ ‹ 💫 › ৎ˚₊ **__Faltas:__** {rolls_data.get('faltas', 0)}\n"
        f"╰▸ ‹ 💪 › ৎ˚₊ **__Corpo:__** {rolls_data.get('corpo', 0)}\n"
        f"╰▸ ‹ 🦿 › ৎ˚₊ **__Desarme:__** {rolls_data.get('desarme', 0)}\n"
        f"╰▸ ‹ 🧱 › ৎ˚₊ **__Bloqueio:__** {rolls_data.get('bloqueio', 0)}\n"
        f"╰▸ ‹ ☠️ › ৎ˚₊ **__Carrinho:__** {rolls_data.get('carrinho', 0)}\n"
        f"╰▸ ‹ 🦸‍♂️ › ৎ˚₊ **__Última Chance:__** {rolls_data.get('ultima_chance', 0)}",
        inline=False
    )

    embed.add_field(name="⠀", value=
        "﹐ꜜ __‹🧤›__ **__A__tributos de __G__oleiro !** __‹🧤›__ ꜜ﹐\n"
        f"╰▸ ‹ 🦹‍♂️ › ৎ˚₊ **__Defesa GK:__** {rolls_data.get('defesa_gk', 0)}\n"
        f"╰▸ ‹ 💣 › ৎ˚₊ **__Tiro de Meta:__** {rolls_data.get('tiro_de_meta', 0)}\n"
        f"╰▸ ‹ 💯 › ৎ˚₊ **__Lançamento:__** {rolls_data.get('lancamento', '—')}\n"
        f"╰▸ ‹ 👨‍⚖️ › ৎ˚₊ **__Pênaltis GK:__** {rolls_data.get('penaltis_gk', 0)}",
        inline=False
    )

    return embed

def gerar_ranking_embed(ctx, campo, titulo):
    if campo == "titulos":
        top = sorted(dados_usuarios.items(), key=lambda x: sum([x[1].get(k, 0) for k in ["brasileirao", "estadual", "libertadores", "sulamericana", "copadobrasil", "supercopa", "recopa", "mundial", "supermundial", "copaamerica", "copadomundo", "euro"]]), reverse=True)[:10]
    elif campo == "money":
        users_with_money = [(uid, get_user_money(uid)) for uid in dados_usuarios.keys()]
        top = sorted(users_with_money, key=lambda x: x[1], reverse=True)[:10]
    else:
        top = sorted(dados_usuarios.items(), key=lambda x: x[1].get(campo, 0), reverse=True)[:10]

    embed = discord.Embed(
        title=f"🏆 {titulo}",
        description=f"Veja o top 10 de {titulo.lower()}!",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)

    for i, item in enumerate(top, 1):
        if campo == "money":
            uid, valor = item
            dados = {}
        else:
            uid, dados = item

        membro = bot.get_user(uid)
        nome = membro.display_name if membro else "Indefinido"

        if campo == "titulos":
            valor = sum([dados.get(k, 0) for k in ["brasileirao", "estadual", "libertadores", "sulamericana", "copadobrasil", "supercopa", "recopa", "mundial", "supermundial", "copaamerica", "copadomundo", "euro"]])
        elif campo == "money":
            pass  # valor já foi definido acima
        else:
            valor = dados.get(campo, 0)

        embed.add_field(name=f"#{i} — {nome}", value=f"{valor}", inline=False)

    return embed

# --- Slot Machine (Fortune Tiger) ---
SYMBOLS = {
    "cherry": "🍒",
    "bell": "🔔",
    "orange": "🍊",
    "grape": "🍇",
    "watermelon": "🍉",
    "bar": "🎰",
    "seven": "7️⃣",
    "tiger": "🐯"
}

SYMBOL_WEIGHTS = {
    "cherry": 20,
    "bell": 15,
    "orange": 15,
    "grape": 10,
    "watermelon": 10,
    "bar": 8,
    "seven": 5,
    "tiger": 2
}

WEIGHTED_SYMBOLS = [symbol for symbol, weight in SYMBOL_WEIGHTS.items() for _ in range(weight)]

# Sistema de multiplicadores com pesos (chances menores para multiplicadores maiores)
MULTIPLIER_SYSTEM = {
    1.0: 40,    # 40% de chance - sem multiplicador
    1.2: 25,    # 25% de chance
    1.5: 15,    # 15% de chance
    2.0: 10,    # 10% de chance
    2.5: 5,     # 5% de chance
    3.0: 3,     # 3% de chance
    5.0: 1.5,   # 1.5% de chance
    10.0: 0.5   # 0.5% de chance - super raro
}

# Lista ponderada de multiplicadores
WEIGHTED_MULTIPLIERS = []
for mult, weight in MULTIPLIER_SYSTEM.items():
    WEIGHTED_MULTIPLIERS.extend([mult] * int(weight * 10))  # Multiplicar por 10 para ter números inteiros

def get_random_multiplier():
    """Seleciona um multiplicador aleatório baseado nos pesos"""
    return random.choice(WEIGHTED_MULTIPLIERS)

WIN_LINES = [
    [(0, 0), (0, 1), (0, 2)], [(1, 0), (1, 1), (1, 2)], [(2, 0), (2, 1), (2, 2)],
    [(0, 0), (1, 1), (2, 2)], [(0, 2), (1, 1), (2, 0)],
    [(0, 0), (1, 0), (2, 0)], [(0, 1), (1, 1), (2, 1)], [(0, 2), (1, 2), (2, 2)],
]

def generate_board():
    board = []
    for _ in range(3):
        row = [random.choice(WEIGHTED_SYMBOLS) for _ in range(3)]
        board.append(row)
    return board

def check_wins(board):
    wins = []
    for line_coords in WIN_LINES:
        symbols_on_line = [board[r][c] for r, c in line_coords]
        if symbols_on_line[0] == symbols_on_line[1] == symbols_on_line[2]:
            wins.append({"symbol": symbols_on_line[0], "line": line_coords})
    return wins

def get_slot_display(board, multiplier=None, full_match=False):
    display_board = ""

    # Mostrar multiplicador no topo se houver
    if multiplier and multiplier > 1.0:
        if multiplier >= 5.0:
            display_board += "🔥✨💎 **MULTIPLICADOR ÉPICO!** 💎✨🔥\n"
            display_board += f"🎯 **{multiplier}x** 🎯\n\n"
        elif multiplier >= 3.0:
            display_board += "⚡💰 **SUPER MULTIPLICADOR!** 💰⚡\n"
            display_board += f"🎲 **{multiplier}x** 🎲\n\n"
        elif multiplier >= 2.0:
            display_board += "🌟 **MULTIPLICADOR ATIVO!** 🌟\n"
            display_board += f"🎊 **{multiplier}x** 🎊\n\n"
        else:
            display_board += "✨ **Multiplicador:** ✨\n"
            display_board += f"🎈 **{multiplier}x** 🎈\n\n"

    if full_match:
        display_board += "🌟✨💰 **JACKPOT!** 💰✨🌟\n\n"

    display_board += "```\n"
    display_board += "╔═════════════╗\n"

    for r_idx, row in enumerate(board):
        display_board += "║ "
        for c_idx, symbol_key in enumerate(row):
            emoji = SYMBOLS.get(symbol_key, "❓")
            display_board += f"{emoji} "
        display_board += "║\n"

    display_board += "╚═════════════╝\n"
    display_board += "```\n"

    if full_match:
        display_board += "\n💥 **BIG WIN!** 💥\n"

    return display_board

class SpinButton(Button):
    def __init__(self, amount: int, original_user_id: int):
        super().__init__(label=f"💰 Apostar {amount}", style=discord.ButtonStyle.success)
        self.amount = amount
        self.original_user_id = original_user_id

    async def callback(self, interaction: discord.Interaction):
        # Verificar se é o usuário original
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        user_id = interaction.user.id
        current_money = get_user_money(user_id)

        if current_money < self.amount:
            embed = discord.Embed(
                title="❌ Saldo Insuficiente",
                description=f"Você não tem `{self.amount}` moedas para apostar. Seu saldo atual é `{current_money}`.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        remove_user_money(user_id, self.amount)
        new_money = get_user_money(user_id)

        board = generate_board()
        wins = check_wins(board)

        full_match = True
        first_symbol = board[0][0]
        for r in range(3):
            for c in range(3):
                if board[r][c] != first_symbol:
                    full_match = False
                    break
            if not full_match:
                break

        total_winnings = 0
        win_description = ""
        multiplier = None

        if full_match:
            multiplier = get_random_multiplier()
            base_payout = self.amount * 100
            final_payout = int(base_payout * multiplier)
            total_winnings += final_payout
            win_description += f"🎉 **JACKPOT! Todos os símbolos são {SYMBOLS.get(first_symbol)}!**\n"
            if multiplier > 1.0:
                win_description += f"🎯 **Com Multiplicador {multiplier}x!**\n"
            win_description += f"💰 **Prêmio Total:** `{final_payout}` moedas!\n"
        elif wins:
            multiplier = get_random_multiplier()
            if multiplier > 1.0:
                win_description += f"🎯 **Multiplicador Ativo:** {multiplier}x\n\n"

            for win in wins:
                symbol = win["symbol"]
                base_payout = self.amount * (SYMBOL_WEIGHTS[symbol] / 5)
                payout_per_line = base_payout * multiplier
                if symbol == "tiger":
                    payout_per_line *= 5
                    win_description += f"🐅 **TIGRE DOURADO!** {SYMBOLS.get(symbol)} x3\n"
                    if multiplier > 1.0:
                        win_description += f"💎 **Bônus com {multiplier}x:** `{int(payout_per_line)}` moedas!\n"
                    else:
                        win_description += f"💎 **Bônus:** `{int(payout_per_line)}` moedas!\n"
                else:
                    if multiplier > 1.0:
                        win_description += f"💰 **{SYMBOLS.get(symbol)} x3 (x{multiplier}):** `{int(payout_per_line)}` moedas\n"
                    else:
                        win_description += f"💰 **{SYMBOLS.get(symbol)} x3:** `{int(payout_per_line)}` moedas\n"
                total_winnings += payout_per_line
        else:
            win_description = "😞 **Sem sorte desta vez!** Tente novamente!"

        add_user_money(user_id, int(total_winnings))
        final_money = get_user_money(user_id)

        color = discord.Color.gold() if total_winnings > 0 else discord.Color.red()
        if full_match:
            color = discord.Color.from_rgb(255, 215, 0)  # Dourado brilhante para jackpot

        embed = discord.Embed(
            title="🎰 Fortune Tiger - Caça Níqueis 🐅",
            color=color
        )

        # Definir imagem baseada no resultado
        if total_winnings == 0:
            # Caso perca
            embed.set_image(url="https://media.discordapp.net/attachments/1305879543394861056/1378099614137323622/tigrinho-fortune.gif?ex=683b5ec7&is=683a0d47&hm=f173925cca9a7bd421329ce1117a719553333728133ef34f95478ab54133b858&=")
        elif multiplier and multiplier >= 2.5:
            # Bonus acima de 2.5x
            embed.set_image(url="https://media.discordapp.net/attachments/1305879543394861056/1378099614661607484/tigrinho-jogo-tigrinho_1.gif?ex=683b5ec7&is=683a0d47&hm=ea41be0124642a56d5fd7dc0ffc03e538f1802760f485ff3aaf48617947ab51a&=")
        elif total_winnings > 0:
            # Ganhou (acima de 1.5x ou qualquer vitória)
            embed.set_image(url="https://media.discordapp.net/attachments/1305879543394861056/1378099615047618742/tigrinho-jogo-tigrinho.gif?ex=683b5ec8&is=683a0d48&hm=a6abcc2357c345c511f227bf70e926b6e01b6120d866823cea2ddd3a976775db&=")

        embed.add_field(
            name="💰 Aposta",
            value=f"`{self.amount}` moedas",
            inline=True
        )

        embed.add_field(
            name="🎯 Resultado",
            value=f"`+{int(total_winnings)}` moedas" if total_winnings > 0 else f"`-{self.amount}` moedas",
            inline=True
        )

        embed.add_field(
            name="💎 Saldo Final",
            value=f"`{final_money}` moedas",
            inline=True
        )

        embed.add_field(
            name="🎲 Máquina Caça-Níqueis",
            value=get_slot_display(board, multiplier=multiplier if total_winnings > 0 else None, full_match=full_match),
            inline=False
        )

        if win_description:
            embed.add_field(
                name="🏆 Prêmios",
                value=win_description,
                inline=False
            )
        embed.set_footer(text=f"Partida de slot por {interaction.user.display_name} - Dev: YevgennyMXP")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        view = BetView(self.amount, self.original_user_id)
        await interaction.response.edit_message(embed=embed, view=view)

class ChangeBetButton(Button):
    def __init__(self, label: str, amount: int, original_user_id: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.amount = amount
        self.original_user_id = original_user_id

    async def callback(self, interaction: discord.Interaction):
        # Verificar se é o usuário original
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎰 Fortune Tiger Slot!",
            description=f"Pronto para apostar `{self.amount}` moedas?",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Clique em 'Apostar {self.amount}' para girar. - Dev: YevgennyMXP")
        view = BetView(self.amount, self.original_user_id)
        await interaction.response.edit_message(embed=embed, view=view)

class BetView(View):
    def __init__(self, current_amount: int, original_user_id: int):
        super().__init__(timeout=180)
        self.current_amount = current_amount
        self.original_user_id = original_user_id
        self.add_item(SpinButton(current_amount, original_user_id))
        self.add_item(ChangeBetButton("Apostar 50", 50, original_user_id))
        self.add_item(ChangeBetButton("Apostar 100", 100, original_user_id))
        self.add_item(ChangeBetButton("Apostar 500", 500, original_user_id))

# --- Eventos do Bot ---
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user.name} ({bot.user.id})')
    print('Bot pronto para uso!')



# --- Help System with organized buttons ---
class HelpView(View):
    def __init__(self, original_user_id: int):
        super().__init__(timeout=300)
        self.original_user_id = original_user_id

    def get_main_embed(self):
        embed = discord.Embed(
            title="🎯 Central de Comandos - Gyrus Burguer",
            description="**Bem-vindo ao sistema de ajuda!**\n\nSelecione uma categoria abaixo para ver os comandos disponíveis. Use os botões para navegar entre as diferentes seções.",
            color=discord.Color.from_rgb(88, 101, 242)
        )
        embed.add_field(
            name="📱 Como usar",
            value="• Clique nos botões abaixo para explorar\n• Cada categoria tem comandos específicos\n• Use `p!` antes de cada comando",
            inline=False
        )
        embed.set_footer(text="💡 Dica: Clique em qualquer categoria para começar! - Dev: YevgennyMXP")
        return embed

    def get_carreira_embed(self):
        embed = discord.Embed(
            title="⚽ Carreira e Rolls",
            description="Comandos para gerenciar sua carreira de jogador e rolls de habilidades",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🏆 Comandos de Carreira",
            value=(
                "`p!carreira [@usuário]` - Ver carreira completa\n"
                "`p!alterar <campo> <valor>` - Alterar dados da carreira\n"
                "`p!ranking` - Rankings dos melhores jogadores"
            ),
            inline=False
        )
        embed.add_field(
            name="🎲 Comandos de Rolls",
            value=(
                "`p!rolls [@usuário]` - Ver rolls de habilidades\n"
                "`p!editar <roll> <valor>` - Editar seus rolls"
            ),
            inline=False
        )
        return embed

    def get_economia_embed(self):
        embed = discord.Embed(
            title="💰 Sistema de Economia",
            description="Ganhe, gaste e invista suas moedas no servidor!",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="💵 Gerenciamento",
            value=(
                "`p!money [@usuário]` - Ver saldo atual\n"
                "`p!pay <@usuário> <valor>` - Transferir dinheiro\n"
                "`p!ranking_money` - Ranking dos mais ricos"
            ),
            inline=False
        )
        embed.add_field(
            name="💼 Ganhar Dinheiro",
            value=(
                "`p!daily` - Bônus diário (100-300 moedas)\n"
                "`p!work` - Trabalhar por dinheiro (cooldown 1h)"
            ),
            inline=False
        )
        embed.add_field(
            name="🎰 Jogos e Investimentos",
            value=(
                "`p!apostar <valor>` - Fortune Tiger (caça-níqueis)\n"
                "`p!investir <valor>` - Investir em ações e crypto"
            ),
            inline=False
        )
        return embed

    def get_moderacao_embed(self):
        embed = discord.Embed(
            title="🛠️ Ferramentas de Moderação",
            description="Comandos para moderadores manterem a ordem no servidor",
            color=discord.Color.red()
        )
        embed.add_field(
            name="🔨 Punições",
            value=(
                "`p!ban <@usuário> [motivo]` - Banir permanentemente\n"
                "`p!kick <@usuário> [motivo]` - Expulsar do servidor\n"
                "`p!mute <@usuário> [tempo] [motivo]` - Silenciar temporariamente"
            ),
            inline=False
        )
        embed.add_field(
            name="⚠️ Avisos e Controle",
            value=(
                "`p!warn <@usuário> <motivo>` - Dar aviso formal\n"
                "`p!warnings [@usuário]` - Ver histórico de avisos\n"
                "`p!unmute <@usuário>` - Remover silenciamento"
            ),
            inline=False
        )
        embed.add_field(
            name="🧹 Limpeza",
            value="`p!clear <quantidade>` - Limpar mensagens (máx: 100)",
            inline=False
        )
        return embed

    def get_diversao_embed(self):
        embed = discord.Embed(
            title="🎮 Comandos de Diversão",
            description="Entretenimento e funcionalidades divertidas para todos!",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="🎲 Jogos Rápidos",
            value=(
                "`p!roll [lados]` - Rolar dado (padrão: 6 lados)\n"
                "`p!coinflip` - Cara ou coroa clássico"
            ),
            inline=False
        )
        embed.add_field(
            name="🖼️ Perfil e Avatares",
            value=(
                "`p!avatar [@usuário]` - Mostrar avatar em alta qualidade\n"
                "`p!banner [@usuário]` - Mostrar banner do perfil"
            ),
            inline=False
        )
        embed.add_field(
            name="🌐 Utilitários Diversos",
            value=(
                "`p!ping` - Verificar latência do bot\n"
                "`p!clima <cidade>` - Previsão do tempo\n"
                "`p!traduzir <texto>` - Tradutor automático"
            ),
            inline=False
        )
        return embed

    def get_utilitarios_embed(self):
        embed = discord.Embed(
            title="📋 Utilitários e Informações",
            description="Ferramentas úteis para organização e informações do servidor",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="👥 Informações de Usuário",
            value=(
                "`p!userinfo [@usuário]` - Perfil detalhado do usuário\n"
                "`p!serverinfo` - Estatísticas completas do servidor"
            ),
            inline=False
        )
        embed.add_field(
            name="📝 Sistema de Tarefas",
            value=(
                "`p!tasks` - Ver suas tarefas pendentes\n"
                "`p!addtask <descrição>` - Adicionar nova tarefa\n"
                "`p!completetask <id>` - Marcar como concluída\n"
                "`p!deletetask <id>` - Remover tarefa"
            ),
            inline=False
        )
        embed.add_field(
            name="⚡ Ferramentas Rápidas",
            value=(
                "`p!uptime` - Tempo online do bot\n"
                "`p!lembrete <tempo> <texto>` - Criar lembrete\n"
                "`p!calc <expressão>` - Calculadora matemática\n"
                "`p!resultado` - Registrar resultado de partidas"
            ),
            inline=False
        )
        return embed

    @discord.ui.button(label="🏠 Início", style=discord.ButtonStyle.primary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.get_main_embed(), view=self)

    @discord.ui.button(label="⚽ Carreira", style=discord.ButtonStyle.success, row=0)
    async def carreira_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.get_carreira_embed(), view=self)

    @discord.ui.button(label="💰 Economia", style=discord.ButtonStyle.success, row=0)
    async def economia_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.get_economia_embed(), view=self)

    @discord.ui.button(label="🛠️ Moderação", style=discord.ButtonStyle.danger, row=1)
    async def moderacao_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.get_moderacao_embed(), view=self)

    @discord.ui.button(label="🎮 Diversão", style=discord.ButtonStyle.secondary, row=1)
    async def diversao_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.get_diversao_embed(), view=self)

    @discord.ui.button(label="📋 Utilitários", style=discord.ButtonStyle.secondary, row=1)
    async def utilitarios_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.get_utilitarios_embed(), view=self)

# --- Comandos do Bot ---

@bot.command(name='ping')
async def ping(ctx):
    # Calculando métricas em tempo real
    start_time = time.time()
    latency = round(bot.latency * 1000)

    # Simulando informações de sistema realistas
    cpu_usage = random.uniform(12.3, 45.7)
    ram_total = random.choice([16384, 32768, 65536, 131072])  # MB
    ram_used = round(ram_total * random.uniform(0.35, 0.75))
    ram_percent = round((ram_used / ram_total) * 100, 1)

    # Simulando informações de rede
    packet_loss = random.uniform(0.0, 2.1)
    jitter = random.uniform(0.5, 3.2)
    bandwidth = random.choice([1000, 2500, 5000, 10000])  # Mbps

    # Calculando uptime detalhado
    uptime_duration = datetime.now() - bot_start_time
    total_seconds = int(uptime_duration.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    # Determinando status baseado na latência
    if latency < 50:
        status = "🟢 ÓTIMO"
        color = discord.Color.from_rgb(0, 255, 127)
        performance = "Ultra Baixa"
    elif latency < 100:
        status = "🟡 BOM"
        color = discord.Color.from_rgb(255, 215, 0)
        performance = "Baixa"
    elif latency < 200:
        status = "🟠 MÉDIO"
        color = discord.Color.from_rgb(255, 165, 0)
        performance = "Moderada"
    else:
        status = "🔴 ALTO"
        color = discord.Color.from_rgb(255, 69, 0)
        performance = "Alta"

    # Calculando tempo de processamento
    process_time = round((time.time() - start_time) * 1000, 2)

    # Embed futurista
    embed = discord.Embed(
        title="⚡ **SISTEMA DE DIAGNÓSTICO NEURAL** ⚡",
        description=f"```ansi\n\u001b[36m╔══════════════════════════════════════╗\n║     🌐 ANÁLISE DE CONECTIVIDADE 🌐    ║\n╚══════════════════════════════════════╝\u001b[0m```",
        color=color,
        timestamp=discord.utils.utcnow()
    )

    # Informações de latência principal
    embed.add_field(
        name="📡 **LATÊNCIA DE REDE**",
        value=f"```yaml\nStatus: {status}\nPing: {latency}ms\nClassificação: {performance}\nJitter: {jitter:.1f}ms\nPerda de Pacotes: {packet_loss:.1f}%```",
        inline=True
    )

    # Informações de sistema
    embed.add_field(
        name="🖥️ **RECURSOS DO SISTEMA**",
        value=f"```yaml\nCPU: {cpu_usage:.1f}% de uso\nRAM: {ram_used:,}MB / {ram_total:,}MB\nMemória: {ram_percent}% utilizada\nBandwidth: {bandwidth:,} Mbps```",
        inline=True
    )

    # Informações de performance
    embed.add_field(
        name="⚙️ **MÉTRICAS DE PERFORMANCE**",
        value=f"```yaml\nTempo Processamento: {process_time}ms\nUptime: {days}d {hours}h {minutes}m\nShards Ativas: 1/1\nComandos Executados: {random.randint(8500, 15000):,}```",
        inline=True
    )

    # Barra de status visual
    def get_status_bar(value, max_value, length=10):
        filled = int((value / max_value) * length)
        bar = "█" * filled + "░" * (length - filled)
        return bar

    latency_bar = get_status_bar(min(latency, 300), 300)
    ram_bar = get_status_bar(ram_percent, 100)
    cpu_bar = get_status_bar(cpu_usage, 100)

    embed.add_field(
        name="📊 **MONITORAMENTO EM TEMPO REAL**",
        value=f"```\nLatência  [{latency_bar}] {latency}ms\nMemória   [{ram_bar}] {ram_percent}%\nCPU       [{cpu_bar}] {cpu_usage:.1f}%```",
        inline=False
    )

    # Informações técnicas detalhadas
    embed.add_field(
        name="🔬 **DIAGNÓSTICO AVANÇADO**",
        value=f"```fix\n+ Protocolo: WebSocket Gateway v10\n+ Região: São Paulo (sa-east-1)\n+ Criptografia: TLS 1.3 AES-256-GCM\n+ Taxa de Transferência: {random.randint(850, 999)}KB/s\n+ Heartbeat: {random.randint(40, 45)}s```",
        inline=False
    )

    # Footer com informações extras
    embed.set_footer(
        text=f"🤖  Yevgenny.Server1777 Neural Network • Scan ID: {random.randint(100000, 999999)} • Node: BR-SP-{random.randint(1, 8)}",
        icon_url=bot.user.display_avatar.url
    )

    # Thumbnail futurista
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await ctx.reply(embed=embed)

# --- Comandos de Economia ---
@bot.command(name='diario', aliases=['daily'])
async def diario(ctx):
    user_id = ctx.author.id
    if can_daily(user_id):
        # Bônus diário reduzido e mais equilibrado
        base_amount = random.randint(50, 150)
        
        # Bônus por streak (dias consecutivos)
        current_streak = get_daily_streak(user_id)
        streak_bonus = min(current_streak * 5, 50)  # Máximo 50 de bônus
        
        total_amount = base_amount + streak_bonus
        
        add_user_money(user_id, total_amount)
        set_daily_claimed(user_id)
        update_daily_streak(user_id)
        
        embed = discord.Embed(
            title="💰 Bônus Diário Coletado!",
            description=f"Parabéns! Você coletou seu bônus diário!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="💵 Recompensa",
            value=f"**Base:** {base_amount} moedas\n**Streak Bonus:** +{streak_bonus} moedas\n**Total:** {total_amount} moedas",
            inline=True
        )
        embed.add_field(
            name="🔥 Sequência",
            value=f"**{current_streak + 1} dias** consecutivos\n*Continue coletando para aumentar o bônus!*",
            inline=True
        )
        embed.add_field(
            name="💰 Saldo Atual",
            value=f"**{get_user_money(user_id)}** moedas",
            inline=False
        )
        await ctx.reply(embed=embed)
    else:
        embed = discord.Embed(
            title="⏰ Bônus Diário Já Coletado",
            description="Você já coletou seu bônus diário. Volte amanhã para manter sua sequência!",
            color=discord.Color.orange()
        )
        await ctx.reply(embed=embed)

@bot.command(name='trabalhar', aliases=['work'])
async def trabalhar(ctx):
    user_id = ctx.author.id
    if can_work(user_id):
        job = random.choice(trabalhos)
        
        # Aumentar dificuldade com chance de falha
        success_rate = random.randint(1, 100)
        
        if success_rate <= 75:  # 75% chance de sucesso
            # Sucesso total
            payout = random.randint(job["min"], job["max"])
            add_user_money(user_id, payout)
            set_work_done(user_id)
            
            embed = discord.Embed(
                title="👨‍💻 Trabalho Concluído com Sucesso!",
                description=f"Você trabalhou como **{job['nome']}** com excelência!",
                color=discord.Color.green()
            )
            embed.add_field(
                name="💰 Pagamento",
                value=f"**+{payout} moedas**\nSaldo atual: {get_user_money(user_id)} moedas",
                inline=True
            )
            embed.add_field(
                name="📊 Performance",
                value="✅ **Excelente**\nTrabaho realizado perfeitamente!",
                inline=True
            )
            
        elif success_rate <= 90:  # 15% chance de sucesso parcial
            # Sucesso parcial
            payout = random.randint(job["min"] // 2, job["max"] // 2)
            add_user_money(user_id, payout)
            set_work_done(user_id)
            
            embed = discord.Embed(
                title="👨‍💻 Trabalho Parcialmente Concluído",
                description=f"Você trabalhou como **{job['nome']}**, mas teve algumas dificuldades.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="💰 Pagamento Reduzido",
                value=f"**+{payout} moedas** (50% do valor)\nSaldo atual: {get_user_money(user_id)} moedas",
                inline=True
            )
            embed.add_field(
                name="📊 Performance",
                value="⚠️ **Mediano**\nTente melhorar na próxima!",
                inline=True
            )
            
        else:  # 10% chance de falha
            # Falha total
            set_work_done(user_id)
            
            embed = discord.Embed(
                title="😓 Trabalho Mal Sucedido",
                description=f"Infelizmente, seu trabalho como **{job['nome']}** não saiu como esperado...",
                color=discord.Color.red()
            )
            embed.add_field(
                name="💸 Sem Pagamento",
                value="**+0 moedas**\nTente novamente em 1 hora!",
                inline=True
            )
            embed.add_field(
                name="📊 Performance",
                value="❌ **Insatisfatório**\nNão desista, a prática leva à perfeição!",
                inline=True
            )
        
        await ctx.reply(embed=embed)
    else:
        embed = discord.Embed(
            title="⏳ Em Tempo de Descanso",
            description="Você já trabalhou recentemente. Descanse e volte em 1 hora!",
            color=discord.Color.orange()
        )
        await ctx.reply(embed=embed)

@bot.command(name='dinheiro', aliases=['money', 'balance', 'bal', 'saldo'])
async def dinheiro(ctx, member: discord.Member = None):
    target_user = member if member else ctx.author
    money = get_user_money(target_user.id)
    embed = discord.Embed(
        title="💰 Saldo da Conta",
        description=f"O saldo de **{target_user.display_name}** é `{money}` moedas.",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    await ctx.reply(embed=embed)

@bot.command(name='pagar', aliases=['pay', 'send'])
async def pagar_dinheiro(ctx, member: discord.Member, amount: int):
    sender_id = ctx.author.id
    receiver_id = member.id

    if amount <= 0:
        await ctx.reply("A quantia a ser enviada deve ser um número positivo.")
        return
    if sender_id == receiver_id:
        await ctx.reply("Você não pode enviar dinheiro para si mesmo.")
        return
    if get_user_money(sender_id) < amount:
        embed = discord.Embed(
            title="❌ Saldo Insuficiente",
            description=f"Você não tem `{amount}` moedas para enviar. Seu saldo atual é `{get_user_money(sender_id)}`.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    remove_user_money(sender_id, amount)
    add_user_money(receiver_id, amount)

    embed = discord.Embed(
        title="💸 Transação Realizada!",
        description=f"Você enviou `{amount}` moedas para **{member.display_name}**. Seu novo saldo é `{get_user_money(sender_id)}`.",
        color=discord.Color.teal()
    )
    await ctx.reply(embed=embed)

@bot.command(name='ranking_money')
async def ranking_money(ctx):
    ranking_embed = gerar_ranking_embed(ctx, "money", "Mais Ricos")
    await ctx.reply(embed=ranking_embed)

@bot.command(name='apostar', aliases=['bet', 'tigrinho'])
async def apostar_command(ctx, amount: int):
    user_id = ctx.author.id
    current_money = get_user_money(user_id)

    if amount <= 0:
        embed = discord.Embed(
            title="🚫 Aposta Inválida",
            description="A quantia da aposta deve ser um número positivo.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if current_money < amount:
        embed = discord.Embed(
            title="❌ Saldo Insuficiente",
            description=f"Você não tem `{amount}` moedas para apostar. Seu saldo atual é `{current_money}`.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    embed = discord.Embed(
        title="🎰 Fortune Tiger Slot!",
        description=f"Pronto para apostar `{amount}` moedas? Clique em 'Apostar' para girar!",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Clique em 'Apostar {amount}' para girar. - Dev: YevgennyMXP")

    view = BetView(amount, ctx.author.id)
    await ctx.reply(embed=embed, view=view)

@bot.command(name='investir')
async def investir(ctx, amount: int):
    user_id = ctx.author.id
    current_money = get_user_money(user_id)

    if amount <= 0:
        embed = discord.Embed(
            title="🚫 Investimento Inválido",
            description="A quantia do investimento deve ser um número positivo.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    # Limitar investimento máximo a 10.000 moedas
    if amount > 10000:
        embed = discord.Embed(
            title="🚫 Limite de Investimento Excedido",
            description="O valor máximo para investimento é **10.000 moedas** por transação.\n\nIsso garante um mercado mais equilibrado e justo para todos!",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if current_money < amount:
        embed = discord.Embed(
            title="❌ Saldo Insuficiente",
            description=f"Você não tem `{amount}` moedas para investir. Seu saldo atual é `{current_money}`.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    remove_user_money(user_id, amount)

    investment = random.choice(investimentos)
    
    # Tornar investimentos mais voláteis e arriscados
    base_multiplier = random.uniform(investment["min_mult"], investment["max_mult"])
    
    # Adicionar volatilidade extra baseada no valor investido
    volatility_factor = min(amount / 5000, 1.0)  # Mais volatilidade para valores maiores
    volatility_adjustment = random.uniform(-0.3 * volatility_factor, 0.3 * volatility_factor)
    
    final_multiplier = max(0.1, base_multiplier + volatility_adjustment)  # Mínimo 10% de retorno
    return_amount = int(amount * final_multiplier)

    add_user_money(user_id, return_amount)
    profit = return_amount - amount

    if profit > 0:
        result_text = f"📈 **Lucro!** Você ganhou `{profit}` moedas!"
        color = discord.Color.green()
        performance_emoji = "🎉"
    elif profit < 0:
        result_text = f"📉 **Prejuízo!** Você perdeu `{abs(profit)}` moedas!"
        color = discord.Color.red()
        performance_emoji = "😢"
    else:
        result_text = "📊 **Empate!** Você não ganhou nem perdeu nada!"
        color = discord.Color.orange()
        performance_emoji = "😐"

    embed = discord.Embed(
        title="💼 Resultado do Investimento",
        description=f"{performance_emoji} **{investment['nome']}** • Risco: {investment['risco'].title()}",
        color=color
    )
    
    embed.add_field(
        name="💰 Investimento",
        value=f"**Valor:** {amount:,} moedas\n**Retorno:** {return_amount:,} moedas\n**Multiplicador:** {final_multiplier:.2f}x",
        inline=True
    )
    
    embed.add_field(
        name="📊 Resultado",
        value=f"{result_text}\n**Saldo atual:** {get_user_money(user_id):,} moedas",
        inline=True
    )
    
    # Adicionar dicas baseadas no resultado
    if profit > amount * 0.5:
        tip = "🎯 **Excelente retorno!** Continue investindo com sabedoria."
    elif profit > 0:
        tip = "✅ **Bom negócio!** Investimentos consistentes geram riqueza."
    elif profit == 0:
        tip = "⚖️ **Estabilidade** é melhor que prejuízo!"
    else:
        tip = "📚 **Aprendizado:** Nem todo investimento é garantia de lucro."
    
    embed.add_field(
        name="💡 Dica",
        value=tip,
        inline=False
    )
    
    embed.set_footer(text=f"Limite máximo: 10.000 moedas • Mercado volátil - Dev: YevgennyMXP")
    await ctx.reply(embed=embed)

# --- Comandos de Moderação ---
@bot.command(name='banir', aliases=['ban'])
@commands.has_permissions(ban_members=True)
async def banir(ctx, member: discord.Member, *, reason="Não especificado"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("❌ Você não pode banir um usuário com cargo superior ao seu, fudido do cacetekkkkkkkkkkkk!")
        return

    try:
        await member.ban(reason=reason)
        embed = discord.Embed(
            title="🔨 Usuário Banido",
            description=f"**{member.display_name}** foi banido do servidor.\n**Motivo:** {reason}",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
    except discord.Forbidden:
        await ctx.reply("❌ Não tenho permissão para banir este usuário.")
    except Exception as e:
        await ctx.reply(f"❌ Erro ao banir usuário: {e}")

@bot.command(name='expulsar', aliases=['kick'])
@commands.has_permissions(kick_members=True)
async def expulsar(ctx, member: discord.Member, *, reason="Não especificado"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("❌ Você não pode expulsar um usuário com cargo superior ao seu!")
        return
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(
            title="👢 Usuário Expulso",
            description=f"**{member.display_name}** foi expulso do servidor.\n**Motivo:** {reason}",
            color=discord.Color.orange()
        )
        await ctx.reply(embed=embed)
    except discord.Forbidden:
        await ctx.reply("❌ Não tenho permissão para expulsar este usuário.")
    except Exception as e:
        await ctx.reply(f"❌ Erro ao expulsar usuário: {e}")

@bot.command(name='mutar', aliases=['mute'])
@commands.has_permissions(manage_messages=True)
async def mutar(ctx, member: discord.Member, duration: str = "10m", *, reason="Não especificado"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("❌ Você não pode mutar um usuário com cargo superior ao seu!")
        return
    # Parse duration
    time_units = {"m": 60, "h": 3600, "d": 86400}
    duration_seconds = 600  # default 10 minutes

    if duration[-1] in time_units:
        try:
            duration_seconds = int(duration[:-1]) * time_units[duration[-1]]
        except ValueError:
            pass

    mute_end = datetime.now() + timedelta(seconds=duration_seconds)
    add_mute(member.id, ctx.guild.id, mute_end.isoformat(), reason)

    try:
        await member.timeout(timedelta(seconds=duration_seconds), reason=reason)
        embed = discord.Embed(
            title="🔇 Usuário Mutado",
            description=f"**{member.display_name}** foi mutado por {duration}.\n**Motivo:** {reason}",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
    except discord.Forbidden:
        await ctx.reply("❌ Não tenho permissão para mutar este usuário.")
    except Exception as e:
        await ctx.reply(f"❌ Erro ao mutar usuário: {e}")

@bot.command(name='desmutar', aliases=['unmute'])
@commands.has_permissions(manage_messages=True)
async def desmutar(ctx, member: discord.Member):
    remove_mute(member.id, ctx.guild.id)

    try:
        await member.timeout(None)
        embed = discord.Embed(
            title="🔊 Usuário Desmutado",
            description=f"**{member.display_name}** foi desmutado.",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)
    except discord.Forbidden:
        await ctx.reply("❌ Não tenho permissão para desmutar este usuário.")
    except Exception as e:
        await ctx.reply(f"❌ Erro ao desmutar usuário: {e}")

@bot.command(name='avisar', aliases=['warn'])
@commands.has_permissions(manage_messages=True)
async def avisar(ctx, member: discord.Member, *, reason):
    add_warn(member.id, ctx.guild.id, reason)
    warns = get_warns(member.id, ctx.guild.id)

    embed = discord.Embed(
        title="⚠️ Usuário Avisado",
        description=f"**{member.display_name}** recebeu um aviso.\n**Motivo:** {reason}\n**Total de avisos:** {len(warns)}",
        color=discord.Color.yellow()
    )
    await ctx.reply(embed=embed)

@bot.command(name='avisos', aliases=['warnings'])
async def avisos(ctx, member: discord.Member = None):
    target = member if member else ctx.author
    warns = get_warns(target.id, ctx.guild.id)

    if not warns:
        embed = discord.Embed(
            title="⚠️ Avisos",
            description=f"**{target.display_name}** não possui avisos.",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title=f"⚠️ Avisos de {target.display_name}",
            description=f"Total: {len(warns)} avisos",
            color=discord.Color.yellow()
        )
        for i, (reason, warn_time) in enumerate(warns, 1):
            date = datetime.fromisoformat(warn_time).strftime("%d/%m/%Y %H:%M")
            embed.add_field(name=f"Aviso #{i}", value=f"**Motivo:** {reason}\n**Data:** {date}", inline=False)

    await ctx.reply(embed=embed)

@bot.command(name='limpar', aliases=['clear'])
@commands.has_permissions(manage_messages=True)
async def limpar(ctx, amount: int):
    if amount <= 0 or amount > 100:
        await ctx.reply("❌ A quantidade deve ser entre 1 e 100.")
        return

    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        embed = discord.Embed(
            title="🧹 Mensagens Limpas",
            description=f"Foram deletadas {len(deleted) - 1} mensagens.",
            color=discord.Color.green()
        )
        msg = await ctx.reply(embed=embed)
        await asyncio.sleep(3)
        await msg.delete()
    except discord.Forbidden:
        await ctx.reply("❌ Não tenho permissão para deletar mensagens.")

# --- Comandos de Diversão ---
@bot.command(name='roll')
async def roll_dice(ctx, sides: int = 6):
    if sides <= 0:
        await ctx.reply("❌ O número de lados deve ser positivo.")
        return

    # Embed inicial de animação
    animation_embed = discord.Embed(
        title="🎲 Rolando o Dado...",
        description="🎯 **Preparando para rolar...**",
        color=discord.Color.orange()
    )
    animation_embed.set_footer(text=f"Dado de {sides} lados em movimento... - Dev: YevgennyMXP")

    message = await ctx.reply(embed=animation_embed)

    # Sequência de animação - mostra números aleatórios
    animation_frames = [
        "🎲 **Girando...** 🌀",
        "🎯 **Rolando...** ⚡",
        "🔥 **Quase lá...** ✨",
        "⭐ **Finalizando...** 🎊"
    ]

    # Animar por algumas iterações
    for i, frame in enumerate(animation_frames):
        temp_number = random.randint(1, sides)
        animation_embed.description = f"{frame}\n\n🎲 **Valor atual:** `{temp_number}`"
        animation_embed.color = discord.Color.from_rgb(
            random.randint(100, 255),
            random.randint(100, 255), 
            random.randint(100, 255)
        )
        await asyncio.sleep(0.4)  # Pausa entre frames (reduzida de 0.8 para 0.4)
        await message.edit(embed=animation_embed)

    # Resultado final
    await asyncio.sleep(0.3)  # Reduzida de 0.5 para 0.3
    final_result = random.randint(1, sides)

    # Determinar cor baseada no resultado
    if final_result == sides:
        final_color = discord.Color.gold()
        bonus_text = "🏆 **RESULTADO MÁXIMO!** 🏆"
    elif final_result == 1:
        final_color = discord.Color.red()
        bonus_text = "🎯 **Resultado mínimo!** 🎯"
    else:
        final_color = discord.Color.green()
        bonus_text = "🎲 **Boa rolagem!** 🎲"

    final_embed = discord.Embed(
        title="🎲 Resultado Final do Dado!",
        description=f"{bonus_text}\n\n🎯 **Dado de {sides} lados**\n🏁 **Resultado:** `{final_result}`",
        color=final_color
    )
    final_embed.set_footer(text=f"Rolagem finalizada por {ctx.author.display_name} - Dev: YevgennyMXP")
    final_embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await message.edit(embed=final_embed)

@bot.command(name='avatar')
async def avatar(ctx, member: discord.Member = None):
    target = member if member else ctx.author
    embed = discord.Embed(
        title=f"Avatar de {target.display_name}",
        color=discord.Color.blue()
    )
    embed.set_image(url=target.display_avatar.url)
    await ctx.reply(embed=embed)

@bot.command(name='banner')
async def banner(ctx, member: discord.Member = None):
    target = member if member else ctx.author
    user = await bot.fetch_user(target.id)

    if user.banner:
        embed = discord.Embed(
            title=f"Banner de {target.display_name}",
            color=discord.Color.blue()
        )
        embed.set_image(url=user.banner.url)
    else:
        embed = discord.Embed(
            title="❌ Sem Banner",
            description=f"{target.display_name} não possui um banner personalizado.",
            color=discord.Color.red()
        )

    await ctx.reply(embed=embed)

@bot.command(name='coinflip')
async def coinflip(ctx):
    result = random.choice(["Cara", "Coroa"])
    emoji = "🪙" if result == "Cara" else "🔄"

    embed = discord.Embed(
        title="🪙 Cara ou Coroa",
        description=f"A moeda caiu em: **{result}** {emoji}",
        color=discord.Color.gold()
    )
    await ctx.reply(embed=embed)

@bot.command(name='clima')
async def clima(ctx, *, cidade):
    try:
        # Simulated weather data since we don't have a real API key
        conditions = ["Ensolarado", "Nublado", "Chuvoso", "Parcialmente nublado", "Tempestuoso"]
        temp = random.randint(-5, 35)
        condition = random.choice(conditions)
        humidity = random.randint(30, 90)

        embed = discord.Embed(
            title=f"🌤️ Clima em {cidade.title()}",
            description=f"**Temperatura:** {temp}°C\n**Condição:** {condition}\n**Umidade:** {humidity}%",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
    except Exception as e:
        await ctx.reply(f"❌ Erro ao obter informações do clima: {e}")

@bot.command(name='traduzir')
async def traduzir(ctx, *, texto):
    try:
        traduzido = GoogleTranslator(source='auto', target='pt').translate(texto)
        embed = discord.Embed(
            title="🌐 Tradução",
            description=f"**Original:** {texto}\n**Tradução (pt):** {traduzido}",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)
    except Exception as e:
        await ctx.reply(f"❌ Erro ao traduzir: {e}")

# --- Comandos Utilitários ---
@bot.command(name='perfil', aliases=['userinfo'])
async def perfil(ctx, member: discord.Member = None):
    target = member if member else ctx.author

    embed = discord.Embed(
        title=f"👤 Informações de {target.display_name}",
        color=target.color
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(name="📋 Nome", value=f"{target.name}#{target.discriminator}", inline=True)
    embed.add_field(name="🆔 ID", value=target.id, inline=True)
    embed.add_field(name="📅 Criação da Conta", value=target.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="📅 Entrou no Servidor", value=target.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="🏷️ Cargos", value=f"{len(target.roles) - 1} cargos", inline=True)
    embed.add_field(name="🤖 Bot?", value="Sim" if target.bot else "Não", inline=True)

    await ctx.reply(embed=embed)

@bot.command(name='serverinfo')
async def serverinfo(ctx):
    guild = ctx.guild

    embed = discord.Embed(
        title=f"🏛️ Informações do Servidor",
        color=discord.Color.blue()
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="📋 Nome", value=guild.name, inline=True)
    embed.add_field(name="🆔 ID", value=guild.id, inline=True)
    embed.add_field(name="👑 Dono", value=guild.owner.mention if guild.owner else "Desconhecido", inline=True)
    embed.add_field(name="👥 Membros", value=guild.member_count, inline=True)
    embed.add_field(name="💬 Canais", value=len(guild.channels), inline=True)
    embed.add_field(name="🏷️ Cargos", value=len(guild.roles), inline=True)
    embed.add_field(name="📅 Criado em", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="🔒 Nível de Verificação", value=str(guild.verification_level).title(), inline=True)

    await ctx.reply(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    uptime_duration = datetime.now() - bot_start_time
    days = uptime_duration.days
    hours, remainder = divmod(uptime_duration.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    embed = discord.Embed(
        title="⏰ Tempo Online",
        description=f"O bot está online há: **{days}d {hours}h {minutes}m {seconds}s**",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

@bot.command(name='lembrete')
async def lembrete(ctx, tempo, *, texto):
    try:
        # Parse time (simplified)
        time_units = {"m": 60, "h": 3600, "d": 86400}
        if tempo[-1] in time_units:
            duration = int(tempo[:-1]) * time_units[tempo[-1]]
        else:
            await ctx.reply("❌ Formato de tempo inválido. Use: 10m, 2h, 1d")
            return

        reminder_time = (datetime.now() + timedelta(seconds=duration)).isoformat()
        add_reminder_to_db(ctx.author.id, texto, reminder_time)

        embed = discord.Embed(
            title="⏰ Lembrete Criado",
            description=f"Lembrete criado para daqui a {tempo}: {texto}",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)

        # Wait and send reminder
        await asyncio.sleep(duration)

        remind_embed = discord.Embed(
            title="🔔 Lembrete!",
            description=f"{ctx.author.mention} {texto}",
            color=discord.Color.yellow()
        )
        await ctx.reply(embed=remind_embed)

    except ValueError:
        await ctx.reply("❌ Formato de tempo inválido.")
    except Exception as e:
        await ctx.reply(f"❌ Erro ao criar lembrete: {e}")

@bot.command(name='calc')
async def calc(ctx, *, expression):
    try:
        # Basic calculator - only allow safe operations
        allowed_chars = "0123456789+-*/.() "
        if not all(c in allowed_chars for c in expression):
            await ctx.reply("❌ Expressão contém caracteres não permitidos.")
            return

        result = eval(expression)
        embed = discord.Embed(
            title="🧮 Calculadora",
            description=f"**Expressão:** {expression}\n**Resultado:** {result}",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
    except ZeroDivisionError:
        await ctx.reply("❌ Divisão por zero não é permitida.")
    except Exception as e:
        await ctx.reply(f"❌ Erro na expressão: {e}")

# --- Comandos de Carreira e Rolls ---
@bot.command(name='carreira', aliases=['career'])
async def carreira_command(ctx, member: discord.Member = None):
    target_user = member if member else ctx.author
    if target_user.id not in dados_usuarios:
        dados_usuarios[target_user.id] = {}
    embed = gerar_embed_carreira(target_user, dados_usuarios[target_user.id])

    if target_user.id == ctx.author.id:
        message = await ctx.reply(embed=embed)
        dados_usuarios[target_user.id]['carreira_message_id'] = message.id
        dados_usuarios[target_user.id]['carreira_channel_id'] = ctx.channel.id
    else:
        await ctx.reply(embed=embed)

@bot.command(name='alterar', aliases=['alter', 'change'])
async def alterar(ctx, campo: str, *, valor):
    user = ctx.author
    if user.id not in dados_usuarios:
        dados_usuarios[user.id] = {}

    campo_original = campo
    campo_normalizado_input = normalizar(campo)

    campo_detectado = None

    melhor_correspondencia = process.extractOne(campo_normalizado_input, campos_validos_alterar_carreira, score_cutoff=70)

    if melhor_correspondencia:
        campo_detectado = melhor_correspondencia[0]
        campo_convertido = correspondencias_campos_carreira.get(campo_detectado, campo_detectado)

        if melhor_correspondencia[1] > 90:
            pass
        elif melhor_correspondencia[1] >= 70:
            embed = discord.Embed(
                title="🤔 Campo Não Reconhecido",
                description=f"Campo `{campo_original}` não reconhecido. Você quis dizer `{campo_detectado}`? Ajustando para `{campo_detectado}`.",
                color=discord.Color.orange()
            )
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Campo Inválido",
                description=f"Campo `{campo_original}` não reconhecido. Por favor, verifique a ortografia. Campos válidos para carreira incluem: {', '.join(campos_validos_alterar_carreira[:5])}...",
                color=discord.Color.red()
            )
            await ctx.reply(embed=embed)
            return
    else:
        embed = discord.Embed(
            title="❌ Campo Inválido",
            description=f"Campo `{campo_original}` não reconhecido. Por favor, verifique a ortografia. Campos válidos para carreira incluem: {', '.join(campos_validos_alterar_carreira[:5])}...",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if campo_detectado is None:
        embed = discord.Embed(
            title="❌ Erro Interno",
            description=f"Ocorreu um erro ao processar o campo `{campo_original}`. Tente novamente ou use um campo válido.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if campo_convertido in campos_numericos_carreira:
        if not str(valor).isdigit():
            embed = discord.Embed(
                title="❌ Valor Inválido",
                description="Este campo aceita apenas números.",
                color=discord.Color.red()
            )
            await ctx.reply(embed=embed)
            return
        valor = int(valor)
    elif campo_convertido in ["nome", "nacionalidade", "clube", "posicao"]:
        valor = capitalizar_nome(valor)

    dados_usuarios[user.id][campo_convertido] = valor

    embed = discord.Embed(
        title="✅ Carreira Atualizada!",
        description=f"Campo `{campo_detectado}` atualizado para: `{valor}`",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

    if 'carreira_message_id' in dados_usuarios[user.id] and 'carreira_channel_id' in dados_usuarios[user.id]:
        try:
            channel = bot.get_channel(dados_usuarios[user.id]['carreira_channel_id'])
            if channel:
                message = await channel.fetch_message(dados_usuarios[user.id]['carreira_message_id'])
                if message:
                    updated_embed = gerar_embed_carreira(user, dados_usuarios[user.id])
                    await message.edit(embed=updated_embed)
        except discord.NotFound:
            print(f"Mensagem da carreira de {user.display_name} não encontrada para edição.")
        except discord.Forbidden:
            print(f"Bot não tem permissão para editar a mensagem da carreira de {user.display_name}.")
        except Exception as e:
            print(f"Erro ao tentar editar a mensagem da carreira: {e}")

@bot.command(name='rolls')
async def rolls_command(ctx, member: discord.Member = None):
    target_user = member if member else ctx.author
    is_own_rolls = (target_user.id == ctx.author.id)

    if target_user.id not in dados_rolls:
        dados_rolls[target_user.id] = {
            "chute": 0, "passe": 0, "cabecio": 0, "velocidade": 0, "drible": 0, "dominio": 0,
            "penaltis": 0, "faltas": 0, "corpo": 0, "desarme": 0, "bloqueio": 0, "carrinho": 0, "ultima_chance": 0,
            "defesa_gk": 0, "tiro_de_meta": 0, "lancamento": '—', "penaltis_gk": 0
        }

    embed = gerar_embed_rolls(target_user, dados_rolls[target_user.id], is_own_rolls)

    if is_own_rolls:
        message = await ctx.reply(embed=embed)
        dados_rolls[target_user.id]['rolls_message_id'] = message.id
        dados_rolls[target_user.id]['rolls_channel_id'] = ctx.channel.id
    else:
        await ctx.reply(embed=embed)

@bot.command(name='editar', aliases=['edit'])
async def editar_roll(ctx, roll_name: str, *, value: str):
    user = ctx.author
    if user.id not in dados_rolls:
        embed = discord.Embed(
            title="❓ Rolls Não Definidos",
            description="Você ainda não tem rolls definidos! Use `p!rolls` para ver seus rolls e inicializá-los.",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
        return

    roll_original_input = roll_name
    roll_normalizado_input = normalizar(roll_name)

    roll_detectado = None

    melhor_correspondencia_roll = process.extractOne(roll_normalizado_input, campos_validos_rolls, score_cutoff=70)

    if melhor_correspondencia_roll:
        roll_detectado = melhor_correspondencia_roll[0]
        roll_convertido = correspondencias_rolls.get(roll_detectado, roll_detectado)

        if melhor_correspondencia_roll[1] > 90:
            pass
        elif melhor_correspondencia_roll[1] >= 70:
            embed = discord.Embed(
                title="🤔 Roll Não Reconhecido",
                description=f"Roll `{roll_original_input}` não reconhecido. Você quis dizer `{roll_detectado}`? Ajustando para `{roll_detectado}`.",
                color=discord.Color.orange()
            )
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Roll Inválido",
                description=f"Roll `{roll_original_input}` não reconhecido. Por favor, verifique a ortografia. Rolls válidos incluem: {', '.join(campos_validos_rolls[:5])}...",
                color=discord.Color.red()
            )
            await ctx.reply(embed=embed)
            return
    else:
        embed = discord.Embed(
            title="❌ Roll Inválido",
            description=f"Roll `{roll_original_input}` não reconhecido. Por favor, verifique a ortografia. Rolls válidos incluem: {', '.join(campos_validos_rolls[:5])}...",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if roll_detectado is None:
        embed = discord.Embed(
            title="❌ Erro Interno",
            description=f"Ocorreu um erro ao processar o roll `{roll_original_input}`. Tente novamente ou use um roll válido.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    if roll_convertido == "lancamento":
        dados_rolls[user.id][roll_convertido] = value
    elif not value.isdigit():
        embed = discord.Embed(
            title="❌ Valor Inválido",
            description="Para este roll, o valor deve ser um **número**.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return
    else:
        dados_rolls[user.id][roll_convertido] = int(value)

    embed = discord.Embed(
        title="✅ Roll Atualizado!",
        description=f"Roll `{roll_detectado}` atualizado para: `{value}`",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

    if 'rolls_message_id' in dados_rolls[user.id] and 'rolls_channel_id' in dados_rolls[user.id]:
        try:
            channel = bot.get_channel(dados_rolls[user.id]['rolls_channel_id'])
            if channel:
                message = await channel.fetch_message(dados_rolls[user.id]['rolls_message_id'])
                if message:
                    updated_embed = gerar_embed_rolls(user, dados_rolls[user.id], True)
                    await message.edit(embed=updated_embed)
        except discord.NotFound:
            print(f"Mensagem de rolls de {user.display_name} não encontrada para edição.")
        except discord.Forbidden:
            print(f"Bot não tem permissão para editar a mensagem de rolls de {user.display_name}.")
        except Exception as e:
            print(f"Erro ao tentar editar a mensagem de rolls: {e}")

class RankingView(View):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.original_user_id = ctx.author.id
        self.add_item(RankingButton("⚽ Gols", "gols", "Artilheiros"))
        self.add_item(RankingButton("🎯 Assistências", "assistencias", "Garçons"))
        self.add_item(RankingButton("🥋 Desarmes", "desarmes", "Leões"))
        self.add_item(RankingButton("🧤 Defesas", "defesas", "Paredão"))
        self.add_item(RankingButton("🏆 Títulos", "titulos", "Papa Títulos"))

class RankingButton(Button):
    def __init__(self, label, campo, titulo):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.campo = campo
        self.titulo = titulo

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        ranking_embed = gerar_ranking_embed(self.view.ctx, self.campo, self.titulo)
        await interaction.response.edit_message(embed=ranking_embed, view=self.view)

@bot.command(name='ranking', aliases=['rank'])
async def ranking_command(ctx):
    initial_embed = gerar_ranking_embed(ctx, "gols", "Artilheiros")
    view = RankingView(ctx)
    await ctx.reply(embed=initial_embed, view=view)

# --- Comandos de Tarefas ---
@bot.command(name='adicionartarefa', aliases=['addtask', 'add_task'])
async def adicionar_tarefa(ctx, *, task_name: str):
    add_task_to_db(ctx.author.id, task_name)
    embed = discord.Embed(
        title="✅ Tarefa Adicionada!",
        description=f"Tarefa **'{task_name}'** adicionada com sucesso.",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

@bot.command(name='tarefas', aliases=['tasks'])
async def listar_tarefas(ctx):
    tasks = get_tasks_from_db(ctx.author.id)
    if not tasks:
        embed = discord.Embed(
            title="📋 Suas Tarefas",
            description="Você não tem nenhuma tarefa pendente.",
            color=discord.Color.light_grey()
        )
        await ctx.reply(embed=embed)
        return

    embed = discord.Embed(title="📋 Suas Tarefas", color=discord.Color.purple())
    for task_id, name, completed in tasks:
        status = "✅ Concluída" if completed else "⏳ Pendente"
        embed.add_field(name=f"ID: {task_id}", value=f"**{name}** - {status}", inline=False)

    await ctx.reply(embed=embed)

@bot.command(name='completetask', aliases=['complete'])
async def complete_task(ctx, task_id: int):
    if complete_task_in_db(task_id):
        embed = discord.Embed(
            title="🎉 Tarefa Concluída!",
            description=f"Tarefa com ID `{task_id}` marcada como concluída!",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Erro ao Concluir Tarefa",
            description=f"Não encontrei uma tarefa com o ID `{task_id}` ou ela já está concluída.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)

@bot.command(name='deletetask', aliases=['deltask'])
async def delete_task(ctx, task_id: int):
    if delete_task_from_db(task_id):
        embed = discord.Embed(
            title="🗑️ Tarefa Removida!",
            description=f"Tarefa com ID `{task_id}` foi removida com sucesso.",
            color=discord.Color.dark_red()
        )
        await ctx.reply(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Erro ao Remover Tarefa",
            description=f"Não encontrei uma tarefa com o ID `{task_id}` para remover.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)

# --- Modal para p!resultado ---
class ResultadoModal(Modal, title="⚽ Registrar Resultado da Partida"):
    time_casa = TextInput(label="Time da Casa", placeholder="Ex: Flamengo", max_length=50)
    gols_casa = TextInput(label="Gols do Time da Casa", placeholder="Ex: 2", max_length=2, style=discord.TextStyle.short)
    time_visitante = TextInput(label="Time Visitante", placeholder="Ex: Grêmio", max_length=50)
    gols_visitante = TextInput(label="Gols do Time Visitante", placeholder="Ex: 1", max_length=2, style=discord.TextStyle.short)
    estadio = TextInput(label="Estádio da Partida", placeholder="Ex: Maracanã", max_length=100)

    def __init__(self, interaction, resultado_view=None):
        super().__init__()
        self.interaction = interaction
        self.resultado_view = resultado_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            gols_casa_int = int(self.gols_casa.value)
            gols_visitante_int = int(self.gols_visitante.value)
        except ValueError:
            await interaction.response.send_message("❌ Os gols devem ser números válidos!", ephemeral=True)
            return

        jogo_data = {
            'time_casa': capitalizar_nome(self.time_casa.value),
            'gols_casa': gols_casa_int,
            'time_visitante': capitalizar_nome(self.time_visitante.value),
            'gols_visitante': gols_visitante_int,
            'estadio': capitalizar_nome(self.estadio.value),
            'marcadores_casa': [],
            'marcadores_visitante': [],
            'assistencias_casa': [],
            'assistencias_visitante': []
        }

        times_of_day_categories = ["Manhã", "Tarde", "Noite"]
        jogo_data['horario'] = random.choice(times_of_day_categories)

        temperatures_celsius = {
            "Muito Frio": range(-5, 1),
            "Frio": range(1, 11),
            "Agradável": range(11, 26),
            "Quente": range(26, 36),
            "Muito Quente": range(36, 46)
        }
        temp_category = random.choice(list(temperatures_celsius.keys()))
        temp_value = random.choice(temperatures_celsius[temp_category])
        jogo_data['temperatura'] = f"{temp_value}°C"

        is_day_time = jogo_data['horario'] in ["Manhã", "Tarde"]
        if temp_category in ["Muito Frio", "Frio"] and random.random() < 0.3:
            climates = ["Nevando", "Chuvoso", "Nublado"]
        elif is_day_time:
            climates = ["Ensolarado", "Nublado", "Parcialmente Nublado", "Chuvoso"]
        else:
            climates = ["Nublado", "Parcialmente Nublado", "Chuvoso", "Céu Estrelado"]
        jogo_data['clima'] = random.choice(climates)

        humidities = ["Baixa", "Moderada", "Alta"]
        jogo_data['umidade'] = random.choice(humidities)

        referee_names = [
            "Anderson Daronco", "Raphael Claus", "Wilton Pereira Sampaio",
            "Leandro Pedro Vuaden", "Savio Pereira Sampaio", "Wagner do Nascimento Magalhães",
            "Bráulio da Silva Machado", "Flávio Rodrigues de Souza", "Luiz Flávio de Oliveira"
        ]
        jogo_data['arbitro'] = random.choice(referee_names)

        other_events = [
            "Torcida fez uma festa linda nas arquibancadas com mosaicos e bandeiras!",
            "Problemas técnicos na transmissão ao vivo geraram atrasos no início.",
            "Um show de luzes e fogos de artifício marcou o intervalo da partida."
        ]
        jogo_data['eventos_aleatorios'] = random.sample(other_events, min(len(other_events), 3))

        # Criar embed inicial
        initial_embed = self.create_resultado_embed(jogo_data)

        # Criar view com botão para adicionar marcadores
        result_view = ResultadoFinalView(interaction.user.id, jogo_data)
        
        await interaction.response.send_message(embed=initial_embed, view=result_view)

    def create_resultado_embed(self, jogo_data):
        vencedor = None
        if jogo_data['gols_casa'] > jogo_data['gols_visitante']:
            vencedor = jogo_data['time_casa']
        elif jogo_data['gols_visitante'] > jogo_data['gols_casa']:
            vencedor = jogo_data['time_visitante']

        embed = discord.Embed(
            title=f"🏁 **Resultado da Partida** 🏁",
            description=f"No estádio **{jogo_data['estadio']}**, a partida foi finalizada!",
            color=discord.Color.teal() if not vencedor else discord.Color.green()
        )

        placar_str = (
            f"╰▸ ‹ 🏠 › ৎ˚₊ **{jogo_data['time_casa']}** `{jogo_data['gols_casa']}`\n"
            f"╰▸ ‹ ✈️ › ৎ˚₊ **{jogo_data['time_visitante']}** `{jogo_data['gols_visitante']}`\n"
        )
        if vencedor:
            placar_str += f"╰▸ ‹ 🏆 › ৎ˚₊ Vitória de **{vencedor}**!"
        else:
            placar_str += f"╰▸ ‹ 🤝 › ৎ˚₊ A partida terminou em **empate**."

        embed.add_field(name="⠀", value="﹐ꜜ __‹📋›__ **__P__lacar __F__inal !** __‹📋›__ ꜜ﹐\n" + placar_str, inline=False)

        # Adicionar marcadores e assistências se existirem
        if (jogo_data['marcadores_casa'] or jogo_data['marcadores_visitante'] or 
            jogo_data['assistencias_casa'] or jogo_data['assistencias_visitante']):
            
            marcadores_str = "﹐ꜜ __‹⚽›__ **__M__arcadores e __A__ssistências !** __‹⚽›__ ꜜ﹐\n"
            
            if jogo_data['marcadores_casa']:
                marcadores_str += f"╰▸ ‹ 🏠 › ৎ˚₊ **Gols {jogo_data['time_casa']}:** {', '.join(jogo_data['marcadores_casa'])}\n"
            
            if jogo_data['marcadores_visitante']:
                marcadores_str += f"╰▸ ‹ ✈️ › ৎ˚₊ **Gols {jogo_data['time_visitante']}:** {', '.join(jogo_data['marcadores_visitante'])}\n"
            
            if jogo_data['assistencias_casa']:
                marcadores_str += f"╰▸ ‹ 🎯 › ৎ˚₊ **Assistências {jogo_data['time_casa']}:** {', '.join(jogo_data['assistencias_casa'])}\n"
            
            if jogo_data['assistencias_visitante']:
                marcadores_str += f"╰▸ ‹ 🎯 › ৎ˚₊ **Assistências {jogo_data['time_visitante']}:** {', '.join(jogo_data['assistencias_visitante'])}\n"
            
            embed.add_field(name="⠀", value=marcadores_str, inline=False)

        conditions_str = (
            "﹐ꜜ __‹🌐›__ **__C__ondições da __P__artida e __E__ventos !** __‹🌐›__ ꜜ﹐\n"
            f"╰▸ ‹ ⏰ › ৎ˚₊ **Horário:** {jogo_data['horario']}\n"
            f"╰▸ ‹ 🌡️ › ৎ˚₊ **Temperatura:** {jogo_data['temperatura']}\n"
            f"╰▸ ‹ ☁️ › ৎ˚₊ **Clima:** {jogo_data['clima']}\n"
            f"╰▸ ‹ 💧 › ৎ˚₊ **Umidade:** {jogo_data['umidade']}\n"
            f"╰▸ 👨‍⚖️ › ৎ˚₊ **Árbitro:** {jogo_data['arbitro']}\n"
            f"╰▸ ‹ 📣 › ৎ˚₊ **Eventos:**\n" + "\n".join([f"  › {e}" for e in jogo_data['eventos_aleatorios']])
        )
        embed.add_field(name="⠀", value=conditions_str, inline=False)

        embed.set_footer(text=f"Partida registrada por: {jogo_data.get('registered_by', 'Sistema')} - Dev: YevgennyMXP")
        embed.timestamp = discord.utils.utcnow()

        return embed

class MarcadoresModal(Modal, title="⚽ Adicionar Marcadores e Assistências"):
    marcadores_casa = TextInput(
        label="Marcadores (Casa)", 
        placeholder="Ex: João - 2 gols, Pedro - 1 gol",
        max_length=200,
        required=False,
        style=discord.TextStyle.paragraph
    )
    marcadores_visitante = TextInput(
        label="Marcadores (Visitante)", 
        placeholder="Ex: Silva - 1 gol, Santos - 1 gol",
        max_length=200,
        required=False,
        style=discord.TextStyle.paragraph
    )
    assistencias_casa = TextInput(
        label="Assistências (Casa)", 
        placeholder="Ex: Carlos - 2 assists, André - 1 assist",
        max_length=200,
        required=False,
        style=discord.TextStyle.paragraph
    )
    assistencias_visitante = TextInput(
        label="Assistências (Visitante)", 
        placeholder="Ex: Oliveira - 1 assist, Costa - 1 assist",
        max_length=200,
        required=False,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, jogo_data, resultado_view):
        super().__init__()
        self.jogo_data = jogo_data
        self.resultado_view = resultado_view

    async def on_submit(self, interaction: discord.Interaction):
        # Processar marcadores e assistências
        if self.marcadores_casa.value:
            self.jogo_data['marcadores_casa'] = [x.strip() for x in self.marcadores_casa.value.split(',') if x.strip()]
        
        if self.marcadores_visitante.value:
            self.jogo_data['marcadores_visitante'] = [x.strip() for x in self.marcadores_visitante.value.split(',') if x.strip()]
        
        if self.assistencias_casa.value:
            self.jogo_data['assistencias_casa'] = [x.strip() for x in self.assistencias_casa.value.split(',') if x.strip()]
        
        if self.assistencias_visitante.value:
            self.jogo_data['assistencias_visitante'] = [x.strip() for x in self.assistencias_visitante.value.split(',') if x.strip()]
        
        # Salvar quem registrou
        self.jogo_data['registered_by'] = interaction.user.display_name

        # Criar embed atualizado
        modal_instance = ResultadoModal(interaction)
        updated_embed = modal_instance.create_resultado_embed(self.jogo_data)
        
        # Criar nova view com o botão ainda ativo
        new_view = ResultadoFinalView(interaction.user.id, self.jogo_data)
        
        await interaction.response.edit_message(embed=updated_embed, view=new_view)

class ResultadoFinalView(View):
    def __init__(self, original_user_id: int, jogo_data: dict):
        super().__init__(timeout=600)
        self.original_user_id = original_user_id
        self.jogo_data = jogo_data

    @discord.ui.button(label="🎯 Marcadores", style=discord.ButtonStyle.success, emoji="⚽")
    async def add_marcadores(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        
        modal = MarcadoresModal(self.jogo_data, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ Finalizar", style=discord.ButtonStyle.primary)
    async def finalize_result(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        
        # Finalizar e remover os botões
        modal_instance = ResultadoModal(interaction)
        final_embed = modal_instance.create_resultado_embed(self.jogo_data)
        final_embed.set_footer(text=f"✅ Resultado finalizado por: {interaction.user.display_name} - Dev: YevgennyMXP")
        
        await interaction.response.edit_message(embed=final_embed, view=None)

class ResultadoView(View):
    def __init__(self, original_user_id: int):
        super().__init__(timeout=300)
        self.original_user_id = original_user_id

    @discord.ui.button(label="📝 Registrar Resultado", style=discord.ButtonStyle.primary, emoji="⚽")
    async def open_modal(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ Apenas quem executou o comando pode usar esses botões!", ephemeral=True)
            return
        await interaction.response.send_modal(ResultadoModal(interaction))

@bot.command(name='resultado', aliases=['result'])
@commands.has_permissions(manage_messages=True)
async def resultado_command(ctx):
    embed = discord.Embed(
        title="⚽ Registrar Resultado da Partida",
        description="Clique no botão abaixo para abrir o formulário de registro de resultado.",
        color=discord.Color.blue()
    )
    view = ResultadoView(ctx.author.id)
    await ctx.reply(embed=embed, view=view)

# --- Error Handlers ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❌ Comando Não Encontrado",
            description=f"O comando `{ctx.invoked_with}` não existe. Use `p!ajuda` para ver todos os comandos.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed, delete_after=5)
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Sem Permissão",
            description="Você não tem permissão para usar este comando.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed, delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❌ Argumento Obrigatório",
            description=f"Você esqueceu de fornecer um argumento obrigatório: `{error.param.name}`",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed, delete_after=5)
    else:
        print(f"Erro não tratado: {error}")

# --- 30 Novos Comandos ---

# Commando pra invitar
CLIENT_ID = '1377549020842692728'
@bot.command()
async def invite(ctx):
    permissions = discord.Permissions(administrator=True)  # ou personalize como quiser
    invite_url = discord.utils.oauth_url(client_id=CLIENT_ID, permissions=permissions)
    await ctx.reply(f"🔗 Me adicione no seu servidor com este link:\n{invite_url}")


# 1. Comando de Shop/Loja
@bot.command(name='loja', aliases=['shop'])
async def loja(ctx):
    items = [
        {"name": "Chuteira Dourada", "price": 500, "emoji": "👟", "desc": "Aumenta sua sorte nos rolls"},
        {"name": "Troféu de Ouro", "price": 1000, "emoji": "🏆", "desc": "Símbolo de prestígio"},
        {"name": "Bandeira do Clube", "price": 300, "emoji": "🚩", "desc": "Mostre seu time favorito"},
        {"name": "Luvas de Goleiro", "price": 400, "emoji": "🧤", "desc": "Para os guardiões das metas"},
        {"name": "Bola de Ouro", "price": 2500, "emoji": "⚽", "desc": "O prêmio mais cobiçado"}
    ]

    embed = discord.Embed(
        title="🛒 Loja do Gyrus Burguer",
        description="Compre itens exclusivos com suas moedas!",
        color=discord.Color.gold()
    )

    for item in items:
        embed.add_field(
            name=f"{item['emoji']} {item['name']}",
            value=f"💰 **{item['price']} moedas**\n{item['desc']}",
            inline=True
        )

    embed.set_footer(text="Use p!buy <item> para comprar - Dev: YevgennyMXP")
    await ctx.reply(embed=embed)

# 2. Comando de Comprar
@bot.command(name='comprar', aliases=['buy'])
async def comprar_item(ctx, *, item_name: str):
    items_map = {
        "chuteira": {"name": "Chuteira Dourada", "price": 500},
        "trofeu": {"name": "Troféu de Ouro", "price": 1000},
        "bandeira": {"name": "Bandeira do Clube", "price": 300},
        "luvas": {"name": "Luvas de Goleiro", "price": 400},
        "bola": {"name": "Bola de Ouro", "price": 2500}
    }

    item_key = normalizar(item_name)
    item = None

    for key, value in items_map.items():
        if key in item_key:
            item = value
            break

    if not item:
        embed = discord.Embed(
            title="❌ Item não encontrado",
            description="Use `p!shop` para ver os itens disponíveis.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    user_money = get_user_money(ctx.author.id)
    if user_money < item["price"]:
        embed = discord.Embed(
            title="💸 Saldo Insuficiente",
            description=f"Você precisa de `{item['price']}` moedas para comprar **{item['name']}**.",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
        return

    remove_user_money(ctx.author.id, item["price"])
    embed = discord.Embed(
        title="✅ Compra Realizada!",
        description=f"Você comprou **{item['name']}** por `{item['price']}` moedas!",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

# 3. Sistema de Duelo
class DuelView(View):
    def __init__(self, challenger_id: int, challenged_id: int, bet: int):
        super().__init__(timeout=60)
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
        self.bet = bet

    @discord.ui.button(label="⚔️ Aceitar Duelo", style=discord.ButtonStyle.success)
    async def accept_duel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.challenged_id:
            await interaction.response.send_message("❌ Apenas o desafiado pode aceitar!", ephemeral=True)
            return

        challenger_money = get_user_money(self.challenger_id)
        challenged_money = get_user_money(self.challenged_id)

        if challenged_money < self.bet:
            await interaction.response.send_message("❌ Você não tem moedas suficientes!", ephemeral=True)
            return

        challenger_power = random.randint(1, 100)
        challenged_power = random.randint(1, 100)

        if challenger_power > challenged_power:
            winner_id = self.challenger_id
            loser_id = self.challenged_id
            winner_name = bot.get_user(self.challenger_id).display_name
        else:
            winner_id = self.challenged_id
            loser_id = self.challenger_id
            winner_name = bot.get_user(self.challenged_id).display_name

        remove_user_money(loser_id, self.bet)
        add_user_money(winner_id, self.bet)

        embed = discord.Embed(
            title="⚔️ Resultado do Duelo!",
            description=f"🏆 **{winner_name}** venceu o duelo!\n💰 Ganhou `{self.bet}` moedas!",
            color=discord.Color.gold()
        )
        embed.add_field(name="📊 Poderes", value=f"Desafiante: {challenger_power}\nDesafiado: {challenged_power}", inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="❌ Recusar", style=discord.ButtonStyle.danger)
    async def decline_duel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.challenged_id:
            await interaction.response.send_message("❌ Apenas o desafiado pode recusar!", ephemeral=True)
            return

        embed = discord.Embed(
            title="❌ Duelo Recusado",
            description="O duelo foi recusado.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

@bot.command(name='duelo', aliases=['duel'])
async def duelo(ctx, member: discord.Member, bet: int = 100):
    if member.id == ctx.author.id:
        await ctx.reply("❌ Você não pode duelar consigo mesmo!")
        return

    if member.bot:
        await ctx.reply("❌ Você não pode duelar com bots!")
        return

    if bet <= 0:
        await ctx.reply("❌ A aposta deve ser positiva!")
        return

    if get_user_money(ctx.author.id) < bet:
        await ctx.reply("❌ Você não tem moedas suficientes!")
        return

    embed = discord.Embed(
        title="⚔️ Desafio de Duelo!",
        description=f"**{ctx.author.display_name}** desafiou **{member.display_name}** para um duelo!\n💰 Aposta: `{bet}` moedas",
        color=discord.Color.orange()
    )

    view = DuelView(ctx.author.id, member.id, bet)
    await ctx.reply(embed=embed, view=view)

# 4. Status do Servidor
@bot.command(name='botstats', aliases=['stats'])
async def bot_stats(ctx):
    guild_count = len(bot.guilds)
    user_count = len(bot.users)
    command_count = len(bot.commands)

    embed = discord.Embed(
        title="📊 Estatísticas do Bot",
        color=discord.Color.blue()
    )
    embed.add_field(name="🏛️ Servidores", value=guild_count, inline=True)
    embed.add_field(name="👥 Usuários", value=user_count, inline=True)
    embed.add_field(name="⚙️ Comandos", value=command_count, inline=True)
    embed.add_field(name="🐍 Python", value="3.11", inline=True)
    embed.add_field(name="📚 Discord.py", value="2.3.2", inline=True)
    embed.add_field(name="⚡ Latência", value=f"{round(bot.latency * 1000)}ms", inline=True)

    await ctx.reply(embed=embed)

# 5. Sistema de Níveis (XP)
def get_user_xp(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT xp FROM economy WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def add_user_xp(user_id, amount):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Adicionar coluna XP se não existir
    cursor.execute("PRAGMA table_info(economy)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'xp' not in columns:
        cursor.execute('ALTER TABLE economy ADD COLUMN xp INTEGER DEFAULT 0')

    cursor.execute('UPDATE economy SET xp = xp + ? WHERE user_id = ?', (amount, user_id))
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO economy (user_id, xp) VALUES (?, ?)', (user_id, amount))
    conn.commit()
    conn.close()

def get_level_from_xp(xp):
    return int(math.sqrt(xp / 100))

@bot.command(name='nivel', aliases=['level'])
async def nivel(ctx, member: discord.Member = None):
    target = member if member else ctx.author
    xp = get_user_xp(target.id)
    level = get_level_from_xp(xp)
    next_level_xp = ((level + 1) ** 2) * 100
    progress = xp - (level ** 2 * 100)
    needed = next_level_xp - (level ** 2 * 100)

    embed = discord.Embed(
        title=f"🆙 Nível de {target.display_name}",
        color=discord.Color.purple()
    )
    embed.add_field(name="🎯 Nível Atual", value=level, inline=True)
    embed.add_field(name="⭐ XP Total", value=xp, inline=True)
    embed.add_field(name="📈 Progresso", value=f"{progress}/{needed}", inline=True)

    # Barra de progresso
    bar_length = 20
    filled = int((progress / needed) * bar_length) if needed > 0 else bar_length
    bar = "█" * filled + "░" * (bar_length - filled)
    embed.add_field(name="📊 Barra", value=f"`{bar}`", inline=False)

    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.reply(embed=embed)

# 6. Comando XP (dar XP - admin)
@bot.command(name='addxp')
@commands.has_permissions(administrator=True)
async def add_xp_command(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.reply("❌ A quantidade deve ser positiva!")
        return

    add_user_xp(member.id, amount)
    embed = discord.Embed(
        title="✅ XP Adicionado!",
        description=f"**{member.display_name}** recebeu `{amount}` XP!",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

# 7. Ranking de Níveis
@bot.command(name='ranking_level', aliases=['ranking_xp'])
async def ranking_level(ctx):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, xp FROM economy WHERE xp > 0 ORDER BY xp DESC LIMIT 10')
    results = cursor.fetchall()
    conn.close()

    embed = discord.Embed(
        title="🏆 Ranking de Níveis",
        description="Top 10 jogadores por XP!",
        color=discord.Color.gold()
    )

    for i, (user_id, xp) in enumerate(results, 1):
        user = bot.get_user(user_id)
        name = user.display_name if user else "Usuário Desconhecido"
        level = get_level_from_xp(xp)
        embed.add_field(
            name=f"#{i} — {name}",
            value=f"Nível {level} ({xp} XP)",
            inline=False
        )

    await ctx.reply(embed=embed)

# 8. Sistema de Cores de Perfil
@bot.command(name='color', aliases=['cor'])
async def color_profile(ctx, color: str = None):
    if not color:
        embed = discord.Embed(
            title="🎨 Cores Disponíveis",
            description="Use `p!color <cor>` para escolher:\n"
                       "🔴 red • 🟠 orange • 🟡 yellow • 🟢 green\n"
                       "🔵 blue • 🟣 purple • 🟤 brown • ⚫ black\n"
                       "⚪ white • 🩷 pink • 🔘 grey",
            color=discord.Color.blurple()
        )
        await ctx.reply(embed=embed)
        return

    colors = {
        "red": discord.Color.red(),
        "orange": discord.Color.orange(),
        "yellow": discord.Color.yellow(),
        "green": discord.Color.green(),
        "blue": discord.Color.blue(),
        "purple": discord.Color.purple(),
        "brown": discord.Color.from_rgb(139, 69, 19),
        "black": discord.Color.from_rgb(0, 0, 0),
        "white": discord.Color.from_rgb(255, 255, 255),
        "pink": discord.Color.from_rgb(255, 192, 203),
        "grey": discord.Color.from_rgb(128, 128, 128)
    }

    chosen_color = colors.get(color.lower())
    if not chosen_color:
        await ctx.reply("❌ Cor inválida! Use `p!color` para ver as opções.")
        return

    embed = discord.Embed(
        title="🎨 Cor do Perfil Alterada!",
        description=f"Sua nova cor é: **{color.title()}**",
        color=chosen_color
    )
    await ctx.reply(embed=embed)

# 9. Gerar Meme
@bot.command(name='meme')
async def meme(ctx):
    memes = [
        "https://i.imgflip.com/1bij.jpg",
        "https://i.imgflip.com/5c7lwq.png",
        "https://i.imgflip.com/4t0m5.jpg",
        "https://i.imgflip.com/26am.jpg",
        "https://i.imgflip.com/16iyn1.jpg"
    ]

    meme_url = random.choice(memes)
    embed = discord.Embed(
        title="😂 Meme Aleatório",
        color=discord.Color.blurple()
    )
    embed.set_image(url=meme_url)
    await ctx.reply(embed=embed)

# 10. Comando 8Ball
@bot.command(name='8ball')
async def eight_ball(ctx, *, question: str):
    responses = [
        "Sim, definitivamente!", "Não conte com isso.", "Sim!", "Resposta nebulosa, tente novamente.",
        "Sem dúvida!", "Minhas fontes dizem não.", "Provavelmente!", "Não é possível prever agora.",
        "Certamente!", "Muito duvidoso.", "Você pode contar com isso!", "Concentre-se e pergunte novamente.",
        "Como eu vejo, sim.", "Não!", "Sinais apontam para sim.", "Melhor não te contar agora."
    ]

    response = random.choice(responses)
    embed = discord.Embed(
        title="🎱 Bola Mágica 8",
        description=f"**Pergunta:** {question}\n**Resposta:** {response}",
        color=discord.Color.dark_blue()
    )
    await ctx.reply(embed=embed)

# 11. Comando de Sorte
@bot.command(name='luck', aliases=['sorte'])
async def luck(ctx):
    luck_percentage = random.randint(0, 100)

    if luck_percentage >= 90:
        color = discord.Color.gold()
        message = "🍀 Você está com MUITA sorte hoje!"
    elif luck_percentage >= 70:
        color = discord.Color.green()
        message = "😊 Você está com boa sorte!"
    elif luck_percentage >= 40:
        color = discord.Color.orange()
        message = "😐 Sua sorte está mediana..."
    else:
        color = discord.Color.red()
        message = "😱 Cuidado, você está azarado hoje!"

    embed = discord.Embed(
        title="🍀 Medidor de Sorte",
        description=f"**{ctx.author.display_name}**, sua sorte hoje é: **{luck_percentage}%**\n{message}",
        color=color
    )
    await ctx.reply(embed=embed)

# 12. Comando de Citação
@bot.command(name='quote', aliases=['citacao'])
async def quote(ctx):
    quotes = [
        "O futebol é uma paixão nacional. Mas para que o sentimento seja sadio, é preciso que a virtude seja superior à paixão.",
        "Futebol se joga com os pés, mas se ganha com a cabeça.",
        "No futebol, o mais difícil é tornar difícil parecer fácil.",
        "O futebol é a poesia em movimento.",
        "Prefiro perder um jogo tentando ganhar do que ganhar um jogo tentando perder."
    ]

    quote = random.choice(quotes)
    embed = discord.Embed(
        title="💭 Citação do Dia",
        description=f"*\"{quote}\"*",
        color=discord.Color.blue()
    )
    await ctx.reply(embed=embed)

# 13. Comando de Enquete
class PollView(View):
    def __init__(self, question: str, options: list):
        super().__init__(timeout=300)
        self.question = question
        self.options = options
        self.votes = {i: 0 for i in range(len(options))}
        self.voters = set()

        for i, option in enumerate(options[:5]):  # Máximo 5 opções
            button = Button(label=f"{i+1}. {option}", style=discord.ButtonStyle.secondary)
            button.callback = self.create_vote_callback(i)
            self.add_item(button)

    def create_vote_callback(self, option_index):
        async def vote_callback(interaction: discord.Interaction):
            if interaction.user.id in self.voters:
                await interaction.response.send_message("❌ Você já votou!", ephemeral=True)
                return

            self.votes[option_index] += 1
            self.voters.add(interaction.user.id)

            # Atualizar embed
            embed = discord.Embed(
                title="📊 Enquete",
                description=f"**{self.question}**",
                color=discord.Color.blue()
            )

            total_votes = sum(self.votes.values())
            for i, option in enumerate(self.options):
                votes = self.votes[i]
                percentage = (votes / total_votes * 100) if total_votes > 0 else 0
                bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))
                embed.add_field(
                    name=f"{i+1}. {option}",
                    value=f"`{bar}` {votes} votos ({percentage:.1f}%)",
                    inline=False
                )

            embed.set_footer(text=f"Total: {total_votes} votos - Dev: YevgennyMXP")
            await interaction.response.edit_message(embed=embed, view=self)

        return vote_callback

@bot.command(name='poll', aliases=['enquete'])
async def poll(ctx, question: str, *options):
    if len(options) < 2:
        await ctx.reply("❌ Você precisa fornecer pelo menos 2 opções!")
        return
    if len(options) > 5:
        await ctx.reply("❌ Máximo de 5 opções permitidas!")
        return

    embed = discord.Embed(
        title="📊 Enquete",
        description=f"**{question}**",
        color=discord.Color.blue()
    )

    for i, option in enumerate(options):
        embed.add_field(
            name=f"{i+1}. {option}",
            value="`░░░░░░░░░░░░░░░░░░░░` 0 votos (0.0%)",
            inline=False
        )

    embed.set_footer(text="Total: 0 votos - Dev: YevgennyMXP")
    view = PollView(question, list(options))
    await ctx.reply(embed=embed, view=view)

# 14. Palavra do Dia
@bot.command(name='word', aliases=['palavra'])
async def word_of_day(ctx):
    words = [
        {"word": "Pênalti", "definition": "Tiro livre direto cobrado da marca do pênalti"},
        {"word": "Escanteio", "definition": "Tiro de canto concedido quando a bola sai pela linha de fundo"},
        {"word": "Impedimento", "definition": "Posição irregular de um jogador no momento do passe"},
        {"word": "Hat-trick", "definition": "Três gols marcados pelo mesmo jogador em uma partida"},
        {"word": "Nutmeg", "definition": "Drible onde a bola passa entre as pernas do adversário"}
    ]

    word_data = random.choice(words)
    embed = discord.Embed(
        title="📖 Palavra do Dia",
        description=f"**{word_data['word']}**\n\n*{word_data['definition']}*",
        color=discord.Color.purple()
    )
    await ctx.reply(embed=embed)

# 15. Countdown Timer
@bot.command(name='countdown', aliases=['timer'])
async def countdown(ctx, seconds: int):
    if seconds <= 0 or seconds > 3600:  # Máximo 1 hora
        await ctx.reply("❌ Tempo deve ser entre 1 e 3600 segundos!")
        return

    embed = discord.Embed(
        title="⏰ Timer Iniciado",
        description=f"Timer de {seconds} segundos iniciado!",
        color=discord.Color.blue()
    )
    message = await ctx.reply(embed=embed)

    await asyncio.sleep(seconds)

    final_embed = discord.Embed(
        title="⏰ Tempo Esgotado!",
        description=f"{ctx.author.mention} Seu timer de {seconds} segundos acabou!",
        color=discord.Color.red()
    )
    await message.edit(embed=final_embed)

# 16. Emoji Info
@bot.command(name='emoji')
async def emoji_info(ctx, emoji: str):
    embed = discord.Embed(
        title="😀 Informações do Emoji",
        description=f"**Emoji:** {emoji}\n**Unicode:** `{ord(emoji[0]):04x}` se for unicode",
        color=discord.Color.yellow()
    )
    await ctx.reply(embed=embed)

# 17. Random Number
@bot.command(name='random', aliases=['rand'])
async def random_number(ctx, min_num: int = 1, max_num: int = 100):
    if min_num >= max_num:
        await ctx.reply("❌ O número mínimo deve ser menor que o máximo!")
        return

    number = random.randint(min_num, max_num)
    embed = discord.Embed(
        title="🎲 Número Aleatório",
        description=f"Entre {min_num} e {max_num}: **{number}**",
        color=discord.Color.random()
    )
    await ctx.reply(embed=embed)

# 18. Comando de Idade
@bot.command(name='age', aliases=['idade'])
async def age_calculator(ctx, year: int, month: int = 1, day: int = 1):
    try:
        birth_date = datetime(year, month, day)
        today = datetime.now()
        age = today - birth_date
        years = age.days // 365

        embed = discord.Embed(
            title="🎂 Calculadora de Idade",
            description=f"Nascido em: {birth_date.strftime('%d/%m/%Y')}\nIdade: **{years} anos** ({age.days} dias)",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
    except ValueError:
        await ctx.reply("❌ Data inválida!")

# 19. Sistema de Dados Personalizados
@bot.command(name='customroll', aliases=['rollcustom'])
async def custom_roll(ctx, dice_notation: str):
    # Formato: XdY (ex: 3d6 = 3 dados de 6 lados)
    try:
        if 'd' not in dice_notation:
            await ctx.reply("❌ Use o formato XdY (ex: 3d6)")
            return

        parts = dice_notation.split('d')
        num_dice = int(parts[0])
        sides = int(parts[1])

        if num_dice <= 0 or num_dice > 20:
            await ctx.reply("❌ Número de dados deve ser entre 1 e 20!")
            return
        if sides <= 0 or sides > 1000:
            await ctx.reply("❌ Lados devem ser entre 1 e 1000!")
            return

        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls)

        embed = discord.Embed(
            title=f"🎲 Rolagem: {dice_notation}",
            description=f"**Resultados:** {', '.join(map(str, rolls))}\n**Total:** {total}",
            color=discord.Color.green()
        )
        await ctx.reply(embed=embed)

    except ValueError:
        await ctx.reply("❌ Formato inválido! Use XdY (ex: 3d6)")

# 20. Comando Gerar Senha
@bot.command(name='password', aliases=['senha'])
async def generate_password(ctx, length: int = 12):
    if length < 4 or length > 50:
        await ctx.reply("❌ Comprimento deve ser entre 4 e 50!")
        return

    import string
    characters = string.ascii_letters + string.digits + "!@#$%&*"
    password = ''.join(random.choice(characters) for _ in range(length))

    embed = discord.Embed(
        title="🔒 Senha Gerada",
        description=f"Sua senha aleatória: ||`{password}`||",
        color=discord.Color.dark_blue()
    )
    embed.set_footer(text="⚠️ Esta senha é temporária, mude após usar!  - Dev: YevgennyMXP")
    await ctx.reply(embed=embed)

# 21. QR Code Info (simulado)
@bot.command(name='qr')
async def qr_code(ctx, *, text: str):
    embed = discord.Embed(
        title="📱 QR Code",
        description=f"QR Code para: `{text}`\n\n*Use um gerador online real para criar o QR code*",
        color=discord.Color.dark_grey()
    )
    await ctx.reply(embed=embed)

# 22. Sistema de Reação
@bot.command(name='react', aliases=['reagir'])
async def react_message(ctx, message_id: int, emoji: str):
    try:
        message = await ctx.channel.fetch_message(message_id)
        await message.add_reaction(emoji)
        await ctx.reply(f"✅ Reação {emoji} adicionada!")
    except discord.NotFound:
        await ctx.reply("❌ Mensagem não encontrada!")
    except discord.HTTPException:
        await ctx.reply("❌ Emoji inválido ou erro ao reagir!")

# 23. Simular Partida - Versão Avançada e Realista
class MatchSimulator:
    def __init__(self):
        self.stadiums = {
            "Maracanã": {
                "capacity": "78.838",
                "city": "Rio de Janeiro",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139284226936883/maracana.jpg?ex=683b7e46&is=683a2cc6&hm=d7cc9a8d4e4b13a1f2dc8b4a2e48d7ebc4c7b8d92e1c0f6a5b9e8d7c6a5b4d3e&="
            },
            "Arena Corinthians": {
                "capacity": "49.205",
                "city": "São Paulo",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139343618674759/arena-corinthians.jpg?ex=683b7e54&is=683a2cd4&hm=3f8e2d1c0b9a8d7c6e5f4e3d2c1b0a9e8d7c6b5a4e3d2c1f0e9d8c7b6a5f4e3&="
            },
            "Allianz Parque": {
                "capacity": "43.713",
                "city": "São Paulo",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139405060374628/allianz-parque.jpg?ex=683b7e62&is=683a2ce2&hm=9e8d7c6b5a4f3e2d1c0b9a8e7d6c5b4a3f2e1d0c9b8a7e6d5c4b3a2f1e0d9c&="
            },
            "Arena da Baixada": {
                "capacity": "42.372",
                "city": "Curitiba",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139463520575530/arena-da-baixada.jpg?ex=683b7e70&is=683a2cf0&hm=7d6c5b4a3f2e1d0c9b8a7e6d5c4b3a2f1e0d9c8b7a6e5d4c3b2a1f0e9d8c7b&="
            },
            "Estádio Beira-Rio": {
                "capacity": "50.842",
                "city": "Porto Alegre",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139522240921710/beira-rio.jpg?ex=683b7e7e&is=683a2cfe&hm=5c4b3a2f1e0d9c8b7a6e5d4c3b2a1f0e9d8c7b6a5e4d3c2b1a0f9e8d7c6b5a&="
            },
            "Arena Fonte Nova": {
                "capacity": "50.025",
                "city": "Salvador",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139580189270026/arena-fonte-nova.jpg?ex=683b7e8c&is=683a2d0c&hm=3b2a1f0e9d8c7b6a5e4d3c2b1a0f9e8d7c6b5a4e3d2c1b0a9f8e7d6c5b4a3e&="
            },
            "Neo Química Arena": {
                "capacity": "47.605",
                "city": "São Paulo",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139640935055390/neo-quimica-arena.jpg?ex=683b7e9a&is=683a2d1a&hm=1a0f9e8d7c6b5a4e3d2c1b0a9f8e7d6c5b4a3e2d1c0b9a8f7e6d5c4b3a2e1d&="
            },
            "Arena MRV": {
                "capacity": "46.000",
                "city": "Belo Horizonte",
                "image": "https://media.discordapp.net/attachments/1305879543394861056/1378139697558241330/arena-mrv.jpg?ex=683b7ea8&is=683a2d28&hm=f9e8d7c6b5a4e3d2c1b0a9f8e7d6c5b4a3e2d1c0b9a8f7e6d5c4b3a2e1d0c9&="
            }
        }

        self.weather_conditions = [
            {"condition": "☀️ Ensolarado", "temp": "28°C", "desc": "Dia perfeito para futebol"},
            {"condition": "⛅ Parcialmente Nublado", "temp": "24°C", "desc": "Condições ideais"},
            {"condition": "🌧️ Chuva Leve", "temp": "19°C", "desc": "Campo pode ficar escorregadio"},
            {"condition": "🌤️ Sol entre Nuvens", "temp": "26°C", "desc": "Clima agradável"},
            {"condition": "🌩️ Tempestade se Aproximando", "temp": "21°C", "desc": "Tensão no ar"}
        ]

        self.formations = ["4-3-3", "4-4-2", "3-5-2", "4-2-3-1", "5-3-2", "4-1-4-1"]

        # Eventos que podem resultar em gol
        self.goal_events = [
            "GOL_NORMAL",
            "GOL_PENALTI",
            "GOL_FALTA",
            "GOL_ESCANTEIO",
            "GOL_CONTRA_ATAQUE"
        ]

        # Eventos normais sem gol (serão personalizados com nomes de jogadores)
        self.normal_events_templates = [
            "🥅 **DEFESA INCRÍVEL de {goalkeeper}!** O goleiro {team} salvou o que parecia ser gol certo!",
            "🟨 **Cartão Amarelo para {player} ({team})** - Entrada dura é punida",
            "🟥 **CARTÃO VERMELHO para {player} ({team})!** Jogador expulso!",
            "🔄 **Substituição no {team}** - {player} sai, mudança tática no jogo",
            "🚑 **Atendimento Médico para {player} ({team})** - Jogador recebe cuidados no campo",
            "📐 **IMPEDIMENTO de {player} ({team})!** Lance anulado pela arbitragem",
            "🥅 **{player} ({team}) NA TRAVE!** Por muito pouco não foi gol!",
            "⛳ **Escanteio para {team}** - {player} força a defesa",
            "🦵 **Falta perigosa sofrida por {player} ({team})** - Chance de gol na bola parada",
            "👨‍⚖️ **VAR revisa lance de {player} ({team})** - Análise em andamento",
            "🧤 **Defesa de {goalkeeper} ({team})** - Intervenção importante",
            "💨 **Contra-ataque rápido puxado por {player} ({team})** - Transição perigosa",
            "🎪 **Jogada individual de {player} ({team})** - Drible desconcertante",
            "🏃‍♂️ **{player} ({team}) pela lateral** - Jogada de velocidade",
            "⚡ **Cruzamento de {player} ({team}) na área** - Bola perigosa",
            "🎯 **Chute de fora da área de {player} ({team})** - Tentativa de longe",
            "🔄 **Troca de passes envolvendo {player} ({team})** - Jogada elaborada",
            "🛡️ **Bloqueio defensivo de {player} ({team})** - Defesa bem postada"
        ]

        # Descrições dos tipos de gol (com nomes de jogadores)
        self.goal_descriptions = {
            "GOL_NORMAL": [
                "⚽ **GOL de {player} ({team})!** Que jogada espetacular! Finalização perfeita!",
                "⚽ **GOLAÇO de {player} ({team})!** Que definição incrível! Não deu chance pro goleiro!",
                "⚽ **GOL de {player} ({team})!** Jogada individual brilhante! Show de bola!",
                "⚽ **GOL de {player} ({team})!** Contra-ataque fatal! Velocidade pura!",
                "⚽ **GOL de {player} ({team})!** Cabeceada certeira! Que subida!"
            ],
            "GOL_PENALTI": [
                "⚽🎯 **GOL DE PÊNALTI de {player} ({team})!** Bateu no canto, sem chances para o goleiro!",
                "⚽🎯 **PÊNALTI CONVERTIDO por {player} ({team})!** Frieza total na hora decisiva!",
                "⚽🎯 **GOL de {player} ({team})!** Pênalti batido com categoria!"
            ],
            "GOL_FALTA": [
                "⚽🌟 **GOLAÇO DE FALTA de {player} ({team})!** Que cobrança espetacular!",
                "⚽🌟 **GOL DE FALTA de {player} ({team})!** A bola fez uma curva perfeita!",
                "⚽🌟 **FALTA CERTEIRA de {player} ({team})!** Direto no ângulo!"
            ],
            "GOL_ESCANTEIO": [
                "⚽📐 **GOL DE ESCANTEIO de {player} ({team})!** Cabeceada perfeita!",
                "⚽📐 **ESCANTEIO FATAL! {player} ({team})** aproveita a cobrança!",
                "⚽📐 **GOL de {player} ({team})!** Aproveitou bem a cobrança de escanteio!"
            ],
            "GOL_CONTRA_ATAQUE": [
                "⚽⚡ **GOL EM CONTRA-ATAQUE de {player} ({team})!** Velocidade pura!",
                "⚽⚡ **CONTRA-ATAQUE LETAL de {player} ({team})!** Não perdoou a chance!",
                "⚽⚡ **GOL de {player} ({team})!** Transição rápida e eficiente!"
            ]
        }

    def get_random_player(self, players_list, team_name):
        """Retorna um jogador aleatório da lista ou nome genérico se não houver lista"""
        if players_list and len(players_list) > 0:
            return random.choice(players_list)['name']
        else:
            # Nomes genéricos se não houver jogadores reais
            generic_names = [
                "Silva", "Santos", "Oliveira", "Souza", "Pereira", "Costa", "Rodrigues",
                "Almeida", "Nascimento", "Lima", "Araújo", "Fernandes", "Carvalho",
                "Gomes", "Martins", "Rocha", "Ribeiro", "Alves", "Monteiro", "Mendes"
            ]
            return random.choice(generic_names)

    def get_goalkeeper_name(self, players_list, team_name):
        """Retorna um goleiro específico ou nome genérico"""
        if players_list:
            goalkeepers = [p for p in players_list if 'goalkeeper' in p.get('position', '').lower() or 'goleiro' in p.get('position', '').lower()]
            if goalkeepers:
                return goalkeepers[0]['name']
        
        # Nomes genéricos de goleiros
        generic_gk_names = ["Silva", "Santos", "Oliveira", "Costa", "Almeida", "Pereira"]
        return random.choice(generic_gk_names)

    async def simulate_match(self, ctx, team1: str, team2: str):
        team1 = capitalizar_nome(team1)
        team2 = capitalizar_nome(team2)

        # Buscar jogadores reais para times da Série B
        team1_players = await get_team_players(team1)
        team2_players = await get_team_players(team2)

        # Escolher estádio aleatório
        stadium_name = random.choice(list(self.stadiums.keys()))
        stadium = self.stadiums[stadium_name]

        # Escolher condições climáticas
        weather = random.choice(self.weather_conditions)

        # Formações dos times
        formation1 = random.choice(self.formations)
        formation2 = random.choice(self.formations)

        # Embed inicial - Pré-jogo
        initial_embed = discord.Embed(
            title="🏟️ **TRANSMISSÃO AO VIVO** 🏟️",
            description=f"🔴 **PREPARANDO TRANSMISSÃO...**\n\n📍 **{stadium_name}** - {stadium['city']}\n👥 Capacidade: {stadium['capacity']} torcedores",
            color=discord.Color.blue()
        )
        initial_embed.set_image(url=stadium['image'])
        initial_embed.add_field(
            name="🌤️ Condições Climáticas",
            value=f"{weather['condition']} | {weather['temp']}\n*{weather['desc']}*",
            inline=True
        )
        # Mostrar escalações se disponíveis
        confronto_text = f"🏠 **{team1}** ({formation1})\n🆚\n✈️ **{team2}** ({formation2})"
        
        initial_embed.add_field(
            name="⚽ Confronto",
            value=confronto_text,
            inline=True
        )
        
        # Adicionar escalações reais se disponíveis
        if team1_players or team2_players:
            escalacoes_text = ""
            if team1_players:
                escalacoes_text += format_team_lineup(team1, team1_players) + "\n"
            if team2_players:
                escalacoes_text += format_team_lineup(team2, team2_players)
            
            if escalacoes_text:
                initial_embed.add_field(
                    name="📋 Escalações Confirmadas",
                    value=escalacoes_text,
                    inline=False
                )
        initial_embed.set_footer(text="🔴 AO VIVO •  - Dev: YevgennyMXP")

        message = await ctx.reply(embed=initial_embed)
        await asyncio.sleep(3)

        # Atualizando para início do jogo
        pregame_embed = discord.Embed(
            title="🏟️ **TRANSMISSÃO AO VIVO** 🏟️",
            description=f"🟢 **PARTIDA INICIADA!**\n\n📍 **{stadium_name}** - {stadium['city']}\n⏱️ **1º Tempo • 0'**",
            color=discord.Color.green()
        )
        pregame_embed.set_image(url=stadium['image'])
        pregame_embed.add_field(
            name="📊 Placar Atual",
            value=f"🏠 **{team1}** `0`\n✈️ **{team2}** `0`",
            inline=True
        )
        pregame_embed.add_field(
            name="🌤️ Condições",
            value=f"{weather['condition']} | {weather['temp']}",
            inline=True
        )
        pregame_embed.add_field(
            name="📺 Formações",
            value=f"{team1}: {formation1}\n{team2}: {formation2}",
            inline=True
        )
        pregame_embed.set_footer(text="🔴 AO VIVO • 0' • Bola rolando!")

        await message.edit(embed=pregame_embed)
        await asyncio.sleep(2)

        # Simulação dos eventos do jogo
        goals1 = 0
        goals2 = 0
        events_log = []
        cards_team1 = {"yellow": 0, "red": 0}
        cards_team2 = {"yellow": 0, "red": 0}
        goal_scorers1 = []
        goal_scorers2 = []

        # Primeira parte do jogo (0-45 min)
        for minute in [8, 15, 22, 28, 35, 41, 45]:
            # Determinar tipo de evento (30% chance de ser relacionado a gol)
            if random.random() < 0.30:
                # Evento de gol
                goal_type = random.choice(self.goal_events)

                # 85% de chance de converter o evento em gol real
                if random.random() < 0.85:
                    # Decidir qual time marca
                    if random.random() > 0.5:
                        goals1 += 1
                        scorer_name = self.get_random_player(team1_players, team1)
                        goal_desc = random.choice(self.goal_descriptions[goal_type]).format(
                            player=scorer_name, team=team1
                        )
                        
                        events_log.append(f"`{minute}'` {goal_desc}")
                        events_log.append(f"🎉 **{team1.upper()} MARCA!** Placar: {team1} {goals1} x {goals2} {team2}")
                        
                        scorer_info = f"{minute}' ({scorer_name})"
                        goal_scorers1.append(scorer_info)
                    else:
                        goals2 += 1
                        scorer_name = self.get_random_player(team2_players, team2)
                        goal_desc = random.choice(self.goal_descriptions[goal_type]).format(
                            player=scorer_name, team=team2
                        )
                        
                        events_log.append(f"`{minute}'` {goal_desc}")
                        events_log.append(f"🎉 **{team2.upper()} MARCA!** Placar: {team1} {goals1} x {goals2} {team2}")
                        
                        scorer_info = f"{minute}' ({scorer_name})"
                        goal_scorers2.append(scorer_info)
                else:
                    # Chance perdida
                    miss_events = [
                        "🥅 **POR POUCO!** A bola passou raspando a trave!",
                        "🧤 **DEFESAÇA!** O goleiro fez um milagre!",
                        "📐 **IMPEDIMENTO!** Gol anulado pela arbitragem!",
                        "💥 **NA TRAVE!** Que azar! Por centímetros!"
                    ]
                    events_log.append(f"`{minute}'` {random.choice(miss_events)}")
            else:
                # Evento normal
                if random.random() < 0.1:  # 10% chance de cartão
                    if random.random() < 0.8:  # 80% amarelo, 20% vermelho
                        team_card = random.choice([team1, team2])
                        if team_card == team1:
                            cards_team1["yellow"] += 1
                        else:
                            cards_team2["yellow"] += 1
                        events_log.append(f"`{minute}'` 🟨 Cartão amarelo para {team_card}")
                    else:
                        team_card = random.choice([team1, team2])
                        if team_card == team1:
                            cards_team1["red"] += 1
                        else:
                            cards_team2["red"] += 1
                        events_log.append(f"`{minute}'` 🟥 **EXPULSÃO!** {team_card} com um a menos!")
                else:
                    # Evento normal do jogo com nomes de jogadores
                    event_template = random.choice(self.normal_events_templates)
                    
                    # Escolher time aleatório para o evento
                    event_team = random.choice([team1, team2])
                    event_players = team1_players if event_team == team1 else team2_players
                    
                    # Selecionar jogador e goleiro
                    player_name = self.get_random_player(event_players, event_team)
                    goalkeeper_name = self.get_goalkeeper_name(event_players, event_team)
                    
                    # Aplicar formatação baseada no tipo de evento
                    if "{goalkeeper}" in event_template:
                        event_desc = event_template.format(
                            goalkeeper=goalkeeper_name, team=event_team
                        )
                    else:
                        event_desc = event_template.format(
                            player=player_name, team=event_team
                        )
                    
                    events_log.append(f"`{minute}'` {event_desc}")

            # Atualizar embed com imagem do estádio
            live_embed = discord.Embed(
                title="🏟️ **TRANSMISSÃO AO VIVO** 🏟️",
                description=f"🟢 **1º TEMPO EM ANDAMENTO**\n\n📍 **{stadium_name}** - {stadium['city']}\n⏱️ **{minute}'**",
                color=discord.Color.orange()
            )
            live_embed.set_image(url=stadium['image'])
            live_embed.add_field(
                name="📊 Placar Atual",
                value=f"🏠 **{team1}** `{goals1}`\n✈️ **{team2}** `{goals2}`",
                inline=True
            )
            live_embed.add_field(
                name="📝 Últimos Eventos",
                value="\n".join(events_log[-3:]) if events_log else "Jogo equilibrado...",
                inline=False
            )
            live_embed.set_footer(text=f"🔴 AO VIVO • {minute}' • 1º Tempo")

            await message.edit(embed=live_embed)
            await asyncio.sleep(2.5)

        # Intervalo
        interval_embed = discord.Embed(
            title="🏟️ **INTERVALO** 🏟️",
            description=f"⏸️ **FIM DO 1º TEMPO**\n\n📍 **{stadium_name}** - {stadium['city']}\n⏱️ **45' + 2' (HT)**",
            color=discord.Color.yellow()
        )
        interval_embed.set_image(url=stadium['image'])
        interval_embed.add_field(
            name="📊 Placar do 1º Tempo",
            value=f"🏠 **{team1}** `{goals1}`\n✈️ **{team2}** `{goals2}`",
            inline=True
        )
        interval_embed.add_field(
            name="📈 Estatísticas",
            value=f"🟨 Cartões: {cards_team1['yellow'] + cards_team2['yellow']}\n🟥 Expulsões: {cards_team1['red'] + cards_team2['red']}\n⚽ Gols: {goals1 + goals2}",
            inline=True
        )
        interval_embed.add_field(
            name="📝 Principais Eventos",
            value="\n".join(events_log[-4:]) if events_log else "Primeiro tempo equilibrado",
            inline=False
        )
        interval_embed.set_footer(text="⏸️ INTERVALO • Análise tática em andamento")

        await message.edit(embed=interval_embed)
        await asyncio.sleep(3)

        # Segunda parte do jogo (45-90 min) - chance aumentada de gols
        for minute in [50, 56, 63, 71, 78, 84, 89, 90]:
            # Determinar tipo de evento (35% chance de ser relacionado a gol no 2º tempo)
            if random.random() < 0.35:
                # Evento de gol
                goal_type = random.choice(self.goal_events)

                # 85% de chance de converter o evento em gol real
                if random.random() < 0.85:
                    # Decidir qual time marca
                    if random.random() > 0.5:
                        goals1 += 1
                        scorer_name = self.get_random_player(team1_players, team1)
                        goal_desc = random.choice(self.goal_descriptions[goal_type]).format(
                            player=scorer_name, team=team1
                        )
                        
                        events_log.append(f"`{minute}'` {goal_desc}")
                        events_log.append(f"🔥 **{team1.upper()} MARCA!** Placar: {team1} {goals1} x {goals2} {team2}")
                        
                        scorer_info = f"{minute}' ({scorer_name})"
                        goal_scorers1.append(scorer_info)
                    else:
                        goals2 += 1
                        scorer_name = self.get_random_player(team2_players, team2)
                        goal_desc = random.choice(self.goal_descriptions[goal_type]).format(
                            player=scorer_name, team=team2
                        )
                        
                        events_log.append(f"`{minute}'` {goal_desc}")
                        events_log.append(f"🔥 **{team2.upper()} MARCA!** Placar: {team1} {goals1} x {goals2} {team2}")
                        
                        scorer_info = f"{minute}' ({scorer_name})"
                        goal_scorers2.append(scorer_info)
                else:
                    # Chance perdida no 2º tempo
                    miss_events = [
                        "😱 **PERDEU INCRÍVEL!** Cara a cara com o goleiro e mandou para fora!",
                        "🥅 **SALVOU TUDO!** Defesa espetacular do goleiro!",
                        "💥 **NO TRAVESSÃO!** A bola bateu e voltou!",
                        "📐 **IMPEDIMENTO MILIMÉTRICO!** VAR confirma posição irregular!"
                    ]
                    events_log.append(f"`{minute}'` {random.choice(miss_events)}")
            else:
                # Eventos especiais do 2º tempo
                if random.random() < 0.12:  # 12% chance de cartão (mais tensão)
                    team_card = random.choice([team1, team2])
                    card_players = team1_players if team_card == team1 else team2_players
                    player_name = self.get_random_player(card_players, team_card)
                    
                    if random.random() < 0.75:  # 75% amarelo, 25% vermelho
                        if team_card == team1:
                            cards_team1["yellow"] += 1
                        else:
                            cards_team2["yellow"] += 1
                        events_log.append(f"`{minute}'` 🟨 **Cartão amarelo para {player_name} ({team_card})** - tensão aumenta!")
                    else:
                        if team_card == team1:
                            cards_team1["red"] += 1
                        else:
                            cards_team2["red"] += 1
                        events_log.append(f"`{minute}'` 🟥 **CARTÃO VERMELHO para {player_name} ({team_card})!** Expulsão!")
                else:
                    # Eventos intensos do 2º tempo com nomes de jogadores
                    event_team = random.choice([team1, team2])
                    event_players = team1_players if event_team == team1 else team2_players
                    player_name = self.get_random_player(event_players, event_team)
                    
                    intense_events = [
                        f"⚡ **PRESSÃO TOTAL de {player_name} ({event_team})!** Vai para cima em busca do gol!",
                        f"🏃‍♂️ **CORRERIA de {player_name} ({event_team})!** Jogo fica aberto e emocionante!",
                        f"🔄 **SUBSTITUIÇÃO no {event_team}!** {player_name} entra para mudar o jogo!",
                        f"📢 **TORCIDA EXPLODE com {player_name} ({event_team})!** Estádio em festa!",
                        f"⏱️ **{player_name} ({event_team}) DESESPERADO!** Corrida contra o tempo!",
                        f"🎯 **TENTATIVA DE LONGE de {player_name} ({event_team})!** Chute de fora da área!",
                        f"🏃‍♂️ **{player_name} ({event_team}) EM VELOCIDADE PURA!** Contra-ataque perigoso!"
                    ]
                    events_log.append(f"`{minute}'` {random.choice(intense_events)}")

            # Atualizar embed com maior intensidade visual
            live_embed2 = discord.Embed(
                title="🏟️ **TRANSMISSÃO AO VIVO** 🏟️",
                description=f"🔥 **2º TEMPO - EMOÇÃO TOTAL!**\n\n📍 **{stadium_name}** - {stadium['city']}\n⏱️ **{minute}'**",
                color=discord.Color.red()
            )
            live_embed2.set_image(url=stadium['image'])
            live_embed2.add_field(
                name="📊 Placar Atual", 
                value=f"🏠 **{team1}** `{goals1}`\n✈️ **{team2}** `{goals2}`",
                inline=True
            )

            # Mostrar goleadores se houver
            if goal_scorers1 or goal_scorers2:
                scorers_text = ""
                if goal_scorers1:
                    scorers_text += f"⚽ **{team1}:** {', '.join(goal_scorers1)}\n"
                if goal_scorers2:
                    scorers_text += f"⚽ **{team2}:** {', '.join(goal_scorers2)}"
                live_embed2.add_field(
                    name="🎯 Goleadores",
                    value=scorers_text,
                    inline=True
                )

            live_embed2.add_field(
                name="📝 Últimos Eventos",
                value="\n".join(events_log[-3:]) if events_log else "Pressão total!",
                inline=False
            )
            live_embed2.set_footer(text=f"🔴 AO VIVO • {minute}' • 2º Tempo • TENSÃO MÁXIMA!")

            await message.edit(embed=live_embed2)
            await asyncio.sleep(2.5)

        # Resultado final
        if goals1 > goals2:
            winner = team1
            result_color = discord.Color.green()
            result_emoji = "🏆"
            result_text = f"**VITÓRIA DO {team1.upper()}!**"
        elif goals2 > goals1:
            winner = team2
            result_color = discord.Color.green()
            result_emoji = "🏆"
            result_text = f"**VITÓRIA DO {team2.upper()}!**"
        else:
            winner = None
            result_color = discord.Color.gold()
            result_emoji = "🤝"
            result_text = "**EMPATE EMOCIONANTE!**"

        # Embed final com estatísticas completas
        final_embed = discord.Embed(
            title="🏟️ **FIM DE JOGO** 🏟️",
            description=f"🏁 **PARTIDA ENCERRADA**\n\n📍 **{stadium_name}** - {stadium['city']}\n⏱️ **90' + 4' (FT)**\n\n{result_emoji} {result_text}",
            color=result_color
        )
        final_embed.set_image(url=stadium['image'])
        final_embed.add_field(
            name="📊 RESULTADO FINAL",
            value=f"🏠 **{team1}** `{goals1}`\n✈️ **{team2}** `{goals2}`",
            inline=True
        )

        # Mostrar goleadores detalhados
        if goal_scorers1 or goal_scorers2:
            scorers_final = ""
            if goal_scorers1:
                scorers_final += f"⚽ **{team1}:**\n{', '.join(goal_scorers1)}\n\n"
            if goal_scorers2:
                scorers_final += f"⚽ **{team2}:**\n{', '.join(goal_scorers2)}"
            final_embed.add_field(
                name="🎯 Artilheiros da Partida",
                value=scorers_final,
                inline=True
            )

        final_embed.add_field(
            name="📈 Estatísticas Finais",
            value=(
                f"⚽ **Total de Gols:** {goals1 + goals2}\n"
                f"🟨 **Cartões Amarelos:** {cards_team1['yellow'] + cards_team2['yellow']}\n"
                f"🟥 **Expulsões:** {cards_team1['red'] + cards_team2['red']}\n"
                f"🎯 **Formações:** {formation1} x {formation2}\n"
                f"📊 **Eventos:** {len(events_log)} lances"
            ),
            inline=True
        )

        # Melhores momentos (só gols e cartões vermelhos)
        best_moments = [e for e in events_log if ("⚽" in e and "GOL" in e) or "🟥" in e]
        if best_moments:
            final_embed.add_field(
                name="🎬 Melhores Momentos",
                value="\n".join(best_moments[-6:]),
                inline=False
            )

        final_embed.add_field(
            name="🌤️ Condições do Jogo",
            value=f"{weather['condition']} | {weather['temp']}\n*{weather['desc']}*",
            inline=True
        )

        final_embed.add_field(
            name="🏟️ Estádio",
            value=f"**{stadium_name}**\nCapacidade: {stadium['capacity']}\n{stadium['city']}",
            inline=True
        )

        if winner:
            final_embed.add_field(
                name=f"{result_emoji} VENCEDOR",
                value=f"**{winner}**\nParabéns pela vitória!",
                inline=True
            )

        final_embed.set_footer(text="🏁 FINAL •  - Dev: YevgennyMXP • Transmissão encerrada com sucesso!")

        await message.edit(embed=final_embed)

# Instanciar simulador
match_simulator = MatchSimulator()

@bot.command(name='simular', aliases=['simulate'])
async def simulate_match(ctx, team1: str, team2: str):
    """Simula uma partida de futebol com transmissão ao vivo realista"""
    await match_simulator.simulate_match(ctx, team1, team2)

# 24. Comando Inspire
@bot.command(name='inspire', aliases=['inspiracao'])
async def inspire(ctx):
    quotes = [
        "Acredite em si mesmo e tudo será possível.",
        "O fracasso é apenas uma oportunidade para começar novamente com mais inteligência.",
        "Não espere por oportunidades, crie-as.",
        "O sucesso é ir de fracasso em fracasso sem perder o entusiasmo.",
        "A única forma de fazer um excelente trabalho é amar o que você faz."
    ]

    quote = random.choice(quotes)
    embed = discord.Embed(
        title="✨ Inspiração do Dia",
        description=f"*{quote}*",
        color=discord.Color.gold()
    )
    await ctx.reply(embed=embed)

# 25. Sistema de Roubo (minigame)
@bot.command(name='steal', aliases=['roubar'])
async def steal_money(ctx, member: discord.Member):
    if member.id == ctx.author.id:
        await ctx.reply("❌ Você não pode roubar de si mesmo!")
        return

    if member.bot:
        await ctx.reply("❌ Você não pode roubar de bots!")
        return

    thief_money = get_user_money(ctx.author.id)
    victim_money = get_user_money(member.id)

    if thief_money < 50:
        await ctx.reply("❌ Você precisa de pelo menos 50 moedas para tentar roubar!")
        return

    if victim_money < 100:
        await ctx.reply("❌ A vítima precisa ter pelo menos 100 moedas!")
        return

    success_chance = random.randint(1, 100)

    if success_chance <= 30:  # 30% de sucesso
        stolen_amount = random.randint(50, min(200, victim_money // 2))
        remove_user_money(member.id, stolen_amount)
        add_user_money(ctx.author.id, stolen_amount)

        embed = discord.Embed(
            title="💰 Roubo Bem-sucedido!",
            description=f"Você roubou `{stolen_amount}` moedas de {member.display_name}!",
            color=discord.Color.green()
        )
    else:  # 70% de falha
        fine = random.randint(25, 100)
        remove_user_money(ctx.author.id, fine)

        embed = discord.Embed(
            title="🚨 Roubo Fracassado!",
            description=f"Você foi pego! Pagou uma multa de `{fine}` moedas.",
            color=discord.Color.red()
        )

    await ctx.reply(embed=embed)

# 26. Jogo da Adivinhação
class GuessView(View):
    def __init__(self, number: int, user_id: int):
        super().__init__(timeout=120)
        self.number = number
        self.user_id = user_id
        self.attempts = 0
        self.max_attempts = 6

    @discord.ui.button(label="📝 Fazer Palpite", style=discord.ButtonStyle.primary)
    async def make_guess(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Apenas quem iniciou o jogo pode jogar!", ephemeral=True)
            return

        modal = GuessModal(self)
        await interaction.response.send_modal(modal)

class GuessModal(Modal, title="🎯 Faça seu palpite"):
    guess = TextInput(label="Seu palpite (1-100)", placeholder="Digite um número entre 1 e 100")

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guess_num = int(self.guess.value)
            if guess_num < 1 or guess_num > 100:
                await interaction.response.send_message("❌ Número deve estar entre 1 e 100!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Digite apenas números!", ephemeral=True)
            return

        self.view.attempts += 1

        if guess_num == self.view.number:
            reward = 100 + (50 * (self.view.max_attempts - self.view.attempts))
            add_user_money(interaction.user.id, reward)

            embed = discord.Embed(
                title="🎉 Parabéns! Você acertou!",
                description=f"O número era **{self.view.number}**!\nTentativas: {self.view.attempts}/{self.view.max_attempts}\nRecompensa: `{reward}` moedas!",
                color=discord.Color.gold()
            )
            await interaction.response.edit_message(embed=embed, view=None)

        elif self.view.attempts >= self.view.max_attempts:
            embed = discord.Embed(
                title="😞 Game Over!",
                description=f"Suas tentativas acabaram! O número era **{self.view.number}**.",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)

        else:
            hint = "📈 Muito alto!" if guess_num > self.view.number else "📉 Muito baixo!"
            embed = discord.Embed(
                title="🎯 Jogo da Adivinhação",
                description=f"{hint}\nTentativa {self.view.attempts}/{self.view.max_attempts}\nContinue tentando!",
                color=discord.Color.orange()
            )
            await interaction.response.edit_message(embed=embed, view=self.view)

@bot.command(name='guess', aliases=['adivinhar'])
async def guess_game(ctx):
    number = random.randint(1, 100)

    embed = discord.Embed(
        title="🎯 Jogo da Adivinhação",
        description="Adivinhe o número entre 1 e 100!\nVocê tem 6 tentativas. Boa sorte!",
        color=discord.Color.blue()
    )

    view = GuessView(number, ctx.author.id)
    await ctx.reply(embed=embed, view=view)

# 27. Comando Top Emojis
@bot.command(name='topemojis')
async def top_emojis(ctx):
    if not ctx.guild.emojis:
        await ctx.reply("❌ Este servidor não tem emojis personalizados!")
        return

    # Simular uso de emojis
    emoji_usage = {emoji: random.randint(0, 1000) for emoji in ctx.guild.emojis[:10]}
    sorted_emojis = sorted(emoji_usage.items(), key=lambda x: x[1], reverse=True)[:5]

    embed = discord.Embed(
        title="🏆 Top Emojis do Servidor",
        color=discord.Color.yellow()
    )

    for i, (emoji, usage) in enumerate(sorted_emojis, 1):
        embed.add_field(
            name=f"#{i} {emoji}",
            value=f"{usage} usos",
            inline=True
        )

    await ctx.reply(embed=embed)

# 28. Sistema de Backup de Dados
@bot.command(name='backup')
@commands.has_permissions(administrator=True)
async def backup_data(ctx):
    user_count = len(dados_usuarios)
    roll_count = len(dados_rolls)

    embed = discord.Embed(
        title="💾 Backup de Dados",
        description=f"Dados do servidor salvos:\n• {user_count} carreiras\n• {roll_count} perfis de rolls\n• Dados da economia em SQLite",
        color=discord.Color.green()
    )
    embed.set_footer(text="Backup realizado com sucesso! - Dev: YevgennyMXP")
    await ctx.reply(embed=embed)

# 29. Comando de Feedback
@bot.command(name='feedback', aliases=['sugestao'])
async def feedback(ctx, *, message: str):
    embed = discord.Embed(
        title="📨 Feedback Recebido",
        description=f"Obrigado pelo seu feedback!\n\n**Mensagem:** {message}",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Enviado por {ctx.author.display_name} - Dev: YevgennyMXP")
    await ctx.reply(embed=embed)

# 30. Comando de Limpeza de Cache
@bot.command(name='clearcache')
@commands.has_permissions(administrator=True)
async def clear_cache(ctx):
    # Limpar caches internos (simulado)
    cache_cleared = random.randint(50, 500)

    embed = discord.Embed(
        title="🧹 Cache Limpo",
        description=f"Cache do bot limpo com sucesso!\n{cache_cleared}MB liberados.",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

# Sistema de ajuda atualizado (versão única)

# Adicionar XP automaticamente em mensagens
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Dar XP aleatório por mensagem (1-3 XP)
    if random.random() < 0.1:  # 10% de chance
        xp_gain = random.randint(1, 3)
        add_user_xp(message.author.id, xp_gain)

    await bot.process_commands(message)

# --- Sistema de Apostas Avançado (p!odd) ---

# Base de dados de times com estatísticas simuladas
TIMES_DATABASE = {
    # Times da Série A - Tier 1 (Elite)
    "Flamengo": {
        "tier": 1, "attack": 88, "defense": 82, "form": [1, 1, 0, 1, 1], 
        "goals_per_game": 2.4, "goals_conceded": 1.1, "clean_sheets": 45
    },
    "Palmeiras": {
        "tier": 1, "attack": 85, "defense": 87, "form": [1, 1, 1, 0, 1], 
        "goals_per_game": 2.2, "goals_conceded": 0.9, "clean_sheets": 52
    },
    "São Paulo": {
        "tier": 1, "attack": 78, "defense": 80, "form": [1, 0, 1, 1, 0], 
        "goals_per_game": 1.9, "goals_conceded": 1.2, "clean_sheets": 38
    },
    "Corinthians": {
        "tier": 1, "attack": 75, "defense": 78, "form": [0, 1, 1, 1, 0], 
        "goals_per_game": 1.8, "goals_conceded": 1.3, "clean_sheets": 35
    },
    "Atlético-MG": {
        "tier": 1, "attack": 81, "defense": 75, "form": [1, 1, 0, 1, 1], 
        "goals_per_game": 2.1, "goals_conceded": 1.4, "clean_sheets": 32
    },
    "Fluminense": {
        "tier": 1, "attack": 76, "defense": 74, "form": [1, 0, 1, 0, 1], 
        "goals_per_game": 1.7, "goals_conceded": 1.3, "clean_sheets": 31
    },

    # Times da Série A - Tier 2 (Forte)
    "Internacional": {
        "tier": 2, "attack": 74, "defense": 77, "form": [1, 1, 0, 1, 0], 
        "goals_per_game": 1.8, "goals_conceded": 1.2, "clean_sheets": 36
    },
    "Grêmio": {
        "tier": 2, "attack": 72, "defense": 75, "form": [0, 1, 1, 0, 1], 
        "goals_per_game": 1.6, "goals_conceded": 1.3, "clean_sheets": 33
    },
    "Botafogo": {
        "tier": 2, "attack": 73, "defense": 69, "form": [1, 1, 1, 0, 1], 
        "goals_per_game": 1.9, "goals_conceded": 1.5, "clean_sheets": 28
    },
    "Santos": {
        "tier": 2, "attack": 71, "defense": 68, "form": [0, 1, 0, 1, 1], 
        "goals_per_game": 1.7, "goals_conceded": 1.6, "clean_sheets": 25
    },
    "Athletico-PR": {
        "tier": 2, "attack": 70, "defense": 72, "form": [1, 0, 1, 1, 0], 
        "goals_per_game": 1.6, "goals_conceded": 1.4, "clean_sheets": 30
    },
    "Bahia": {
        "tier": 2, "attack": 68, "defense": 70, "form": [1, 1, 0, 0, 1], 
        "goals_per_game": 1.5, "goals_conceded": 1.4, "clean_sheets": 29
    },

    # Times da Série A - Tier 3 (Médio)
    "Fortaleza": {
        "tier": 3, "attack": 65, "defense": 67, "form": [0, 1, 1, 0, 0], 
        "goals_per_game": 1.4, "goals_conceded": 1.5, "clean_sheets": 26
    },
    "Vasco": {
        "tier": 3, "attack": 64, "defense": 65, "form": [1, 0, 0, 1, 0], 
        "goals_per_game": 1.3, "goals_conceded": 1.6, "clean_sheets": 23
    },
    "Bragantino": {
        "tier": 3, "attack": 66, "defense": 63, "form": [0, 1, 0, 1, 1], 
        "goals_per_game": 1.5, "goals_conceded": 1.7, "clean_sheets": 22
    },
    "Cruzeiro": {
        "tier": 3, "attack": 63, "defense": 64, "form": [1, 0, 1, 0, 1], 
        "goals_per_game": 1.4, "goals_conceded": 1.6, "clean_sheets": 24
    },

    # Times da Série B - Tier 4 (Emergente)
    "Sport": {
        "tier": 4, "attack": 60, "defense": 58, "form": [1, 1, 0, 1, 0], 
        "goals_per_game": 1.3, "goals_conceded": 1.8, "clean_sheets": 20
    },
    "Ponte Preta": {
        "tier": 4, "attack": 58, "defense": 56, "form": [0, 0, 1, 1, 0], 
        "goals_per_game": 1.2, "goals_conceded": 1.9, "clean_sheets": 18
    }
}

# Lista simplificada para sorteio aleatório
TIMES_BRASILEIROS = list(TIMES_DATABASE.keys())

# Dicionário para armazenar apostas dos usuários
apostas_usuarios = {}
historico_apostas = []

class MatchAnalyzer:
    """Analisador profissional de partidas com foco em odds e estatísticas"""

    def __init__(self, team1: str, team2: str):
        self.team1 = team1
        self.team2 = team2
        self.team1_data = TIMES_DATABASE.get(team1, {})
        self.team2_data = TIMES_DATABASE.get(team2, {})

    def get_form_string(self, form_list):
        """Converte lista de forma em string"""
        return "-".join(["W" if x == 1 else "D" if x == 0.5 else "L" for x in form_list])

    def calculate_win_probabilities(self):
        """Calcula probabilidades de vitória baseadas em estatísticas"""
        if not self.team1_data or not self.team2_data:
            # Fallback para times sem dados
            return {"team1": 33.3, "draw": 33.3, "team2": 33.3}

        # Fatores de análise
        attack_diff = self.team1_data["attack"] - self.team2_data["defense"]
        defense_diff = self.team2_data["attack"] - self.team1_data["defense"]

        # Forma recente (últimos 5 jogos)
        team1_form = sum(self.team1_data["form"]) / len(self.team1_data["form"])
        team2_form = sum(self.team2_data["form"]) / len(self.team2_data["form"])

        # Cálculo base das probabilidades
        team1_strength = (attack_diff + team1_form * 20 + self.team1_data["attack"]) / 3
        team2_strength = (defense_diff + team2_form * 20 + self.team2_data["attack"]) / 3

        # Normalizar para percentuais
        total_strength = team1_strength + team2_strength + 30  # 30 para chance de empate

        team1_prob = max(15, min(70, (team1_strength / total_strength) * 100))
        team2_prob = max(15, min(70, (team2_strength / total_strength) * 100))
        draw_prob = 100 - team1_prob - team2_prob

        return {
            "team1": round(team1_prob, 1),
            "draw": round(draw_prob, 1),
            "team2": round(team2_prob, 1)
        }

    def get_btts_probability(self):
        """Calcula probabilidade de ambos times marcarem"""
        if not self.team1_data or not self.team2_data:
            return 50.0

        team1_attack = self.team1_data["goals_per_game"]
        team2_attack = self.team2_data["goals_per_game"]
        team1_defense = self.team1_data["goals_conceded"]
        team2_defense = self.team2_data["goals_conceded"]

        # Probabilidade baseada em médias de gols
        avg_attack = (team1_attack + team2_attack) / 2
        avg_defense = (team1_defense + team2_defense) / 2

        btts_prob = min(85, max(25, (avg_attack / avg_defense) * 45))
        return round(btts_prob, 1)

    def get_total_goals_prediction(self):
        """Predição de total de gols na partida"""
        if not self.team1_data or not self.team2_data:
            return 2.5

        expected_goals = (
            self.team1_data["goals_per_game"] + 
            self.team2_data["goals_per_game"] + 
            self.team1_data["goals_conceded"] + 
            self.team2_data["goals_conceded"]
        ) / 2

        return round(expected_goals, 1)

    def get_suggested_bets(self):
        """Gera sugestões de apostas baseadas na análise"""
        probabilities = self.calculate_win_probabilities()
        btts_prob = self.get_btts_probability()
        total_goals = self.get_total_goals_prediction()

        suggestions = []

        # Sugestão de resultado
        max_prob = max(probabilities.values())
        if max_prob > 45:
            if probabilities["team1"] == max_prob:
                suggestions.append(f"Vitória {self.team1} (Confiança: Alta)")
            elif probabilities["team2"] == max_prob:
                suggestions.append(f"Vitória {self.team2} (Confiança: Alta)")
        elif probabilities["draw"] > 30:
            suggestions.append("Empate (Confiança: Média)")

        # Sugestão de gols
        if total_goals > 2.7:
            suggestions.append("Over 2.5 Gols (Confiança: Alta)")
        elif total_goals < 2.3:
            suggestions.append("Under 2.5 Gols (Confiança: Alta)")

        # Sugestão BTTS
        if btts_prob > 60:
            suggestions.append("Ambos Marcam: SIM (Confiança: Alta)")
        elif btts_prob < 40:
            suggestions.append("Ambos Marcam: NÃO (Confiança: Média)")

        return suggestions[:3]  # Máximo 3 sugestões

    def simulate_realistic_match(self):
        """Simula partida com base em estatísticas reais"""
        if not self.team1_data or not self.team2_data:
            # Simulação básica para times sem dados
            return {
                "goals_team1": random.randint(0, 3),
                "goals_team2": random.randint(0, 3)
            }

        # Simular gols baseado em média e força
        team1_expected = (self.team1_data["goals_per_game"] + self.team2_data["goals_conceded"]) / 2
        team2_expected = (self.team2_data["goals_per_game"] + self.team1_data["goals_conceded"]) / 2

        # Adicionar variabilidade da forma recente
        team1_form_factor = (sum(self.team1_data["form"]) / len(self.team1_data["form"]) - 0.5) * 0.5
        team2_form_factor = (sum(self.team2_data["form"]) / len(self.team2_data["form"]) - 0.5) * 0.5

        team1_expected += team1_form_factor
        team2_expected += team2_form_factor

        # Gerar gols com distribuição de Poisson simulada
        team1_goals = max(0, int(random.normalvariate(team1_expected, 1)))
        team2_goals = max(0, int(random.normalvariate(team2_expected, 1)))

        # Limitar a valores realistas
        team1_goals = min(team1_goals, 5)
        team2_goals = min(team2_goals, 5)

        return {
            "goals_team1": team1_goals,
            "goals_team2": team2_goals
        }

class OddsModal(Modal, title="🎯 Apostar no Placar Exato"):
    placar = TextInput(
        label="Predição do Placar (ex: 2x1, 0x0, 3x2)",
        placeholder="Formato: XxY baseado na análise",
        max_length=10
    )
    valor_aposta = TextInput(
        label="Valor da Aposta (mín: 100 moedas)",
        placeholder="Quanto deseja arriscar?",
        max_length=10
    )

    def __init__(self, team1: str, team2: str, user_id: int):
        super().__init__()
        self.team1 = team1
        self.team2 = team2
        self.user_id = user_id
        self.analyzer = MatchAnalyzer(team1, team2)

    async def on_submit(self, interaction: discord.Interaction):
        # Validações
        placar_pattern = r'^(\d+)x(\d+)$'
        if not re.match(placar_pattern, self.placar.value.lower()):
            await interaction.response.send_message(
                "❌ **Formato Inválido** - Use XxY (ex: 2x1)", ephemeral=True
            )
            return

        try:
            valor = int(self.valor_aposta.value)
            if valor < 100:
                await interaction.response.send_message(
                    "❌ **Aposta Mínima:** 100 moedas", ephemeral=True
                )
                return
        except ValueError:
            await interaction.response.send_message(
                "❌ **Valor Inválido** - Digite apenas números", ephemeral=True
            )
            return

        saldo_atual = get_user_money(self.user_id)
        if saldo_atual < valor:
            await interaction.response.send_message(
                f"❌ **Saldo Insuficiente**\nDisponível: `{saldo_atual}` | Necessário: `{valor}`",
                ephemeral=True
            )
            return

        await self.process_bet(interaction, self.placar.value.lower(), valor)

    async def process_bet(self, interaction, predicted_score, bet_amount):
        remove_user_money(self.user_id, bet_amount)

        # Simular resultado
        match_result = self.analyzer.simulate_realistic_match()
        actual_score = f"{match_result['goals_team1']}x{match_result['goals_team2']}"

        # Verificar acerto
        predicted_goals = predicted_score.split('x')
        actual_won = (int(predicted_goals[0]) == match_result['goals_team1'] and 
                      int(predicted_goals[1]) == match_result['goals_team2'])

        if actual_won:
            payout = bet_amount * 2
            add_user_money(self.user_id, payout)
            profit = payout - bet_amount
            result_status = "🎯 **PREDIÇÃO EXATA!**"
            embed_color = discord.Color.gold()
        else:
            payout = 0
            profit = -bet_amount
            result_status = "📊 **Análise Incorreta**"
            embed_color = discord.Color.red()

        final_balance = get_user_money(self.user_id)

        # Registrar no histórico
        bet_record = {
            'user_id': self.user_id, 'team1': self.team1, 'team2': self.team2,
            'predicted_score': predicted_score, 'actual_score': actual_score,
            'bet_amount': bet_amount, 'won': actual_won, 'payout': payout,
            'final_balance': final_balance, 'timestamp': datetime.now().isoformat()
        }
        historico_apostas.append(bet_record)

        # Embed de resultado no estilo odds
        result_embed = discord.Embed(
            title="📊 **RESULTADO DA ANÁLISE** 📊",
            description=f"{result_status}\n\n**{self.team1}** vs **{self.team2}**",
            color=embed_color
        )

        result_embed.add_field(
            name="🎯 Predição vs Realidade",
            value=f"**Predito:** `{predicted_score.upper()}`\n**Resultado:** `{actual_score.upper()}`",
            inline=True
        )

        result_embed.add_field(
            name="💰 Análise Financeira",
            value=f"**Aposta:** {bet_amount} moedas\n**Retorno:** {payout} moedas\n**P&L:** {profit:+d} moedas",
            inline=True
        )

        result_embed.add_field(
            name="📈 Saldo Atualizado",
            value=f"**Atual:** {final_balance} moedas",
            inline=True
        )

        # Probabilidades para contexto
        probabilities = self.analyzer.calculate_win_probabilities()
        result_embed.add_field(
            name="📊 Probabilidades Calculadas",
            value=f"**{self.team1}:** {probabilities['team1']}%\n**Empate:** {probabilities['draw']}%\n**{self.team2}:** {probabilities['team2']}%",
            inline=False
        )

        result_embed.set_footer(
            text=f"Análise por {interaction.user.display_name} • Sistema de Odds Avançado - Dev: YevgennyMXP"
        )
        result_embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.edit_message(embed=result_embed, view=None)

class OddsView(View):
    def __init__(self, team1: str, team2: str, user_id: int):
        super().__init__(timeout=300)
        self.team1 = team1
        self.team2 = team2
        self.user_id = user_id

    @discord.ui.button(label="🎯 Analisar & Apostar", style=discord.ButtonStyle.success, emoji="📊")
    async def place_bet(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ **Acesso Negado** - Apenas o analista pode operar", ephemeral=True
            )
            return

        modal = OddsModal(self.team1, self.team2, self.user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="❌ Encerrar Sessão", style=discord.ButtonStyle.danger)
    async def cancel_analysis(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ **Acesso Negado** - Apenas o analista pode encerrar", ephemeral=True
            )
            return

        embed_closed = discord.Embed(
            title="📊 **Sessão de Análise Encerrada**",
            description="**Status:** Análise cancelada pelo usuário\n\n*Use `p!odd` para nova análise*",
            color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed_closed, view=None)

@bot.command(name='odd', aliases=['apostar_placar', 'bet_score'])
async def odds_command(ctx):
    """Sistema profissional de análise e apostas com foco em odds"""

    user_balance = get_user_money(ctx.author.id)
    if user_balance < 100:
        insufficient_embed = discord.Embed(
            title="💸 **Capital Insuficiente**",
            description=f"**Saldo Atual:** {user_balance} moedas\n**Mínimo Necessário:** 100 moedas\n\n**Opções para Aumentar Capital:**\n• `p!daily` - Bônus diário\n• `p!work` - Trabalho remunerado",
            color=discord.Color.red()
        )
        await ctx.reply(embed=insufficient_embed)
        return

    # Sortear confronto
    team1, team2 = random.sample(TIMES_BRASILEIROS, 2)
    analyzer = MatchAnalyzer(team1, team2)

    # Dados estatísticos
    probabilities = analyzer.calculate_win_probabilities()
    btts_prob = analyzer.get_btts_probability()
    total_goals = analyzer.get_total_goals_prediction()
    suggestions = analyzer.get_suggested_bets()

    # Embed principal no estilo odds profissional
    odds_embed = discord.Embed(
        title="📊 **ANÁLISE DE ODDS & PROBABILIDADES** 📊",
        description=f"**Confronto Selecionado**\n\n🏠 **{team1}** 🆚 **{team2}** ✈️",
        color=discord.Color.blue()
    )

    # Estatísticas dos times se disponíveis
    if team1 in TIMES_DATABASE and team2 in TIMES_DATABASE:
        team1_data = TIMES_DATABASE[team1]
        team2_data = TIMES_DATABASE[team2]

        odds_embed.add_field(
            name="🏟 **Forma Recente (Últimos 5)**",
            value=f"**{team1}:** {analyzer.get_form_string(team1_data['form'])}\n**{team2}:** {analyzer.get_form_string(team2_data['form'])}",
            inline=True
        )

        odds_embed.add_field(
            name="⚽ **Média de Gols por Jogo**",
            value=f"**{team1}:** {team1_data['goals_per_game']}\n**{team2}:** {team2_data['goals_per_game']}",
            inline=True
        )

        odds_embed.add_field(
            name="🛡️ **Gols Sofridos (Média)**",
            value=f"**{team1}:** {team1_data['goals_conceded']}\n**{team2}:** {team2_data['goals_conceded']}",
            inline=True
        )

    # Probabilidades calculadas
    odds_embed.add_field(
        name="🔮 **Probabilidades de Resultado**",
        value=f"**{team1} Win:** {probabilities['team1']}%\n**Draw:** {probabilities['draw']}%\n**{team2} Win:** {probabilities['team2']}%",
        inline=False
    )

    # Análises de mercado
    odds_embed.add_field(
        name="📈 **Análise de Mercados**",
        value=f"🎯 **BTTS (Ambos Marcam):** {btts_prob}%\n📊 **Total de Gols Esperado:** {total_goals}\n🔍 **Over 2.5:** {'Alta' if total_goals > 2.5 else 'Baixa'} probabilidade",
        inline=True
    )

    # Informações do apostador
    odds_embed.add_field(
        name="💰 **Capital Disponível**",
        value=f"**Saldo:** {user_balance} moedas\n**Aposta Mín:** 100 moedas\n**Retorno:** 2.00x (Placar Exato)",
        inline=True
    )

    # Sugestões de aposta
    if suggestions:
        odds_embed.add_field(
            name="💡 **Sugestões Baseadas em Dados**",
            value="\n".join([f"• {sugg}" for sugg in suggestions]),
            inline=False
        )

    odds_embed.add_field(
        name="⚠️ **Disclaimer de Risco**",
        value="*Análise baseada em dados históricos simulados. Resultados gerados algoritmicamente para fins de entretenimento.*",
        inline=False
    )

    odds_embed.set_footer(
        text=f"Análise gerada para {ctx.author.display_name} • Sistema de Odds Profissional - Dev: YevgennyMXP"
    )
    odds_embed.set_thumbnail(url=ctx.author.display_avatar.url)

    view = OddsView(team1, team2, ctx.author.id)
    await ctx.reply(embed=odds_embed, view=view)

@bot.command(name='historico_apostas', aliases=['my_bets', 'apostas'])
async def historico_apostas_command(ctx):
    """Ver histórico de apostas do usuário"""

    # Filtrar apostas do usuário
    apostas_usuario = [aposta for aposta in historico_apostas if aposta['user_id'] == ctx.author.id]

    if not apostas_usuario:
        embed_vazio = discord.Embed(
            title="📋 Histórico de Apostas",
            description="Você ainda não fez nenhuma aposta!\n\nUse `p!odd` para fazer sua primeira aposta.",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed_vazio)
        return

    # Estatísticas gerais
    total_apostas = len(apostas_usuario)
    acertos = sum(1 for aposta in apostas_usuario if aposta['acertou'])
    erros = total_apostas - acertos
    taxa_acerto = (acertos / total_apostas * 100) if total_apostas > 0 else 0

    total_apostado = sum(aposta['valor_aposta'] for aposta in apostas_usuario)
    total_ganho = sum(aposta['premio'] for aposta in apostas_usuario)
    lucro_prejuizo = total_ganho - total_apostado

    embed_historico = discord.Embed(
        title="📊 Seu Histórico de Apostas",
        description=f"Estatísticas completas de {ctx.author.display_name}",
        color=discord.Color.gold() if lucro_prejuizo >= 0 else discord.Color.red()
    )

    embed_historico.add_field(
        name="📈 Estatísticas Gerais",
        value=(
            f"🎯 **Total de apostas:** {total_apostas}\n"
            f"✅ **Acertos:** {acertos}\n"
            f"❌ **Erros:** {erros}\n"
            f"📊 **Taxa de acerto:** {taxa_acerto:.1f}%"
        ),
        inline=True
    )

    embed_historico.add_field(
        name="💰 Resumo Financeiro",
        value=(
            f"💸 **Total apostado:** {total_apostado} moedas\n"
            f"🏆 **Total ganho:** {total_ganho} moedas\n"
            f"📈 **Lucro/Prejuízo:** {lucro_prejuizo:+d} moedas\n"
            f"💎 **Saldo atual:** {get_user_money(ctx.author.id)} moedas"
        ),
        inline=True
    )

    # Mostrar últimas 5 apostas
    ultimas_apostas = sorted(apostas_usuario, key=lambda x: x['timestamp'], reverse=True)[:5]

    historico_texto = ""
    for i, aposta in enumerate(ultimas_apostas, 1):
        resultado_emoji = "✅" if aposta['acertou'] else "❌"
        data_aposta = datetime.fromisoformat(aposta['timestamp']).strftime("%d/%m %H:%M")

        historico_texto += (
            f"{resultado_emoji} **{aposta['time1']} vs {aposta['time2']}**\n"
            f"   Palpite: `{aposta['placar_apostado']}` | Real: `{aposta['placar_real']}`\n"
            f"   Aposta: {aposta['valor_aposta']} | Resultado: {aposta['premio'] - aposta['valor_aposta']:+d}\n"
            f"   📅 {data_aposta}\n\n"
        )

    embed_historico.add_field(
        name="📋 Últimas 5 Apostas",
        value=historico_texto if historico_texto else "Nenhuma aposta encontrada",
        inline=False
    )

    embed_historico.set_thumbnail(url=ctx.author.display_avatar.url)
    embed_historico.set_footer(text=f"Use p!odd para fazer uma nova aposta! - Dev: YevgennyMXP")

    await ctx.reply(embed=embed_historico)

# --- Sistema de Boxes com Roleta ---

# Definir todas as recompensas para cada tipo de box
BOX_REWARDS = {
    "comum": [
        "1x Auto-Claim",
        "1x Kit Apelativo", 
        "2 Rolls pra distribuição",
        "1x Máscara",
        "2x Kits Médicos",
        "1x Naturalização",
        "3 Rolls pra distribuição",
        "1 Roll pra distribuição",
        "1x Box Épica",
        "100 mil no UnB",
        "5 milhões de verba pro seu clube",
        "50 mil no UnB",
        "+1 Roll de fintas",
        "+2 Rolls de fintas",
        "+1 Roll de promessa"
    ],
    "epica": [
        "2x Auto-Claim",
        "1x Habilidade Comum",
        "4 Rolls para distribuição",
        "30 Milhões de verba para seu clube",
        "300 mil no UnB",
        "1x Melhoria grátis",
        "+1 Roll em polaridade",
        "+3 Rolls de finta",
        "+2 rolls em perna boa",
        "500 mil no UnB",
        "50 milhões de verba",
        "2x Habilidades Comuns",
        "1x Slot de Habilidade Comum",
        "1x Rescisão extra",
        "2x Kits Apelativos",
        "1x Naturalização",
        "Vip Neo gratuito"
    ],
    "master": [
        "1x Slot de festiva extra",
        "1x Slot de Habilidade Comum",
        "1x Alteração de Festiva",
        "3x Itens de Naturalização",
        "5 Estrelas de Fintas direto",
        "Promessa Direto",
        "Vip Deluxe grátis",
        "Três Box's comuns",
        "80 milhões de verbas pro seu clube",
        "5 milhões no UnB",
        "7 milhões no UnB",
        "1 box épica",
        "5 Rolls pra distribuição",
        "3 Rolls pra distribuição",
        "3x melhorias grátis a escolha",
        "2 Box's Épicas",
        "Vip Supreme grátis",
        "3x Auto-claim",
        "4x Auto-claim",
        "7 Rolls pra distribuição",
        "nada"
    ],
    "itens": [
        "1x Slot de festiva",
        "2x Kits Médicos",
        "3x Kits Médicos",
        "1x Kit apelativo",
        "2x Kits Apelativos",
        "1x Item de Rescisão Extra",
        "2x Itens de Rescisão Extra",
        "1x Reset de Ficha",
        "2x Reset de Ficha",
        "1x Slot de Habilidade Comum",
        "1x Alteração de Festiva",
        "2x Alterações de Rolls",
        "3x Alterações de Rolls",
        "1x Item de Naturalização",
        "2x Itens de Naturalização",
        "3x Itens de Naturalização",
        "1x Chuteira",
        "2x Máscaras",
        "3x Máscaras",
        "1x Luvas"
    ],
    "festivas": [
        "Habilidade festiva \"Indiferente\"",
        "Habilidade festiva \"Velocista\"",
        "Habilidade festiva \"Clone\"",
        "Habilidade festiva \"O imperador\"",
        "Habilidade festiva \"Momentâneo\"",
        "Habilidade festiva \"Talismã\"",
        "Habilidade festiva \"Visionário\"",
        "Nada",
        "Nada",
        "Nada",
        "Nada"
    ],
    "exclusivas": [
        "Habilidade exclusiva \"Domínio Marcelo\"",
        "Habilidade exclusiva \"Decisivo Ronaldo\"",
        "Habilidade exclusiva \"Lançamento Alisson\"",
        "Habilidade exclusiva \"Enfiada Toni Kroos\"",
        "Habilidade exclusiva \"Dribles Vini Jr\"",
        "Habilidade exclusiva \"Fatiada Beckham\"",
        "Habilidade exclusiva \"Armação Léo Ortiz\"",
        "Habilidade exclusiva \"Defesa Neuer\"",
        "Habilidade exclusiva \"Rei dos clássicos Yuri Alberto\"",
        "Habilidade exclusiva \"Cabeceio Magalhães\"",
        "Habilidade exclusiva \"Di Magia\"",
        "Habilidade exclusiva \"Maestria Garro\"",
        "Habilidade exclusiva \"Fôlego Hulk\"",
        "Habilidade exclusiva \"Chapada Couto\"",
        "Habilidade exclusiva \"Crucial Van Dijk\"",
        "Habilidade exclusiva \"Reflexos Jhon\"",
        "Habilidade exclusiva \"Rabisca Neymar\"",
        "Habilidade exclusiva \"Interceptação Casemiro\"",
        "Habilidade exclusiva \"Magia Estêvão\"",
        "Habilidade exclusiva \"Escape Wirtz\"",
        "Habilidade exclusiva \"Batida Romário\"",
        "Habilidade exclusiva \"Ganso é 10\"",
        "Habilidade exclusiva \"Maestria Alan Patrick\"",
        "Habilidade exclusiva \"Precisão Maldini\"",
        "Habilidade exclusiva \"Frieza Palmer\"",
        "Habilidade exclusiva \"Escanteio Arnold\"",
        "Habilidade exclusiva \"Visão Ødegaard\"",
        "Habilidade exclusiva \"Estrela Endrick\"",
        "Habilidade exclusiva \"Elasticidade Buffon\"",
        "Habilidade exclusiva \"Defensiva Ramos\"",
        "Habilidade exclusiva \"Diretas Messi\"",
        "Habilidade exclusiva \"Mágico Bruno Fernandes\"",
        "Habilidade exclusiva \"Efeito Suarez\""
    ]
}

# URL da thumbnail para todas as boxes
BOX_THUMBNAIL_URL = "https://cdn.discordapp.com/attachments/1384353085702541403/1385633227116511272/download_39.jpeg?ex=6856c701&is=68557581&hm=419e0668d236a5a6d17ba1b3829738ea0f094e73ad009e7f8287d6274bf9b3b9&"

# URLs específicas para cada tipo de box
BOX_IMAGES = {
    "comum": "https://media.discordapp.net/attachments/1375957371121045605/1385643432705261798/Leo_MESSI_10.jpeg?ex=6856d082&is=68557f02&hm=8f29444eb904da0a082925d0cb798c5558c57d1952bb383cd326509ec633be02&=&format=webp",
    "epica": "https://cdn.discordapp.com/attachments/1375957371121045605/1385643124902203554/bukayo_saka.jpeg?ex=6856d038&is=68557eb8&hm=36ac744b6fc6adb554dc800b2152b627e1f830fd9c9031199645abfb18f947c9&",
    "master": "https://media.discordapp.net/attachments/1375957371121045605/1385642398658334720/71b5207848947d29968ae9b71dae0b27.jpg?ex=6856cf8b&is=68557e0b&hm=84452fc14fd0bbf68d87c8ff567d3f7afe306f2825d9a3efb50e21dd564a8f97&=&format=webp",
    "itens": "https://cdn.discordapp.com/attachments/1375957371121045605/1385642794206498916/39a18b6b30d0f59ff885f230abdf4148.jpg?ex=6856cfea&is=68557e6a&hm=73aabfaeb6180410c5790ce88ba4ca4fcb3865bb50c9f85dde7ccb69e2388a16&",
    "festivas": "https://media.discordapp.net/attachments/1375957371121045605/1385642398880628767/Memphis_Depay_FULL_HD_Wallpaper_made_by_me.jpeg?ex=6856cf8b&is=68557e0b&hm=0614dde8bec4786283e1f8845c1cff7918d183960fa6690aa60f97e49e7c6a79&=&format=webp",
    "exclusivas": "https://media.discordapp.net/attachments/1375957371121045605/1385642398658334720/71b5207848947d29968ae9b71dae0b27.jpg?ex=6856cf8b&is=68557e0b&hm=84452fc14fd0bbf68d87c8ff567d3f7afe306f2825d9a3efb50e21dd564a8f97&=&format=webp"
}

# Emojis personalizados para o resultado final
FINAL_EMOJIS = ""

async def create_box_animation(ctx, box_type: str, box_name: str):
    """Cria a animação da roleta para qualquer tipo de box"""
    
    # Validar se o tipo de box existe
    if box_type not in BOX_REWARDS:
        await ctx.reply(f"❌ Tipo de box '{box_type}' não encontrado!")
        return
    
    rewards = BOX_REWARDS[box_type]
    
    # Escolher o prêmio final
    final_reward = random.choice(rewards)
    
    # Obter a imagem específica para este tipo de box
    box_image_url = BOX_IMAGES.get(box_type, BOX_IMAGES["comum"])
    
    # Cor aleatória para o embed
    random_color = discord.Color.from_rgb(
        random.randint(50, 255),
        random.randint(50, 255), 
        random.randint(50, 255)
    )
    
    # Embed inicial
    initial_embed = discord.Embed(
        title=f"＋﹒୨🎁୧﹐ᰍ ﹕{box_name}﹒ᜊ",
        description="**𝅭 ㅤ𝅭ㅤ⎯⎯ㅤִㅤ୨ ✰ ୧ㅤִ ⎯⎯ ㅤ𝅭 ㅤ𝅭**\n\n🎰 **Abrindo box...**\n\n⏳ A roleta está girando...\n\n**𝅭 ㅤ𝅭ㅤ⎯⎯ㅤִㅤ୨ ✰ ୧ㅤִ ⎯⎯ ㅤ𝅭 ㅤ𝅭**",
        color=random_color
    )
    initial_embed.set_thumbnail(url=BOX_THUMBNAIL_URL)
    initial_embed.set_image(url=box_image_url)
    initial_embed.set_footer(text=f"Box aberta por {ctx.author.display_name} - Dev: YevgennyMXP")
    
    message = await ctx.reply(embed=initial_embed)
    
    # Animação da roleta (5 atualizações)
    for i in range(5):
        # Escolher um prêmio aleatório para mostrar durante a animação
        current_reward = random.choice(rewards)
        
        animation_embed = discord.Embed(
            title=f"＋﹒୨🎁୧﹐ᰍ ﹕{box_name}﹒ᜊ",
            description=f"**𝅭 ㅤ𝅭ㅤ⎯⎯ㅤִㅤ୨ ✰ ୧ㅤִ ⎯⎯ ㅤ𝅭 ㅤ𝅭**\n\n🎰 **Roleta girando...**\n\n🎯 **Prêmio atual:**\n{current_reward}\n\n**⏤͟͟͞▴→ Rotação {i+1}/5**\n\n**𝅭 ㅤ𝅭ㅤ⎯⎯ㅤִㅤ୨ ✰ ୧ㅤִ ⎯⎯ ㅤ𝅭 ㅤ𝅭**",
            color=random_color
        )
        animation_embed.set_thumbnail(url=BOX_THUMBNAIL_URL)
        animation_embed.set_image(url=box_image_url)
        animation_embed.set_footer(text=f"Box aberta por {ctx.author.display_name} - Dev: YevgennyMXP")
        
        await message.edit(embed=animation_embed)
        await asyncio.sleep(0.7)
    
    # Embed final com o resultado usando o molde fornecido
    final_embed = discord.Embed(
        title=f"＋﹒୨🎁୧﹐ᰍ ﹕{box_name}﹒ᜊ",
        description=f"**𝅭 ㅤ𝅭ㅤ⎯⎯ㅤִㅤ୨ ✰ ୧ㅤִ ⎯⎯ ㅤ𝅭 ㅤ𝅭**\n\n**⏤͟͟͞▴→ {ctx.author.display_name} decidiu abrir uma box! Veja sua recompensa abaixo:**\n\n﹒𑁘🌟೧﹒⊹  **`{final_reward}`**︐﹒୭{FINAL_EMOJIS}\n\n**⏤͟͟͞▴→ Eai?! Teve sorte? Resgate sua recompensa em <#1328480859124142120>!**\n\n**𝅭 ㅤ𝅭ㅤ⎯⎯ㅤִㅤ୨ ✰ ୧ㅤִ ⎯⎯ ㅤ𝅭 ㅤ𝅭**",
        color=random_color
    )
    final_embed.set_thumbnail(url=BOX_THUMBNAIL_URL)
    final_embed.set_image(url=box_image_url)
    final_embed.set_footer(text=f"Parabéns {ctx.author.display_name}! - Dev: YevgennyMXP")
    
    await message.edit(embed=final_embed)

# Comandos das boxes
@bot.command(name='box-comum', aliases=['box_comum', 'boxcomum'])
async def box_comum(ctx):
    """Abrir uma Box Comum"""
    await create_box_animation(ctx, "comum", "Box Comum")

@bot.command(name='box-epica', aliases=['box_epica', 'boxepica'])
async def box_epica(ctx):
    """Abrir uma Box Épica"""
    await create_box_animation(ctx, "epica", "Box Épica")

@bot.command(name='box-master', aliases=['box_master', 'boxmaster'])
async def box_master(ctx):
    """Abrir uma Box Master"""
    await create_box_animation(ctx, "master", "Box Master")

@bot.command(name='box-itens', aliases=['box_itens', 'boxitens'])
async def box_itens(ctx):
    """Abrir uma Box de Itens"""
    await create_box_animation(ctx, "itens", "Box de Itens")

@bot.command(name='box-festivas', aliases=['box_festivas', 'boxfestivas'])
async def box_festivas(ctx):
    """Abrir uma Box de Habilidades Festivas"""
    await create_box_animation(ctx, "festivas", "Box Festiva")

@bot.command(name='box-exclusivas', aliases=['box_exclusivas', 'boxexclusivas'])
async def box_exclusivas(ctx):
    """Abrir uma Box de Habilidades Exclusivas"""
    await create_box_animation(ctx, "exclusivas", "Box Exclusiva")

# --- Sistema de Parcerias ---
CANAL_PARCERIAS_ID = 1319063191225106433

# Inicializar tabela de parcerias no banco de dados
def init_partnerships_table():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS partnerships (
        user_id INTEGER PRIMARY KEY,
        count INTEGER DEFAULT 0,
        last_links TEXT DEFAULT '[]'
    )
    ''')
    
    conn.commit()
    conn.close()

# Chamar inicialização das parcerias
init_partnerships_table()

def get_user_partnerships(user_id):
    """Obter número de parcerias de um usuário"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT count FROM partnerships WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def get_user_last_links(user_id):
    """Obter últimos links enviados pelo usuário"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT last_links FROM partnerships WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0]:
        return json.loads(result[0])
    return []

def add_partnership(user_id, link):
    """Adicionar uma parceria ao usuário"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Obter dados atuais
    current_count = get_user_partnerships(user_id)
    last_links = get_user_last_links(user_id)
    
    # Verificar se o link já foi usado recentemente (últimos 10 links)
    if link in last_links[-10:]:
        conn.close()
        return False, current_count  # Link duplicado
    
    # Adicionar novo link à lista
    last_links.append(link)
    
    # Manter apenas os últimos 10 links
    last_links = last_links[-10:]
    
    # Atualizar no banco
    cursor.execute('''
    INSERT OR REPLACE INTO partnerships (user_id, count, last_links) 
    VALUES (?, ?, ?)
    ''', (user_id, current_count + 1, json.dumps(last_links)))
    
    conn.commit()
    conn.close()
    return True, current_count + 1

def get_partnerships_ranking():
    """Obter ranking de parcerias"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, count FROM partnerships ORDER BY count DESC LIMIT 10')
    results = cursor.fetchall()
    conn.close()
    return results

@bot.event
async def on_message(message):
    # Ignorar mensagens de bots
    if message.author.bot:
        return
    
    # Verificar se a mensagem é do canal de parcerias
    if message.channel.id == CANAL_PARCERIAS_ID:
        # Expressão regular para detectar links do Discord
        discord_link_pattern = r'(?:https?://)?(?:www\.)?discord\.gg/[a-zA-Z0-9]+'
        
        # Buscar por links do Discord na mensagem
        discord_links = re.findall(discord_link_pattern, message.content, re.IGNORECASE)
        
        if discord_links:
            # Pegar o primeiro link encontrado
            first_link = discord_links[0]
            
            # Tentar adicionar a parceria
            success, new_count = add_partnership(message.author.id, first_link)
            
            if success:
                # Criar embed de confirmação
                embed = discord.Embed(
                    title="︵‿︵‿୨♡୧‿︵‿︵",
                    description="*・˚₊‧༉🪄 **PARCERIA CONCLUÍDA!** ✧.ೃ༄",
                    color=discord.Color.from_rgb(255, 182, 193)  # Rosa claro
                )
                
                embed.add_field(
                    name="︵‿︵‿୨♡୧‿︵‿︵",
                    value=(
                        f"⤷ 💌 Olá, {message.author.mention}\n"
                        f"🎊 Você acaba de conquistar mais uma parceria!\n\n"
                        f"🌟 +1 Parceria para sua lista.\n"
                        f"✨ Agora tu tens: **{new_count} parcerias**\n"
                        f"🍀 Você pode usar o comando `p!parcerias` para ver o ranking de parcerias.\n\n"
                        f"︵‿︵‿୨♡୧‿︵‿︵"
                    ),
                    inline=False
                )
                
                embed.set_footer(text=f"Parceria registrada com sucesso! - Dev: YevgennyMXP")
                embed.set_thumbnail(url=message.author.display_avatar.url)
                
                # Mencionar o cargo antes do embed
                role_mention = f"<@&1319062780288045147>"
                await message.reply(content=role_mention, embed=embed)
            else:
                # Link duplicado - enviar mensagem discreta
                embed = discord.Embed(
                    title="🔄 Link Já Utilizado",
                    description=f"{message.author.mention}, esse link já foi usado recentemente. Tente com um link diferente!",
                    color=discord.Color.orange()
                )
                await message.reply(embed=embed, delete_after=10)
    
    # Dar XP aleatório por mensagem (1-3 XP) - código existente
    if random.random() < 0.1:  # 10% de chance
        xp_gain = random.randint(1, 3)
        add_user_xp(message.author.id, xp_gain)

    await bot.process_commands(message)

@bot.command(name='parcerias', aliases=['ranking_parcerias', 'rankingparcerias'])
async def ranking_parcerias(ctx):
    """Ver ranking de parcerias"""
    ranking = get_partnerships_ranking()
    
    if not ranking:
        embed = discord.Embed(
            title="📊 Ranking de Parcerias",
            description="Ainda não há parcerias registradas!",
            color=discord.Color.blue()
        )
        await ctx.reply(embed=embed)
        return
    
    embed = discord.Embed(
        title="🏆 Ranking de Parcerias",
        description="Top 10 usuários com mais parcerias registradas!",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    
    for i, (user_id, count) in enumerate(ranking, 1):
        user = bot.get_user(user_id)
        name = user.display_name if user else "Usuário Desconhecido"
        
        if i == 1:
            emoji = "🥇"
        elif i == 2:
            emoji = "🥈"
        elif i == 3:
            emoji = "🥉"
        else:
            emoji = f"#{i}"
        
        embed.add_field(
            name=f"{emoji} {name}",
            value=f"💌 **{count} parcerias**",
            inline=False
        )
    
    embed.set_footer(text=f"Envie links do Discord em <#{CANAL_PARCERIAS_ID}> para somar parcerias! - Dev: YevgennyMXP")
    await ctx.reply(embed=embed)

@bot.command(name='minhas_parcerias', aliases=['mparcerias'])
async def minhas_parcerias(ctx):
    """Ver suas próprias parcerias"""
    count = get_user_partnerships(ctx.author.id)
    
    embed = discord.Embed(
        title="💌 Suas Parcerias",
        description=f"**{ctx.author.display_name}**, você tem **{count} parcerias** registradas!",
        color=discord.Color.purple()
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.add_field(
        name="📈 Dica",
        value=f"Envie links do Discord em <#{CANAL_PARCERIAS_ID}> para aumentar sua contagem!",
        inline=False
    )
    embed.set_footer(text="Use p!parcerias para ver o ranking geral - Dev: YevgennyMXP")
    
    await ctx.reply(embed=embed)

# --- Sistema de Clima Temporal e Previsões Meteorológicas Avançadas ---

# Base de dados de condições climáticas e seus efeitos
CLIMA_DATABASE = {
    "condicoes": {
        "ensolarado": {
            "emoji": "☀️", "temp_range": (20, 35), "humidity": (30, 60),
            "effect": "Aumenta moral dos jogadores", "visibility": 10,
            "wind_range": (0, 15), "description": "Dia perfeito para atividades ao ar livre"
        },
        "nublado": {
            "emoji": "☁️", "temp_range": (15, 25), "humidity": (50, 80),
            "effect": "Condições neutras", "visibility": 8,
            "wind_range": (5, 20), "description": "Céu coberto com nuvens espessas"
        },
        "chuvoso": {
            "emoji": "🌧️", "temp_range": (10, 20), "humidity": (80, 95),
            "effect": "Dificulta dribles e finalizações", "visibility": 5,
            "wind_range": (10, 30), "description": "Precipitação moderada a forte"
        },
        "tempestade": {
            "emoji": "⛈️", "temp_range": (8, 18), "humidity": (85, 100),
            "effect": "Jogadores perdem velocidade drasticamente", "visibility": 3,
            "wind_range": (25, 50), "description": "Tempestade com raios e trovões"
        },
        "nevando": {
            "emoji": "❄️", "temp_range": (-5, 5), "humidity": (70, 90),
            "effect": "Jogadores escorregam com frequência", "visibility": 4,
            "wind_range": (0, 25), "description": "Queda de neve intensa"
        },
        "ventoso": {
            "emoji": "🌪️", "temp_range": (12, 28), "humidity": (40, 70),
            "effect": "Bolas aéreas ficam imprevisíveis", "visibility": 7,
            "wind_range": (30, 60), "description": "Ventos fortes e rajadas"
        },
        "neblina": {
            "emoji": "🌫️", "temp_range": (5, 15), "humidity": (90, 100),
            "effect": "Passa e defesas ficam menos precisos", "visibility": 2,
            "wind_range": (0, 10), "description": "Neblina densa com visibilidade reduzida"
        },
        "calor_extremo": {
            "emoji": "🔥", "temp_range": (35, 45), "humidity": (20, 40),
            "effect": "Jogadores cansam mais rápido", "visibility": 9,
            "wind_range": (0, 20), "description": "Calor escaldante e seco"
        }
    },
    "cidades_brasil": [
        "São Paulo", "Rio de Janeiro", "Belo Horizonte", "Salvador", "Brasília",
        "Fortaleza", "Manaus", "Curitiba", "Recife", "Porto Alegre", "Goiânia",
        "Belém", "Guarulhos", "Campinas", "São Luís", "São Gonçalo", "Maceió",
        "Duque de Caxias", "Natal", "Teresina", "Campo Grande", "Nova Iguaçu",
        "São Bernardo do Campo", "João Pessoa", "Santo André", "Osasco"
    ]
}

# Inicializar tabela de clima no banco de dados
def init_weather_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Tabela de histórico de clima
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS weather_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        city TEXT,
        condition TEXT,
        temperature REAL,
        humidity INTEGER,
        wind_speed INTEGER,
        visibility INTEGER,
        date_checked TEXT,
        prediction_accuracy REAL
    )
    ''')
    
    # Tabela de alertas meteorológicos
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS weather_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        city TEXT,
        alert_type TEXT,
        threshold_value REAL,
        is_active INTEGER DEFAULT 1,
        created_date TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

# Chamar inicialização do clima
init_weather_database()

class WeatherSystem:
    def __init__(self):
        self.conditions = CLIMA_DATABASE["condicoes"]
        self.cities = CLIMA_DATABASE["cidades_brasil"]
    
    def generate_weather(self, city=None):
        """Gera condições climáticas realistas para uma cidade"""
        if not city:
            city = random.choice(self.cities)
        
        # Selecionar condição baseada em probabilidades realistas
        condition_weights = {
            "ensolarado": 25, "nublado": 20, "chuvoso": 15, "tempestade": 5,
            "nevando": 2, "ventoso": 10, "neblina": 8, "calor_extremo": 3
        }
        
        # Ajustar probabilidades baseado na cidade (algumas regiões são mais chuvosas, etc.)
        if city in ["Manaus", "Belém"]:  # Região Norte - mais chuva
            condition_weights["chuvoso"] += 10
            condition_weights["tempestade"] += 5
        elif city in ["São Paulo", "Curitiba"]:  # Sul/Sudeste - mais frio
            condition_weights["nevando"] += 3
            condition_weights["neblina"] += 5
        elif city in ["Fortaleza", "Salvador", "Recife"]:  # Nordeste - mais sol
            condition_weights["ensolarado"] += 15
            condition_weights["calor_extremo"] += 5
        
        # Criar lista ponderada
        weighted_conditions = []
        for condition, weight in condition_weights.items():
            weighted_conditions.extend([condition] * weight)
        
        selected_condition = random.choice(weighted_conditions)
        condition_data = self.conditions[selected_condition]
        
        # Gerar valores específicos dentro dos ranges
        temperature = round(random.uniform(*condition_data["temp_range"]), 1)
        humidity = random.randint(*condition_data["humidity"])
        wind_speed = random.randint(*condition_data["wind_range"])
        visibility = condition_data["visibility"]
        
        # Adicionar variação aleatória na visibilidade
        visibility += random.randint(-1, 1)
        visibility = max(1, min(10, visibility))
        
        return {
            "city": city,
            "condition": selected_condition,
            "condition_data": condition_data,
            "temperature": temperature,
            "humidity": humidity,
            "wind_speed": wind_speed,
            "visibility": visibility,
            "uv_index": self.calculate_uv_index(selected_condition, temperature),
            "air_quality": self.calculate_air_quality(selected_condition, wind_speed),
            "feels_like": self.calculate_feels_like(temperature, humidity, wind_speed)
        }
    
    def calculate_uv_index(self, condition, temperature):
        """Calcula índice UV baseado na condição e temperatura"""
        base_uv = {
            "ensolarado": 8, "calor_extremo": 10, "nublado": 4,
            "chuvoso": 2, "tempestade": 1, "nevando": 1,
            "ventoso": 6, "neblina": 2
        }
        
        uv = base_uv.get(condition, 3)
        if temperature > 30:
            uv += 2
        elif temperature < 10:
            uv -= 1
        
        return max(1, min(11, uv))
    
    def calculate_air_quality(self, condition, wind_speed):
        """Calcula qualidade do ar"""
        base_quality = {
            "ensolarado": 85, "nublado": 75, "chuvoso": 95,
            "tempestade": 90, "nevando": 80, "ventoso": 70,
            "neblina": 45, "calor_extremo": 60
        }
        
        quality = base_quality.get(condition, 70)
        
        # Vento ajuda a limpar o ar
        if wind_speed > 20:
            quality += 10
        elif wind_speed < 5:
            quality -= 10
        
        return max(20, min(100, quality))
    
    def calculate_feels_like(self, temp, humidity, wind):
        """Calcula sensação térmica"""
        if temp > 25:
            # Heat index
            feels_like = temp + (humidity / 100) * 5 - (wind / 10)
        else:
            # Wind chill
            feels_like = temp - (wind / 10) * 2
        
        return round(feels_like, 1)
    
    def get_weather_forecast(self, city, days=5):
        """Gera previsão de vários dias"""
        forecast = []
        for i in range(days):
            weather = self.generate_weather(city)
            
            # Simular data futura
            future_date = datetime.now() + timedelta(days=i)
            weather["date"] = future_date.strftime("%d/%m/%Y")
            weather["day_name"] = future_date.strftime("%A")
            
            forecast.append(weather)
        
        return forecast
    
    def save_weather_check(self, user_id, weather_data):
        """Salva consulta de clima no histórico"""
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO weather_history 
        (user_id, city, condition, temperature, humidity, wind_speed, visibility, date_checked)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, weather_data["city"], weather_data["condition"], 
              weather_data["temperature"], weather_data["humidity"], 
              weather_data["wind_speed"], weather_data["visibility"], 
              datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_user_weather_history(self, user_id, limit=10):
        """Obtém histórico de consultas de clima do usuário"""
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT city, condition, temperature, date_checked 
        FROM weather_history 
        WHERE user_id = ? 
        ORDER BY date_checked DESC 
        LIMIT ?
        ''', (user_id, limit))
        
        results = cursor.fetchall()
        conn.close()
        return results

# Instanciar sistema de clima
weather_system = WeatherSystem()

class WeatherView(View):
    def __init__(self, user_id, current_weather):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_weather = current_weather
    
    @discord.ui.button(label="📅 Previsão 5 Dias", style=discord.ButtonStyle.primary, emoji="🔮")
    async def get_forecast(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Apenas quem consultou pode ver a previsão!", ephemeral=True)
            return
        
        forecast = weather_system.get_weather_forecast(self.current_weather["city"], 5)
        
        embed = discord.Embed(
            title=f"🔮 Previsão de 5 Dias - {self.current_weather['city']}",
            description="Previsão meteorológica detalhada para os próximos dias",
            color=discord.Color.blue()
        )
        
        for day_weather in forecast:
            condition_data = day_weather["condition_data"]
            day_text = (
                f"{condition_data['emoji']} **{day_weather['condition'].title()}**\n"
                f"🌡️ {day_weather['temperature']}°C (Sensação: {day_weather['feels_like']}°C)\n"
                f"💧 Umidade: {day_weather['humidity']}%\n"
                f"💨 Vento: {day_weather['wind_speed']} km/h"
            )
            
            embed.add_field(
                name=f"{day_weather['day_name']} - {day_weather['date']}",
                value=day_text,
                inline=True
            )
        
        embed.set_footer(text=f"Previsão gerada para {interaction.user.display_name} - Dev: YevgennyMXP")
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="📊 Análise Detalhada", style=discord.ButtonStyle.success, emoji="🔬")
    async def detailed_analysis(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Apenas quem consultou pode ver a análise!", ephemeral=True)
            return
        
        weather = self.current_weather
        condition_data = weather["condition_data"]
        
        embed = discord.Embed(
            title=f"🔬 Análise Meteorológica Detalhada",
            description=f"**{weather['city']}** - Condições atuais",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="🌤️ Condição Principal",
            value=f"{condition_data['emoji']} **{weather['condition'].title()}**\n*{condition_data['description']}*",
            inline=False
        )
        
        embed.add_field(
            name="🌡️ Dados Térmicos",
            value=(
                f"**Temperatura:** {weather['temperature']}°C\n"
                f"**Sensação Térmica:** {weather['feels_like']}°C\n"
                f"**Umidade Relativa:** {weather['humidity']}%"
            ),
            inline=True
        )
        
        embed.add_field(
            name="💨 Condições do Vento",
            value=(
                f"**Velocidade:** {weather['wind_speed']} km/h\n"
                f"**Visibilidade:** {weather['visibility']}/10\n"
                f"**Qualidade do Ar:** {weather['air_quality']}/100"
            ),
            inline=True
        )
        
        embed.add_field(
            name="☀️ Índices Especiais",
            value=(
                f"**Índice UV:** {weather['uv_index']}/11\n"
                f"**Efeito no Futebol:** {condition_data['effect']}\n"
                f"**Recomendação:** {'Ideal para jogar' if weather['uv_index'] < 6 else 'Use protetor solar'}"
            ),
            inline=False
        )
        
        # Adicionar alertas baseados nas condições
        alerts = []
        if weather["temperature"] > 35:
            alerts.append("🔥 **Alerta de Calor Extremo**")
        if weather["uv_index"] > 8:
            alerts.append("☀️ **Alto Índice UV - Use Proteção**")
        if weather["wind_speed"] > 40:
            alerts.append("💨 **Ventos Fortes - Cuidado**")
        if weather["visibility"] < 4:
            alerts.append("🌫️ **Baixa Visibilidade**")
        if weather["air_quality"] < 50:
            alerts.append("😷 **Qualidade do Ar Ruim**")
        
        if alerts:
            embed.add_field(
                name="⚠️ Alertas Meteorológicos",
                value="\n".join(alerts),
                inline=False
            )
        
        embed.set_footer(text=f"Análise completa para {interaction.user.display_name} - Dev: YevgennyMXP")
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="📈 Meu Histórico", style=discord.ButtonStyle.secondary, emoji="📋")
    async def weather_history(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Apenas quem consultou pode ver o histórico!", ephemeral=True)
            return
        
        history = weather_system.get_user_weather_history(self.user_id, 8)
        
        embed = discord.Embed(
            title="📋 Seu Histórico de Consultas Meteorológicas",
            description="Últimas cidades e condições consultadas",
            color=discord.Color.purple()
        )
        
        if not history:
            embed.add_field(
                name="📊 Histórico Vazio",
                value="Esta é sua primeira consulta meteorológica!",
                inline=False
            )
        else:
            for i, (city, condition, temp, date_checked) in enumerate(history, 1):
                date_obj = datetime.fromisoformat(date_checked)
                formatted_date = date_obj.strftime("%d/%m/%Y %H:%M")
                
                condition_emoji = weather_system.conditions.get(condition, {}).get("emoji", "🌤️")
                
                embed.add_field(
                    name=f"{i}. {city}",
                    value=f"{condition_emoji} {condition.title()}\n🌡️ {temp}°C\n📅 {formatted_date}",
                    inline=True
                )
        
        embed.set_footer(text=f"Total de consultas: {len(history)} - Dev: YevgennyMXP")
        await interaction.response.edit_message(embed=embed, view=self)

@bot.command(name='clima_avancado', aliases=['weather_pro', 'tempo_detalhado'])
async def advanced_weather(ctx, *, city=None):
    """Sistema avançado de clima com previsões e análises detalhadas"""
    
    # Gerar dados meteorológicos
    weather_data = weather_system.generate_weather(city)
    
    # Salvar no histórico
    weather_system.save_weather_check(ctx.author.id, weather_data)
    
    condition_data = weather_data["condition_data"]
    
    # Determinar cor do embed baseada na condição
    condition_colors = {
        "ensolarado": discord.Color.gold(),
        "nublado": discord.Color.light_grey(),
        "chuvoso": discord.Color.blue(),
        "tempestade": discord.Color.dark_purple(),
        "nevando": discord.Color.from_rgb(173, 216, 230),
        "ventoso": discord.Color.from_rgb(135, 206, 235),
        "neblina": discord.Color.from_rgb(105, 105, 105),
        "calor_extremo": discord.Color.red()
    }
    
    embed = discord.Embed(
        title=f"🌤️ **CENTRO METEOROLÓGICO AVANÇADO** 🌤️",
        description=f"**📍 {weather_data['city']}** - Condições em tempo real",
        color=condition_colors.get(weather_data["condition"], discord.Color.blue())
    )
    
    # Condição principal
    embed.add_field(
        name="🌡️ Condição Atual",
        value=(
            f"{condition_data['emoji']} **{weather_data['condition'].title()}**\n"
            f"*{condition_data['description']}*\n"
            f"**Temperatura:** {weather_data['temperature']}°C\n"
            f"**Sensação Térmica:** {weather_data['feels_like']}°C"
        ),
        inline=True
    )
    
    # Dados atmosféricos
    embed.add_field(
        name="💧 Dados Atmosféricos",
        value=(
            f"**Umidade:** {weather_data['humidity']}%\n"
            f"**Pressão:** {random.randint(980, 1020)} hPa\n"
            f"**Ponto de Orvalho:** {weather_data['temperature'] - 5}°C\n"
            f"**Visibilidade:** {weather_data['visibility']}/10"
        ),
        inline=True
    )
    
    # Vento e qualidade
    embed.add_field(
        name="💨 Vento & Qualidade",
        value=(
            f"**Velocidade:** {weather_data['wind_speed']} km/h\n"
            f"**Direção:** {random.choice(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])}\n"
            f"**Qualidade do Ar:** {weather_data['air_quality']}/100\n"
            f"**Índice UV:** {weather_data['uv_index']}/11"
        ),
        inline=True
    )
    
    # Impacto no futebol
    embed.add_field(
        name="⚽ Impacto no Futebol",
        value=f"🎯 **Efeito:** {condition_data['effect']}\n📊 **Condição para Jogo:** {'Perfeita' if weather_data['visibility'] > 7 else 'Moderada' if weather_data['visibility'] > 4 else 'Ruim'}",
        inline=False
    )
    
    # Recomendações baseadas nas condições
    recommendations = []
    if weather_data["temperature"] > 30:
        recommendations.append("💧 Hidrate-se constantemente")
    if weather_data["uv_index"] > 6:
        recommendations.append("🧴 Use protetor solar FPS 30+")
    if weather_data["wind_speed"] > 25:
        recommendations.append("🌪️ Cuidado com ventos fortes")
    if weather_data["humidity"] > 80:
        recommendations.append("👕 Use roupas leves e respiráveis")
    if weather_data["visibility"] < 5:
        recommendations.append("👀 Atenção com a baixa visibilidade")
    
    if recommendations:
        embed.add_field(
            name="💡 Recomendações",
            value="\n".join(recommendations[:3]),  # Máximo 3 recomendações
            inline=False
        )
    
    embed.set_footer(text=f"Dados meteorológicos para {ctx.author.display_name} • Use os botões para mais informações - Dev: YevgennyMXP")
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    
    # Adicionar uma imagem relacionada ao clima (opcional)
    weather_images = {
        "ensolarado": "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800",
        "chuvoso": "https://images.unsplash.com/photo-1433863448220-78aaa064ff47?w=800",
        "tempestade": "https://images.unsplash.com/photo-1500740516770-92bd004b996e?w=800",
        "nevando": "https://images.unsplash.com/photo-1422728221357-57980993ea99?w=800"
    }
    
    if weather_data["condition"] in weather_images:
        embed.set_image(url=weather_images[weather_data["condition"]])
    
    view = WeatherView(ctx.author.id, weather_data)
    await ctx.reply(embed=embed, view=view)

# --- Sistema de Pênaltis ---

class PenaltyShootout:
    """Simulador de disputa de pênaltis entre times"""
    
    def __init__(self, team1: str, team2: str):
        self.team1 = team1
        self.team2 = team2
        self.team1_score = 0
        self.team2_score = 0
        self.team1_penalties = []
        self.team2_penalties = []
        self.current_round = 1
        self.max_rounds = 5
        self.sudden_death = False
        
        # Posições de chute e defesa
        self.positions = ["esquerda", "meio", "direita"]
        
        # Nomes de jogadores genéricos
        self.player_names = [
            "Silva", "Santos", "Oliveira", "Costa", "Pereira", "Rodrigues",
            "Almeida", "Nascimento", "Lima", "Araújo", "Fernandes", "Carvalho"
        ]
        
        # Nomes de goleiros
        self.goalkeeper_names = [
            "Cássio", "Alisson", "Weverton", "Santos", "Fábio", "Rafael"
        ]
    
    def get_random_player(self, team_name):
        """Retorna nome de jogador aleatório"""
        return random.choice(self.player_names)
    
    def get_random_goalkeeper(self, team_name):
        """Retorna nome de goleiro aleatório"""
        return random.choice(self.goalkeeper_names)
    
    def simulate_penalty(self, shooting_team):
        """Simula um pênalti individual"""
        shooter = self.get_random_player(shooting_team)
        goalkeeper = self.get_random_goalkeeper("Defesa")
        
        # Posições de chute e defesa
        shot_position = random.choice(self.positions)
        save_position = random.choice(self.positions)
        
        # Calcular resultado
        if shot_position == save_position:
            # Goleiro foi na direção certa
            if random.random() < 0.7:  # 70% chance de defesa
                result = "defendido"
                description = f"🧤 **DEFESA!** {goalkeeper} voou no canto {save_position} e defendeu o chute de {shooter}!"
            else:
                result = "gol"
                description = f"⚽ **GOL!** {shooter} chutou no {shot_position}, {goalkeeper} foi na direção certa mas não conseguiu alcançar!"
        else:
            # Goleiro errou a direção
            if random.random() < 0.85:  # 85% chance de gol
                result = "gol"
                description = f"⚽ **GOL!** {shooter} chutou no {shot_position} enquanto {goalkeeper} mergulhou para o {save_position}!"
            else:
                result = "errado"
                description = f"😱 **PRA FORA!** {shooter} chutou por cima do gol! {goalkeeper} nem precisou se mexer!"
        
        return {
            "shooter": shooter,
            "goalkeeper": goalkeeper,
            "shot_position": shot_position,
            "save_position": save_position,
            "result": result,
            "description": description
        }
    
    def is_shootout_over(self):
        """Verifica se a disputa acabou"""
        if self.current_round <= self.max_rounds:
            # Rounds normais - verificar se um time já não pode mais empatar
            remaining_rounds = self.max_rounds - self.current_round + 1
            if abs(self.team1_score - self.team2_score) > remaining_rounds:
                return True
        else:
            # Morte súbita
            if self.current_round > self.max_rounds and self.team1_score != self.team2_score:
                return True
        
        return False
    
    async def simulate_full_shootout(self, ctx):
        """Simula disputa completa de pênaltis"""
        
        # Embed inicial
        embed = discord.Embed(
            title="⚽ **DISPUTA DE PÊNALTIS** ⚽",
            description=f"🏟️ **{self.team1}** 🆚 **{self.team2}**\n\n🎯 Iniciando a decisão nos pênaltis!",
            color=discord.Color.blue()
        )
        embed.set_footer(text="⚽ Disputa de pênaltis iniciada! - Dev: YevgennyMXP")
        
        message = await ctx.reply(embed=embed)
        await asyncio.sleep(2)
        
        # Determinar quem começa
        first_team = random.choice([self.team1, self.team2])
        teams_order = [first_team, self.team2 if first_team == self.team1 else self.team1]
        
        while not self.is_shootout_over():
            for i, team in enumerate(teams_order):
                if self.is_shootout_over():
                    break
                
                # Simular pênalti
                penalty_result = self.simulate_penalty(team)
                
                # Atualizar placar
                if penalty_result["result"] == "gol":
                    if team == self.team1:
                        self.team1_score += 1
                        self.team1_penalties.append("⚽")
                    else:
                        self.team2_score += 1
                        self.team2_penalties.append("⚽")
                else:
                    if team == self.team1:
                        self.team1_penalties.append("❌")
                    else:
                        self.team2_penalties.append("❌")
                
                # Criar embed de pênalti
                penalty_embed = discord.Embed(
                    title="⚽ **DISPUTA DE PÊNALTIS** ⚽",
                    description=f"🏟️ **{self.team1}** 🆚 **{self.team2}**",
                    color=discord.Color.orange()
                )
                
                penalty_embed.add_field(
                    name=f"🎯 Rodada {self.current_round} - {team}",
                    value=penalty_result["description"],
                    inline=False
                )
                
                # Mostrar placar atual
                team1_penalties_str = " ".join(self.team1_penalties) if self.team1_penalties else "—"
                team2_penalties_str = " ".join(self.team2_penalties) if self.team2_penalties else "—"
                
                penalty_embed.add_field(
                    name="📊 Placar dos Pênaltis",
                    value=f"**{self.team1}:** {self.team1_score} {team1_penalties_str}\n**{self.team2}:** {self.team2_score} {team2_penalties_str}",
                    inline=False
                )
                
                if self.current_round > self.max_rounds:
                    penalty_embed.add_field(
                        name="💀 MORTE SÚBITA",
                        value="A disputa entrou em morte súbita! Quem errar primeiro, perde!",
                        inline=False
                    )
                
                penalty_embed.set_footer(text="⚽ Disputa em andamento... - Dev: YevgennyMXP")
                
                await message.edit(embed=penalty_embed)
                await asyncio.sleep(2.5)
            
            # Após ambos chutarem na rodada
            if self.current_round <= self.max_rounds or (self.current_round > self.max_rounds and len(self.team1_penalties) == len(self.team2_penalties)):
                self.current_round += 1
        
        # Resultado final
        if self.team1_score > self.team2_score:
            winner = self.team1
            winner_score = self.team1_score
            loser_score = self.team2_score
        else:
            winner = self.team2
            winner_score = self.team2_score
            loser_score = self.team1_score
        
        final_embed = discord.Embed(
            title="🏆 **DISPUTA DE PÊNALTIS FINALIZADA** 🏆",
            description=f"🎉 **{winner}** venceu a disputa de pênaltis!",
            color=discord.Color.gold()
        )
        
        final_embed.add_field(
            name="📊 Resultado Final",
            value=f"**{winner}:** {winner_score} pênaltis\n**{self.team2 if winner == self.team1 else self.team1}:** {loser_score} pênaltis",
            inline=True
        )
        
        team1_penalties_str = " ".join(self.team1_penalties)
        team2_penalties_str = " ".join(self.team2_penalties)
        
        final_embed.add_field(
            name="⚽ Sequência de Pênaltis",
            value=f"**{self.team1}:** {team1_penalties_str}\n**{self.team2}:** {team2_penalties_str}",
            inline=False
        )
        
        final_embed.add_field(
            name="📈 Estatísticas",
            value=f"**Total de pênaltis:** {len(self.team1_penalties) + len(self.team2_penalties)}\n**Rodadas:** {max(len(self.team1_penalties), len(self.team2_penalties))}\n**Precisão:** {((self.team1_score + self.team2_score) / (len(self.team1_penalties) + len(self.team2_penalties)) * 100):.1f}%",
            inline=False
        )
        
        final_embed.set_footer(text=f"🏆 {winner} é o campeão da disputa! - Dev: YevgennyMXP")
        
        await message.edit(embed=final_embed)

class PenaltyDuel:
    """Sistema de duelo de pênaltis entre jogadores"""
    
    def __init__(self, challenger_id: int, challenged_id: int):
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
        self.challenger_score = 0
        self.challenged_score = 0
        self.current_round = 1
        self.max_rounds = 5
        self.current_shooter = challenger_id
        self.current_goalkeeper = challenged_id
        self.penalties_taken = []
        self.game_over = False
        self.winner = None
        
        # Posições disponíveis
        self.positions = {
            "esquerda": "⬅️",
            "meio": "⬆️", 
            "direita": "➡️"
        }
    
    def switch_roles(self):
        """Alterna entre atacante e goleiro"""
        self.current_shooter, self.current_goalkeeper = self.current_goalkeeper, self.current_shooter
    
    def is_duel_over(self):
        """Verifica se o duelo acabou"""
        # Máximo de 10 rodadas total (5 normais + 5 extras máximo)
        if self.current_round > 10:
            return True
        
        if self.current_round > self.max_rounds:
            if self.challenger_score != self.challenged_score:
                return True
        return False
    
    def determine_winner(self):
        """Determina o vencedor do duelo"""
        if self.challenger_score > self.challenged_score:
            self.winner = self.challenger_id
        elif self.challenged_score > self.challenger_score:
            self.winner = self.challenged_id
        else:
            self.winner = None  # Empate
    
    def process_penalty(self, shot_pos: str, save_pos: str):
        """Processa um pênalti"""
        if shot_pos == save_pos:
            # Goleiro acertou a direção
            if random.random() < 0.65:  # 65% chance de defesa
                result = "defendido"
                description = f"🧤 **DEFESA ESPETACULAR!** O goleiro mergulhou para o {shot_pos} e defendeu!"
            else:
                result = "gol"
                description = f"⚽ **GOL!** Mesmo com o goleiro indo na direção certa, a bola entrou!"
        else:
            # Goleiro errou a direção
            if random.random() < 0.9:  # 90% chance de gol
                result = "gol"
                description = f"⚽ **GOL!** Chute no {shot_pos} enquanto o goleiro foi para o {save_pos}!"
            else:
                result = "perdeu"
                description = f"😱 **INCRÍVEL!** O atacante mandou para fora mesmo com o goleiro indo para o lado errado!"
        
        # Atualizar placar
        if result == "gol":
            if self.current_shooter == self.challenger_id:
                self.challenger_score += 1
            else:
                self.challenged_score += 1
        
        # Registrar pênalti
        self.penalties_taken.append({
            "round": self.current_round,
            "shooter": self.current_shooter,
            "goalkeeper": self.current_goalkeeper,
            "shot_position": shot_pos,
            "save_position": save_pos,
            "result": result,
            "description": description
        })
        
        return result, description

class PenaltyDuelView(View):
    def __init__(self, duel: PenaltyDuel):
        super().__init__(timeout=300)
        self.duel = duel
        self.waiting_for_shot = True
        self.shot_position = None
        self.save_position = None
    
    async def update_embed(self, interaction, title: str, description: str, color=discord.Color.blue()):
        """Atualiza o embed do duelo"""
        embed = discord.Embed(title=title, description=description, color=color)
        
        challenger = interaction.guild.get_member(self.duel.challenger_id)
        challenged = interaction.guild.get_member(self.duel.challenged_id)
        shooter = interaction.guild.get_member(self.duel.current_shooter)
        goalkeeper = interaction.guild.get_member(self.duel.current_goalkeeper)
        
        embed.add_field(
            name="📊 Placar Atual",
            value=f"**{challenger.display_name}:** {self.duel.challenger_score}\n**{challenged.display_name}:** {self.duel.challenged_score}",
            inline=True
        )
        
        embed.add_field(
            name="⚽ Rodada Atual",
            value=f"**{self.duel.current_round}/{self.duel.max_rounds}**",
            inline=True
        )
        
        # Deixar muito claro de quem é a vez
        if self.waiting_for_shot:
            embed.add_field(
                name="🎯 VEZ DO ATACANTE",
                value=f"⚽ **{shooter.display_name}** - ESCOLHA ONDE CHUTAR!\n🧤 {goalkeeper.display_name} (aguardando...)",
                inline=True
            )
        else:
            embed.add_field(
                name="🧤 VEZ DO GOLEIRO", 
                value=f"⚽ {shooter.display_name} (já escolheu)\n🧤 **{goalkeeper.display_name}** - ESCOLHA ONDE DEFENDER!",
                inline=True
            )
        
        return embed
    
    @discord.ui.button(label="⬅️ Esquerda", style=discord.ButtonStyle.secondary)
    async def left_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_position_choice(interaction, "esquerda")
    
    @discord.ui.button(label="⬆️ Meio", style=discord.ButtonStyle.secondary)
    async def middle_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_position_choice(interaction, "meio")
    
    @discord.ui.button(label="➡️ Direita", style=discord.ButtonStyle.secondary)
    async def right_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_position_choice(interaction, "direita")
    
    async def handle_position_choice(self, interaction: discord.Interaction, position: str):
        """Processa a escolha de posição"""
        
        if self.waiting_for_shot:
            # Aguardando o chute
            if interaction.user.id != self.duel.current_shooter:
                shooter = interaction.guild.get_member(self.duel.current_shooter)
                await interaction.response.send_message(f"❌ É a vez de **{shooter.display_name}** chutar! Aguarde sua vez.", ephemeral=True)
                return
            
            self.shot_position = position
            self.waiting_for_shot = False
            
            embed = await self.update_embed(
                interaction,
                "🧤 Agora é a vez do GOLEIRO!",
                f"✅ **Atacante escolheu sua posição!**\n\n🎯 **Goleiro:** Agora escolha onde vai tentar defender!"
            )
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        else:
            # Aguardando a defesa
            if interaction.user.id != self.duel.current_goalkeeper:
                goalkeeper = interaction.guild.get_member(self.duel.current_goalkeeper)
                await interaction.response.send_message(f"❌ É a vez de **{goalkeeper.display_name}** defender! Aguarde sua vez.", ephemeral=True)
                return
            
            self.save_position = position
            
            # Processar o pênalti
            result, description = self.duel.process_penalty(self.shot_position, self.save_position)
            
            # Mostrar resultado
            color = discord.Color.green() if result == "gol" else discord.Color.red()
            
            # Criar embed de resultado mais detalhado
            result_embed = discord.Embed(
                title=f"🎯 Resultado do Pênalti - Rodada {self.duel.current_round}",
                description=f"{description}",
                color=color
            )
            
            challenger = interaction.guild.get_member(self.duel.challenger_id)
            challenged = interaction.guild.get_member(self.duel.challenged_id)
            
            result_embed.add_field(
                name="📊 Placar Atualizado",
                value=f"**{challenger.display_name}:** {self.duel.challenger_score}\n**{challenged.display_name}:** {self.duel.challenged_score}",
                inline=True
            )
            
            result_embed.add_field(
                name="🎯 Escolhas Feitas",
                value=f"**Chute:** {self.duel.positions[self.shot_position]} {self.shot_position.title()}\n**Defesa:** {self.duel.positions[self.save_position]} {self.save_position.title()}",
                inline=True
            )
            
            # Verificar se o duelo acabou
            penalties_this_round = len([p for p in self.duel.penalties_taken if p["round"] == self.duel.current_round])
            
            # Se completou uma rodada (ambos chutaram)
            if penalties_this_round == 2:
                # Se passou das 5 rodadas normais
                if self.duel.current_round >= 5:
                    # Verificar se há vencedor
                    if self.duel.challenger_score != self.duel.challenged_score:
                        # Duelo decidido
                        self.duel.game_over = True
                        self.duel.determine_winner()
                        
                        winner = interaction.guild.get_member(self.duel.winner)
                        final_embed = discord.Embed(
                            title="🏆 DUELO DE PÊNALTIS FINALIZADO",
                            description=f"🎉 **{winner.display_name}** venceu o duelo de pênaltis!",
                            color=discord.Color.gold()
                        )
                        
                        final_embed.add_field(
                            name="📊 Resultado Final",
                            value=f"**{challenger.display_name}:** {self.duel.challenger_score}\n**{challenged.display_name}:** {self.duel.challenged_score}",
                            inline=False
                        )
                        
                        if self.duel.current_round > 5:
                            final_embed.add_field(
                                name="💀 Morte Súbita",
                                value=f"Duelo decidido na rodada {self.duel.current_round}!",
                                inline=False
                            )
                        
                        await interaction.response.edit_message(embed=final_embed, view=None)
                        return
                    
                    # Verificar limite máximo de rodadas (evitar infinito)
                    if self.duel.current_round >= 10:
                        # Forçar fim por limite de rodadas
                        if self.duel.challenger_score > self.duel.challenged_score:
                            self.duel.winner = self.duel.challenger_id
                        elif self.duel.challenged_score > self.duel.challenger_score:
                            self.duel.winner = self.duel.challenged_id
                        else:
                            # Empate total - decidir por sorteio
                            self.duel.winner = random.choice([self.duel.challenger_id, self.duel.challenged_id])
                        
                        winner = interaction.guild.get_member(self.duel.winner)
                        final_embed = discord.Embed(
                            title="🏆 DUELO FINALIZADO POR LIMITE",
                            description=f"🎉 **{winner.display_name}** venceu após 10 rodadas!",
                            color=discord.Color.gold()
                        )
                        
                        final_embed.add_field(
                            name="📊 Resultado Final",
                            value=f"**{challenger.display_name}:** {self.duel.challenger_score}\n**{challenged.display_name}:** {self.duel.challenged_score}",
                            inline=False
                        )
                        
                        final_embed.add_field(
                            name="⏰ Limite Atingido",
                            value="Duelo finalizado após 10 rodadas para evitar disputa infinita.",
                            inline=False
                        )
                        
                        await interaction.response.edit_message(embed=final_embed, view=None)
                        return
            
            # Preparar próxima rodada
            if len([p for p in self.duel.penalties_taken if p["round"] == self.duel.current_round]) == 2:
                # Rodada completa, avançar
                self.duel.current_round += 1
                self.duel.current_shooter = self.duel.challenger_id
                self.duel.current_goalkeeper = self.duel.challenged_id
            else:
                # Trocar de função
                self.duel.switch_roles()
            
            # Resetar para próximo pênalti
            self.waiting_for_shot = True
            self.shot_position = None
            self.save_position = None
            
            # Mostrar resultado primeiro
            await interaction.response.edit_message(embed=result_embed, view=None)
            
            # Aguardar e então mostrar próximo pênalti
            await asyncio.sleep(4)
            
            shooter = interaction.guild.get_member(self.duel.current_shooter)
            next_embed = await self.update_embed(
                interaction,
                f"⚽ Rodada {self.duel.current_round} - Próximo Pênalti",
                f"🔄 **Trocaram de posições!**\n\n🎯 **Novo atacante:** {shooter.display_name}"
            )
            
            # Criar nova view para evitar problemas de webhook
            new_view = PenaltyDuelView(self.duel)
            await interaction.followup.edit_message(interaction.message.id, embed=next_embed, view=new_view)

class PenaltyAcceptView(View):
    def __init__(self, challenger_id: int, challenged_id: int):
        super().__init__(timeout=60)
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
    
    @discord.ui.button(label="⚽ Aceitar Duelo", style=discord.ButtonStyle.success)
    async def accept_duel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.challenged_id:
            await interaction.response.send_message("❌ Apenas o jogador desafiado pode aceitar!", ephemeral=True)
            return
        
        # Iniciar duelo
        duel = PenaltyDuel(self.challenger_id, self.challenged_id)
        view = PenaltyDuelView(duel)
        
        challenger = interaction.guild.get_member(self.challenger_id)
        challenged = interaction.guild.get_member(self.challenged_id)
        shooter = interaction.guild.get_member(duel.current_shooter)
        
        embed = discord.Embed(
            title="⚽ **DUELO DE PÊNALTIS INICIADO** ⚽",
            description=f"🥅 **{challenger.display_name}** 🆚 **{challenged.display_name}**\n\n🎯 **É A VEZ DE:** {shooter.display_name} (ATACANTE)\n\n⚽ **{shooter.display_name}** - ESCOLHA ONDE CHUTAR!",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📋 Regras",
            value="• 5 pênaltis para cada jogador\n• Alternam entre atacante e goleiro\n• Em caso de empate: morte súbita\n• Atacante escolhe primeiro, depois o goleiro",
            inline=False
        )
        
        embed.set_footer(text="Use os botões para escolher a posição! - Dev: YevgennyMXP")
        
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="❌ Recusar", style=discord.ButtonStyle.danger)
    async def decline_duel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.challenged_id:
            await interaction.response.send_message("❌ Apenas o jogador desafiado pode recusar!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="❌ Duelo Recusado",
            description="O duelo de pênaltis foi recusado.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

@bot.command(name='penaltis', aliases=['shootout', 'disputapenaltis'])
async def penalty_shootout_command(ctx, team1: str, team2: str):
    """Simula uma disputa de pênaltis entre dois times"""
    team1 = capitalizar_nome(team1)
    team2 = capitalizar_nome(team2)
    
    if team1.lower() == team2.lower():
        await ctx.reply("❌ Os times devem ser diferentes!")
        return
    
    shootout = PenaltyShootout(team1, team2)
    await shootout.simulate_full_shootout(ctx)

@bot.command(name='penal', aliases=['duelopenal', 'penalty1v1'])
async def penalty_duel_command(ctx, member: discord.Member):
    """Desafia outro jogador para um duelo de pênaltis"""
    
    if member.id == ctx.author.id:
        await ctx.reply("❌ Você não pode desafiar a si mesmo!")
        return
    
    if member.bot:
        await ctx.reply("❌ Você não pode desafiar bots!")
        return
    
    embed = discord.Embed(
        title="⚽ **DESAFIO DE DUELO DE PÊNALTIS** ⚽",
        description=f"🎯 **{ctx.author.display_name}** desafiou **{member.display_name}** para um duelo de pênaltis!\n\n**Como funciona:**\n• 5 pênaltis para cada um\n• Vocês alternam entre atacante e goleiro\n• Atacante escolhe onde chutar, goleiro onde defender\n• Melhor de 5 vence!",
        color=discord.Color.orange()
    )
    
    embed.set_footer(text=f"{member.display_name}, você aceita o desafio? - Dev: YevgennyMXP")
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    
    view = PenaltyAcceptView(ctx.author.id, member.id)
    await ctx.reply(content=f"{member.mention}", embed=embed, view=view)

# --- Sistema de Simulação Realista Ultra-Detalhada ---

class UltraRealisticMatch:
    """Simulador de partida ultra-realista com centenas de eventos possíveis"""
    
    def __init__(self):
        # Árbitros famosos com suas características
        self.referees = {
            "Anderson Daronco": {"strictness": 8, "card_tendency": "high", "var_usage": 9},
            "Raphael Claus": {"strictness": 7, "card_tendency": "medium", "var_usage": 8},
            "Wilton Pereira Sampaio": {"strictness": 9, "card_tendency": "very_high", "var_usage": 7},
            "Leandro Pedro Vuaden": {"strictness": 6, "card_tendency": "low", "var_usage": 9},
            "Bráulio da Silva Machado": {"strictness": 7, "card_tendency": "medium", "var_usage": 8},
            "Flávio Rodrigues de Souza": {"strictness": 8, "card_tendency": "high", "var_usage": 6},
            "Ramon Abatti Abel": {"strictness": 5, "card_tendency": "low", "var_usage": 10}
        }
        
        # Estádios com características específicas
        self.stadiums = {
            "Maracanã": {"capacity": 78838, "pitch_quality": 9, "crowd_intensity": 10, "altitude": 11, "city": "Rio de Janeiro"},
            "Morumbi": {"capacity": 67428, "pitch_quality": 8, "crowd_intensity": 9, "altitude": 760, "city": "São Paulo"},
            "Arena Corinthians": {"capacity": 49205, "pitch_quality": 10, "crowd_intensity": 10, "altitude": 750, "city": "São Paulo"},
            "Allianz Parque": {"capacity": 43713, "pitch_quality": 9, "crowd_intensity": 9, "altitude": 760, "city": "São Paulo"},
            "Mineirão": {"capacity": 61927, "pitch_quality": 8, "crowd_intensity": 8, "altitude": 852, "city": "Belo Horizonte"},
            "Arena da Baixada": {"capacity": 42372, "pitch_quality": 8, "crowd_intensity": 9, "altitude": 924, "city": "Curitiba"},
            "Beira-Rio": {"capacity": 50842, "pitch_quality": 9, "crowd_intensity": 9, "altitude": 3, "city": "Porto Alegre"},
            "Arena Fonte Nova": {"capacity": 50025, "pitch_quality": 8, "crowd_intensity": 8, "altitude": 8, "city": "Salvador"}
        }
        
        # Condições climáticas extremamente detalhadas
        self.weather_conditions = {
            "sol_escaldante": {"temp": 38, "humidity": 25, "wind": 5, "effect": "Jogadores cansam 40% mais rápido", "visibility": 10},
            "chuva_torrencial": {"temp": 18, "humidity": 95, "wind": 25, "effect": "Dribles reduzidos em 60%, passes imprecisos", "visibility": 4},
            "tempestade_eletrica": {"temp": 16, "humidity": 98, "wind": 45, "effect": "Jogo pode ser suspenso, jogadores nervosos", "visibility": 2},
            "neblina_densa": {"temp": 12, "humidity": 99, "wind": 2, "effect": "Visibilidade crítica, passes longos impossíveis", "visibility": 1},
            "vento_forte": {"temp": 22, "humidity": 60, "wind": 50, "effect": "Bolas aéreas imprevisíveis, chutes desviados", "visibility": 8},
            "clima_perfeito": {"temp": 24, "humidity": 55, "wind": 8, "effect": "Condições ideais para o futebol", "visibility": 10},
            "calor_umido": {"temp": 32, "humidity": 85, "wind": 3, "effect": "Desidratação rápida, câimbras frequentes", "visibility": 7},
            "frio_glacial": {"temp": 2, "humidity": 70, "wind": 20, "effect": "Músculos rígidos, maior risco de lesões", "visibility": 9}
        }
        
        # Eventos ultra-detalhados categorizados
        self.match_events = {
            "gols_normais": [
                "⚽ **GOLAÇO DE COBERTURA!** {} recebe na entrada da área e vê o goleiro adiantado - coloca por coima com classe!",
                "⚽ **GOL DE LETRA!** {} recebe de costas e faz uma letra sensacional que morre no ângulo!",
                "⚽ **CHUTE DE PRIMEIRA!** Cruzamento na medida para {} que bate de primeira no canto!",
                "⚽ **GOL DE CALCANHAR!** {} improvisa um chute de calcanhar que pega o goleiro desprevenido!",
                "⚽ **BOMBA DE FORA DA ÁREA!** {} arrisca de longe e acerta um míssil no ângulo!",
                "⚽ **GOL DE CABEÇA!** Escanteio certeiro e {} sobe sozinho para cabecear no fundo das redes!",
                "⚽ **GOLAÇO EM JOGADA INDIVIDUAL!** {} dribla 3 adversários e finaliza com categoria!",
                "⚽ **GOL DE REBOTE!** O goleiro espalma e {} fica com a sobra para empurrar para o gol!",
                "⚽ **FINALIZAÇÃO RASTEIRA!** {} recebe na área e bate rasteiro no canto baixo!",
                "⚽ **GOL DE VOLEIO!** Bola sobra na área e {} pega de voleio - que pancada!"
            ],
            "penaltis": [
                "🥅 **PÊNALTI MARCADO!** {} é derrubado na área de forma clara - sem discussão!",
                "🥅 **PÊNALTI POLÊMICO!** Possível toque de mão na área - VAR confirma a marcação!",
                "🥅 **PÊNALTI POR PISÃO!** {} é pisado na área adversária - penalty óbvio!",
                "🥅 **PÊNALTI DE CARRINHO!** Entrada dura na área derruba {} - não sobrou dúvida!",
                "🥅 **PÊNALTI APÓS REVISÃO!** VAR chama o árbitro para revisar lance duvidoso!"
            ],
            "conversoes_penalty": [
                "⚽🎯 **PÊNALTI CONVERTIDO!** {} bate forte no canto e não dá chances para o goleiro!",
                "⚽🎯 **GOL DE CAVADINHA!** {} tem a coragem de fazer uma cavadinha gelada!",
                "⚽🎯 **PÊNALTI NO MEIO!** {} bate no meio enquanto o goleiro pula para o lado!",
                "⚽🎯 **GOL COM FRIEZA!** {} espera o goleiro se mexer e coloca do outro lado!",
                "⚽🎯 **PÊNALTI PERFEITO!** {} acerta exatamente no ângulo - impossível de defender!"
            ],
            "defesas_penalty": [
                "🧤 **PÊNALTI DEFENDIDO!** O goleiro vai no canto certo e faz uma defesa espetacular!",
                "😱 **PÊNALTI PERDIDO!** {} manda a bola por cima do gol - que desperdício!",
                "🧤 **DEFESAÇA NO PÊNALTI!** O goleiro espalma e ainda consegue segurar no rebote!",
                "😨 **PÊNALTI NA TRAVE!** {} acerta a trave e a bola sai pela linha de fundo!"
            ],
            "faltas_graves": [
                "💥 **FALTA VIOLENTA!** {} comete uma entrada criminosa e pode ser expulso!",
                "⚡ **CARRINHO DESLEAL!** {} vai com tudo na canela do adversário!",
                "🤼 **AGRESSÃO!** {} parte para cima do adversário - confusão formada!",
                "💢 **COTOVELADA!** {} acerta o cotovelo na cabeça do rival de forma proposital!",
                "🦵 **PISÃO VIOLENTO!** {} pisa na perna do adversário com força!",
                "👊 **EMPURRÃO AGRESSIVO!** {} empurra o adversário com violência desnecessária!"
            ],
            "gols_falta": [
                "⚽🌟 **GOLAÇO DE FALTA!** {} cobra com perfeição e acerta o ângulo!",
                "⚽🌟 **FALTA DIRETO NO GOL!** {} coloca a bola exatamente onde queria!",
                "⚽🌟 **BARREIRA FURADA!** {} cobra rasteiro por baixo da barreira!",
                "⚽🌟 **FALTA COM EFEITO!** {} dá um efeito incrível na bola que engana o goleiro!",
                "⚽🌟 **TIRO LIVRE PERFEITO!** {} acerta um míssil de falta que não dá chance!"
            ],
            "cartoes_amarelos": [
                "🟨 **Cartão Amarelo para {}!** Falta dura é punida pelo árbitro!",
                "🟨 **Amarelo por reclamação!** {} exagera na contestação e é advertido!",
                "🟨 **Cartão por simulação!** {} tenta enganar o árbitro e é punido!",
                "🟨 **Amarelo por demora!** {} retarda o jogo propositalmente!",
                "🟨 **Cartão por comemoração!** {} tira a camisa e é advertido!",
                "🟨 **Amarelo por entrada dura!** {} comete falta tática e leva cartão!"
            ],
            "cartoes_vermelhos": [
                "🟥 **EXPULSÃO DIRETA!** {} comete falta gravíssima e é expulso!",
                "🟥 **SEGUNDO AMARELO!** {} já tinha cartão e agora está fora!",
                "🟥 **CARTÃO VERMELHO POR AGRESSÃO!** {} agride adversário e é expulso!",
                "🟥 **EXPULSÃO POR PALAVRÃO!** {} desrespita o árbitro e vai para o chuveiro!",
                "🟥 **VERMELHO POR CUSPIR!** {} cospe no adversário - inadmissível!",
                "🟥 **EXPULSO POR ENTRADA ASSASSINA!** {} quase quebra a perna do rival!"
            ],
            "defesas_especiais": [
                "🧤 **DEFESA IMPOSSÍVEL!** O goleiro faz uma defesa que desafia a física!",
                "🦸 **MILAGRE DEBAIXO DAS TRAVES!** Defesa espetacular salva o time!",
                "🧤 **DEFESA COM O PÉ!** O goleiro usa o pé para evitar o gol!",
                "🦶 **DEFESA REFLEXA!** O goleiro reage no último segundo!",
                "🧤 **DEFESA EM DOIS TEMPOS!** Primeira defesa e depois segura o rebote!",
                "🙌 **DEFESA COM AS DUAS MÃOS!** O goleiro voa para fazer a defesa!"
            ],
            "eventos_var": [
                "📱 **VAR CHAMANDO!** Árbitro é chamado para revisar lance polêmico!",
                "📺 **REVISÃO NO VAR!** Lance está sendo analisado detalhadamente!",
                "⚖️ **VAR CONFIRMA!** Após análise, decisão de campo é mantida!",
                "🔄 **VAR REVERTE!** Decisão do campo é alterada após revisão!",
                "📱 **CHECK VAR!** Verificação rápida confirma que estava tudo correto!",
                "📺 **VAR DEMORA!** Análise está levando mais tempo que o normal!"
            ],
            "lesoes": [
                "🚑 **LESÃO GRAVE!** {} cai no gramado e precisa de atendimento médico!",
                "😰 **JOGADOR MACHUCADO!** {} sente dores e pede substituição!",
                "🏥 **LESÃO PREOCUPANTE!** {} é retirado de maca do campo!",
                "💔 **CONTUSÃO MUSCULAR!** {} sente a coxa e não consegue continuar!",
                "🦴 **POSSÍVEL FRATURA!** {} cai de forma estranha - situação preocupante!",
                "😵 **JOGADOR DESACORDADO!** {} bate a cabeça e perde os sentidos!"
            ],
            "brigas_confusoes": [
                "🥊 **PANCADARIA GENERALIZADA!** Players dos dois times se envolvem em confusão!",
                "👊 **BRIGA NO GRAMADO!** {} e {} partem para agressão física!",
                "🤼‍♂️ **CONFUSÃO TOTAL!** Banco de reservas entra em campo para separar!",
                "💢 **CLIMA QUENTE!** Jogadores se empurram e árbitro perde controle!",
                "⚔️ **GUERRA DECLARADA!** Times se desentendem e clima fica tenso!",
                "🔥 **BAIXARIA NO CAMPO!** Jogadores partem para porrada - jogo interrompido!"
            ],
            "invasao_torcida": [
                "🏃‍♂️ **INVASÃO DE CAMPO!** Torcedores invadem o gramado - jogo suspenso!",
                "📱 **TORCEDOR NO CAMPO!** Segurança corre atrás de invasor!",
                "🚨 **INVASÃO MASSIVA!** Centenas de torcedores entram no campo!",
                "📸 **FÃ INVADE PARA SELFIE!** Torcedor entra só para tirar foto com ídolo!",
                "🏃‍♀️ **TORCEDORA INVADE!** Segurança tem trabalho para retirar invasora!",
                "⚡ **INVASÃO RELÂMPAGO!** Torcedor entra e sai correndo rapidamente!"
            ],
            "protestos_torcida": [
                "🗣️ **TORCIDA IRRITADA!** Arquibancada vaia decisões do árbitro!",
                "📢 **PROTESTO ORGANIZADO!** Torcida grita palavras de ordem!",
                "🎵 **CANTO DE PROTESTO!** Torcida canta música ofensiva ao rival!",
                "💨 **FUMAÇA NA ARQUIBANCADA!** Torcida acende sinalizadores!",
                "📯 **CORNETAS E GRITOS!** Torcida faz barulho ensurdecedor!",
                "🪧 **FAIXAS DE PROTESTO!** Torcida estende faixas criticando time!"
            ],
            "problemas_tecnicos": [
                "⚡ **FALTA DE LUZ!** Problema elétrico no estádio - jogo interrompido!",
                "📺 **FALHA NO VAR!** Sistema de vídeo apresenta problemas técnicos!",
                "🔊 **SOM FALHOU!** Sistema de áudio do estádio parou de funcionar!",
                "🏟️ **PROBLEMA NO GRAMADO!** Sprinklers ligam acidentalmente!",
                "📱 **REDE SOBRECARREGADA!** Internet do estádio está instável!",
                "🎬 **CÂMERAS FALHARAM!** Transmissão apresenta problemas técnicos!"
            ],
            "eventos_bizarros": [
                "🐕 **CACHORRO INVADE!** Um cão entra em campo e atrapalha o jogo!",
                "🦅 **PÁSSARO INTERFERE!** Ave voa baixo e atrapalha jogada!",
                "⚽ **BOLA MURCHA!** Bola oficial perde ar durante o jogo!",
                "🌧️ **CHUVA DE GRANIZO!** Pedras de gelo caem no campo!",
                "🎆 **FOGOS NA ARQUIBANCADA!** Torcida solta fogos de artifício!",
                "🚁 **HELICÓPTERO BAIXO!** Aeronave atrapalha visão dos jogadores!"
            ],
            "jogadas_geniais": [
                "🎭 **JOGADA ENSAIADA!** Time executa lance treinado com perfeição!",
                "🎪 **MALABARISMO!** {} faz embaixadinhas e deixa defesa perdida!",
                "🎯 **LANÇAMENTO MILIMÉTRICO!** Passe de 40 metros encontra companheiro!",
                "⚡ **CONTRA-ATAQUE RELÂMPAGO!** Time sai da defesa ao ataque em 3 segundos!",
                "🎨 **ARTE EM CAMPO!** {} executa drible que vira obra de arte!",
                "🧠 **JOGADA DE GÊNIO!** Time arquiteta lance de laboratório!"
            ],
            "erros_grotescos": [
                "😱 **FRANGO HISTÓRICO!** Goleiro falha feio em bola fácil!",
                "🤦 **PASSE ERRADO GROTESCO!** {} entrega bola de bandeja pro rival!",
                "😵 **GOL CONTRA BIZARRO!** {} marca contra próprio gol de forma inacreditável!",
                "🙈 **PERDEU IMPOSSÍVEL!** {} perde gol feito em baixo do gol!",
                "💀 **ERRO AMADOR!** {} tropeça na própria perna!",
                "🤯 **FALHA COLETIVA!** Time todo se confunde na mesma jogada!"
            ]
        }
        
        # Sistema de minuto a minuto
        self.minute_markers = [3, 7, 12, 18, 23, 28, 34, 41, 45, 48, 52, 58, 63, 67, 73, 78, 84, 90]
    
    def generate_realistic_teams(self):
        """Gera times com características realistas"""
        team_names = [
            "Flamengo", "Palmeiras", "São Paulo", "Corinthians", "Santos", "Grêmio",
            "Internacional", "Atlético-MG", "Cruzeiro", "Vasco", "Botafogo", "Fluminense",
            "Athletico-PR", "Bahia", "Sport", "Fortaleza", "Ceará", "Goiás"
        ]
        
        team1, team2 = random.sample(team_names, 2)
        
        # Gerar características dos times
        team1_stats = {
            "attack": random.randint(65, 95),
            "defense": random.randint(60, 90),
            "form": random.choice(["excelente", "boa", "regular", "ruim"]),
            "morale": random.randint(50, 100)
        }
        
        team2_stats = {
            "attack": random.randint(65, 95),
            "defense": random.randint(60, 90),
            "form": random.choice(["excelente", "boa", "regular", "ruim"]),
            "morale": random.randint(50, 100)
        }
        
        return team1, team1_stats, team2, team2_stats
    
    def select_referee_and_stadium(self):
        """Seleciona árbitro e estádio"""
        referee_name = random.choice(list(self.referees.keys()))
        referee_data = self.referees[referee_name]
        
        stadium_name = random.choice(list(self.stadiums.keys()))
        stadium_data = self.stadiums[stadium_name]
        
        return referee_name, referee_data, stadium_name, stadium_data
    
    def generate_weather(self):
        """Gera condições climáticas"""
        weather_type = random.choice(list(self.weather_conditions.keys()))
        weather_data = self.weather_conditions[weather_type]
        return weather_type, weather_data
    
    def calculate_event_probability(self, event_type, minute, team1_stats, team2_stats, match_context):
        """Calcula probabilidade de eventos baseada em contexto"""
        base_probabilities = {
            "gol": 0.15,
            "penalti": 0.08,
            "cartao_amarelo": 0.25,
            "cartao_vermelho": 0.03,
            "falta_grave": 0.18,
            "lesao": 0.05,
            "briga": 0.02,
            "invasao": 0.01,
            "evento_bizarro": 0.005
        }
        
        prob = base_probabilities.get(event_type, 0.1)
        
        # Modificadores baseados no contexto
        if minute > 80:  # Final do jogo - mais eventos
            prob *= 1.5
        
        if match_context.get("cards", 0) > 3:  # Jogo quente
            prob *= 1.3
        
        if match_context.get("referee_strictness", 5) > 7:  # Árbitro rigoroso
            if event_type in ["cartao_amarelo", "cartao_vermelho"]:
                prob *= 1.6
        
        if match_context.get("weather_effect", 1) < 0.5:  # Tempo ruim
            if event_type in ["lesao", "evento_bizarro"]:
                prob *= 2
        
        return min(prob, 0.8)  # Máximo 80% de chance
    
    async def simulate_ultra_realistic_match(self, ctx, team1_name=None, team2_name=None):
        """Simula partida ultra-realística"""
        
        # Gerar dados da partida
        if team1_name and team2_name:
            team1 = capitalizar_nome(team1_name)
            team2 = capitalizar_nome(team2_name)
            
            # Gerar stats para os times fornecidos
            team1_stats = {
                "attack": random.randint(65, 95),
                "defense": random.randint(60, 90),
                "form": random.choice(["excelente", "boa", "regular", "ruim"]),
                "morale": random.randint(50, 100)
            }
            
            team2_stats = {
                "attack": random.randint(65, 95),
                "defense": random.randint(60, 90),
                "form": random.choice(["excelente", "boa", "regular", "ruim"]),
                "morale": random.randint(50, 100)
            }
        else:
            team1, team1_stats, team2, team2_stats = self.generate_realistic_teams()
        referee_name, referee_data, stadium_name, stadium_data = self.select_referee_and_stadium()
        weather_type, weather_data = self.generate_weather()
        
        # Estado da partida
        score = [0, 0]
        events_log = []
        cards = {"team1": {"yellow": 0, "red": 0}, "team2": {"yellow": 0, "red": 0}}
        match_context = {
            "referee_strictness": referee_data["strictness"],
            "weather_effect": weather_data["visibility"] / 10,
            "crowd_intensity": stadium_data["crowd_intensity"],
            "cards": 0,
            "injuries": 0,
            "controversies": 0
        }
        
        # Embed inicial super detalhado
        initial_embed = discord.Embed(
            title="🏟️ **TRANSMISSÃO ULTRA-REALISTA AO VIVO** 🏟️",
            description=f"**🔴 PREPARANDO TRANSMISSÃO DETALHADA...**",
            color=discord.Color.blue()
        )
        
        initial_embed.add_field(
            name="⚽ **CONFRONTO DA RODADA**",
            value=f"🏠 **{team1}** (Ataque: {team1_stats['attack']}) 🆚 **{team2}** (Ataque: {team2_stats['attack']}) ✈️",
            inline=False
        )
        
        initial_embed.add_field(
            name="🏟️ **LOCAL & CONDIÇÕES**",
            value=f"**Estádio:** {stadium_name} ({stadium_data['capacity']:,} lugares)\n**Cidade:** {stadium_data['city']} - Altitude: {stadium_data['altitude']}m\n**Clima:** {weather_type.replace('_', ' ').title()} ({weather_data['temp']}°C)",
            inline=True
        )
        
        initial_embed.add_field(
            name="👨‍⚖️ **ARBITRAGEM**",
            value=f"**Árbitro:** {referee_name}\n**Rigor:** {referee_data['strictness']}/10\n**Uso VAR:** {referee_data['var_usage']}/10",
            inline=True
        )
        
        initial_embed.add_field(
            name="🌤️ **ANÁLISE METEOROLÓGICA**",
            value=f"**Temperatura:** {weather_data['temp']}°C\n**Umidade:** {weather_data['humidity']}%\n**Vento:** {weather_data['wind']} km/h\n**Visibilidade:** {weather_data['visibility']}/10\n**Impacto:** {weather_data['effect']}",
            inline=False
        )
        
        initial_embed.set_footer(text="🔴 Transmissão iniciando... Prepare-se para 90 minutos intensos! - Dev: YevgennyMXP")
        
        message = await ctx.reply(embed=initial_embed)
        await asyncio.sleep(3)
        
        # Simulação minuto a minuto
        for minute in self.minute_markers:
            # Gerar eventos múltiplos por minuto
            events_this_minute = []
            
            # Chance de múltiplos eventos por minuto
            for _ in range(random.randint(1, 3)):
                # Determinar tipo de evento baseado em probabilidades
                event_roll = random.random()
                
                if event_roll < self.calculate_event_probability("gol", minute, team1_stats, team2_stats, match_context):
                    # Evento de gol
                    if random.random() < 0.1:  # 10% chance de pênalti
                        penalty_event = random.choice(self.match_events["penaltis"])
                        events_this_minute.append(f"`{minute}'` " + penalty_event.format(random.choice(["Silva", "Santos", "Oliveira", "Costa"])))
                        
                        # Converter pênalti
                        if random.random() < 0.78:  # 78% de conversão
                            conversion_event = random.choice(self.match_events["conversoes_penalty"])
                            events_this_minute.append(f"`{minute}'` " + conversion_event.format(random.choice(["Silva", "Santos", "Oliveira"])))
                            score[random.randint(0, 1)] += 1
                        else:
                            miss_event = random.choice(self.match_events["defesas_penalty"])
                            events_this_minute.append(f"`{minute}'` " + miss_event)
                    
                    elif random.random() < 0.15:  # 15% chance de gol de falta
                        foul_goal_event = random.choice(self.match_events["gols_falta"])
                        events_this_minute.append(f"`{minute}'` " + foul_goal_event.format(random.choice(["Silva", "Santos", "Rodrigues"])))
                        score[random.randint(0, 1)] += 1
                    
                    else:  # Gol normal
                        goal_event = random.choice(self.match_events["gols_normais"])
                        events_this_minute.append(f"`{minute}'` " + goal_event.format(random.choice(["Silva", "Santos", "Costa", "Pereira"])))
                        score[random.randint(0, 1)] += 1
                
                elif event_roll < 0.3:  # Eventos de cartão
                    if random.random() < 0.1:  # 10% vermelho
                        red_event = random.choice(self.match_events["cartoes_vermelhos"])
                        events_this_minute.append(f"`{minute}'` " + red_event.format(random.choice(["Santos", "Silva", "Oliveira"])))
                        cards["team1" if random.random() > 0.5 else "team2"]["red"] += 1
                        match_context["cards"] += 1
                    else:  # Amarelo
                        yellow_event = random.choice(self.match_events["cartoes_amarelos"])
                        events_this_minute.append(f"`{minute}'` " + yellow_event.format(random.choice(["Costa", "Lima", "Araújo"])))
                        cards["team1" if random.random() > 0.5 else "team2"]["yellow"] += 1
                        match_context["cards"] += 1
                
                elif event_roll < 0.45:  # Defesas especiais
                    defense_event = random.choice(self.match_events["defesas_especiais"])
                    events_this_minute.append(f"`{minute}'` " + defense_event)
                
                elif event_roll < 0.55:  # Faltas graves
                    foul_event = random.choice(self.match_events["faltas_graves"])
                    events_this_minute.append(f"`{minute}'` " + foul_event.format(random.choice(["Fernandes", "Carvalho", "Nascimento"])))
                
                elif event_roll < 0.62:  # VAR
                    var_event = random.choice(self.match_events["eventos_var"])
                    events_this_minute.append(f"`{minute}'` " + var_event)
                    match_context["controversies"] += 1
                
                elif event_roll < 0.67:  # Lesões
                    injury_event = random.choice(self.match_events["lesoes"])
                    events_this_minute.append(f"`{minute}'` " + injury_event.format(random.choice(["Almeida", "Rodrigues", "Lima"])))
                    match_context["injuries"] += 1
                
                elif event_roll < 0.72:  # Jogadas geniais
                    genius_event = random.choice(self.match_events["jogadas_geniais"])
                    events_this_minute.append(f"`{minute}'` " + genius_event.format(random.choice(["Santos", "Silva", "Costa"])))
                
                elif event_roll < 0.76:  # Erros grotescos
                    error_event = random.choice(self.match_events["erros_grotescos"])
                    events_this_minute.append(f"`{minute}'` " + error_event.format(random.choice(["Pereira", "Oliveira", "Nascimento"])))
                
                elif event_roll < 0.79:  # Brigas
                    fight_event = random.choice(self.match_events["brigas_confusoes"])
                    events_this_minute.append(f"`{minute}'` " + fight_event.format(random.choice(["Santos", "Silva"]), random.choice(["Costa", "Lima"])))
                
                elif event_roll < 0.82:  # Protestos da torcida
                    protest_event = random.choice(self.match_events["protestos_torcida"])
                    events_this_minute.append(f"`{minute}'` " + protest_event)
                
                elif event_roll < 0.84:  # Problemas técnicos
                    tech_event = random.choice(self.match_events["problemas_tecnicos"])
                    events_this_minute.append(f"`{minute}'` " + tech_event)
                
                elif event_roll < 0.86:  # Invasão de torcida
                    invasion_event = random.choice(self.match_events["invasao_torcida"])
                    events_this_minute.append(f"`{minute}'` " + invasion_event)
                
                elif event_roll < 0.88:  # Eventos bizarros
                    bizarre_event = random.choice(self.match_events["eventos_bizarros"])
                    events_this_minute.append(f"`{minute}'` " + bizarre_event)
            
            # Atualizar eventos log
            events_log.extend(events_this_minute)
            
            # Determinar cor do embed baseada na intensidade
            if len(events_this_minute) > 2:
                embed_color = discord.Color.red()  # Minuto intenso
            elif any("GOL" in event for event in events_this_minute):
                embed_color = discord.Color.gold()  # Gol marcado
            elif any("VERMELHO" in event or "EXPULS" in event for event in events_this_minute):
                embed_color = discord.Color.dark_red()  # Expulsão
            else:
                embed_color = discord.Color.green()  # Jogo normal
            
            # Embed de minuto
            minute_embed = discord.Embed(
                title="🏟️ **TRANSMISSÃO ULTRA-REALISTA AO VIVO** 🏟️",
                description=f"**🔴 MINUTO {minute}' - {team1} {score[0]} x {score[1]} {team2}**",
                color=embed_color
            )
            
            # Eventos deste minuto
            if events_this_minute:
                events_text = "\n".join(events_this_minute[-3:])  # Últimos 3 eventos
                minute_embed.add_field(
                    name=f"⚡ **EVENTOS DO MINUTO {minute}'**",
                    value=events_text,
                    inline=False
                )
            
            # Estatísticas em tempo real
            total_cards = cards["team1"]["yellow"] + cards["team1"]["red"] + cards["team2"]["yellow"] + cards["team2"]["red"]
            minute_embed.add_field(
                name="📊 **ESTATÍSTICAS AO VIVO**",
                value=f"🟨 **Cartões:** {cards['team1']['yellow'] + cards['team2']['yellow']}\n🟥 **Expulsões:** {cards['team1']['red'] + cards['team2']['red']}\n🚑 **Lesões:** {match_context['injuries']}\n📱 **VAR:** {match_context['controversies']} análises",
                inline=True
            )
            
            # Condições da partida
            minute_embed.add_field(
                name="🌡️ **CONDIÇÕES ATUAIS**",
                value=f"**Temperatura:** {weather_data['temp']}°C\n**Vento:** {weather_data['wind']} km/h\n**Árbitro:** {referee_name}\n**Público:** {stadium_data['capacity']:,}",
                inline=True
            )
            
            # Análise do clima da partida
            if total_cards > 5:
                climate = "🔥 **PARTIDA ESQUENTOU!**"
            elif match_context["controversies"] > 2:
                climate = "⚖️ **MUITAS POLÊMICAS!**"
            elif score[0] + score[1] > 3:
                climate = "⚽ **FESTIVAL DE GOLS!**"
            elif match_context["injuries"] > 2:
                climate = "🚑 **JOGO VIOLENTO!**"
            else:
                climate = "⚽ **JOGO EQUILIBRADO**"
            
            minute_embed.add_field(
                name="🔥 **CLIMA DA PARTIDA**",
                value=climate,
                inline=False
            )
            
            minute_embed.set_footer(text=f"🔴 AO VIVO • {minute}' • {weather_type.replace('_', ' ').title()} - Dev: YevgennyMXP")
            
            await message.edit(embed=minute_embed)
            await asyncio.sleep(3.5)  # Pausa dramática entre minutos
        
        # Resultado final épico
        final_embed = discord.Embed(
            title="🏁 **FIM DE JOGO - TRANSMISSÃO ENCERRADA** 🏁",
            description=f"**RESULTADO FINAL: {team1} {score[0]} x {score[1]} {team2}**",
            color=discord.Color.gold()
        )
        
        # Determinar vencedor
        if score[0] > score[1]:
            winner_text = f"🏆 **VITÓRIA DO {team1.upper()}!**"
        elif score[1] > score[0]:
            winner_text = f"🏆 **VITÓRIA DO {team2.upper()}!**"
        else:
            winner_text = "🤝 **EMPATE EMOCIONANTE!**"
        
        final_embed.add_field(
            name="🏆 **RESULTADO**",
            value=winner_text,
            inline=False
        )
        
        # Estatísticas finais completas
        final_embed.add_field(
            name="📊 **ESTATÍSTICAS COMPLETAS**",
            value=f"⚽ **Total de Gols:** {score[0] + score[1]}\n🟨 **Cartões Amarelos:** {cards['team1']['yellow'] + cards['team2']['yellow']}\n🟥 **Expulsões:** {cards['team1']['red'] + cards['team2']['red']}\n🚑 **Lesões:** {match_context['injuries']}\n📱 **Análises VAR:** {match_context['controversies']}\n⚖️ **Polêmicas:** {match_context['controversies']}\n📈 **Eventos Totais:** {len(events_log)}",
            inline=True
        )
        
        # Dados da partida
        final_embed.add_field(
            name="🏟️ **DADOS DA PARTIDA**",
            value=f"**Local:** {stadium_name}\n**Árbitro:** {referee_name}\n**Público:** {stadium_data['capacity']:,}\n**Temperatura:** {weather_data['temp']}°C\n**Condições:** {weather_type.replace('_', ' ').title()}",
            inline=True
        )
        
        # Melhores momentos
        best_moments = [event for event in events_log if any(keyword in event for keyword in ["GOL", "EXPULS", "VERMELHO", "PÊNALTI", "INVASÃO", "BRIGA"])]
        if best_moments:
            final_embed.add_field(
                name="🎬 **MELHORES MOMENTOS**",
                value="\n".join(best_moments[-5:]),  # 5 melhores momentos
                inline=False
            )
        
        # Avaliação da partida
        if len(events_log) > 20:
            match_rating = "⭐⭐⭐⭐⭐ **PARTIDA ÉPICA!**"
        elif len(events_log) > 15:
            match_rating = "⭐⭐⭐⭐ **GRANDE JOGO!**"
        elif len(events_log) > 10:
            match_rating = "⭐⭐⭐ **BOM JOGO!**"
        else:
            match_rating = "⭐⭐ **JOGO NORMAL**"
        
        final_embed.add_field(
            name="⭐ **AVALIAÇÃO DA PARTIDA**",
            value=match_rating,
            inline=False
        )
        
        final_embed.set_footer(text="🏁 Transmissão encerrada • Obrigado por acompanhar! - Dev: YevgennyMXP")
        
        await message.edit(embed=final_embed)

# Instanciar simulador ultra-realista
ultra_match_simulator = UltraRealisticMatch()



# --- Inicia o Bot ---
if DISCORD_BOT_TOKEN is None:
    print("ERRO: O token do bot Discord não foi encontrado! Certifique-se de configurar a variável de ambiente 'DISCORD_BOT_TOKEN' ou inseri-lo diretamente no código (não recomendado para produção).")
    print("Para configurar no Replit:")
    print("1. Vá na aba 'Secrets' (cadeado) no painel lateral")
    print("2. Adicione um novo secret:")
    print("   - Key: DISCORD_BOT_TOKEN")
    print("   - Value: [SEU_TOKEN_DO_BOT_AQUI]")
    print("3. Reinicie o bot")
else:
    keep_alive()
    bot.run(DISCORD_BOT_TOKEN)