import os
import time
import logging
import json
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv
from requests.exceptions import ReadTimeout

# Configure logging
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_telegram_notification(message, chat_id):
    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage?chat_id={chat_id}&text={message}"
    try:
        requests.get(url)
    except Exception as e:
        logging.error(f"Failed to send Telegram notification: {e}")

def determine_btc_network(address):
    if address.startswith('3'):
        return 'BTC'
    elif address.startswith('bc1'):
        return 'BTC'
    else:
        return 'BTC'  # Default to legacy (P2PKH) network

def get_btc_withdrawal_fee(client):
    withdraw_fee_data = client.get_asset_details()
    btc_withdraw_fee = float(withdraw_fee_data['BTC']['withdrawFee'])
    return btc_withdraw_fee

def get_min_btc_withdrawal_amount(client):
    try:
        withdraw_info = client.get_asset_details()['BTC']
        return float(withdraw_info['minWithdrawAmount'])
    except Exception as e:
        logging.error(f"Failed to get minimum BTC withdrawal amount: {e}")
        return None

def process_updates(updates, client):
    print("Processing updates:", updates)
    for update in updates:
        if 'message' in update:
            message = update['message']
            if 'text' in message:
                chat_id = message['chat']['id']
                text = message['text']
                print(f"Received message: {text}")
                if text == '/balance':
                    btc_balance = float(client.get_asset_balance(asset='BTC')['free'])
                    send_telegram_notification(f"Current BTC balance: {btc_balance:.8f}", chat_id)


def get_telegram_updates(offset=None, timeout=30, limit=100):
    url = f"https://api.telegram.org/bot{telegram_bot_token}/getUpdates?timeout={timeout}&limit={limit}"
    if offset:
        url += f"&offset={offset}"
    response = requests.get(url)
    return json.loads(response.text)['result']



# Load environment variables
load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
ledger_btc_address = os.getenv('LEDGER_BTC_ADDRESS')
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

# Initialize Binance client
client = Client(api_key, api_secret, {"timeout": 20})  # Increase the timeout to 20 seconds

min_btc_withdrawal_amount = get_min_btc_withdrawal_amount(client)
if min_btc_withdrawal_amount is None:
    logging.error("Unable to proceed without minimum BTC withdrawal amount.")
    exit()

previous_balance_state = None
balance_below_minimum_notification_sent = False
last_update_id = None

while True:
    try:
        # Get Telegram updates
        updates = get_telegram_updates(offset=last_update_id)
        print("Fetched updates:", updates)
        if updates:
            last_update_id = updates[-1]['update_id'] + 1
            process_updates(updates, client)

        # Check BTC balance
        btc_balance = float(client.get_asset_balance(asset='BTC')['free'])
        

        # Withdraw BTC to Ledger wallet if balance is greater than or equal to minimum withdrawal amount
        if btc_balance >= min_btc_withdrawal_amount:
            btc_withdraw_fee = get_btc_withdrawal_fee(client)
            withdrawal_amount = btc_balance - btc_withdraw_fee
            withdrawal_amount_str = "{:.8f}".format(withdrawal_amount)

            net_withdrawal_amount = withdrawal_amount - btc_withdraw_fee
            net_withdrawal_amount_str = "{:.8f}".format(net_withdrawal_amount)

            if withdrawal_amount >= min_btc_withdrawal_amount:
                try:
                    # Determine the network for the address
                    network = determine_btc_network(ledger_btc_address)

                    # Perform withdrawal
                    withdrawal = client.withdraw(coin='BTC', address=ledger_btc_address, amount=withdrawal_amount_str, network=network)
                    logging.info(f"Successfully withdrawn {withdrawal_amount_str} BTC (with a fee of {btc_withdraw_fee}) to Ledger wallet. Net amount deposited: {net_withdrawal_amount_str} BTC.")

                    # Send Telegram notification
                    message = f"Successfully withdrawn {withdrawal_amount_str} BTC (with a fee of {btc_withdraw_fee}) to Ledger wallet. Net amount deposited: {net_withdrawal_amount_str} BTC."
                    send_telegram_notification(message, telegram_chat_id)

                except BinanceAPIException as e:
                    logging.error(f"Failed to withdraw BTC: {e}. Parameters: Address={ledger_btc_address}, Amount={withdrawal_amount_str}, Network={network}")
                    message = f"Failed to withdraw BTC: {e.message}. Parameters: Address={ledger_btc_address}, Amount={withdrawal_amount_str}, Network={network}"
                    send_telegram_notification(message, telegram_chat_id)

            else:
                logging.error("Withdrawal amount is less than the minimum withdrawal amount.")
                message = f"Failed to withdraw BTC: Withdrawal amount ({withdrawal_amount_str}) is less than the minimum withdrawal amount ({min_btc_withdrawal_amount})."
                send_telegram_notification(message, telegram_chat_id)
                exit()

    except BinanceRequestException as e:
        logging.error(f"A request exception occurred: {e}")
        message = f"A request exception occurred: {e}"
        send_telegram_notification(message, telegram_chat_id)

    except ReadTimeout as e:
        logging.warning(f"Read timeout occurred: {e}")
        message = f"Read timeout occurred: {e}"
        send_telegram_notification(message, telegram_chat_id)

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        message = f"An error occurred: {e}"
        send_telegram_notification(message, telegram_chat_id)

    time.sleep(10)
