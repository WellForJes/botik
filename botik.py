# Бот с полной логикой и фиксами (включая баг с депозитом)

import os
import time
import pandas as pd
from threading import Thread
from dotenv import load_dotenv
import telebot
from telebot import types
from binance.client import Client
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

# Загрузка .env и ключей
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

bot = telebot.TeleBot(TOKEN)
client = Client(api_key=API_KEY, api_secret=API_SECRET)

monitored_symbols = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "MATICUSDT", "ARBUSDT", "INJUSDT", "OPUSDT", "APTUSDT", "SUIUSDT",
    "RNDRUSDT", "LDOUSDT", "AAVEUSDT", "NEARUSDT", "FTMUSDT"
]

user_data = {}
awaiting_deposit_input = {}
user_analysis_flags = {}
last_signals = []
last_analysis_logs = []
SIGNALS_LOG = 'signals_log.csv'

if not os.path.exists(SIGNALS_LOG):
    pd.DataFrame(columns=['symbol', 'entry', 'stop', 'take', 'timestamp', 'status', 'direction']).to_csv(SIGNALS_LOG, index=False)

@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.chat.id
    if user_id not in user_data:
        user_data[user_id] = {'deposit': 100, 'risk': 1.0}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('💼 Установить депозит')
    markup.row('📊 Последние сигналы', '🧠 Начать анализ')
    markup.row('📈 Монета', '📘 Статистика', '🦾 Отчёт')
    bot.send_message(user_id, "Добро пожаловать в PRO трейдинг-бота. Выберите опцию:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '💼 Установить депозит')
def set_deposit(message):
    awaiting_deposit_input[message.chat.id] = True
    bot.send_message(message.chat.id, "Введите сумму вашего депозита в USDT:")

@bot.message_handler(func=lambda m: awaiting_deposit_input.get(m.chat.id, False))
def save_deposit(message):
    text = message.text.strip().replace(",", ".")
    if text.lower() == "отмена":
        awaiting_deposit_input[message.chat.id] = False
        bot.send_message(message.chat.id, "🚫 Установка депозита отменена.")
        return
    try:
        deposit = float(text)
        if deposit <= 0:
            bot.send_message(message.chat.id, "❌ Введите число больше нуля.")
            return
        user_data[message.chat.id]['deposit'] = deposit
        awaiting_deposit_input[message.chat.id] = False
        bot.send_message(message.chat.id, f"✅ Депозит установлен: {deposit} USDT")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка. Введите только положительное число или напишите 'Отмена'")

@bot.message_handler(func=lambda m: m.text == '🧠 Начать анализ')
def start_analysis(message):
    user_id = message.chat.id
    if user_analysis_flags.get(user_id, False):
        bot.send_message(user_id, "⏳ Анализ уже запущен.")
    else:
        bot.send_message(user_id, "🚀 Запускаю анализ рынка...")
        user_analysis_flags[user_id] = True
        Thread(target=analyze_market, args=(user_id,)).start()

@bot.message_handler(func=lambda m: m.text == '📈 Монета')
def choose_coin(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    for symbol in monitored_symbols:
        markup.add(types.InlineKeyboardButton(text=symbol.replace("USDT", ""), callback_data=symbol))
    bot.send_message(message.chat.id, "Выберите монету:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '📘 Статистика')
def show_stats(message):
    try:
        df = pd.read_csv(SIGNALS_LOG)
        total = len(df)
        win = len(df[df.status == 'win'])
        loss = len(df[df.status == 'loss'])
        pending = len(df[df.status == 'pending'])
        bot.send_message(message.chat.id, f"📊 Всего сигналов: {total}\n🟢 Побед: {win}\n🔴 Поражений: {loss}\n⏳ В ожидании: {pending}")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка чтения статистики: {e}")

@bot.message_handler(func=lambda m: m.text == '🦾 Отчёт')
def show_analysis_info(message):
    total = len(monitored_symbols)
    logs = "\n\n".join(last_analysis_logs[-5:]) if last_analysis_logs else "Пока нет анализа."
    bot.send_message(message.chat.id, f"🔍 Монет в анализе: {total}\n📋 Последние проверки:\n\n{logs}")

@bot.callback_query_handler(func=lambda call: True)
def handle_coin_callback(call):
    symbol = call.data
    try:
        klines = client.get_klines(symbol=symbol, interval="1h", limit=100)
        df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "c1", "c2", "c3", "c4", "c5", "c6"])
        df['close'] = pd.to_numeric(df['close'])
        price = df['close'].iloc[-1]
        rsi = RSIIndicator(df['close']).rsi().iloc[-1]
        bot.send_message(call.message.chat.id, f"📈 {symbol}\nЦена: {price:.2f} USDT\nRSI (1H): {rsi:.2f}")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"Ошибка получения данных по {symbol}: {e}")

def detect_candle_pattern(df, direction):
    last_open = float(df['open'].iloc[-1])
    last_close = float(df['close'].iloc[-1])
    prev_open = float(df['open'].iloc[-2])
    prev_close = float(df['close'].iloc[-2])
    if direction == 'long':
        return last_close > last_open and last_open < prev_close and last_close > prev_open
    else:
        return last_close < last_open and last_open > prev_close and last_close < prev_open

def analyze_market(user_id):
    while True:
        for symbol in monitored_symbols:
            try:
                df_1h = pd.DataFrame(client.get_klines(symbol=symbol, interval="1h", limit=100),
                                  columns=["timestamp", "open", "high", "low", "close", "volume", "c1", "c2", "c3", "c4", "c5", "c6"])
                df_1h['close'] = pd.to_numeric(df_1h['close'])
                df_1h['open'] = pd.to_numeric(df_1h['open'])
                df_1h['volume'] = pd.to_numeric(df_1h['volume'])

                rsi_1h = RSIIndicator(df_1h['close']).rsi().iloc[-1]
                ema_1h = EMAIndicator(df_1h['close'], window=200).ema_indicator().iloc[-1]
                macd_1h = MACD(df_1h['close']).macd_diff().iloc[-1]
                price_1h = df_1h['close'].iloc[-1]
                support = df_1h['close'].rolling(window=20).min().iloc[-1]
                resistance = df_1h['close'].rolling(window=20).max().iloc[-1]

                trend_long = rsi_1h < 30 and price_1h > ema_1h and macd_1h > 0 and price_1h <= support * 1.02
                trend_short = rsi_1h > 70 and price_1h < ema_1h and macd_1h < 0 and price_1h >= resistance * 0.98

                df_5m = pd.DataFrame(client.get_klines(symbol=symbol, interval="5m", limit=100),
                                  columns=["timestamp", "open", "high", "low", "close", "volume", "c1", "c2", "c3", "c4", "c5", "c6"])
                df_5m['close'] = pd.to_numeric(df_5m['close'])
                df_5m['open'] = pd.to_numeric(df_5m['open'])
                df_5m['volume'] = pd.to_numeric(df_5m['volume'])

                price_5m = df_5m['close'].iloc[-1]

                if trend_long and detect_candle_pattern(df_5m, 'long'):
                    send_signal(user_id, symbol, price_5m, 'long')
                elif trend_short and detect_candle_pattern(df_5m, 'short'):
                    send_signal(user_id, symbol, price_5m, 'short')
                else:
                    last_analysis_logs.append(f"{symbol}: тренд не подтверждён или нет свечи входа.")
                    if len(last_analysis_logs) > 10:
                        last_analysis_logs.pop(0)

            except Exception as e:
                bot.send_message(user_id, f"Ошибка анализа {symbol}: {e}")
        time.sleep(60)

def send_signal(user_id, symbol, price, direction):
    deposit = user_data[user_id]['deposit']
    risk = deposit * user_data[user_id]['risk'] / 100
    stop = price * (0.98 if direction == 'long' else 1.02)
    take = price * (1.04 if direction == 'long' else 0.96)
    volume = round(risk / abs(price - stop), 2)
    last_signals.append({'symbol': symbol, 'entry': price, 'stop': stop, 'take': take, 'dir': direction})
    with open(SIGNALS_LOG, 'a') as f:
        f.write(f"{symbol},{price:.2f},{stop:.2f},{take:.2f},{int(time.time())},pending,{direction}\n")
    bot.send_message(user_id,
        f"📢 Новый сигнал {symbol} ({'LONG' if direction == 'long' else 'SHORT'})\n💰 Цена: {price:.2f} USDT\n⛔ Стоп: {stop:.2f}\n🎯 Тейк: {take:.2f}\n📦 Объём: {volume}")

bot.polling(none_stop=True)
