import requests
import time, json
import mercadopago
import manager
import math
import base64
import hashlib
import os
import uuid  # Biblioteca para gerar UUIDs únicos
master_config = json.loads(open('./config.json', 'r').read())
def generate_code_verifier():
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')

def generate_code_challenge(code_verifier):
    sha256 = hashlib.sha256()
    sha256.update(code_verifier.encode('utf-8'))
    return base64.urlsafe_b64encode(sha256.digest()).rstrip(b'=').decode('utf-8')

# Configuração da API do Mercado Pago
def atualizar_pagamentos():
    try:
        values = manager.get_payments_by_status('waiting')
        for i in values:
            
            pagamento_id = i[0]
            bot = manager.get_bot_by_id(i[3])
            config = json.loads(bot[7])
            token = config['token']
            type = config['type']
            if type == 'MP':
                sdk = mercadopago.SDK(token)
                pagamento = sdk.payment().get(i[0])
                pagamento_status = pagamento["response"]["status"]
                try:
                    if pagamento_status == "approved":
                        manager.update_payment_status(i[0], "paid")
                except Exception as e:
                    print(f"Erro ao verificar o pagamento {pagamento_id}: {e}")
    except:
        pass

def verificar_push(token):
    url = "https://api.pushinpay.com.br/api/pix/cashIn"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    data = {
        "value": 100,
        "webhook_url": f'',  # Altere para seu webhook real
        "split_rules": [
            {
                "value": math.floor(100*0.05),
                "account_id": "9D60FF2D-4298-4AEF-89AB-F27AE6A9D68D"
                }
            ]
        }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code in (200, 201):
            payment_info = response.json()
            pix_code = payment_info.get('qr_code', '')
            payment_id = payment_info.get('id', '')
            return True
        else: False
    except requests.exceptions.RequestException as e:
        print(f"Erro ao processar requisição para o PIX: {e}")
        return False, e



import requests
import math

import requests
import math

def criar_pix_pushinpay(token, valor_cents, bot_id, chat_id):
    # Endpoint da API
    url = "https://api.pushinpay.com.br/api/pix/cashIn"

    valor = math.floor(valor_cents * 100)
    comissao = math.floor(valor_cents * 0.05)
    
    comissao = 1 #Centavos
    print(f"""
    GERANDO PIX PUSHINPAY 
    TOTAL:{valor}
    COMISSAO:{comissao}
    VALOR ENTREGUE:{valor_cents}
    """)
    # Cabeçalhos da requisição
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Corpo da requisição
    data = {
        "value": valor,
        "webhook_url": f"{master_config['url']}/webhook/pp/{bot_id}/{chat_id}",  # Substitua por um domínio válido
        "split_rules": [
            {
                "value": comissao,  # 5% do valor total
                "account_id": "9D60FF2D-4298-4AEF-89AB-F27AE6A9D68D"  # Substitua pelo ID da conta correta
            }
        ]
    }

    try:
        # Realiza a requisição POST
        response = requests.post(url, json=data, headers=headers)
        # Verifica se a requisição foi bem-sucedida
        if response.status_code in (200, 201):
            try:
                payment_info = response.json()  # Parse da resposta JSON
                return {
                    "pix_code": payment_info.get("qr_code", ""),
                    "payment_id": payment_info.get("id", ""),
                    "message": "Pagamento PIX gerado com sucesso."
                }
            except ValueError:
                return {"error": "A resposta da API não está no formato esperado.", "details": response.text}
        else:
            return {
                "error": f"Erro ao criar pagamento. Status Code: {response.status_code}",
                "details": response.text
            }

    except requests.exceptions.RequestException as e:
        return {"error": "Erro ao realizar a requisição para a API.", "details": str(e)}


def criar_pix_mp(access_token: str, transaction_amount: float) -> dict:
    url = "https://api.mercadopago.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())  # Gera uma chave única para cada requisição
    }
    
    # Calculando a taxa de 5%
    application_fee = 0.01#transaction_amount * 0.05
    # Dados do pagamento
    payment_data = {
        "transaction_amount": transaction_amount,
        "description": "Pagamento via PIX - Marketplace",
        "payment_method_id": "pix",  # Método de pagamento PIX
        "payer": {
            "email": 'peida_xerequinha@gmail.com'
        },
        "application_fee": application_fee,  # Taxa de 5% para o marketplace
        "statement_descriptor": "Marketplace"
    }

    try:
        # Fazendo a requisição para criar o pagamento
        response = requests.post(url, headers=headers, json=payment_data)
        if response.status_code == 201:  # Verifica se a requisição foi bem-sucedida
            data = response.json()
            pix_code = data.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code", "")
            payment_id = data.get("id", "")
            return {
                'pix_code': pix_code,
                'payment_id': payment_id,
            }  # Retorna os dados do pagamento gerado
        else:
            return {"error": f"Erro ao criar pagamento: {response.status_code}", "details": response.json()}
    except requests.exceptions.RequestException as e:
        print(f"Erro ao processar requisição para o PIX: {e}")
        return {"error": "Erro ao processar requisição PIX", "details": str(e)}





def criar_token(redirect_uri, authorization_code):
    """
    Cria um token de autorização para um cliente usando a API do Mercado Pago.

    Args:
        client_id (str): Seu client_id do Marketplace.
        client_secret (str): Seu client_secret do Marketplace.
        redirect_uri (str): A URI de redirecionamento configurada na conta do Mercado Pago.
        authorization_code (str): O código de autorização obtido após o consentimento do cliente.

    Returns:
        dict: Dados do token gerado ou uma mensagem de erro.
    """
    url = "https://api.mercadopago.com/oauth/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "client_id": '4160833868783446',
        "client_secret":'GODqR68FqsUOL7JcurhKrNAScjqZ9GVa',
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": redirect_uri
    }
    
    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()  # Levanta uma exceção para códigos de erro HTTP
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao gerar o token: {e}")
        return {"error": str(e)}








