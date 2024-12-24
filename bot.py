import nest_asyncio, asyncio, os, requests, queue, json, re, threading

import manager, payment

from multiprocessing import Process
from asyncio import Lock
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters, Updater, CallbackContext, ChatJoinRequestHandler
from telegram.error import BadRequest, Conflict

from flask import Flask, request, jsonify
from flask_cors import CORS

from datetime import datetime, timedelta
from urllib.parse import urlparse

async def verificar_chat_existe(chat_id: int) -> bool:
    bot_instance = bot_application.bot
    """
    Verifica se um chat de usuário existe no Telegram.

    Args:
        bot (Bot): Instância do bot do Telegram.
        chat_id (int): ID do chat do usuário.

    Returns:
        bool: Retorna True se o chat existir, False caso contrário.
    """
    try:
        # Tenta buscar informações do chat
        await bot_instance.get_chat(chat_id)
        return True
    except (BadRequest):
        # BadRequest ou Unauthorized indicam que o chat não existe ou não está acessível
        return False

cache = {
    'url':'',
    'plano':{
        'tempo':0,
        'tipo':'',
        'message':None
    },
    'payments':{},
    'recovery':[],
    'users_waiting':{}
}
CANCEL = 0
MEDIA, TEXT, LINK, CONFIRM = range(4)
INPUT_DESCONTO_RECUPERACAO, CONFIGURAR_RECUPERACAO, INPUT_MEDIA_RECUPERACAO, INPUT_TEXTO_RECUPERACAO, INPUT_TEMPO_RECUPERACAO = range(5)
SELECIONAR_MENSAGEM_DELETAR = 23
INPUT_UPSELL_LINK = 24  # Novo estado para o link do botão upsell
SELECIONAR_MENSAGEM = 16
CONFIRMAR_CRIACAO = 20  # Novo estado para a confirmação da criação do plano
INPUT_REMOVER_TEXTO = 9
INPUT_TOKEN = 6
INPUT_REMOVER_MIDIA = 8
SELECT_PLAN_TO_DELETE = 10
INPUT_UPSELL_CONTENT = 22
INPUT_PLAN_NAME = 3
INPUT_PLAN_DURATION = 4
INPUT_UPSELL = 21
INPUT_TEXT_BUTTON = range(1)
INPUT_PLAN_VALUE = 5
INPUT_GRUPO_ID = 7  # Novo estado para o ID do grupo 
INPUT_MEDIA_DISPARO = 101
INPUT_TEXT_DISPARO = 102
INPUT_LINK_DISPARO = 103
INPUT_PLAN_CUSTON = 105
TOKEN_RETRY = 104

master_config = json.loads(open('./config.json', 'r').read())
app = Flask(__name__)
CORS(app)  # Permite que o aplicativo Flask aceite requisições de qualquer origem


SEU_CLIENT_ID = 4160833868783446
IP_DA_API = master_config['url']
URL_REDIRECT = IP_DA_API+'/callback'



# Função para verificar se um usuário é administrador de um bot específico

async def notificar_admin(chat_id, plano_escolhido):
    bot_instance = bot_application.bot
    try:
        user = await bot_instance.get_chat(int(chat_id))
        username = user.username or "Não definido"
        first_name = user.first_name or "Não definido"

        mensagem_venda = (
            f"✅ Venda realizada!\n\n"
            f"🆔 Clientid: {chat_id}\n"
            f"👤 User: @{username}\n"
            f"📝 Nome: {first_name}\n"
            f"💵 Valor: R$ {str(plano_escolhido['valor']).replace('.', ',')}\n"
            f"🔗 Plano: {plano_escolhido['nome']}"
        )
        await bot_instance.send_message(chat_id=int(cache['owner']), text=mensagem_venda)
    except Exception as e:
        print(f'[ERROR] Erro ao notificar admin? {e}')

async def disparar_recuperacao(chat_id, payment_id):
    bot_instance = bot_application.bot
    bot_id = cache['bot_id']
    print(f'recuperação {chat_id}:{payment_id}')
    configuracoes_recuperacao = load_recuperacao_config(bot_id)

    try:
        paid = manager.get_payment_by_id(payment_id)[4]
        index = 0
        for config in configuracoes_recuperacao:
            await asyncio.sleep(config.get('tempo')*60)
            if paid != 'paid' and not cache['payments'][payment_id]['invited']:  
                # Configuração do botão "Pagar Agora"
                keyboard = [[InlineKeyboardButton("Pagar Agora", callback_data=f"pagar_{payment_id}_{index}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                media_content = config.get("midia")
                media_type = config.get("tipo", "photo")  # Padrão para 'photo'

                try:
                    if media_content:
                        if media_type == "photo":
                            await bot_instance.send_photo(chat_id=chat_id, photo=media_content, caption=config.get("texto"), reply_markup=reply_markup)
                            print(f"[INFO] Foto enviada com sucesso para chat_id {chat_id}")
                        elif media_type == "video":
                            await bot_instance.send_video(chat_id=chat_id, video=media_content, caption=config.get("texto"), reply_markup=reply_markup)
                            print(f"[INFO] Vídeo enviado com sucesso para chat_id {chat_id}")
                        else:
                            # Fallback para tentar como foto, depois vídeo
                            try:
                                await bot_instance.send_photo(chat_id=chat_id, photo=media_content, caption=config.get("texto"), reply_markup=reply_markup)
                                print(f"[INFO] Foto enviada com sucesso (fallback) para chat_id {chat_id}")
                            except Exception as e_photo:
                                print(f"[WARNING] Falha ao enviar como foto, tentando como vídeo. Erro: {e_photo}")
                                await bot_instance.send_video(chat_id=chat_id, video=media_content, caption=config.get("texto"), reply_markup=reply_markup)
                                print(f"[INFO] Vídeo enviado com sucesso (fallback) para chat_id {chat_id}")
                    else:
                        #bot_instance = bot_application.bot
                        # Caso não haja mídia, apenas envia a mensagem de texto
                        await bot_instance.send_message(chat_id=chat_id, text=config["texto"], reply_markup=reply_markup)
                        print(f"[INFO] Mensagem de texto enviada com sucesso para chat_id {chat_id}")
                except Exception as e:
                        print(f"[ERROR] Falha ao enviar a mídia ou mensagem: {e}")
            else:
                return
    except Exception as e:
        print(f"[ERROR] Erro inesperado durante o ciclo de recuperação: {e}")


async def disparar_upsell(chat_id):
    bot_instance = bot_application.bot
    upsell_message = load_upsell(cache['bot_id'])

    # Verifica se há upsell configurado
    if upsell_message and (upsell_message.get('media') or upsell_message.get('text')):
        upsell_text = upsell_message.get('text', 'Confira essa oferta especial!')
        upsell_link = upsell_message.get('link', 'https://default-link.com')  # Link padrão

                    # Envia a mídia de upsell, se houver
        if upsell_message.get('media'):
            try:
                if upsell_message['type'] == 'photo':
                    await bot_instance.send_photo(chat_id=chat_id, photo=upsell_message['media'])
                    print("[DEBUG] Foto de upsell enviada")
                elif upsell_message['type'] == 'video':
                    await bot_instance.send_video(chat_id=chat_id, video=upsell_message['media'])
                    print("[DEBUG] Vídeo de upsell enviado")
            except Exception as e:
                print(f"[ERRO] Erro ao enviar mídia de upsell: {e}")

            # Envia o texto com o botão
            upsell_keyboard = [[InlineKeyboardButton("✅  𝗔𝗖𝗘𝗜𝗧𝗔𝗥 𝗢𝗙𝗘𝗥𝗧𝗔", url=upsell_link)]]
            reply_markup = InlineKeyboardMarkup(upsell_keyboard)
            try:
                await bot_instance.send_message(chat_id=chat_id, text=upsell_text, reply_markup=reply_markup)
            except Exception as e:
                print(f"[ERRO] Erro ao enviar mensagem para chat_id {chat_id}: {e}")

async def gerar_convite(user_chat, user):
    bot_instance = bot_application.bot
    try:
        # Carrega as informações do grupo
        grupo_info = load_grupo_id(bot_id=cache['bot_id'])
        print(grupo_info)
        # Cria o link de convite com solicitação de entrada ativada
        
        
        group_invite_link = await bot_instance.create_chat_invite_link(
            chat_id=grupo_info, 
            creates_join_request=True
        )
        nickname = user.username
        # Adiciona o usuário à lista de espera para verificar ao entrar no grupo
        cache['users_waiting'][nickname] = str(user_chat)


        keyboard = [
            [InlineKeyboardButton("ENTRAR NO GRUPO", url=group_invite_link.invite_link)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot_instance.send_message(
            chat_id=user_chat,
            text="✅ Pagamento aprovado! Clique no botão abaixo para entrar no grupo.",
            reply_markup=reply_markup
        )
        print(f"[INFO] Link de convite criado com sucesso: {group_invite_link.invite_link}")
    except ValueError as ve:
        print(f"[ERRO] Erro no ID do grupo: {ve}")
        await bot_instance.send_message(
            chat_id=user_chat,
            text="❌ Não foi possível identificar o grupo. Por favor, entre em contato com o suporte."
        )
    except Exception as e:
        print(f"[ERRO] Erro ao criar link de grupo: {e}")
        await bot_instance.send_message(
            chat_id=user_chat,
            text="❌ Ocorreu um erro ao gerar o link de convite. Por favor, tente novamente mais tarde."
        )



async def check_join_request(update: Update, context: CallbackContext):
    join_request = update.chat_join_request  # Detalhes da solicitação de entrada
    user = join_request.from_user
    if str(user.username) in cache['users_waiting'].keys():
        await join_request.approve()
        await disparar_upsell(cache['users_waiting'][user.username])
        cache['users_waiting'].pop(user.username)
    #else:
        #print(f'usuario {user.username} barrado de entrar no grupo do bot {cache["bot_id"]}')
        #await join_request.decline()


#update.message.from_user


def add_payment_info(id, chat):   
    payment_object = {'chat':chat, 'recovery':[], 'invited':False}
    cache['payments'][id] = payment_object
    cache['payments'][id]['recovery_thread'] = asyncio.create_task(disparar_recuperacao(chat, id))

def add_payment_recovery(id, recovery):
    if id in cache['payments'].keys():
        cache['payments'][id]['recovery'].append(recovery) 


def remove_payment_info(id):
    cache['payments'].pop(id)

def expire_payment_info(id):
    #cache['payments'].pop(id)
    manager.update_payment_status(id, 'expired')

async def finalizar_compra(base_payment_id, user_chat, user, plano_escolhido):
    await gerar_convite(user_chat, user)
    await notificar_admin(cache['owner'], plano_escolhido)
    
    adicionar_usuario_expiracao(
                bot_id=cache['bot_id'],
                user_id=user_chat,
                grupo_id=cache['grupo'],
                duracao=calcular_duracao(plano_escolhido["duracao"])
                )
    cache['payments'][base_payment_id]['invited'] = True


async def payment_task():
    bot_instance = bot_application.bot

    print('payment task')
    while True:
        payment_cache = list(cache['payments'].keys())
        if len(payment_cache) > 0:
            payment.atualizar_pagamentos()
            for payment_id in payment_cache:
                if payment_id in cache['payments'].keys():
                    
                    user_chat = cache['payments'][payment_id]['chat']
                    user = await bot_instance.get_chat(user_chat)
                    
                        
                    if not cache['payments'][payment_id]['invited']:
                        payment_data = manager.get_payment_by_id(payment_id)
                        if payment_data[4] == 'paid':
                            print('pago normal')
                            plano_escolhido = json.loads(payment_data[2])
                            await finalizar_compra(payment_id, user_chat, user, plano_escolhido)
                        else:
                            keys = [payment_id]
                            try:
                                for key in cache['payments'][payment_id]['recovery']:
                                    print(key)
                                    if key != False:
                                        payment_data = manager.get_payment_by_id(key)
                                        if payment_data[4] == 'paid':
                                            plano_escolhido = json.loads(payment_data[2])
                                            print('pago na rec')
                                            await finalizar_compra(payment_id, user_chat, user, plano_escolhido)
                            except Exception as e:
                                print(f'ERRO AO VERIFICAR PAGAMENTOS DE REC {e}')
        await asyncio.sleep(5)      

def is_admin(chat_id):
    if str(chat_id) == str(cache['owner']):
        return True
    else:
        return False

bot_application = None
message_queue = queue.Queue()  # Fila para comunicação entre threads

def load_recuperacao_config(bot_id):
    bot = manager.get_bot_by_id(bot_id)
    if bot:
        config = json.loads(bot[5])
        return config
    else:
        return False
        
def load_grupo_id(bot_id):
    bot = manager.get_bot_by_id(bot_id)
    if bot:
        return int(bot[10])
    else: 
        return False
# Função para o comando /texto_botao
async def texto_botao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /texto_botao iniciado.")

    # Verifica se há outro comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /texto_botao devido a comando ativo.")
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /texto_botao.")
        context.user_data['conversacao_ativa'] = False
        return ConversationHandler.END

    # Obtém o bot_id para salvar a configuração corretamente
    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        
        return ConversationHandler.END

    # Salva o bot_id no user_data para uso na próxima etapa
    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True

    # Solicita o texto do botão ao usuário
    await update.message.reply_text("Envie o texto do botão inicial que deseja definir.")
    print("Solicitação de texto do botão enviada com sucesso.")

    return INPUT_TEXT_BUTTON



# Função para salvar o novo texto do botão no JSON do bot
async def salvar_texto_botao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    # Carrega a configuração do JSON e salva o novo texto do botão
    config = load_config(bot_id)
    config['button_text'] = update.message.text.strip()
    save_config(config, bot_id)

    await update.message.reply_text("Texto do botão inicial atualizado com sucesso!")
    context.user_data['conversacao_ativa'] = False  # Finaliza a operação
    return ConversationHandler.END


async def grupo_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /grupo_id.")
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa
    
    keyboard = [[InlineKeyboardButton("❌ CANCELAR", callback_data="cancelar")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("🔗 Por favor, forneça o ID do grupo:", reply_markup=reply_markup)
    print("Solicitação de ID do grupo enviada com sucesso.")
    return INPUT_GRUPO_ID



async def recebe_grupo_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Recebendo ID do grupo...")  # Log para indicar que a função foi chamada
    print(f"Estado de conversação ativa: {context.user_data.get('conversacao_ativa', False)}")  # Verifica se a conversa está ativa

    if not context.user_data.get('conversacao_ativa', False):
        print("Nenhuma operação ativa para receber o ID.")  # Log para indicar que não há operação ativa
        return ConversationHandler.END  # Finaliza a conversa se não houver operação ativa

    grupo_id = update.message.text.strip()
    bot_id = context.user_data.get('bot_id')  # Recupera o bot_id específico do user_data

    # Verifica se o bot_id foi corretamente definido
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    print(f"ID recebido do usuário: {grupo_id}")  # Log do ID recebido
    
    # Verifica se o grupo_id é um número válido
    if not grupo_id.lstrip('-').isdigit():
        await update.message.reply_text("❗️  Por favor, envie um ID de grupo válido.")
        print(f"ID inválido recebido: {grupo_id}")  # Log para indicar que o ID não é válido
        return INPUT_GRUPO_ID

    try:
        # Tenta criar o link de convite do grupo
        print(f"Tentando criar link de convite para o grupo ID: {grupo_id}")
        group_invite_link = await context.bot.create_chat_invite_link(chat_id=grupo_id, member_limit=1, creates_join_request=False)
        # Salva o ID do grupo no arquivo JSON específico do bot
        print(f"ID do grupo será salvo após confirmação de sucesso: {grupo_id}")
        manager.update_bot_group(bot_id, grupo_id)
        cache['grupo'] = grupo_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"𝗟𝗜𝗡𝗞 𝗗𝗘 𝗔𝗖𝗘𝗦𝗦𝗢 𝗔𝗢 𝗚𝗥𝗨𝗣𝗢: {group_invite_link.invite_link}")
        await update.message.reply_text("✅ ID do grupo atualizado com sucesso!")
        
    except Exception as e:
        # Se ocorrer um erro na criação do link, informa o usuário e não salva o ID
        print(f"Erro ao criar link de convite: {e}")  # Log de erro para depuração
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌  Não foi possível alterar o ID. Verifique se o bot está no grupo e possui permissões de administrador.")

    context.user_data['conversacao_ativa'] = False
    print("Estado de 'conversacao_ativa' redefinido para False após recebe_grupo_id.")
    return ConversationHandler.END

# Função para remover o texto inicial
async def remover_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /remover_texto iniciado.")

    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /remover_texto devido a comando ativo.")
        return ConversationHandler.END

    # Marca o comando como ativo antes de iniciar a função
    context.user_data['conversacao_ativa'] = True
    print("Comando /remover_texto marcado como ativo. Estado atual:", context.user_data.get('conversacao_ativa', False))

    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /remover_texto.")
        context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
        return ConversationHandler.END

    # Obtém o bot_id do user_data ou bot_data
    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
        return ConversationHandler.END

    # Carrega as configurações atuais com o bot_id
    config = load_config(bot_id)

    # Remove apenas o texto do início da configuração
    config['start_text'] = ''  # Limpa apenas o Texto 1
    save_config(config, bot_id)  # Salva a configuração atualizada no arquivo específico do bot

    await update.message.reply_text("🗑️  Texto inicial removido com sucesso!")
    print("Texto inicial removido com sucesso.")
    
    # Desmarca o comando como ativo após concluir a função
    context.user_data['conversacao_ativa'] = False
    print("Comando /remover_texto concluído. Estado atual:", context.user_data.get('conversacao_ativa', False))
    return ConversationHandler.END



async def recuperacao_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /recuperacao_compra.")
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa

    # Carrega as configurações de recuperação de compra
    context.user_data['configuracoes_recuperacao'] = load_recuperacao_config(bot_id)

    # Cria os botões para configuração das mensagens
    keyboard = [
        [InlineKeyboardButton(f"𝗠𝗘𝗡𝗦𝗔𝗚𝗘𝗠 {i+1}", callback_data=f"configurar_mensagem_{i}")]
        for i in range(3)
    ]
    keyboard.append([InlineKeyboardButton("❌ CANCELAR", callback_data='cancelar')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📦 Configure mensagens para recuperação de compra:", reply_markup=reply_markup)

    print("Solicitação de configuração de recuperação de compra enviada com sucesso.")
    return SELECIONAR_MENSAGEM




async def selecionar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    if data[-1] == 'cancelar':
        await query.edit_message_text("❌ Ação cancelada com sucesso!")
        context.user_data.clear()  # Limpa todos os dados armazenados
        context.user_data['conversacao_ativa'] = False  # Redefine o estado ativo
        print("Operação de recuperação de compra cancelada.")
        return ConversationHandler.END

    try:
        index = int(data[-1])
        context.user_data['mensagem_index'] = index
        await query.message.reply_text("🎬 Envie a mídia para usar na recuperação de compra:")
        return INPUT_MEDIA_RECUPERACAO
    except ValueError:
        await query.edit_message_text("❌ Ocorreu um erro ao processar sua solicitação.")
        return ConversationHandler.END


async def recebe_midia_recuperacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = cache['bot_id']
    configuracoes_recuperacao = json.loads(manager.get_bot_by_id(cache['bot_id'])[5])
    index = context.user_data['mensagem_index']

    try:
        if update.message.photo:
            configuracoes_recuperacao[index]["midia"] = str(update.message.photo[-1].file_id)
            configuracoes_recuperacao[index]["tipo"] = "photo"  # Armazena o tipo da mídia
            print(f"[DEBUG] Foto salva com ID: {configuracoes_recuperacao[index]['midia']}")

        elif update.message.video:
            configuracoes_recuperacao[index]["midia"] = str(update.message.video.file_id)
            configuracoes_recuperacao[index]["tipo"] = "video"  # Armazena o tipo da mídia
            print(f"[DEBUG] Vídeo salvo com ID: {configuracoes_recuperacao[index]['midia']}")

        else:
            await update.message.reply_text("❗️ Tipo de mídia não suportado. Por favor, envie uma foto ou vídeo.")
            return INPUT_MEDIA_RECUPERACAO
        context.user_data['configuracoes_recuperacao'] = configuracoes_recuperacao
        #save_recuperacao_config(configuracoes_recuperacao, bot_id)
        await update.message.reply_text("📝 Digite o texto para a recuperação de compra:")

        return INPUT_TEXTO_RECUPERACAO
    except Exception as e:
        print(f"[ERROR] Erro ao salvar a mídia: {e}")
        await update.message.reply_text("❗️ Ocorreu um erro ao processar a mídia. Tente novamente.")
        return INPUT_MEDIA_RECUPERACAO



async def remover_midia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /remover_midia iniciado.")

    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /remover_midia devido a comando ativo.")
        return ConversationHandler.END

    # Marca o comando como ativo antes de iniciar a função
    context.user_data['conversacao_ativa'] = True
    print("Comando /remover_midia marcado como ativo. Estado atual:", context.user_data.get('conversacao_ativa', False))

    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /remover_midia.")
        context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
        return ConversationHandler.END

    # Obtém o bot_id do user_data ou bot_data
    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
        return ConversationHandler.END

    # Carrega as configurações específicas do bot
    config = load_config(bot_id)

    # Remove a mídia da configuração
    config['start_media'] = None
    save_config(config, bot_id)  # Salva a configuração atualizada no arquivo específico do bot

    await update.message.reply_text("🗑️ A mídia inicial foi excluída com sucesso!")
    print("Mídia inicial removida com sucesso.")
    
    # Desmarca o comando como ativo após concluir a função
    context.user_data['conversacao_ativa'] = False
    print("Comando /remover_midia concluído. Estado atual:", context.user_data.get('conversacao_ativa', False))
    return ConversationHandler.END




async def recebe_texto_recuperacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')
    configuracoes_recuperacao = context.user_data.get('configuracoes_recuperacao')

    index = context.user_data['mensagem_index']
    configuracoes_recuperacao[index]["texto"] = update.message.text
    context.user_data['configuracoes_recuperacao'] = configuracoes_recuperacao
    #save_recuperacao_config(configuracoes_recuperacao, bot_id)

    await update.message.reply_text("💲 Envie o valor que quer aplicar na recuperação de compra:")
    return INPUT_DESCONTO_RECUPERACAO

async def recebe_desconto_recuperacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')
    configuracoes_recuperacao = context.user_data.get('configuracoes_recuperacao')

    index = context.user_data['mensagem_index']
    try:
        desconto = float(update.message.text.strip())
        if desconto < 3.99:
            raise ValueError("Valor inválido.")
        configuracoes_recuperacao[index]["desconto"] = desconto
        context.user_data['configuracoes_recuperacao'] = configuracoes_recuperacao
        #save_recuperacao_config(configuracoes_recuperacao, bot_id)
        await update.message.reply_text("⏱️ Defina o tempo de envio (em minutos) para este lembrete:")
        return INPUT_TEMPO_RECUPERACAO
    except ValueError:
        await update.message.reply_text("❗️ Por favor, envie um valor válido apartir de 4 reais.")
        return INPUT_DESCONTO_RECUPERACAO
    

async def recebe_tempo_recuperacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')
    configuracoes_recuperacao = context.user_data.get('configuracoes_recuperacao')

    index = context.user_data['mensagem_index']
    try:
        configuracoes_recuperacao[index]["tempo"] = int(update.message.text)
        save_recuperacao_config(configuracoes_recuperacao, bot_id)
        await update.message.reply_text("Configuração de mensagem de recuperação salva com sucesso!")
    except ValueError:
        await update.message.reply_text("❗️ Por favor, envie um número válido para o tempo.")
        return INPUT_TEMPO_RECUPERACAO

    context.user_data['conversacao_ativa'] = False  # Finaliza a operação
    return ConversationHandler.END

# Função para o comando /deletar_recuperacao
async def deletar_recuperacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /deletar_recuperacao iniciado.")

    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        print("Encerrando /deletar_recuperacao devido a comando ativo.")
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /deletar_recuperacao.")
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa

    # Carrega as configurações de recuperação para o bot
    context.user_data['configuracoes_recuperacao'] = load_recuperacao_config(bot_id)

    # Cria o teclado para seleção das mensagens de recuperação
    keyboard = [
        [InlineKeyboardButton(f"𝗠𝗘𝗡𝗦𝗔𝗚𝗘𝗠 {i + 1}", callback_data=f"deletar_mensagem_{i}")]
        for i in range(3)
    ]
    keyboard.append([InlineKeyboardButton("❌ CANCELAR", callback_data='cancelar')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📦 Selecione a mensagem de recuperação que deseja deletar:", reply_markup=reply_markup)
    print("Teclado de seleção enviado com sucesso.")

    return SELECIONAR_MENSAGEM_DELETAR




# Função para processar a seleção de mensagem e redefinir a configuração
async def confirmar_deletar_recuperacao(update, context):
    query = update.callback_query
    await query.answer()

    bot_id = context.user_data.get('bot_id')
    configuracoes_recuperacao = context.user_data.get('configuracoes_recuperacao')

    data = query.data.split("_")
    if len(data) == 3 and data[1] == "mensagem":
        try:
            index = int(data[2])
            if index < len(configuracoes_recuperacao):
                configuracoes_recuperacao[index] = {"midia": None, "texto": "", "tempo": 0}
                save_recuperacao_config(configuracoes_recuperacao, bot_id)
                await query.edit_message_text(f"✅ Mensagem {index + 1} de recuperação redefinida com sucesso!")
            else:
                await query.message.reply_text("Erro ao redefinir a mensagem. Índice inválido.")
        except ValueError:
            await query.message.reply_text("Erro ao processar a mensagem de recuperação. Tente novamente.")
    else:
        await query.message.reply_text("Erro ao processar a mensagem de recuperação. Tente novamente.")

    context.user_data['conversacao_ativa'] = False  # Finaliza a operação
    return ConversationHandler.END



# Função para o comando /excluir_plano
async def excluir_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores

    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador para o bot atual
    if not is_admin(chat_id):
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa

    planos = load_plans(bot_id)  # Carrega os planos associados ao bot_id

    if not planos:
        await update.message.reply_text("Não há planos disponíveis para exclusão.")
        context.user_data['conversacao_ativa'] = False  # Finaliza a operação se não houver planos
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(plano['nome'], callback_data=f"delete_{plano_id}")]
        for plano_id, plano in planos.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Selecione o plano que deseja excluir:", reply_markup=reply_markup)

    return SELECT_PLAN_TO_DELETE




# Função para processar a exclusão do plano selecionado
async def confirmar_exclusao_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    bot_id = context.user_data.get('bot_id')
    planos = load_plans(bot_id)

    plano_id = query.data.replace("delete_", "")

    if plano_id in planos:
        del planos[plano_id]
        save_plans(planos, bot_id)
        await query.edit_message_text("✅ Plano deletado com sucesso.")
    else:
        await query.edit_message_text("Erro: plano não encontrado.")

    context.user_data['conversacao_ativa'] = False  # Finaliza a operação
    return ConversationHandler.END

# Função para carregar a lista de IDs de usuários
def load_user_ids(bot_id):
    bot = manager.get_bot_by_id(bot_id)
    return str(bot[8]).split(':')
    
    
def is_valid_url(url):
    try:
        # Adiciona 'https://' se não houver esquema
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False
    
   ######################################## REMOVER USER DO GRUPO @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@  






async def monitorar_entrada_e_revogar(bot_instance, grupo_id, user_id, invite_link, timeout=60):
    """
    Monitora se o usuário entrou no grupo e revoga o link após a entrada ou expiração do timeout.
    """
    try:
        for _ in range(timeout):  # Verifica durante o tempo especificado (timeout segundos)
            membro = await bot_instance.get_chat_member(chat_id=grupo_id, user_id=user_id)
            
            # Verifica se o usuário já é membro
            if membro.status in ['member', 'administrator', 'creator']:
                print(f"[INFO] Usuário {user_id} entrou no grupo {grupo_id}. Revogando link...")
                await bot_instance.revoke_chat_invite_link(chat_id=grupo_id, invite_link=invite_link)
                return
            
            # Espera 1 segundo antes da próxima verificação
            await asyncio.sleep(1)

        # Se o tempo acabar e o usuário não entrar, revoga o link
        print(f"[INFO] Tempo de entrada esgotado para o usuário {user_id}. Revogando link...")
        await bot_instance.revoke_chat_invite_link(chat_id=grupo_id, invite_link=invite_link)

    except Exception as e:
        print(f"[ERRO] Erro ao monitorar entrada ou revogar link: {e}")






def adicionar_usuario_expiracao(bot_id, user_id, grupo_id, duracao):
    """
    Registra o usuário no sistema de expiração com datas completas (YYYY-MM-DD HH:MM:SS).
    """
    filename = f"bot{bot_id}_expiracao_user.json"

    # Calcula a data de expiração
    data_atual = datetime.now()
    data_expiracao = data_atual + timedelta(days=duracao)

    # Formata as datas no padrão completo
    data_atual_formatada = data_atual.strftime("%Y-%m-%d %H:%M:%S")
    data_expiracao_formatada = data_expiracao.strftime("%Y-%m-%d %H:%M:%S")

    # Carrega os dados existentes ou cria um novo
    try:
        with open(filename, 'r') as file:
            expiracao_data = json.load(file)
    except FileNotFoundError:
        expiracao_data = {}

    # Adiciona o novo usuário
    expiracao_data[str(user_id)] = {
        "grupo_id": str(cache['grupo']),
        "data_entrada": data_atual_formatada,
        "data_expiracao": data_expiracao_formatada
    }

    # Salva o arquivo atualizado
    with open(filename, 'w') as file:
        json.dump(expiracao_data, file, indent=4)
    
    
async def verificar_usuarios_expirados(bot_id, bot_instance):
    filename = f'bot{bot_id}_expiracao_user.json'
    try:
        # Carrega os dados do arquivo
        with open(filename, 'r') as file:
            expiracao_data = json.load(file)
    except FileNotFoundError:
        print("Nenhum arquivo de expiração encontrado.")
        return

    # Obtém a data atual
    agora = datetime.now()

    usuarios_removidos = []
    for user_id, info in expiracao_data.items():
        data_expiracao = datetime.fromisoformat(info["data_expiracao"])
        if agora >= data_expiracao:
            grupo_id = info["grupo_id"]

            try:
                # Remove o usuário do grupo
                await bot_instance.ban_chat_member(chat_id=grupo_id, user_id=user_id)
                print(f"Usuário {user_id} removido do grupo {grupo_id}.")
                
                # Desbane o usuário imediatamente
                await bot_instance.unban_chat_member(chat_id=grupo_id, user_id=user_id)
                print(f"Usuário {user_id} desbanido do grupo {grupo_id}.")

                # Envia mensagem ao usuário
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=f"⏳ Seu plano expirou. Você foi removido do grupo {grupo_id}. Para renovar, entre em contato conosco!"
                )
                usuarios_removidos.append(user_id)
            except Exception as e:
                print(f"Erro ao remover/desbanir usuário {user_id}: {e}")

    # Remove os usuários expirados do arquivo
    for user_id in usuarios_removidos:
        del expiracao_data[user_id]

    # Atualiza o arquivo
    with open(filename, 'w') as file:
        json.dump(expiracao_data, file)


async def agendar_verificacao_expiracao(bot_id, bot_instance):
    while True:
        print("Verificando usuários expirados...")
        await verificar_usuarios_expirados(bot_id, bot_instance)
        await asyncio.sleep(30)  # Aguarda 1 hora antes de verificar novamente 
    
def calcular_duracao(duracao_str):
    """
    Converte a duração de um plano em dias.
    Exemplo: "10 dias" -> 10, "1 mês" -> 30.
    """
    unidades = {
        "dia": 1,
        "dias": 1,
        "semana": 7,
        "semanas": 7,
        "mês": 30,
        "meses": 30,
        "ano": 365,
        "anos": 365
    }

    partes = duracao_str.split()
    if len(partes) != 2:
        raise ValueError(f"Formato inválido para duração: {duracao_str}")

    quantidade, unidade = int(partes[0]), partes[1].lower()
    if unidade not in unidades:
        raise ValueError(f"Unidade desconhecida: {unidade}")

    return quantidade * unidades[unidade]


######################################## REMOVER USER DO GRUPO @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@  


async def disparo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /disparo iniciado.")

    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /disparo devido a comando ativo.")
        return ConversationHandler.END

    try:
        # Marca o comando como ativo antes de resetar
        context.user_data['conversacao_ativa'] = True
        print("Comando /disparo marcado como ativo. Estado atual:", context.user_data['conversacao_ativa'])

        # Reseta qualquer conversa anterior, mas mantém o estado ativo
        await reset_conversation(update, context)

        # Obtém o token do bot atual
        bot_token = context.bot.token

        # Verifica se o usuário é administrador do bot atual
        chat_id = update.effective_user.id
        if not is_admin(chat_id):
            print("Usuário não autorizado para /disparo.")
            await update.message.reply_text("⚠️ Você não tem permissão para executar este comando.")
            context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
            return ConversationHandler.END

        # Solicita a mídia ao usuário
        await update.message.reply_text("Envie a mídia (imagem ou vídeo) para o disparo.")
        print("Solicitação de mídia enviada ao usuário.")
        return MEDIA
    except Exception as e:
        print(f"Erro ao executar /disparo: {e}")
        context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo em caso de erro
        return ConversationHandler.END

# Recebe a mídia do disparo
async def receber_midia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Recebendo mídia para disparo.")

    # Não verifica comando ativo aqui, pois faz parte do fluxo iniciado
    try:
        # Verifica o tipo de mídia enviada
        if update.message.photo:
            context.user_data['media_type'] = 'photo'
            context.user_data['media'] = update.message.photo[-1].file_id
        elif update.message.video:
            context.user_data['media_type'] = 'video'
            context.user_data['media'] = update.message.video.file_id
        else:
            await update.message.reply_text("Envie apenas uma imagem ou um vídeo.")
            return MEDIA

        # Solicita o texto para o disparo
        await update.message.reply_text("Agora, envie o texto da mensagem de disparo.")
        return TEXT
    except Exception as e:
        print(f"Erro ao processar mídia: {e}")
        return ConversationHandler.END



# Recebe o texto do disparo
async def receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Recebendo texto para disparo.")

    try:
        # Armazena o texto no contexto do usuário
        context.user_data['text'] = update.message.text
        await update.message.reply_text("Envie o link que deseja incluir no botão.")
        return LINK
    except Exception as e:
        print(f"Erro ao processar texto: {e}")
        return ConversationHandler.END

# Recebe o link do botão e exibe a confirmação
from urllib.parse import urlparse

# Recebe o link do botão e exibe a confirmação
# Recebe o link do botão e exibe a confirmação
async def receber_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Recebendo link para disparo.")

    try:
        # Armazena o link enviado pelo usuário
        user_link = update.message.text.strip()

        # Verifica se o link é válido
        if not (user_link.lower().startswith("http://") or user_link.lower().startswith("https://") or user_link.lower().startswith("t.me/")):
            await update.message.reply_text(
                "⚠️ O link enviado é inválido. O link deve começar com 'http://', 'https://', ou 't.me/'."
            )
            return LINK  # Mantém o estado para o usuário tentar novamente

        # Se o link começa com "t.me", adiciona o esquema "https://"
        if user_link.lower().startswith("t.me/"):
            user_link = f"https://{user_link}"

        # Armazena o link válido no contexto
        context.user_data['link'] = user_link

        # Configura o teclado para confirmação
        keyboard = [
            [
                InlineKeyboardButton("ENVIAR", callback_data='send'),
                InlineKeyboardButton("CANCELAR", callback_data='cancel')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("PRONTO PARA EFETUAR SEU DISPARO?", reply_markup=reply_markup)
        return CONFIRM
    except Exception as e:
        print(f"Erro ao processar link: {e}")
        return ConversationHandler.END

# Confirma e envia a mensagem para todos os usuários ou cancela o disparo
async def confirmacao_disparo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Confirmando disparo.")
    bot_instance = bot_application.bot
    bot_id = context.bot_data.get('bot_id', 1)
    user_ids = load_user_ids(bot_id)
    admin_id = cache['owner']
    try:
        query = update.callback_query
        await query.answer()

        if query.data == 'send':
            print("Disparo confirmado pelo usuário.")

            # Envia a mensagem de disparo para todos os usuários cadastrados
            for user_id in user_ids:
                try:
                    check = await verificar_chat_existe(int(user_id))
                    if user_id != '' and check:
                        keyboard = [[InlineKeyboardButton("Clique aqui", url=context.user_data['link'])]]
                        reply_markup = InlineKeyboardMarkup(keyboard)

                        if context.user_data['media_type'] == 'photo':
                            await context.bot.send_photo(
                                chat_id=user_id,
                                photo=context.user_data['media'],
                                caption=context.user_data['text'],
                                reply_markup=reply_markup
                            )
                        elif context.user_data['media_type'] == 'video':
                            await context.bot.send_video(
                                chat_id=user_id,
                                video=context.user_data['media'],
                                caption=context.user_data['text'],
                                reply_markup=reply_markup
                            )
                except:
                    print(f"Erro ao disparar para o chat {user_id}")
            await bot_instance.send_message(
                        chat_id=admin_id,
                        text=f"✅ Mensagem de disparo enviada para todos os usuários")
        else:
            print("Disparo cancelado pelo usuário.")
            await bot_instance.send_message(
                chat_id=admin_id,
                text=f"❌ Disparo cancelado.")

            # Limpa os dados do usuário
            context.user_data.clear()
    except Exception as e:
        print(f"Erro ao processar confirmação de disparo: {e}")
    finally:
        context.user_data['conversacao_ativa'] = False
        return ConversationHandler.END


def create_cancel_button():
    return InlineKeyboardButton("❌  𝗖𝗔𝗡𝗖𝗘𝗟𝗔𝗥", callback_data='cancelar')

# Handler para /gateway
async def gateway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /gateway iniciado.")

    if await verificar_comando_ativo(update, context):
        print("Encerrando /gateway devido a comando ativo.")
        return ConversationHandler.END

    await reset_conversation(update, context)
    try:
        chat_id = update.effective_chat.id
        context.user_data['chat_id'] = chat_id
        bot_token = context.bot.token

        if not is_admin(chat_id):
            print("Usuário não autorizado para /gateway.")
            return ConversationHandler.END

        bot_id = context.bot_data.get('bot_id', '1')  # Define um valor padrão
        context.user_data['bot_id'] = bot_id

        context.user_data['conversacao_ativa'] = True
        keyboard = [[InlineKeyboardButton("🔑 Pushpay", callback_data='PP')],
                    [InlineKeyboardButton("🔑 Mercado Pago", callback_data='MP')],
                    [InlineKeyboardButton("❌ CANCELAR", callback_data='cancelar')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("🔑 Escolha uma gateway para configurar a conta:", reply_markup=reply_markup)
        print("Solicitação de token enviada.")
        return INPUT_TOKEN

    except Exception as e:
        print(f"Erro ao executar /gateway: {e}")
        await update.message.reply_text("Ocorreu um erro. Tente novamente mais tarde.")
        context.user_data['conversacao_ativa'] = False
        return ConversationHandler.END

async def recebe_token(update: Update, context: CallbackContext):
    query = update.callback_query
    
    await query.answer()
    print(query)
    if query.data.lower() == 'cancelar':
        print('cancelei')
        # Limpa o estado do usuário
        print("macaco cancelou")
        
        context.user_data['conversacao_ativa'] = False  # Garante que `conversacao_ativa` seja redefinido
        print("Todos os estados do usuário foram redefinidos pelo comando /cancel.")

        # Envia uma mensagem de confirmação ao usuário
        try:
            bot_instance = bot_application.bot
            chat_id = update.effective_chat.id
            context.user_data.clear()
            await bot_instance.send_message(chat_id=chat_id, text="❌ Todas as operações foram canceladas com sucesso.")
            return ConversationHandler.END
        except Exception as e:
            print(f'erro ao cancelar: {e}')
                            # Caso não haja mídia, apenas envia a mensagem de texto
            
        if update.callback_query:
            await update.callback_query.message.reply_text("❌ Todas as operações foram canceladas com sucesso.")
            await update.callback_query.answer()
        else:
            await update.message.reply_text("❌ Todas as operações foram canceladas com sucesso.")

        # Finaliza qualquer estado ativo no ConversationHandler
        context.user_data['']
        context.user_data.clear()
        return ConversationHandler.END
    
    cache['token_type'] = query.data
    
    
    if cache['token_type'] == 'PP':
        await context.bot.send_message(chat_id=update.effective_chat.id, text='Envie o token de sua conta PushPay')
        return TOKEN_RETRY
    elif cache['token_type'] == 'MP':
        code_verifier = payment.generate_code_verifier()
        key = payment.generate_code_challenge(code_verifier)
        try:
            response = requests.get(f'{IP_DA_API}/key?key={code_verifier}&bot_id={cache['bot_id']}')
            if response.status_code == 200:
                keyboard = [
                [
                    InlineKeyboardButton(
                        "AUTORIZAR MERCADO PAGO",
                        url=f'https://auth.mercadopago.com/authorization?client_id=4160833868783446&response_type=code&platform_id=mp&state={cache["bot_id"]}&redirect_url={URL_REDIRECT}&code_challenge={key}&code_challenge_method=S256'
                    )
                ]
            ]
            
                # Criação do objeto InlineKeyboardMarkup
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Envio da mensagem com o botão
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Clique no botão abaixo para autorizar o Mercado Pago:",
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f'❌ Falha ao gerar chaves de criptografia do token')
        except Exception as e:
            print(e)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f'❌ Falha ao enviar chaves de criptografia do token')
            
        finally:
            context.user_data['conversacao_ativa'] = False

    

async def repete_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        token = update.message.text.strip()
        bot_id = context.bot_data.get('bot_id', '1')  # Usa bot_data com valor padrão
        if payment.verificar_push(token):
            payment_object = {'token':token, 'type':'PP'}
            manager.update_bot_payment(bot_id, payment_object)
            cache['gate_token'] = token
            await update.message.reply_text(f"✅ Token configurado para o bot {bot_id} com sucesso!")
        else:
            await update.message.reply_text(f"❌ Token invalido, envie um token existente!")
            return TOKEN_RETRY
    except Exception as e:
        print(f"Erro ao salvar token: {e}")
    finally:
        # Redefine o estado para permitir novos comandos
        context.user_data['conversacao_ativa'] = False
        print("Fluxo de configuração de token concluído. Estado redefinido.")
        return ConversationHandler.END




async def verificar_comando_ativo(update, context):
    estado_ativo = context.user_data.get('conversacao_ativa', False)
    print(f"Verificando comando ativo. Estado atual: {estado_ativo}")

    if estado_ativo:
        mensagem = "Você já está em uma operação. Digite /cancel para cancelar."
        if update.callback_query:
            await update.callback_query.message.reply_text(mensagem)
            await update.callback_query.answer()
        else:
            await update.message.reply_text(mensagem)
        print("Comando bloqueado devido a operação ativa.")
        return True  # Bloqueia o comando atual

    print("Nenhuma operação ativa encontrada. Continuando...")
    return False

# Função para resetar a conversa e definir 'conversacao_ativa' como False
async def reset_conversation(update, context):
    print("Resetando conversa e mantendo estado de comando ativo.")
    # Armazena o valor atual de conversacao_ativa
    conversacao_ativa = context.user_data.get('conversacao_ativa', False)
    # Limpa todos os outros dados, mas mantém conversacao_ativa
    context.user_data.clear()
    context.user_data['conversacao_ativa'] = conversacao_ativa
    print(f"Estado de conversacao_ativa após reset: {context.user_data['conversacao_ativa']}")


async def comandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /comandos iniciado.")

    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /comandos devido a comando ativo.")
        return

    # Marca o comando como ativo antes de iniciar a função
    context.user_data['conversacao_ativa'] = True
    print("Comando /comandos marcado como ativo. Estado atual:", context.user_data.get('conversacao_ativa', False))

    try:
        # Limpa conversas anteriores
        await reset_conversation(update, context)
        
        chat_id = update.effective_chat.id
        bot_token = context.bot.token  # Obtém o token do bot atual

        # Verifica se o usuário é administrador para o bot atual
        if not is_admin(chat_id):
            print("Usuário não autorizado para /comandos.")
            return

        # Texto com a lista de comandos
        comandos_texto = (
            "👋 <b>Seja bem-vindo, Administrador!</b>\n\n"
            "⚙️ Estou aqui para ajudar você a gerenciar seu bot de forma eficiente! Aqui estão os comandos disponíveis:\n\n"
            "<b>1. /criar_plano -</b> 🆕 Inicie o processo para criar um novo plano de assinatura.\n\n"
            "<b>2. /excluir_plano -</b> 🗑️ Exiba os planos atuais e permita a exclusão de um plano selecionado.\n\n"
            "<b>3. /gateway -</b> 🔐 Configure o token da conta Pushinpay para integrações de pagamento.\n\n"
            "<b>4. /texto -</b> 📝 Defina o texto de boas-vindas inicial do bot.\n\n"
            "<b>5. /texto2 -</b> 📝 Adicione um segundo texto de boas-vindas.\n\n"
            "<b>6. /midia_inicial -</b> 🖼️ Permita o envio de mídia que será exibida no início.\n\n"
            "<b>7. /remover_midia -</b> ❌ Remova a mídia inicial do bot.\n\n"
            "<b>8. /remover_texto -</b> ❌ Remova o texto inicial do bot.\n\n"
            "<b>9. /upsell -</b> 💸 Configure uma mensagem de upsell que será exibida antes da confirmação de pagamento.\n\n"
            "<b>10. /grupo_id -</b> 🔗 Permita trocar o ID do grupo VIP e gerar link de acesso.\n\n"
            "<b>11. /recuperacao_compra -</b> 🔄 Gerencie mensagens de remarketing para recuperação de compra.\n\n"
            "<b>12. /start -</b> 🏁 Exiba a mensagem inicial para o usuário.\n\n"
            "<b>13. /comandos -</b> 📋 Mostre esta lista de comandos.\n\n"
            "<b>14. /cancel -</b> ⛔ Cancele a operação atual e retorne ao menu principal.\n\n"
            "<b>15. /remover_upsell -</b> 🗑️ Exclua a mensagem de upsell configurada.\n\n"
            "<b>16. /deletar_recuperacao -</b> 🗑️ Exclua mensagens de recuperação de compra configuradas.\n\n"
            "<b>17. /texto_botao -</b> 🔘 Configure o texto do botão inicial exibido aos usuários.\n\n"
            "<b>18. /disparo -</b> 🚀 Configure e envie disparos personalizados para todos os usuários.\n\n"
            "💼 Aproveite ao máximo esses comandos para elevar a qualidade do seu bot e surpreender seus clientes! 🚀"
        )
        
        # Envia a lista de comandos ao administrador
        await update.message.reply_text(comandos_texto, parse_mode='HTML')
        print("Lista de comandos enviada com sucesso.")
    except Exception as e:
        print(f"Erro ao executar /comandos: {e}")
    finally:
        # Desmarca o comando como ativo após finalizar
        context.user_data['conversacao_ativa'] = False
        print("Comando /comandos concluído. Estado atual:", context.user_data.get('conversacao_ativa', False))



def get_bot(self, bot_id):
    # Aqui você implementaria a lógica para retornar o bot certo baseado no bot_id
    return self.bots.get(bot_id)  # Exemplo, onde 'self.bots' contém as instâncias dos bots



def load_upsell(bot_id):
    bot = manager.get_bot_by_id(bot_id)
    if bot:
        config = json.loads(bot[9])
        return config
    else:
        return False


# Função para salvar o upsell no arquivo JSON específico do bot
def save_upsell(content, bot_id):
    manager.update_bot_upsell(bot_id, content)

# Variável global para armazenar o upsell
upsell_message = {}

async def upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /upsell.")
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa

    keyboard = [[InlineKeyboardButton("❌ CANCELAR", callback_data='cancelar')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📲 Envie a mensagem de upsell desejada, com foto ou vídeo.",
        reply_markup=reply_markup
    )
    print("Solicitação de upsell enviada com sucesso.")
    return INPUT_UPSELL_CONTENT


async def recebe_midia_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Função recebe_midia_upsell chamada.")
    print(f"Mensagem recebida: {update.message.text if update.message.text else 'Sem texto'}")

    # Verifica se o usuário deseja cancelar
    if update.message.text and update.message.text.strip().lower() == "/cancel":
        print("Usuário solicitou /cancel. Encerrando operação.")
        return await cancel(update, context)  # Retorna diretamente o fluxo do cancel

    # Verifica se o usuário está tentando enviar outro comando
    if update.message.text and update.message.text.strip().startswith("/") and update.message.text.strip().lower() != "/cancel":
        print(f"Comando detectado durante a operação ativa: {update.message.text.strip()}")
        await update.message.reply_text("Você já está em uma operação. Digite /cancel para cancelar.")
        return  # Bloqueia a execução do próximo passo

    # Continua com o processamento normal do upsell
    bot_id = context.user_data.get('bot_id')
    print(f"Bot ID obtido do contexto: {bot_id}")

    if bot_id is None:
        print("Erro: bot_id não encontrado no contexto.")
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    upsell_data = {"text": "", "media": None, "type": None}
    print("Estrutura upsell_data inicializada.")

    if update.message.photo:
        upsell_data["media"] = update.message.photo[-1].file_id
        upsell_data["type"] = "photo"
        print(f"Foto detectada. File ID: {upsell_data['media']}")
    elif update.message.video:
        upsell_data["media"] = update.message.video.file_id
        upsell_data["type"] = "video"
        print(f"Vídeo detectado. File ID: {upsell_data['media']}")
    else:
        print("Nenhuma mídia detectada na mensagem.")

    upsell_text = update.message.caption.strip() if update.message.caption else "Confira essa oferta especial!"
    upsell_data["text"] = upsell_text
    print(f"Texto da oferta capturado: {upsell_text}")

    print("Salvando dados do upsell...")
    save_upsell(upsell_data, bot_id)
    print(f"Dados do upsell salvos: {upsell_data}")

    await update.message.reply_text("Agora envie o link do botão de upsell:")
    print("Mensagem enviada ao usuário solicitando o link do botão.")

    return INPUT_UPSELL_LINK



async def recebe_link_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip().lower() == "/cancel":
        return await cancel(update, context)

    try:
        bot_id = context.user_data.get('bot_id')
        upsell_data = load_upsell(bot_id)

        upsell_link = update.message.text.strip()

        # Validação do link
        if not (upsell_link.lower().startswith("http://") or upsell_link.lower().startswith("https://") or upsell_link.lower().startswith("t.me/")):
            await update.message.reply_text(
                "⚠️ O link enviado é inválido. O link deve começar com 'http://', 'https://', ou 't.me/'."
            )
            return INPUT_UPSELL_LINK  # Mantém o estado para o usuário tentar novamente

        # Se o link começa com "t.me", adiciona o esquema "https://"
        if upsell_link.lower().startswith("t.me/"):
            upsell_link = f"https://{upsell_link}"


        # Salva o link validado
        upsell_data["link"] = upsell_link
        save_upsell(upsell_data, bot_id)

        await update.message.reply_text("✅ Link de upsell salvo com sucesso!")

        context.user_data['conversacao_ativa'] = False  # Finaliza a operação
        return ConversationHandler.END

    except Exception as e:
        print(f"Erro ao processar link de upsell: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao salvar o link de upsell.")
        return ConversationHandler.END

# Função para salvar as configurações de recuperação no arquivo JSON
def save_recuperacao_config(configuracoes, bot_id):
    manager.update_bot_recovery(bot_id, configuracoes)


# Função para carregar o dicionário de planos específicos para cada bot
def load_plans(bot_id):
    bot = manager.get_bot_by_id(bot_id)
    return json.loads(bot[6])

# Função para salvar o dicionário de planos específicos para cada bot
def save_plans(plans, bot_id):
    manager.update_bot_plans(bot_id, plans)

# Definindo estados para os ConversationHandlers
INPUT_TEXT = 0
INPUT_TEXT2 = 1
INPUT_MEDIA = 2

async def enviar_lista_planos(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    
    # Verifica e define o bot_id se ainda não estiver configurado
    if bot_id is None:
        bot_id = 1  # Ajuste o valor padrão conforme necessário
        context.user_data['bot_id'] = bot_id
        context.bot_data['bot_id'] = bot_id
    
    # Carregar os planos específicos para o bot_id
    planos = load_plans(bot_id)
    print(f"[DEBUG - enviar_lista_planos] Planos carregados: {planos}")

    # Verifica se há planos disponíveis para exibição
    if planos:
        keyboard = [
            [InlineKeyboardButton(f"{plano['nome']} - R$ {plano['valor']}", callback_data=plano_id)]
            for plano_id, plano in planos.items()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=chat_id, text="Escolha uma oferta abaixo:", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text="No momento, não temos planos disponíveis.")


async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Recupera o token do bot atual
    token_do_bot = context.bot_data.get('token')
    if not token_do_bot:
        await update.message.reply_text("Erro: Não foi possível identificar o token do bot em uso.")
        return

    # Ignora o comando /start
    if update.message.text == '/start':
        return  # Não faz nada se for o comando /start

    # Adicione o comando de lista de planos apenas se não estiver em uma operação ativa
    if context.user_data.get('conversacao_ativa', False):
        return  # Não processa mais comandos se estiver em uma operação ativa

    # Se o usuário não é um administrador, envia a lista de planos
    if not is_admin(chat_id):
        await enviar_lista_planos(context, chat_id)  # Envie a lista de planos apenas para usuários comuns

        
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Recupera o token do bot atual
    token_do_bot = context.bot_data.get('token')
    if not token_do_bot:
        await update.message.reply_text("Erro: Não foi possível identificar o token do bot em uso.")
        return

    # Verifica se a conversa está ativa
    if context.user_data.get('conversacao_ativa', False):
        return

    # Ignora comandos
    if update.message.text.startswith('/'):
        return  # Não faz nada se for um comando

    # Se o usuário não é um administrador, envia a lista de planos
    if not is_admin(chat_id):
        await enviar_lista_planos(context, chat_id)  # Envie a lista de planos apenas para usuários comuns











        
def escape_markdown_v2(text):
    # Função para escapar caracteres especiais no MarkdownV2
    return re.sub(r'([_\*\[\]\(\)~`>#+\-=|{}\.!])', r'\\\1', text)

# Handler para o comando /remover_upsell
async def remover_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /remover_upsell iniciado.")

    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /remover_upsell devido a comando ativo.")
        return ConversationHandler.END

    # Marca o comando como ativo antes de iniciar a função
    context.user_data['conversacao_ativa'] = True
    print("Comando /remover_upsell marcado como ativo. Estado atual:", context.user_data.get('conversacao_ativa', False))

    try:
        chat_id = update.effective_chat.id
        bot_token = context.bot.token  # Obtém o token do bot atual

        # Verifica se o usuário é administrador do bot atual
        if not is_admin(chat_id):
            print("Usuário não autorizado para /remover_upsell.")
            context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
            return ConversationHandler.END

        # Obtém o bot_id do user_data ou bot_data
        bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
        if bot_id is None:
            await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
            print("Erro: bot_id não identificado.")
            context.user_data['conversacao_ativa'] = False  # Desmarca o comando como ativo
            return ConversationHandler.END

        # Define o upsell como vazio
        empty_upsell = {"text": "", "media": None, "type": None}
        save_upsell(empty_upsell, bot_id)  # Salva o upsell vazio para o bot específico

        # Carrega novamente para verificar se o conteúdo foi atualizado
        upsell_data = load_upsell(bot_id)
        if upsell_data == empty_upsell:
            await update.message.reply_text("🗑️ Mensagem de upsell excluída com sucesso!")
            print("Upsell removido com sucesso.")
        else:
            await update.message.reply_text("Erro ao remover o upsell. Tente novamente.")
            print("Erro ao remover o upsell.")
    except Exception as e:
        print(f"Erro ao executar /remover_upsell: {e}")
    finally:
        # Desmarca o comando como ativo após concluir a função
        context.user_data['conversacao_ativa'] = False
        print("Comando /remover_upsell concluído. Estado atual:", context.user_data.get('conversacao_ativa', False))

    return ConversationHandler.END




async def criar_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores

    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador para o bot atual
    if not is_admin(chat_id):
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa

    await update.message.reply_text(
        "📝 Qual será o nome do plano?\n\n> Para cancelar a criação do plano, utilize o comando: /cancel",
        parse_mode='MarkdownV2'
    )
    
    return INPUT_PLAN_NAME


async def recebe_nome_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['novo_plano'] = {'nome': update.message.text.strip()}
    
    # Envia a mensagem com instruções para a duração do plano
    instrucoes = (
        "⌛️  Escolha a duração do plano: \n"
    )
    # Gera um botão para cada plano disponível
    keyboard = [
        [InlineKeyboardButton(f"𝗗𝗜𝗔𝗥𝗜𝗢", callback_data='diario')],
        [InlineKeyboardButton(f"𝗦𝗘𝗠𝗔𝗡𝗔𝗟", callback_data='semanal')],
        [InlineKeyboardButton(f"𝗠𝗘𝗡𝗦𝗔𝗟", callback_data='mensal')],
        [InlineKeyboardButton(f"𝗔𝗡𝗨𝗔𝗟", callback_data='anual')],
        [InlineKeyboardButton(f"𝗩𝗜𝗧𝗔𝗟𝗜𝗖𝗜𝗢", callback_data='vitalicio')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['mensagem'] = await update.message.reply_text(instrucoes, parse_mode='MarkdownV2', reply_markup=reply_markup)
    
    return INPUT_PLAN_DURATION  # Retorna o estado para esperar a duração

async def recebe_duracao_plano(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    names = {
        'diario':'dias',
        'semanal':'semanas',
        'mensal':'meses',
        'anual':'anos'
    }

    chat_id = update.effective_chat.id
    context.user_data['novo_plano']['ciclo'] = query.data
    if query.data == 'vitalicio':
        await context.bot.send_message(chat_id=chat_id, text='💰 Defina o valor do plano:')
        context.user_data['novo_plano']['duracao'] = 'vitalício'
        return INPUT_PLAN_VALUE
    await context.bot.send_message(chat_id=chat_id, text=f'Insira o numero de {names[query.data]} do plano:')
    return INPUT_PLAN_CUSTON

async def recebe_quantidade_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dias = int(update.message.text)
        dura = ''
        if int(dias) > 1:
            names = {
                'diario':'dias',
                'semanal':'semanas',
                'mensal':'meses',
                'anual':'anos',
                'vitalicio':''
            }
            dura = f'{dias} {names[context.user_data['novo_plano']['ciclo']]}'
        else:
            names = {
                'diario':'dia',
                'semanal':'semana',
                'mensal':'mes',
                'anual':'ano',
                'vitalicio':''
            }
            dura = f'{dias} {names[context.user_data['novo_plano']['ciclo']]}'
        
        context.user_data['novo_plano']['duracao'] = dura
        await update.message.reply_text('💰 Defina o valor do plano:')    
        return INPUT_PLAN_VALUE
    except ValueError:
        await update.message.reply_text("Por favor, digite um valor numérico válido.")
        return INPUT_PLAN_CUSTON

async def recebe_valor_plano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(update.message.text.replace(',', '.'))
        if valor < 3.99:
            await update.message.reply_text("Por favor, digite um valor igual ou superior que 5")
            return INPUT_PLAN_VALUE
        context.user_data['novo_plano']['valor'] = f"{valor:.2f}"
        nome_plano = context.user_data['novo_plano'].get('nome', 'N/A')
        duracao_plano = context.user_data['novo_plano'].get('duracao', 'N/A')
        
        valor_plano = context.user_data['novo_plano']['valor'].replace('.', '\\.')
        confirmacao_texto = (
            "🚀 Está tudo certo com o plano?\n\n"
            f"> Plano\\: {nome_plano} \n"
            f"> Tempo\\: {duracao_plano}\n"
            f"> Preço\\: R\\$ " + valor_plano
        )

        keyboard = [
            [InlineKeyboardButton("✅ CRIAR PLANO", callback_data='criar_plano')],
            [InlineKeyboardButton("❌ CANCELAR", callback_data='cancelar')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(confirmacao_texto, parse_mode='MarkdownV2', reply_markup=reply_markup)
        return CONFIRMAR_CRIACAO
    except Exception as e:
        await update.message.reply_text(f"Por favor, digite um valor numérico válido.")
        print(e)
        return INPUT_PLAN_VALUE


async def confirmar_criacao(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    bot_id = context.user_data.get('bot_id')

    if query.data == 'criar_plano':
        planos = load_plans(bot_id)
        plano_id = f"plano_{len(planos) + 1}"
        planos[plano_id] = context.user_data['novo_plano']
        save_plans(planos, bot_id)
        await query.edit_message_text(text="✅ Plano criado com sucesso!")
    elif query.data == 'cancelar':
        await query.edit_message_text(text="❌ Ação cancelada com sucesso!")

    context.user_data['conversacao_ativa'] = False  # Finaliza a operação
    return ConversationHandler.END

def load_config(bot_id):
    bot = manager.get_bot_by_id(bot_id)
    if bot:
        return json.loads(bot[4])
    else:
        return False
def save_config(config, bot_id):
    manager.update_bot_config(bot_id, config)






# Função start com suporte para salvar e carregar IDs de usuários específicos por bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Obtém o bot_id do contexto ou define um valor padrão (1)
    bot_id = cache['bot_id']
    context.user_data['bot_id'] = bot_id

    # Carrega o chat_id do usuário que enviou o comando /start
    chat_id = update.effective_chat.id

    # Carrega a lista de IDs de usuários para o bot específico
    bot = manager.get_bot_by_token(cache['token'])
    user_ids = str(bot[8]).split(':')
    # Verifica se o usuário já está na lista; se não estiver, adiciona e salva
    if str(chat_id) not in user_ids:
        #print(user_ids)
        user_ids.append(chat_id)
        new_user = ''
        for i in user_ids:
            new_user = new_user+':'+str(i)
        manager.update_bot_users(bot_id, new_user)
        #print(f"Novo usuário {chat_id} adicionado ao arquivo bot{bot_id}_user_ids.json.")

    # Carrega a configuração do bot
    config = load_config(bot_id)

    # Configura o botão de ação
    button_text = config.get('button_text', "CLIQUE AQUI PARA ACESSAR")
    keyboard = [[InlineKeyboardButton(button_text, callback_data='acessar_agora')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Envia a mídia inicial, se configurada
    if config.get('start_media'):
        media_type = config['start_media']['type']
        media_id = config['start_media']['file_id']
        if media_type == 'photo':
            await update.message.reply_photo(photo=media_id)
        elif media_type == 'video':
            await update.message.reply_video(video=media_id)

    # Envia o texto inicial configurado
    if config.get('start_text'):
        await update.message.reply_text(config['start_text'])

    if config.get('start_text2'):
        await update.message.reply_text(config['start_text2'], reply_markup=reply_markup)

    print("Comando /start processado com sucesso.")



async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    bot_id = context.user_data.get('bot_id')
    
    planos = load_plans(bot_id)

    # Depuração: Verificando os IDs dos planos antes de gerar os botões
    print("Planos disponíveis:", planos.keys())

    # Gera um botão para cada plano disponível
    keyboard = [
        [InlineKeyboardButton(f"{plano['nome']} - R$ {plano['valor']}", callback_data=plano_id)]
        for plano_id, plano in planos.items()
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="Escolha uma oferta abaixo:", reply_markup=reply_markup)

async def plano_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    bot_id = context.user_data.get('bot_id')
    
    planos = load_plans(bot_id)

    # Depuração: verificar o callback_data recebido
    data = query.data
    print("Callback data recebido:", data)  # Depuração

    if data.startswith("plano_"):
        plano_id = data  # Captura o ID completo
    else:
        plano_id = None

    print("Tentando acessar plano com ID:", plano_id)  # Depuração

    plano_escolhido = planos.get(plano_id)
    print("Plano escolhido:", plano_escolhido)  # Depuração

    if plano_escolhido:
        # Armazena o plano no contexto para callbacks futuros
        context.user_data['plano_escolhido'] = plano_escolhido
        
        detalhes_plano = (
            f"Plano selecionado com sucesso.\n"
            f"• Título: {plano_escolhido['nome']}\n"
            f"• Duração: {plano_escolhido['duracao']}\n"
            f"• Valor: R$ {plano_escolhido['valor']}\n"
        )

        # Cria o botão "Pagar via PIX"
        keyboard = [[InlineKeyboardButton("Pagar via PIX", callback_data='gerar_pix')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Envia a mensagem com o botão
        await query.message.reply_text(text=detalhes_plano, reply_markup=reply_markup)
    else:
        await query.message.reply_text("O plano selecionado não está disponível.")

async def gerar_pix_codigo(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    plano_escolhido = context.user_data.get('plano_escolhido')
    bot_id = context.user_data.get('bot_id')  # Obtém o bot_id do contexto

    if not plano_escolhido:
        await context.bot.send_message(chat_id=chat_id, text="Nenhum plano foi selecionado para pagamento.")
        return
    bot = manager.get_bot_by_token(cache['token'])
    
    payment_bot_object = json.loads(bot[7])
    if('token' in payment_bot_object.keys() and 'type' in payment_bot_object.keys()):
        cache['gate_token'] = payment_bot_object['token']
        cache['token_type'] = payment_bot_object['type']
    
    if not 'token_type' in cache:
        await context.bot.send_message(chat_id=chat_id, text="O dono da aplicação não cadastrou nenhuma gateway de pagamento.")
        return
    
    await context.bot.send_message(chat_id=chat_id, text="<b>Aguarde um momento enquanto preparamos tudo :)</b>", parse_mode='HTML')
    await context.bot.send_message(chat_id=chat_id, text="Para efetuar o pagamento, utilize a opção 'Pagar' > 'PIX copia e Cola' no aplicativo do seu banco.")
    await context.bot.send_message(chat_id=chat_id, text="<b>Copie o código abaixo:</b>", parse_mode='HTML')

    if cache['token_type'] == 'PP':
        valor_cents = int(float(plano_escolhido['valor'].replace("R$", "").strip()))
        payment_object = payment.criar_pix_pushinpay(cache['gate_token'], valor_cents, bot_id, chat_id)
        if not 'pix_code' in payment_object.keys():
            await context.bot.send_message(chat_id=chat_id, text="Erro ao gerar o código PIX. A resposta da API não contém um código válido.")
        else:
            manager.create_payment(payment_object['payment_id'].lower(), chat_id, json.dumps(plano_escolhido), bot_id)
            add_payment_info(payment_object['payment_id'], chat_id)
            pix_code_escaped = escape_markdown_v2(payment_object['pix_code'])
            await context.bot.send_message(chat_id=chat_id, text=f"`{pix_code_escaped}`", parse_mode='MarkdownV2')
            await context.bot.send_message(chat_id=chat_id, text="Por favor, confirme quando realizar o pagamento.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("JÁ FIZ O PAGAMENTO", callback_data="noop")]]))
        
    elif cache['token_type'] == 'MP':

        valor_cents = int(float(plano_escolhido['valor'].replace("R$", "").strip()))
        payment_object = payment.criar_pix_mp(cache['gate_token'], valor_cents)
        if not 'pix_code' in payment_object.keys():
            await context.bot.send_message(chat_id=chat_id, text="Erro ao gerar o código PIX. A resposta da API não contém um código válido.")
        else:
            manager.create_payment(payment_object['payment_id'], chat_id, json.dumps(plano_escolhido), bot_id)
            add_payment_info(payment_object['payment_id'], chat_id)
            pix_code_escaped = escape_markdown_v2(payment_object['pix_code'])
            await context.bot.send_message(chat_id=chat_id, text=f"`{pix_code_escaped}`", parse_mode='MarkdownV2')
            await context.bot.send_message(chat_id=chat_id, text="Por favor, confirme quando realizar o pagamento.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("JÁ FIZ O PAGAMENTO", callback_data="noop")]]))

async def noop(update: Update, context: CallbackContext):
    # Simplesmente responde à consulta para evitar timeout no botão
    query = update.callback_query
    await query.answer()

async def pagar_pix(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    payment_id = query.data.split('_')[1]
    payment_index = int(query.data.split('_')[2])
    bot_id = context.user_data.get('bot_id')  # Obtém o bot_id do contexto

    print(f"Tentando processar o pagamento para payment_id: {payment_id} no chat_id: {chat_id}")

    # Obtém as informações de pagamento com o bot_id
    payment_info = manager.get_payment_by_id(payment_id)
    cache['payments'][payment_id]['continue'] = False
    print(f"Informações de pagamento recuperadas: {payment_info}")

    if payment_info[4] != "paid":
        plano_escolhido = json.loads(payment_info[2])
        # Captura o texto ou legenda da mensagem
        query_message_text = (
            query.message.text or query.message.caption
        ).strip().lower() if query.message.text or query.message.caption else None
        print(f"[DEBUG] Texto ou legenda da mensagem enviada: '{query_message_text}'")

        # Busca o desconto correspondente
        configuracoes_recuperacao = load_recuperacao_config(bot_id)
        desconto_configurado = 50  # Desconto padrão

        if query_message_text:  # Verifica se o texto ou legenda não está vazio
            for config in configuracoes_recuperacao:
                texto_config = config.get("texto", "").strip().lower()
                print(f"[DEBUG] Comparando texto: '{texto_config}' com '{query_message_text}'")
                if texto_config and texto_config in query_message_text:
                    desconto_configurado = config.get("desconto", 50)
                    print(f"[DEBUG] Desconto encontrado: {desconto_configurado}% para o texto '{texto_config}'")
                    break
        else:
            print("[DEBUG] Texto ou legenda da mensagem está vazio. Aplicando desconto padrão (50%).")
        valor_cents = desconto_configurado

        print(f"Preparando para gerar código PIX com valor descontado: {desconto_configurado} reais (Desconto: {desconto_configurado}%)")

        try:
            await gerar_pix_codigo_com_valor(update, context, valor_cents, payment_index, payment_id)
        except Exception as e:
            print(f"[ERRO] Erro ao tentar gerar código PIX: {e}")
            await context.bot.send_message(chat_id=chat_id, text="Erro inesperado ao se comunicar com a API de pagamento. Por favor, tente novamente.")
    else:
        print(f"[DEBUG] Nenhuma ação necessária ou pagamento já processado para payment_id: {payment_id}")
        await context.bot.send_message(chat_id=chat_id, text="Nenhum pagamento pendente ou não autorizado para gerar PIX.")

async def gerar_pix_codigo_com_valor(update: Update, context: CallbackContext, valor_cents: float, index, payment_cur) -> None:
    chat_id = update.effective_chat.id
    plano_escolhido = context.user_data.get('plano_escolhido')
    bot_id = context.user_data.get('bot_id')  # Obtém o bot_id do contexto

    if not plano_escolhido:
        await context.bot.send_message(chat_id=chat_id, text="Nenhum plano foi selecionado para pagamento.")
        return
    bot = manager.get_bot_by_token(cache['token'])
    
    payment_bot_object = json.loads(bot[7])
    if('token' in payment_bot_object.keys() and 'type' in payment_bot_object.keys()):
        cache['gate_token'] = payment_bot_object['token']
        cache['token_type'] = payment_bot_object['type']
    
    if not 'token_type' in cache:
        await context.bot.send_message(chat_id=chat_id, text="O dono da aplicação não cadastrou nenhuma gateway de pagamento.")
        return
    
    await context.bot.send_message(chat_id=chat_id, text="<b>Aguarde um momento enquanto preparamos tudo :)</b>", parse_mode='HTML')
    await context.bot.send_message(chat_id=chat_id, text="Para efetuar o pagamento, utilize a opção 'Pagar' > 'PIX copia e Cola' no aplicativo do seu banco.")
    await context.bot.send_message(chat_id=chat_id, text="<b>Copie o código abaixo:</b>", parse_mode='HTML')

    if cache['token_type'] == 'PP':
        #valor_cents = int(float(plano_escolhido['valor'].replace("R$", "").strip()))
        payment_object = payment.criar_pix_pushinpay(cache['gate_token'], valor_cents, bot_id, chat_id)
        print(payment_object)
        if not 'pix_code' in payment_object.keys():
            await context.bot.send_message(chat_id=chat_id, text="Erro ao gerar o código PIX. A resposta da API não contém um código válido.")
        else:
            plano_escolhido['valor'] = valor_cents
            manager.create_payment(payment_object['payment_id'].lower(), chat_id, json.dumps(plano_escolhido), bot_id)
            add_payment_recovery(payment_cur, payment_object['payment_id'])
            pix_code_escaped = escape_markdown_v2(payment_object['pix_code'])
            await context.bot.send_message(chat_id=chat_id, text=f"`{pix_code_escaped}`", parse_mode='MarkdownV2')

            await context.bot.send_message(chat_id=chat_id, text="Por favor, confirme quando realizar o pagamento.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("JÁ FIZ O PAGAMENTO", callback_data="noop")]]))
        
    elif cache['token_type'] == 'MP':
        #valor_cents = int(float(plano_escolhido['valor'].replace("R$", "").strip()))
        payment_object = payment.criar_pix_mp(cache['gate_token'], valor_cents)
        if not 'pix_code' in payment_object.keys():
            await context.bot.send_message(chat_id=chat_id, text="Erro ao gerar o código PIX. A resposta da API não contém um código válido.")
        else:
            plano_escolhido['valor'] = valor_cents
            manager.create_payment(payment_object['payment_id'], chat_id, json.dumps(plano_escolhido), bot_id)
            add_payment_recovery(payment_cur, payment_object['payment_id'])
            pix_code_escaped = escape_markdown_v2(payment_object['pix_code'])
            await context.bot.send_message(chat_id=chat_id, text=f"`{pix_code_escaped}`", parse_mode='MarkdownV2')

            await context.bot.send_message(chat_id=chat_id, text="Por favor, confirme quando realizar o pagamento.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("JÁ FIZ O PAGAMENTO", callback_data="noop")]]))



# Handler para /texto
async def texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /texto iniciado.")

    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        print("Encerrando /texto devido a comando ativo.")
        return ConversationHandler.END

    # Marca o comando como ativo antes de iniciar a função
    context.user_data['conversacao_ativa'] = True
    print("Comando /texto marcado como ativo. Estado atual:", context.user_data.get('conversacao_ativa', False))

    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador para o bot atual
    if not is_admin(chat_id):
        print("Usuário não autorizado para /texto.")
        context.user_data['conversacao_ativa'] = False
        return  # Sai da função se o usuário não for administrador

    # Obtém o bot_id do contexto global `bot_data` ou `user_data`
    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        print("Erro: bot_id não identificado.")
        context.user_data['conversacao_ativa'] = False
        return ConversationHandler.END

    # Armazena o bot_id no user_data para as próximas funções
    context.user_data['bot_id'] = bot_id
    print("bot_id armazenado:", bot_id)

    # Define a conversa como ativa e pede o texto ao usuário
    keyboard = [[create_cancel_button()]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📝  Envie aqui o texto que deseja:", reply_markup=reply_markup)
    print("Mensagem solicitando texto enviada.")
    return INPUT_TEXT


async def recebe_tempo_recuperacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')
    configuracoes_recuperacao = context.user_data.get('configuracoes_recuperacao')

    index = context.user_data['mensagem_index']
    try:
        configuracoes_recuperacao[index]["tempo"] = int(update.message.text)
        save_recuperacao_config(configuracoes_recuperacao, bot_id)
        await update.message.reply_text("✅ Configuração de mensagem de recuperação salva com sucesso!")
    except ValueError:
        await update.message.reply_text("❗️ Por favor, envie um número válido para o tempo.")
        return INPUT_TEMPO_RECUPERACAO

    # Redefine o estado de operação ativa
    context.user_data['conversacao_ativa'] = False
    context.user_data.clear()  # Limpa todos os dados remanescentes do fluxo
    print("Fluxo de recuperação de compra finalizado. Estado redefinido.")
    return ConversationHandler.END



async def texto2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /texto2 iniciado")
    # Verifica se já há um comando ativo
    if await verificar_comando_ativo(update, context):
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id

    # Recupera o token do bot em uso a partir do contexto
    token_do_bot = context.bot_data.get('token')  # Certifique-se de que o token está sendo armazenado corretamente
    if not token_do_bot:
        await update.message.reply_text("Erro: Não foi possível identificar o token do bot em uso.")
        return ConversationHandler.END

    # Verifica se o usuário é admin do bot associado a este token
    if not is_admin(chat_id):
        return ConversationHandler.END

    # Recupera o bot_id do contexto global `bot_data` ou `user_data`
    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    # Armazena o bot_id no user_data para uso nas próximas funções
    context.user_data['bot_id'] = bot_id

    # Marca a conversa como ativa e pede o texto ao usuário
    context.user_data['conversacao_ativa'] = True
    keyboard = [[create_cancel_button()]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("📝 Envie aqui o texto 2 que deseja:", reply_markup=reply_markup)
    return INPUT_TEXT2






async def recebe_texto2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')  # Recupera o bot_id do contexto
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    config = load_config(bot_id)  # Passa o bot_id para carregar a configuração específica
    config['start_text2'] = update.message.text.strip()
    save_config(config, bot_id)  # Passa o bot_id para salvar a configuração específica

    await update.message.reply_text("✅ Mensagem do texto 2 atualizada com sucesso!")
    
    # Limpa o estado da conversação ativa e encerra o ConversationHandler
    context.user_data['conversacao_ativa'] = False
    return ConversationHandler.END


async def recebe_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Recupera o `bot_id` do `user_data`
    bot_id = context.user_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    # Carrega a configuração específica do bot
    config = load_config(bot_id)
    config['start_text'] = update.message.text.strip()
    save_config(config, bot_id)  # Salva a configuração com o `bot_id`

    await update.message.reply_text("✅ Mensagem de boas-vindas atualizada com sucesso!")
    
    # Limpa o estado da conversação ativa e encerra o ConversationHandler
    context.user_data['conversacao_ativa'] = False
    return ConversationHandler.END



# Handler para /midia_inicial
async def midia_inicial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await verificar_comando_ativo(update, context):  # Verifica se há outra operação ativa
        return ConversationHandler.END

    await reset_conversation(update, context)  # Limpa conversas anteriores
    chat_id = update.effective_chat.id
    bot_token = context.bot.token  # Obtém o token do bot atual

    # Verifica se o usuário é administrador do bot atual
    if not is_admin(chat_id):
        return ConversationHandler.END

    bot_id = context.user_data.get('bot_id') or context.bot_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    context.user_data['bot_id'] = bot_id
    context.user_data['conversacao_ativa'] = True  # Marca a conversa como ativa

    keyboard = [[InlineKeyboardButton("❌ CANCELAR", callback_data='cancelar')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🎬 Adicione a mídia para a abertura do bot (foto ou vídeo).",
        reply_markup=reply_markup
    )
    return INPUT_MEDIA  # Retorna o estado para esperar a mídia


async def recebe_midia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get('bot_id')
    if bot_id is None:
        await update.message.reply_text("Erro ao identificar o bot_id. Por favor, tente novamente.")
        return ConversationHandler.END

    config = load_config(bot_id)

    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            config['start_media'] = {'type': 'photo', 'file_id': photo_file.file_id}
            await update.message.reply_text("✅ Foto adicionada com sucesso!")

        elif update.message.video:
            video_file = await update.message.video.get_file()
            config['start_media'] = {'type': 'video', 'file_id': video_file.file_id}
            await update.message.reply_text("✅ Vídeo adicionada com sucesso!")

        else:
            await update.message.reply_text("❌ Tipo de mídia não suportado. Por favor, envie uma foto ou um vídeo.")
            return INPUT_MEDIA
    except BadRequest as e:
        await update.message.reply_text("❌ Erro ao enviar o arquivo. Tente novamente.")
    
    save_config(config, bot_id)
    context.user_data['conversacao_ativa'] = False  # Finaliza a operação
    return ConversationHandler.END


async def cancel(update, context):
    # Limpa o estado do usuário
    print("macaco cancelou")
    
    context.user_data['conversacao_ativa'] = False  # Garante que `conversacao_ativa` seja redefinido
    print("Todos os estados do usuário foram redefinidos pelo comando /cancel.")

    # Envia uma mensagem de confirmação ao usuário
    try:
        bot_instance = bot_application.bot
        chat_id = update.effective_chat.id
        context.user_data.clear()
        await bot_instance.send_message(chat_id=chat_id, text="❌ Todas as operações foram canceladas com sucesso.")
        return ConversationHandler.END
    except Exception as e:
        print(f'erro ao cancelar: {e}')
                        # Caso não haja mídia, apenas envia a mensagem de texto
        
    if update.callback_query:
        await update.callback_query.message.reply_text("❌ Todas as operações foram canceladas com sucesso.")
        await update.callback_query.answer()
    else:
        await update.message.reply_text("❌ Todas as operações foram canceladas com sucesso.")

    # Finaliza qualquer estado ativo no ConversationHandler
    context.user_data.clear()
    return ConversationHandler.END


def run_bot(token, bot_id):
    global bot_application  # Declara que bot_application é global
    print(f"Iniciando bot com token: {token} e bot_id: {bot_id}")
    bot = manager.get_bot_by_token(token)
    # Cria a aplicação do bot
    application = Application.builder().token(token).build()
    bot_application = application
    # Adiciona informações ao bot_data
    cache['owner'] = bot[2]
    cache['bot_id'] = bot_id
    cache['token'] = token
    cache['grupo'] = bot[10]
    payment_object = json.loads(bot[7])
    if('token' in payment_object.keys() and 'token' in payment_object.keys()):
        cache['gate_token'] = payment_object['token']
        cache['token_type'] = payment_object['type']
    
    application.bot_data['bot_id'] = bot_id
    application.bot_data['token'] = token
    
    # Outros setups podem ser adicionados aqui (handlers, comandos, etc.)

        
    fallbacks = [
    CommandHandler("cancel", cancel),
    CallbackQueryHandler(cancel, pattern='cancelar')
]

    # Adiciona o ConversationHandler para /texto
    conv_handler_texto = ConversationHandler(
        entry_points=[CommandHandler("texto", texto)],
        states={
            INPUT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_texto)]
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='cancelar')]
    )

    # ConversationHandler para o comando /texto2
    conv_handler_texto2 = ConversationHandler(
    entry_points=[CommandHandler("texto2", texto2)],
    states={
        INPUT_TEXT2: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_texto2)]
    },
    fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='cancelar')]
)
    # Adiciona o ConversationHandler para /midia_inicial
    conv_handler_midia = ConversationHandler(
    entry_points=[CommandHandler("midia_inicial", midia_inicial)],
    states={
        INPUT_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, recebe_midia)]
    },
    fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='cancelar')]
)
    
    conv_handler_texto_botao = ConversationHandler(
    entry_points=[CommandHandler("texto_botao", texto_botao)],
    states={
        INPUT_TEXT_BUTTON: [MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_texto_botao)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)
    
    conv_handler_disparo = ConversationHandler(
    entry_points=[CommandHandler('disparo', disparo)],
    states={
        MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, receber_midia)],
        TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_texto)],
        LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link)],
        CONFIRM: [CallbackQueryHandler(confirmacao_disparo)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)


    
    conv_handler_deletar_recuperacao = ConversationHandler(
    entry_points=[CommandHandler("deletar_recuperacao", deletar_recuperacao)],
    states={
        SELECIONAR_MENSAGEM_DELETAR: [
            CallbackQueryHandler(confirmar_deletar_recuperacao, pattern="^deletar_mensagem_"),
            CallbackQueryHandler(cancel, pattern="cancelar")
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel),  # Suporte ao comando /cancel
        CallbackQueryHandler(cancel, pattern="cancelar")  # Suporte ao botão "CANCELAR"
    ]
)
    conv_handler_gateway = ConversationHandler(
    entry_points=[CommandHandler("gateway", gateway)],
    states={
        INPUT_TOKEN: [CallbackQueryHandler(recebe_token)],
        TOKEN_RETRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, repete_token)]#,
        #CANCEL: [CallbackQueryHandler(cancel, pattern='cancelar')]
    },
    fallbacks=[
        CommandHandler("cancel", cancel),  # Suporte ao comando /cancel
        CallbackQueryHandler(cancel, pattern="cancelar")  # Suporte ao botão "CANCELAR"
    ]
)

    conv_handler_remover_texto = ConversationHandler(
    entry_points=[CommandHandler("remover_texto", remover_texto)],
    states={},
    fallbacks=[CommandHandler("cancel", cancel)]
)
    
    conv_handler_recuperacao_compra = ConversationHandler(
    entry_points=[CommandHandler("recuperacao_compra", recuperacao_compra)],
    states={
        SELECIONAR_MENSAGEM: [CallbackQueryHandler(selecionar_mensagem)],
        INPUT_MEDIA_RECUPERACAO: [MessageHandler(filters.PHOTO | filters.VIDEO, recebe_midia_recuperacao)],
        INPUT_TEXTO_RECUPERACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_texto_recuperacao)],
        INPUT_DESCONTO_RECUPERACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_desconto_recuperacao)],
        INPUT_TEMPO_RECUPERACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_tempo_recuperacao)],
    },
    fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='cancelar')]
)

    # Adiciona o ConversationHandler para /criar_plano
    conv_handler_criar_plano = ConversationHandler(
    entry_points=[CommandHandler("criar_plano", criar_plano)],
    states={
        INPUT_PLAN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_nome_plano)],
        INPUT_PLAN_DURATION: [CallbackQueryHandler(recebe_duracao_plano)],
        INPUT_PLAN_CUSTON: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_quantidade_plano)],
        INPUT_PLAN_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_valor_plano)],
        CONFIRMAR_CRIACAO: [CallbackQueryHandler(confirmar_criacao, pattern='^(criar_plano|cancelar)$')]
    },
    fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='^cancelar$')]
)
    conv_handler_upsell = ConversationHandler(
    entry_points=[CommandHandler("upsell", upsell)],
    states={
        INPUT_UPSELL_CONTENT: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, recebe_midia_upsell)],
        INPUT_UPSELL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_link_upsell)]
    },
    fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='cancelar')]
)

    
    # Adiciona o ConversationHandler para /grupo_id
    conv_handler_grupo_id = ConversationHandler(
    entry_points=[CommandHandler("vip", grupo_id)],
    states={
        INPUT_GRUPO_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, recebe_grupo_id)]
    },
    fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern='cancelar')]
)
 
    conv_handler_remover_midia = ConversationHandler(
    entry_points=[CommandHandler("remover_midia", remover_midia)],
    states={},
    fallbacks=[CommandHandler("cancel", cancel)]
)

    conv_handler_excluir_plano = ConversationHandler(
    entry_points=[CommandHandler("excluir_plano", excluir_plano)],
    states={
        SELECT_PLAN_TO_DELETE: [CallbackQueryHandler(confirmar_exclusao_plano, pattern="^delete_")]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)
    application.add_handler(ChatJoinRequestHandler(check_join_request))
    application.add_handler(conv_handler_texto)
    application.add_handler(conv_handler_texto2)
    application.add_handler(conv_handler_midia)
    application.add_handler(CommandHandler("start", start), group=0)
    application.add_handler(conv_handler_grupo_id)
    application.add_handler(conv_handler_upsell)
    application.add_handler(conv_handler_disparo)
    application.add_handler(MessageHandler(filters.COMMAND, handle_commands), group=1)
    application.add_handler(CallbackQueryHandler(button_callback_handler, pattern='^acessar_agora$'))
    application.add_handler(CallbackQueryHandler(plano_callback_handler, pattern='^plano_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages), group=2)
    application.add_handler(CallbackQueryHandler(gerar_pix_codigo, pattern='^gerar_pix$'))
    application.add_handler(CallbackQueryHandler(pagar_pix, pattern='^pagar_'))
    application.add_handler(conv_handler_texto_botao)
    application.add_handler(conv_handler_deletar_recuperacao)
    application.add_handler(CallbackQueryHandler(noop, pattern='noop'))
    application.add_handler(CommandHandler("remover_upsell", remover_upsell))
    application.add_handler(conv_handler_excluir_plano)
    application.add_handler(conv_handler_gateway)
    application.add_handler(conv_handler_criar_plano)
    application.add_handler(conv_handler_remover_texto)
    application.add_handler(conv_handler_recuperacao_compra)
    application.add_handler(CommandHandler("comandos", comandos))
    application.add_handler(conv_handler_remover_midia)
    application.add_handler(CallbackQueryHandler(cancel, pattern='cancelar'))
    application.add_handler(CommandHandler("cancel", cancel))

    print("Handler para /start adicionado.")  # Confirma que o handler foi adicionado
    try:
        #loop = asyncio.new_event_loop()  # Cria um novo loop de eventos
        #asyncio.set_event_loop(loop)    # Define o loop de eventos na thread atual
        cache['payment_loop'] = asyncio.new_event_loop()
        asyncio.set_event_loop(cache['payment_loop'])
        # Agendar verificação de expiração antes de iniciar o polling
        bot_instance = application.bot  # Define a instância do bot
        cache['payment_loop'].create_task(payment_task())
        cache['payment_loop'].create_task(agendar_verificacao_expiracao(bot_id, bot_instance))  # Adiciona a verificação de expiração
        print("Bot iniciado e pronto para receber comandos.")  # Log para indicar que o bot está pronto
        try:
            application.run_polling()  # Inicia o polling do bot Telegram
        except Conflict as e:
            print(f"Erro de conflito detectado: {e}")
            # Adicione ações para corrigir o conflito, como encerrar outras instâncias
            exit(1)  # Finaliza o script para evitar múltiplas execuções
    except Exception as e:
        print(f"[ERRO] Problema ao iniciar o bot: {e}")

    finally:
        cache['payment_loop'].run_until_complete(cache['payment_loop'].shutdown_asyncgens())  # Encerra geradores assíncronos, se houver
        cache['payment_loop'].close()  # Fecha o loop de eventos

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Por favor, forneça o token do bot como argumento.")
    else:
        #asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        run_bot(sys.argv[1])