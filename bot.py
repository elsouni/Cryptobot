import requests
import time
import re
import os
from datetime import datetime

BOT_TOKEN = os.environ.get(“BOT_TOKEN”, “”)
CHAT_ID = os.environ.get(“CHAT_ID”, “”)
SCAN_INTERVAL_MINUTES = 15

BLOCK = set([
“USDCUSDT”,“BUSDUSDT”,“TUSDUSDT”,“FDUSDUSDT”,“USDEUSDT”,“USDSUSDT”,
“USD1USDT”,“RLUSDUSDT”,“XAUTUSDT”,“PAXGUSDT”,“WBTCUSDT”,“BTCBUSDT”,
“BARDUSDT”,“GIGGLEUSDT”,“BABYUSDT”,
])
BLOCK_PFX = [
“USDC”,“BUSD”,“TUSD”,“FDUS”,“USDE”,“USDS”,“USD1”,“RLUS”,
“XAUT”,“PAXG”,“WBTC”,“BTCB”,“UP”,“DOWN”,“BULL”,“BEAR”,“3L”,“3S”,
]

def is_bad(symbol, price):
if symbol in BLOCK:
return True
for p in BLOCK_PFX:
if symbol.startswith(p):
return True
if not re.match(r”^[A-Z]{1,9}USDT$”, symbol):
return True
try:
p = float(price)
if 0.985 <= p <= 1.015:
return True
except:
return True
return False

def send_message(text):
url = “https://api.telegram.org/bot” + BOT_TOKEN + “/sendMessage”
try:
requests.post(url, json={“chat_id”: CHAT_ID, “text”: text, “parse_mode”: “HTML”}, timeout=10)
except Exception as e:
print(“Telegram error: “ + str(e))

def get_tickers():
r = requests.get(“https://api.binance.com/api/v3/ticker/24hr”, timeout=20)
data = r.json()
if not isinstance(data, list):
return []
return data

def get_klines(symbol, interval, limit=150):
r = requests.get(
“https://api.binance.com/api/v3/klines”,
params={“symbol”: symbol, “interval”: interval, “limit”: limit},
timeout=15
)
data = r.json()
if not isinstance(data, list):
return []
return data

def ema(values, period):
k = 2.0 / (period + 1)
result = [values[0]]
for v in values[1:]:
result.append(v * k + result[-1] * (1 - k))
return result

def calc_macd(closes):
if len(closes) < 40:
return None
ef = ema(closes, 12)
es = ema(closes, 26)
ml = [ef[i] - es[i] for i in range(len(ef))]
sl = ema(ml, 9)
n = len(ml) - 1
return {
“macd”: ml[n],
“signal”: sl[n],
“hist”: ml[n] - sl[n],
“prev_macd”: ml[n-1],
“prev_sig”: sl[n-1],
“prev_hist”: ml[n-1] - sl[n-1],
}

def calc_rsi(closes, period=14):
if len(closes) < period + 2:
return 50
g = 0.0
l = 0.0
for i in range(1, period + 1):
d = closes[i] - closes[i-1]
if d > 0:
g += d
else:
l -= d
ag = g / period
al = l / period
for i in range(period + 1, len(closes)):
d = closes[i] - closes[i-1]
ag = (ag * (period - 1) + max(d, 0)) / period
al = (al * (period - 1) + max(-d, 0)) / period
if al == 0:
return 100
return 100 - 100 / (1 + ag / al)

def calc_vwap(klines):
vp = 0.0
v = 0.0
for k in klines:
tp = (float(k[2]) + float(k[3]) + float(k[4])) / 3
vol = float(k[5])
vp += tp * vol
v += vol
if v == 0:
return 0
return vp / v

def calc_atr(klines, period=14):
s = 0.0
n = 0
start = max(1, len(klines) - period)
for i in range(start, len(klines)):
h = float(klines[i][2])
lo = float(klines[i][3])
pc = float(klines[i-1][4])
s += max(h - lo, abs(h - pc), abs(lo - pc))
n += 1
if n == 0:
return 0
return s / n

def get_signal(klines_15m, klines_1h):
if len(klines_15m) < 60 or len(klines_1h) < 60:
return None
closes = [float(k[4]) for k in klines_15m]
price = closes[-1]
hi = max(closes[-20:])
lo = min(closes[-20:])
if lo == 0 or (hi - lo) / lo < 0.01:
return None
macd = calc_macd(closes)
if not macd:
return None
rsi_val = calc_rsi(closes[-30:])
vwap_val = calc_vwap(klines_15m)
atr_val = calc_atr(klines_15m)
vols = [float(k[5]) for k in klines_15m]
vol_avg = sum(vols[-20:-1]) / 19
vol_up = vols[-1] > vol_avg if vol_avg > 0 else False
closes_1h = [float(k[4]) for k in klines_1h]
ema21 = ema(closes_1h, 21)
ema50 = ema(closes_1h, 50)
trend_bull = ema21[-1] > ema50[-1]
trend_bear = ema21[-1] < ema50[-1]
bull_cross = (
(macd[“prev_macd”] <= macd[“prev_sig”] and macd[“macd”] > macd[“signal”]) or
(macd[“macd”] > macd[“signal”] and macd[“hist”] > macd[“prev_hist”] and macd[“hist”] > 0)
)
bear_cross = (
(macd[“prev_macd”] >= macd[“prev_sig”] and macd[“macd”] < macd[“signal”]) or
(macd[“macd”] < macd[“signal”] and macd[“hist”] < macd[“prev_hist”] and macd[“hist”] < 0)
)
above_vwap = price > vwap_val
long_rsi = 45 <= rsi_val <= 68
short_rsi = 32 <= rsi_val <= 55
long_ok = bull_cross and above_vwap and long_rsi and trend_bull
short_ok = bear_cross and (not above_vwap) and short_rsi and trend_bear
if not long_ok and not short_ok:
return None
direction = “LONG” if long_ok else “SHORT”
if direction == “LONG”:
score = sum([bull_cross, above_vwap, long_rsi, vol_up, trend_bull])
signals = {“MACD UP”: bull_cross, “ABOVE VWAP”: above_vwap, “RSI OK”: long_rsi, “VOL UP”: vol_up, “1H BULL”: trend_bull}
else:
score = sum([bear_cross, not above_vwap, short_rsi, vol_up, trend_bear])
signals = {“MACD DOWN”: bear_cross, “BELOW VWAP”: not above_vwap, “RSI OK”: short_rsi, “VOL UP”: vol_up, “1H BEAR”: trend_bear}
stop_dist = max(atr_val * 1.5, price * 0.012)
entry = price
if direction == “LONG”:
sl = entry - stop_dist
tp1 = entry + stop_dist * 2
tp2 = entry + stop_dist * 3.5
else:
sl = entry + stop_dist
tp1 = entry - stop_dist * 2
tp2 = entry - stop_dist * 3.5
pct_risk = abs((sl - entry) / entry * 100)
if pct_risk > 5 or pct_risk < 0.3:
return None
return {
“direction”: direction,
“score”: score,
“signals”: signals,
“entry”: entry,
“sl”: sl,
“tp1”: tp1,
“tp2”: tp2,
“rsi”: rsi_val,
“pct_risk”: round(pct_risk, 1),
“pct_target”: round(abs((tp1 - entry) / entry * 100), 1),
}

def fmt(n):
if n >= 10000:
return str(round(n, 1))
if n >= 100:
return str(round(n, 2))
if n >= 1:
return str(round(n, 4))
if n >= 0.1:
return str(round(n, 5))
return str(round(n, 6))

def format_signal(name, sig):
d = sig[“direction”]
stars = str(sig[“score”]) + “/5”
lines = []
for k, v in sig[“signals”].items():
lines.append((“YES “ if v else “NO  “) + k)
sig_text = “\n”.join(lines)
msg = (
d + “ – “ + name + “/USDT\n”
“—————––\n”
“Entry:  “ + fmt(sig[“entry”]) + “\n”
“Stop:   “ + fmt(sig[“sl”]) + “  (-” + str(sig[“pct_risk”]) + “%)\n”
“TP1:    “ + fmt(sig[“tp1”]) + “  (+” + str(sig[“pct_target”]) + “%)\n”
“TP2:    “ + fmt(sig[“tp2”]) + “\n”
“—————––\n”
+ sig_text + “\n”
“—————––\n”
“Confidence: “ + stars + “\n”
“RSI: “ + str(round(sig[“rsi”], 1)) + “  RR: 2.0\n”
“Check Bybit 15m before entering”
)
return msg

def run_scan():
print(”[” + datetime.utcnow().strftime(”%H:%M:%S”) + “] Scanning…”)
try:
tickers = get_tickers()
except Exception as e:
print(“Ticker error: “ + str(e))
return
if not tickers:
print(“No tickers”)
return
candidates = []
for t in tickers:
try:
if not isinstance(t, dict):
continue
sym = str(t.get(“symbol”, “”))
price = float(t.get(“lastPrice”, 0))
vol = float(t.get(“quoteVolume”, 0))
chg = float(t.get(“priceChangePercent”, 0))
if not sym.endswith(“USDT”):
continue
if is_bad(sym, price):
continue
if vol < 15000000:
continue
if chg == 0:
continue
candidates.append((sym, vol))
except:
continue
candidates.sort(key=lambda x: x[1], reverse=True)
candidates = [c[0] for c in candidates[:80]]
print(“Scanning “ + str(len(candidates)) + “ coins…”)
signals_found = []
for sym in candidates:
try:
k15 = get_klines(sym, “15m”, 150)
k1h = get_klines(sym, “1h”, 100)
if len(k15) < 60 or len(k1h) < 60:
continue
price = float(k15[-1][4])
if is_bad(sym, price):
continue
sig = get_signal(k15, k1h)
if sig:
name = sym.replace(“USDT”, “”)
signals_found.append((name, sig))
print(“SIGNAL: “ + name + “ “ + sig[“direction”] + “ score=” + str(sig[“score”]))
time.sleep(0.15)
except Exception as e:
print(“Error “ + sym + “: “ + str(e))
continue
signals_found.sort(key=lambda x: x[1][“score”], reverse=True)
top = signals_found[:5]
if not top:
print(“No signals this scan.”)
return
send_message(“SCAN “ + datetime.utcnow().strftime(”%H:%M UTC”) + “ – “ + str(len(top)) + “ signal(s) found”)
time.sleep(1)
for name, sig in top:
send_message(format_signal(name, sig))
time.sleep(1)

if **name** == “**main**”:
print(“BOT STARTED”)
if not BOT_TOKEN:
print(“ERROR: BOT_TOKEN environment variable not set”)
else:
send_message(“Signal Bot Started - scanning every “ + str(SCAN_INTERVAL_MINUTES) + “ min”)
while True:
try:
run_scan()
except Exception as e:
print(“Loop error: “ + str(e))
send_message(“Error: “ + str(e))
print(“Sleeping “ + str(SCAN_INTERVAL_MINUTES) + “ min…”)
time.sleep(SCAN_INTERVAL_MINUTES * 60)
