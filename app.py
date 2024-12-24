from flask import Flask, jsonify, request, send_file, session, redirect, url_for
import random
import time, json
import manager
import requests
from multiprocessing import Process
from telegram.error import Conflict
from manager import update_bot_status, get_bot_by_id, get_all_active_bots
from registro import main
from bot import run_bot

master_config = json.loads(open('./config.json', 'r').read())
app = Flask(__name__)
app.secret_key = master_config['secret_key']
processes = {
    'bot':'process',
}
bots_data = []

dashboard_data = {
    "botsActive": 0,
    "usersCount": 0,
    "salesCount": 0
}

debug = True

#===============================================================================================================================
# GERENCIADOR DE BOTS 
#===============================================================================================================================
# MOD BY <GW>

bots_data = {}
processes = {}
tokens = []

def start_bot(new_token, bot_id):
    """Inicia um novo bot em um processo separado."""
    if not new_token in tokens:
        update_bot_status(new_token, 'true')

        process = Process(target=run_bot, args=(new_token, bot_id))
        process.start()

        tokens.append(new_token)
        bot = get_bot_by_id(bot_id)
        bot_details = manager.check_bot_token(new_token)
        bot_obj = {
            'id': bot_id,
            'url':f'https://t.me/{bot_details['result'].get('username', "INDEFINIDO")}',
            'token': bot[1],
            'owner': bot[2],
            'data': json.loads(bot[4])
        }
        bots_data[str(bot_id)] = bot_obj
        processes[str(bot_id)] = process
        
        return True

def start_register():
    register = Process(target=main)
    register.start()

def initialize_all_registered_bots():
    """Inicializa todos os bots registrados e ativos."""
    global bots_data, processes
    bots = get_all_active_bots()

    for bot in bots:
        bot_id = bot[0]

        # Verifica se já existe um processo rodando para este bot
        if bot_id in processes and processes[str(bot_id)].is_alive():
            print(f"Bot {bot_id} já está em execução. Ignorando nova inicialização.")
            continue

        try:
            start_bot(bot[1], bot_id)
            print(f"Bot {bot_id} iniciado com sucesso.")
            
        except Exception as e:
            print(f"Erro ao iniciar o bot {bot_id}: {e}")



@app.route('/', methods=['GET'])
def home():
    if session.get("auth", False):
        
        """
        Retorna os dados do dashboard.
        """
        print(session)
        # Simulação de alterações dinâmicas nos dados
        dashboard_data['botsActive'] = len(manager.get_all_active_bots())
        dashboard_data['usersCount'] = '?'
        dashboard_data['salesCount'] = len(manager.get_payments_by_status('paid'))
        return send_file('./templates/terminal.html')
    return redirect(url_for('login'))


@app.route('/visualizar', methods=['GET'])
def view():
    if session.get("auth", False):
        return send_file('./templates/bots.html')
    return redirect(url_for('login'))

@app.route('/delete/<id>', methods=['DELETE'])
def delete(id):
    if session.get("auth", False):
        processes[id].kill()
        open('blacklist.txt', 'a').write(str(bots_data[id]['owner'])+'\n')
        processes.pop(id)
        bots_data.pop(id)
        manager.delete_bot(id)
        return 'true'
    else:
        return 403

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        username = request.form['password']
        if username == master_config['password']:
            session['auth'] = True  # Armazena o autorização da sessão
            return redirect('/')
    return '''
        <form method="post">
            <p><input type="text" name="password" placeholder="Digite a senha"></p>
            <p><input type="submit" value="Entrar"></p>
        </form>
    '''

@app.route('/start/<id>', methods=['get'])
def start(id):
    bot = get_bot_by_id(id)
    if id in processes and processes[id].is_alive():
        print(f"Bot {id} já está em execução. Ignorando nova inicialização.")
        return '', 400
    
    start_bot(bot[1], id)
    print(f"Bot {id} iniciado com sucesso.")
    return '', 200

@app.route('/dashboard-data', methods=['GET'])
def get_dashboard_data():
    if session.get("auth", False):
        dashboard_data['botsActive'] = len(manager.get_all_active_bots())
        dashboard_data['usersCount'] = '?'
        dashboard_data['salesCount'] = len(manager.get_payments_by_status('paid'))
        return jsonify(dashboard_data)

@app.route('/bots', methods=['GET'])
def bots():
    if session.get("auth", False):
        bots = []
        for i in bots_data.keys():
            print(i)
            bot = get_bot_by_id(i)

            bots_data[i]['data'] = json.loads(bot[4])
            bots.append(bots_data[i])

        return jsonify(bots)


@app.route('/terminal', methods=['POST'])
def terminal():
    if session.get("auth", False):
        """
        Processa comandos enviados pelo terminal.
        """
        data = request.get_json()
        command = data.get('command', '').strip()
        if not command:
            return jsonify({"response": "Comando vazio. Digite algo para enviar."}), 400

        # Simulação de resposta ao comando
        response = f"Comando '{command}' recebido com sucesso. Processado às {time.strftime('%H:%M:%S')}."
        return jsonify({"response": response})


@app.route('/webhook/pp/<bot_id>/<chat_id>', methods=['POST'])
def webhook(bot_id, chat_id):
    if request.content_type == 'application/json':
        data = request.get_json()
    elif request.content_type == 'application/x-www-form-urlencoded':
        data = request.form.to_dict()
    else:
        print("[ERRO] Tipo de conteúdo não suportado")  # Log de erro para tipo de conteúdo não suportado
        return jsonify({"error": "Unsupported Media Type"}), 415

    if not data:
        print("[ERRO] Dados JSON ou Form Data inválidos")  # Log de erro para dados inválidos
        return jsonify({"error": "Invalid JSON or Form Data"}), 400
    print(f"[DEBUG] Webhook recebido: {data}")  # Log para verificar dados do webhook
    transaction_id = data.get("id").lower()
    # Carrega o mapeamento de pagamentos do bot específico
    bot = manager.get_bot_by_id(bot_id)
    # Verifica o status do pagamento
    if data.get('status', '').lower() == 'paid':
        print(transaction_id + ' Pago')
        manager.update_payment_status(transaction_id, 'paid')
    else:
        print("[ERRO] Status do pagamento não é 'paid'")  # Log para status diferente de "paid"

    return jsonify({"status": "success"})
keys = {}


@app.route('/key', methods=['GET'])
def get_key():
    bot_id = request.args.get('bot_id')
    key = request.args.get('key')
    if key and bot_id:
        keys[bot_id] = key
        return 'Chave recebida', 200
    else:
        return 'Chave incompleta', 400

@app.route('/callback', methods=['GET'])
def callback():
    """
    Endpoint para receber o webhook de redirecionamento do Mercado Pago.
    """
    # Obter o authorization_code da query string
    TOKEN_URL = "https://api.mercadopago.com/oauth/token"

    authorization_code = request.args.get('code')
    bot_id = request.args.get('state')

    if not authorization_code:
        return jsonify({"error": "Authorization code not provided"}), 400

    try:
        # Dados para a troca de tokens
        
        payload = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": authorization_code,
            "redirect_uri": IP_DA_VPS+'/callback',  # A mesma configurada no Mercado Pago
            "state":bot_id,
            "code_verifier":keys[bot_id]
        }
        
        # Fazer a requisição para obter o token
        response = requests.post(TOKEN_URL, data=payload)
        response_data = response.json()

        if response.status_code == 200:
            # Sucesso - Retorna o access token
            access_token = response_data.get("access_token")
            print(access_token)
            manager.update_bot_payment(bot_id, {'type':"MP", 'token':access_token})
            return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Token Cadastrado</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f9;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            color: #333;
        }
        .container {
            background-color: #fff;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            padding: 20px 30px;
            text-align: center;
            max-width: 400px;
        }
        .container h1 {
            color: #4caf50;
            font-size: 24px;
            margin-bottom: 10px;
        }
        .container p {
            font-size: 16px;
            margin-bottom: 20px;
        }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            font-size: 14px;
            color: #fff;
            background-color: #4caf50;
            text-decoration: none;
            border-radius: 4px;
            transition: background-color 0.3s ease;
        }
        .btn:hover {
            background-color: #45a049;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Token Cadastrado com Sucesso!</h1>
        <p>O seu token Mercado Pago está pronto para uso.</p>
      
    </div>
</body>
</html>
"""
        else:
            # Erro na troca de tokens
            return jsonify({"error": response_data}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


CLIENT_ID = "4160833868783446"
CLIENT_SECRET = "GODqR68FqsUOL7JcurhKrNAScjqZ9GVa"
IP_DA_VPS = master_config['url']


if __name__ == '__main__':
    # Inicializar todos os bots registrados automaticamente
    print('Inciando Database')
    manager.create_database()
    start_register()
    print('Inciando Bots')
    initialize_all_registered_bots()
    print('Bots Iniciados')
    app.run(debug=False, host='0.0.0.0', port=4040)



#DEV BY <GL>