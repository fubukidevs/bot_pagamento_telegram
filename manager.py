import sqlite3, json
from multiprocessing import Process
from bot import run_bot
from registro import main
import mercadopago
import requests
from multiprocessing import Process

default = {
    "config":{'start_text': '', 'start_text2': '💼  Bem-vindo! Defina a mensagem inicial com os comandos /texto, /texto2 ou /midia_inicial.', 'start_media': None, 'button_text': 'CLIQUE AQUI PARA ACESSAR'},
    "recovery":[
            {
                "midia": None,
                "texto": "Lembrete: não se esqueça de concluir sua compra!",
                "tempo": 8640000,
                "desconto": 10.0  # Desconto de 10%
            },
            {
                "midia": None,
                "texto": "Estamos aguardando seu pagamento.",
                "tempo": 8640000,
                "desconto": 20.0  # Desconto de 20%
            },
            {
                "midia": None,
                "texto": "Última chance! Não perca a oportunidade de concluir sua compra.",
                "tempo": 8640000,
                "desconto": 50.0  # Desconto de 50%
            }
        ]
}


def calcular_tempo(dias_totais):
    """
    Converte uma quantidade de dias em anos, meses, semanas e dias.
    
    :param dias_totais: Número total de dias.
    :return: Uma string formatada com o resultado.
    """
    # Constantes
    DIAS_POR_ANO = 365
    DIAS_POR_MES = 30
    DIAS_POR_SEMANA = 7

    # Cálculos
    anos = dias_totais // DIAS_POR_ANO
    dias_restantes = dias_totais % DIAS_POR_ANO

    meses = dias_restantes // DIAS_POR_MES
    dias_restantes %= DIAS_POR_MES

    semanas = dias_restantes // DIAS_POR_SEMANA
    dias_restantes %= DIAS_POR_SEMANA
    text = 'Seu plano possui'
    result = {
        'Anos':anos,
        'Meses':meses,
        'Semanas':semanas,
        'Dias':dias_restantes
    }
    for key in result.keys():
        if result[key] > 0:
            text = f'{text}, {result[key]} {key}'
    return text

#===============================================================================================================================
# GERENCIADOR DE DATABASE
#===============================================================================================================================
#CREATED BY <GW>

def check_bot_token(token):
    response = requests.get(f'https://api.telegram.org/bot{token}/getMe')
    if response.status_code == 200:
        return json.loads(response.text)
    else:
        return False

def bot_banned(id):
    ban = open('blacklist.txt', 'r').read()
    banned_list = ban.split('\n')
    if id in banned_list:
        print('banned '+id)
        return True
    print('ok '+id)
    return False



def start_bot(new_token, id):


    update_bot_status(new_token, 'true')
    process = Process(target=run_bot, args=(new_token, id))
    process.start()
    bot = get_bot_by_id(id)
    bot_obj = {
        'id': id,
        'token': bot[1],
        'owner': bot[2],
        'data': bot[4]
    }
    return {'process': process, 'bot': bot_obj}


def create_database():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS BOTS (
            id INTEGER PRIMARY KEY,
            token TEXT UNIQUE,
            owner TEXT,
            status TEXT CHECK(status IN ('true', 'false')),
            config TEXT,
            recovery TEXT,
            plans TEXT,
            payment TEXT,
            users TEXT,
            upsell TEXT,
            "group" TEXT
        )
        """
    )
    conn.commit()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS USERS (
            user TEXT,
            plan TEXT,
            "group" TEXT,
            "join" TEXT,
            expiration TEXT
        )
        """
    )
    conn.commit()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS PAYMENTS (
            id TEXT,
            chat TEXT,
            plano TEXT,
            bot TEXT,
            status TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def bot_exists(token):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM BOTS WHERE token = ?", (token,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def get_bot_by_token(token):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM BOTS WHERE token = ?", (token,))
    bot = cursor.fetchone()
    conn.close()
    return bot

def get_bot_by_id(bot_id):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM BOTS WHERE id = ?", (bot_id,))
    bot = cursor.fetchone()
    conn.close()
    return bot
#DELETE FROM bots WHERE id = X;

def get_all_bots():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM BOTS")
    bot = cursor.fetchall()
    conn.close()
    return bot

def get_all_active_bots():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM BOTS WHERE status = ?", ('true',))
    bots = cursor.fetchall()
    conn.close()
    return bots


def create_bot(id, token, owner, status="false", config=default['config'], recovery=default["recovery"], plans={}, payment={}, upsell={"text": "", "media": None, "type": None}, group=''):
    if bot_exists(token):
        return False
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO BOTS (id, token, owner, status, config, recovery, plans, payment, users, upsell, 'group') VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, token, owner, status, json.dumps(config), json.dumps(recovery), json.dumps(plans), json.dumps(payment), '', json.dumps(upsell), group)
    )
    conn.commit()
    conn.close()
    return

def delete_bot(id):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute(
        f"DELETE FROM BOTS WHERE id = {id}"
    )
    conn.commit()
    conn.close()
    return


def update_bot_status(token, status):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET status = ? WHERE token = ?", (status, token))
    conn.commit()
    conn.close()

def update_bot_config(bot_id, config):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET config = ? WHERE id = ?", (json.dumps(config), bot_id))
    conn.commit()
    conn.close()

def update_bot_upsell(bot_id, upsell):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET upsell = ? WHERE id = ?", (json.dumps(upsell), bot_id))
    conn.commit()
    conn.close()

def update_bot_recovery(bot_id, recovery):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET recovery = ? WHERE id = ?", (json.dumps(recovery), bot_id))
    conn.commit()
    conn.close()

def update_bot_plans(bot_id, plans):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET plans = ? WHERE id = ?", (json.dumps(plans), bot_id))
    conn.commit()
    conn.close()

def update_bot_payment(bot_id, payment):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET payment = ? WHERE id = ?", (json.dumps(payment), bot_id))
    conn.commit()
    conn.close()

def update_bot_users(bot_id, users):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET users = ? WHERE id = ?", (users, bot_id))
    conn.commit()
    conn.close()

def update_bot_group(bot_id, group):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE BOTS SET 'group' = ? WHERE id = ?", (group, bot_id))
    conn.commit()
    conn.close()

def create_payment(id, chat, plano, bot, status='waiting'):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO PAYMENTS (id, chat, plano, bot, status) VALUES (?, ?, ?, ?, ?)",
        (id, chat, plano, bot, status)
    )
    conn.commit()
    conn.close()
    return

def update_payment_status(id, status):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE PAYMENTS SET status = ? WHERE id = ?", (status, id))
    conn.commit()
    conn.close()

def get_payment_by_id(id):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM PAYMENTS WHERE id = ?", (id,))
    payment = cursor.fetchone()
    conn.close()
    return payment

def get_payment_by_chat(id):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM PAYMENTS WHERE chat = ?", (id,))
    payment = cursor.fetchone()
    conn.close()
    return payment


def get_payment_by_chat(id):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM PAYMENTS WHERE chat = ?", (id,))
    payment = cursor.fetchone()
    conn.close()
    return payment

def get_payments_by_status(status):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM PAYMENTS WHERE status = ?", (status,))
    payment = cursor.fetchall()
    conn.close()
    return payment





