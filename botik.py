import telebot
import time
import pandas as pd
import os
from binance.client import Client
from binance.exceptions import BinanceAPIException
from threading import Thread
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from telebot import types

TOKEN = '7192149351:AAFQOu1ODlMwuzokt31NwR_VoEgwTxvoJEM'
bot = telebot.TeleBot(TOKEN)

client = Client()

user_data = {}
awaiting_deposit_input = {}
watched_signals = set()
monitored_symbols = ["DOGEUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT", "BNBUSDT"]
last_signals = []
last_announcement_time = 0
SIGNALS_LOG = 'signals_log.csv'

if not os.path.exists(SIGNALS_LOG):
    df_init = pd.DataFrame(columns=['symbol', 'entry', 'stop', 'take', 'timestamp', 'status', 'direction'])
    df_init.to_csv(SIGNALS_LOG, index=False)

@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.chat.id
    if user_id not in user_data:
        user_data[user_id] = {'deposit': 50, 'risk': 1.0}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('💼 Установить депозит')
    markup.row('📊 Последние сигналы', '🧠 Начать анализ')
    markup.row('📈 Монета', '📘 Статистика')
    bot.send_message(user_id, "🧠 Я ваш трейдинг-бот, мой господин.\nВыберите действие с клавиатуры:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '📘 Статистика')
def show_stats(message):
    try:
        df = pd.read_csv(SIGNALS_LOG)
        total = len(df)
        wins = len(df[df['status'] == 'win'])
        losses = len(df[df['status'] == 'loss'])
        pending = len(df[df['status'] == 'pending'])
        winrate = round((wins / total) * 100, 1) if total > 0 else 0
        latest = df.tail(3)
        lines = [f"• {row['symbol']} → {row['status']}" for _, row in latest.iterrows()]
        result = (
            f"📘 Ваша торговая статистика:\n\n"
            f"Всего сигналов: {total}\n"
            f"🟢 В плюс: {wins}\n"
            f"🔴 В минус: {losses}\n"
            f"⏳ Ожидают: {pending}\n"
            f"📊 Winrate: {winrate}%\n\n"
            f"Последние:\n" + '\n'.join(lines)
        )
        bot.send_message(message.chat.id, result)
    except Exception as e:
        bot.send_message(message.chat.id, "⚠️ Ошибка чтения статистики.")
        print("Ошибка статистики:", e)

@bot.message_handler(func=lambda message: message.text == '📊 Последние сигналы')
def show_signals(message):
    if not last_signals:
        bot.send_message(message.chat.id, "📭 Пока нет активных сигналов.")
    else:
        response = "📜 Последние сигналы:\n"
        for s in last_signals[-10:]:
            response += (
                f"\n📈 {s['symbol']} ({'LONG' if s['dir'] == 'long' else 'SHORT'})\n"
                f"• Вход: {s['entry']}\n"
                f"• Стоп: {s['stop']}\n"
                f"• Тейк: {s['take']}\n"
                f"• RSI: {s['rsi']}\n"
            )
        bot.send_message(message.chat.id, response)

@bot.message_handler(func=lambda m: True)
def handle_buttons(message):
    user_id = message.chat.id
    if message.text == '💼 Установить депозит':
        awaiting_deposit_input[user_id] = True
        bot.send_message(user_id, "💰 Введите сумму вашего депозита в USDT:")
    elif awaiting_deposit_input.get(user_id):
        try:
            val = float(message.text.strip())
            user_data[user_id]['deposit'] = val
            awaiting_deposit_input[user_id] = False
            bot.send_message(user_id, f"✅ Депозит установлен: {val} USDT")
        except:
            bot.send_message(user_id, "❌ Ошибка. Введите только число, например: 50")
    elif message.text == '🧠 Начать анализ':
        bot.send_message(user_id, "📡 Запускаю анализ рынка...")
        Thread(target=analyze_market, args=(user_id,)).start()
        Thread(target=update_signal_status).start()
    elif message.text == '📈 Монета':
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [types.InlineKeyboardButton(text=s.replace("USDT", ""), callback_data=f"монета_{s}") for s in monitored_symbols]
        markup.add(*buttons)
        bot.send_message(user_id, "💠 Выберите монету:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("монета_"))
def handle_coin_selection(call):
    symbol = call.data.replace("монета_", "")
    try:
        klines = client.get_klines(symbol=symbol, interval="1h", limit=100)
        df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume",
                                           "close_time", "quote_asset_volume", "trades", "taker_base", "taker_quote", "ignore"])
        df["close"] = pd.to_numeric(df["close"])
        rsi = RSIIndicator(df["close"], window=14).rsi().iloc[-1]
        price = float(df["close"].iloc[-1])
        signal = next((s for s in last_signals if s['symbol'] == symbol), None)
        text = f"📈 {symbol}\n💵 Рыночная цена: {round(price, 4)} USDT\n📊 RSI (1H): {round(rsi, 2)}\n"
        if signal:
            text += f"🟢 Активный сигнал ({'LONG' if signal['dir']=='long' else 'SHORT'}):\n• Вход: {signal['entry']}\n• Стоп: {signal['stop']}\n• Тейк: {signal['take']}"
        else:
            text += "🔍 Пока нет сигнала для входа."
        bot.send_message(call.message.chat.id, text)
    except Exception as e:
        bot.send_message(call.message.chat.id, "⚠️ Ошибка при получении информации по монете.")
        print("Ошибка в handle_coin_selection:", e)

def check_reversal_pattern(df, direction):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    open_ = float(last['open'])
    close = float(last['close'])
    low = float(last['low'])
    high = float(last['high'])
    body = abs(close - open_)
    shadow = (open_ - low) if close > open_ else (high - close)
    if direction == 'long':
        is_hammer = shadow > body * 1.5 and close > open_
        is_engulfing = close > open_ and open_ < prev['close'] and close > prev['open']
        return is_hammer or is_engulfing
    else:
        is_inverted_hammer = shadow > body * 1.5 and close < open_
        is_bearish_engulfing = close < open_ and open_ > prev['close'] and close < prev['open']
        return is_inverted_hammer or is_bearish_engulfing

def update_signal_status():
    while True:
        try:
            df = pd.read_csv(SIGNALS_LOG)
            updated = False
            for idx, row in df[df['status'] == 'pending'].iterrows():
                symbol = row['symbol']
                stop = float(row['stop'])
                take = float(row['take'])
                candles = client.get_klines(symbol=symbol, interval="5m", limit=10)
                closes = [float(c[4]) for c in candles]
                high = max(closes)
                low = min(closes)
                if row['direction'] == 'long':
                    if high >= take:
                        df.at[idx, 'status'] = 'win'
                        updated = True
                    elif low <= stop:
                        df.at[idx, 'status'] = 'loss'
                        updated = True
                else:
                    if low <= take:
                        df.at[idx, 'status'] = 'win'
                        updated = True
                    elif high >= stop:
                        df.at[idx, 'status'] = 'loss'
                        updated = True
            if updated:
                df.to_csv(SIGNALS_LOG, index=False)
        except Exception as e:
            print("Ошибка обновления сигналов:", e)
        time.sleep(300)

def analyze_market(user_id):
    global last_announcement_time
    while True:
        current_time = time.time()
        if current_time - last_announcement_time > 1800:
            bot.send_message(user_id, "🔍 Бот продолжает анализировать рынок...")
            last_announcement_time = current_time
        for symbol in monitored_symbols:
            try:
                h1_klines = client.get_klines(symbol=symbol, interval="1h", limit=100)
                h1_df = pd.DataFrame(h1_klines, columns=["timestamp", "open", "high", "low", "close", "volume",
                                                          "close_time", "quote_asset_volume", "trades", "taker_base", "taker_quote", "ignore"])
                h1_df["close"] = pd.to_numeric(h1_df["close"])
                rsi_h1 = RSIIndicator(h1_df["close"], window=14).rsi().iloc[-1]
                ema = EMAIndicator(h1_df["close"], window=200).ema_indicator().iloc[-1]
                price_now = h1_df["close"].iloc[-1]
                direction = None
                if rsi_h1 < 30 and price_now > ema:
                    direction = 'long'
                elif rsi_h1 > 70 and price_now < ema:
                    direction = 'short'
                if direction:
                    m5_klines = client.get_klines(symbol=symbol, interval="5m", limit=10)
                    df = pd.DataFrame(m5_klines, columns=["timestamp", "open", "high", "low", "close", "volume",
                                                          "close_time", "quote_asset_volume", "trades", "taker_base", "taker_quote", "ignore"])
                    df["close"] = pd.to_numeric(df["close"])
                    df["open"] = pd.to_numeric(df["open"])
                    df["low"] = pd.to_numeric(df["low"])
                    df["high"] = pd.to_numeric(df["high"])
                    if check_reversal_pattern(df, direction) and f"{symbol}_{direction}" not in watched_signals:
                        price = float(df["close"].iloc[-1])
                        stop = price - price * 0.02 if direction == 'long' else price + price * 0.02
                        take = price + price * 0.04 if direction == 'long' else price - price * 0.04
                        user_deposit = user_data[user_id]['deposit']
                        user_risk_percent = user_data[user_id]['risk']
                        risk_usdt = user_deposit * user_risk_percent / 100
                        volume = round(risk_usdt / abs(price - stop), 2)
                        last_signals.append({
                            'symbol': symbol,
                            'entry': round(price, 4),
                            'stop': round(stop, 4),
                            'take': round(take, 4),
                            'rsi': round(rsi_h1, 2),
                            'dir': direction,
                            'volume': volume,
                            'cost': round(volume * price, 2),
                            'risk': round(risk_usdt, 2),
                            'percent': round((volume * price) / user_deposit * 100, 1)
                        })
                        watched_signals.add(f"{symbol}_{direction}")
                        timestamp = int(time.time())
                        with open(SIGNALS_LOG, 'a') as f:
                            f.write(f"{symbol},{round(price, 4)},{round(stop, 4)},{round(take, 4)},{timestamp},pending,{direction}\n")
                        bot.send_message(user_id,
                            f"📊 Сигнал ({'🟩 LONG' if direction == 'long' else '🟥 SHORT'}): {symbol}\n"
                            f"💵 Цена: {round(price, 4)} | RSI(1H): {round(rsi_h1, 2)}\n"
                            f"🛑 Стоп: {round(stop, 4)} | 🎯 Тейк: {round(take, 4)}\n"
                            f"📦 Объём: {volume} ({round(volume * price, 2)} USDT)\n"
                            f"📍 Условие: RSI + свеча + EMA фильтр\n"
                            f"⚙️ Binance вход: 100% от депозита | Плечо: x1")
            except Exception as e:
                print("Ошибка анализа:", e)
        time.sleep(60)

bot.polling(none_stop=True)
