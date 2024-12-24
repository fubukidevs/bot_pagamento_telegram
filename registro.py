import manager
import asyncio, json, requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from multiprocessing import Process
# Função para carregar e iniciar todos os bots registrados


config = json.loads(open('./config.json', 'r').read())

# Função para lidar com o comando /start no registro de novos bots
async def start_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Envie o TOKEN do seu bot para registrá-lo.')

# Função para verificar se o usuário é o administrador do bot registrado
def is_admin_of_bot(user_id, token):
    bot = manager.get_bot_by_token(token)
    if bot[2] == user_id:
        return True
    return False




# Função para receber o token e iniciar um novo bot
async def receive_token_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_token = update.message.text.strip()
    admin_id = update.effective_user.id  # Obtém o ID do usuário que enviou o token
    # Verificar se o token já está registrado
    if manager.bot_exists(new_token):
        await update.message.reply_text('Token já registrado no sistema.')
    if manager.bot_banned(str(admin_id)):
        await update.message.reply_photo('https://media.tenor.com/BosnE3kdeu8AAAAM/banned-pepe.gif', caption='Você foi banido do sistema.')
    
    
    else:
        telegram_bot = manager.check_bot_token(new_token)
        if telegram_bot:
            print('Novo BOT no sistema')
            print(telegram_bot)
            id = telegram_bot['result']['id']
            bot = manager.create_bot(id, new_token, admin_id, 'false')
            requests.get(f'{config['url']}/start/{id}')
            await update.message.reply_text(f'Bot t.me/{telegram_bot['result']['username']} registrado e iniciado. Apenas você pode gerenciá-lo.')
        else:
            await update.message.reply_text(f'O token inserido e invalido.')
    return 

    
    

# Função principal para rodar o bot de registro
def main():
    # Token do bot de registro
    registro_token = config['registro']  # Substitua pelo token do bot de registro

    # Criar o aplicativo do bot com o token de registro
    application = Application.builder().token(registro_token).build()

    # Adicionar um manipulador para o comando /start
    application.add_handler(CommandHandler('start', start_register))
    
    # Adicionar um manipulador para receber o token do novo bot
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token_register))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token_register))
    # Preparar o loop de eventos para o asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print('Iniciando BOT de Registro')
    application.run_polling()





if __name__ == '__main__':
    main()