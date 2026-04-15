import requests
import time
import json
import re
from datetime import datetime

# ── Config ──────────────────────────────────────────────────

BOT_TOKEN = “8441286239:AAEiGauHKn7j8HZzvwuTcbF1vpYqGekwFJI”
CHAT_ID   = “1540373986”
SCAN_INTERVAL_MINUTES = 15

# ── Coin blacklist ───────────────────────────────────────────

BLOCK = {
‘USDCUSDT’,‘BUSDUSDT’,‘TUSDUSDT’,‘FDUSDUSDT’,‘USDEUSDT’,‘USDSUSDT’,
‘USD1USDT’,‘RLUSDUSDT’,‘XAUTUSDT’,‘PAXGUSDT’,‘WBTCUSDT’,‘BTCBUSDT’,
‘BARDUSDT’,‘GIGGLEUSDT’,‘BABYUSDT’,
}
BLOCK_PFX = [
‘USDC’,‘BUSD’,‘TUSD’,‘FDUS’,‘USDE’,‘USDS’,‘USD1’,‘RLUS’,
‘XAUT’,‘PAXG’,‘WBTC’,‘BTCB’,‘UP’,‘DOWN’,‘BULL’,‘BEAR’,‘3L’,‘3S’,
]

def is_bad(symbol, price):
if symbol in BLOCK: return True
if any(symbol.startswith(p) for p in BLOCK_PFX): return True
if not re.match(r’^[A-Z]{1,9}USDT$’, symbol): return True
if 0.985 <= float(price) <= 1.015: return True
return False

# ── Telegram ─────────────────────────────────────────────────

def send_message(text):
url = f”https://api.telegram.org/bot{BOT_TOKEN}/sendMessage”
try:
requests.post(url, json={
“chat_id”: CHAT_ID,
“text”: text,
“parse_mode”: “HTML”
}, timeout=10)
except Exception as e:
print(f”Telegram error: {e}”)

# ── Binance data ─────────────────────────────────────────────

def get_tickers():
r = requests.get(
“https://api.binance.com/api/v3/ticker/24hr”,
timeout=20
)
data = r.json()
# Make sure it’s a list
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

# ── Indicators ───────────────────────────────────────────────

def ema(values, period):
k = 2 / (period + 1)
result = [values[0]]
for v in values[1:]:
result.append(v * k + result[-1] * (1 - k))
return result

def calc_macd(closes, fast=12, slow=26, signal=9):
if len(closes) < slow + signal + 5:
return None
ema_fast   = ema(closes, fast)
ema_slow   = ema(closes, slow)
macd_line  = [f - s for f, s in zip(ema_fast, ema_slow)]
signal_line= ema(macd_line, signal)
n = len(macd_line) - 1
return {
‘macd’:      macd_line[n],
‘signal’:    signal_line[n],
‘hist’:      macd_line[n] - signal_line[n],
‘prev_macd’: macd_line[n-1],
‘prev_sig’:  signal_line[n-1],
‘prev_hist’: macd_line[n-1] - signal_line[n-1],
}

def calc_rsi(closes, period=14):
if len(closes) < period + 2:
return 50
gains, losses = 0, 0
for i in range(1, period + 1):
d = closes[i] - closes[i-1]
if d > 0: gains += d
else: losses -= d
avg_gain = gains / period
avg_loss = losses / period
for i in range(period + 1, len(closes)):
d = closes[i] - closes[i-1]
avg_gain = (avg_gain * (period-1) + max(d, 0)) / period
avg_loss = (avg_loss * (period-1) + max(-d, 0)) / period
if avg_loss == 0: return 100
return 100 - 100 / (1 + avg_gain / avg_loss)

def calc_vwap(klines):
vp, v = 0, 0
for k in klines:
tp  = (float(k[2]) + float(k[3]) + float(k[4])) / 3
vol = float(k[5])
vp += tp * vol
v  += vol
return vp / v if v else 0

def calc_atr(klines, period=14):
s, n = 0, 0
start = max(1, len(klines) - period)
for i in range(start, len(klines)):
h  = float(klines[i][2])
l  = float(klines[i][3])
pc = float(klines[i-1][4])
s += max(h - l, abs(h - pc), abs(l - pc))
n += 1
return s / n if n else 0

# ── Signal logic ─────────────────────────────────────────────

def get_signal(klines_15m, klines_1h):
if len(klines_15m) < 60 or len(klines_1h) < 60:
return None

```
closes_15m = [float(k[4]) for k in klines_15m]
price = closes_15m[-1]

# Dead coin check
hi = max(closes_15m[-20:])
lo = min(closes_15m[-20:])
if lo == 0 or (hi - lo) / lo < 0.01:
    return None

macd = calc_macd(closes_15m)
if not macd: return None

rsi_val  = calc_rsi(closes_15m[-30:])
vwap_val = calc_vwap(klines_15m)
atr_val  = calc_atr(klines_15m)

vols    = [float(k[5]) for k in klines_15m]
vol_avg = sum(vols[-20:-1]) / 19 if len(vols) >= 20 else sum(vols) / len(vols)
vol_up  = vols[-1] > vol_avg if vol_avg > 0 else False

# 1H trend filter
closes_1h  = [float(k[4]) for k in klines_1h]
ema21_1h   = ema(closes_1h, 21)
ema50_1h   = ema(closes_1h, 50)
trend_bull = ema21_1h[-1] > ema50_1h[-1]
trend_bear = ema21_1h[-1] < ema50_1h[-1]

# MACD crossover
bull_cross = (
    (macd['prev_macd'] <= macd['prev_sig'] and macd['macd'] > macd['signal']) or
    (macd['macd'] > macd['signal'] and macd['hist'] > macd['prev_hist'] and macd['hist'] > 0)
)
bear_cross = (
    (macd['prev_macd'] >= macd['prev_sig'] and macd['macd'] < macd['signal']) or
    (macd['macd'] < macd['signal'] and macd['hist'] < macd['prev_hist'] and macd['hist'] < 0)
)

above_vwap = price > vwap_val
long_rsi   = 45 <= rsi_val <= 68
short_rsi  = 32 <= rsi_val <= 55

long_ok  = bull_cross and above_vwap and long_rsi  and trend_bull
short_ok = bear_cross and not above_vwap and short_rsi and trend_bear

if not long_ok and not short_ok:
    return None

direction = 'LONG' if long_ok else 'SHORT'

if direction == 'LONG':
    score   = sum([bull_cross, above_vwap, long_rsi, vol_up, trend_bull])
    signals = {
        'MACD↑':     bull_cross,
        'ABOVE VWAP': above_vwap,
        'RSI OK':    long_rsi,
        'VOL↑':      vol_up,
        '1H TREND↑': trend_bull,
    }
else:
    score   = sum([bear_cross, not above_vwap, short_rsi, vol_up, trend_bear])
    signals = {
        'MACD↓':     bear_cross,
        'BELOW VWAP': not above_vwap,
        'RSI OK':    short_rsi,
        'VOL↑':      vol_up,
        '1H TREND↓': trend_bear,
    }

stop_dist = max(atr_val * 1.5, price * 0.012)
entry = price
sl    = entry - stop_dist if direction == 'LONG' else entry + stop_dist
tp1   = entry + stop_dist * 2   if direction == 'LONG' else entry - stop_dist * 2
tp2   = entry + stop_dist * 3.5 if direction == 'LONG' else entry - stop_dist * 3.5

pct_risk = abs((sl - entry) / entry * 100)
if pct_risk > 5 or pct_risk < 0.3:
    return None

return {
    'direction':  direction,
    'score':      score,
    'signals':    signals,
    'entry':      entry,
    'sl':         sl,
    'tp1':        tp1,
    'tp2':        tp2,
    'rsi':        rsi_val,
    'macd_hist':  macd['hist'],
    'pct_risk':   round(pct_risk, 1),
    'pct_target': round(abs((tp1 - entry) / entry * 100), 1),
}
```

# ── Format price ─────────────────────────────────────────────

def fmt(n):
if n >= 10000: return f”{n:.1f}”
if n >= 1000:  return f”{n:.2f}”
if n >= 100:   return f”{n:.2f}”
if n >= 10:    return f”{n:.3f}”
if n >= 1:     return f”{n:.4f}”
if n >= 0.1:   return f”{n:.5f}”
return f”{n:.6f}”

# ── Format Telegram message ──────────────────────────────────

def format_signal(name, sig):
emoji = “🟢” if sig[‘direction’] == ‘LONG’ else “🔴”
arrow = “▲” if sig[‘direction’] == ‘LONG’ else “▼”
stars = “⭐” * sig[‘score’]

```
sig_line = "\n".join([
    f"  {'✅' if v else '❌'} {k}"
    for k, v in sig['signals'].items()
])

return (
    f"{emoji} <b>{arrow} {sig['direction']} — {name}/USDT</b>\n"
    f"━━━━━━━━━━━━━━━━━━\n"
    f"📍 Entry:   <b>{fmt(sig['entry'])}</b>\n"
    f"🛑 Stop:    <b>{fmt(sig['sl'])}</b>  (-{sig['pct_risk']}%)\n"
    f"🎯 TP1:     <b>{fmt(sig['tp1'])}</b>  (+{sig['pct_target']}%)\n"
    f"🎯 TP2:     <b>{fmt(sig['tp2'])}</b>\n"
    f"━━━━━━━━━━━━━━━━━━\n"
    f"{sig_line}\n"
    f"━━━━━━━━━━━━━━━━━━\n"
    f"Confidence: {stars} {sig['score']}/5\n"
    f"RSI: {sig['rsi']:.1f}  |  R/R: 2.0\n"
    f"⚡ Confirm on Bybit 15m before entering"
)
```

# ── Main scan ─────────────────────────────────────────────────

def run_scan():
print(f”[{datetime.utcnow().strftime(’%H:%M:%S’)}] Scanning…”)

```
try:
    tickers = get_tickers()
except Exception as e:
    print(f"Ticker fetch error: {e}")
    return

if not tickers:
    print("Empty ticker list")
    return

# Build candidate list safely
candidates = []
for t in tickers:
    try:
        if not isinstance(t, dict): continue
        sym   = t.get('symbol', '')
        price = float(t.get('lastPrice', 0))
        vol   = float(t.get('quoteVolume', 0))
        chg   = float(t.get('priceChangePercent', 0))
        if not sym.endswith('USDT'): continue
        if is_bad(sym, price): continue
        if vol < 15_000_000: continue
        if chg == 0: continue
        candidates.append((sym, vol))
    except Exception:
        continue

# Top 80 by volume
candidates.sort(key=lambda x: x[1], reverse=True)
candidates = [c[0] for c in candidates[:80]]
print(f"Scanning {len(candidates)} coins...")

signals_found = []

for sym in candidates:
    try:
        klines_15m = get_klines(sym, '15m', 150)
        klines_1h  = get_klines(sym, '1h',  100)

        if len(klines_15m) < 60 or len(klines_1h) < 60:
            continue

        price = float(klines_15m[-1][4])
        if is_bad(sym, price):
            continue

        sig = get_signal(klines_15m, klines_1h)
        if sig:
            name = sym.replace('USDT', '')
            signals_found.append((name, sig))
            print(f"  ✓ {name} {sig['direction']} score={sig['score']}")

        time.sleep(0.15)

    except Exception as e:
        print(f"  Error {sym}: {e}")
        continue

# Sort by score, send top 5
signals_found.sort(key=lambda x: x[1]['score'], reverse=True)
top = signals_found[:5]

if not top:
    print("No signals this scan.")
    return

print(f"Sending {len(top)} signals...")
send_message(
    f"🔍 <b>SCAN — {datetime.utcnow().strftime('%H:%M UTC')}</b>\n"
    f"Found {len(top)} signal(s) from {len(candidates)} coins"
)
time.sleep(1)

for name, sig in top:
    send_message(format_signal(name, sig))
    time.sleep(1)
```

# ── Entry point ───────────────────────────────────────────────

if **name** == “**main**”:
print(”=” * 40)
print(”  CRYPTO SIGNAL BOT STARTED”)
print(f”  Scanning every {SCAN_INTERVAL_MINUTES} minutes”)
print(”=” * 40)

```
send_message(
    f"🤖 <b>Signal Bot Started</b>\n"
    f"Scanning top 80 coins every {SCAN_INTERVAL_MINUTES} min\n"
    f"Strategy: MACD + RSI + VWAP + 1H Trend\n"
    f"Target win rate: 70%+"
)

while True:
    try:
        run_scan()
    except Exception as e:
        print(f"Loop error: {e}")
        send_message(f"⚠️ Error: {e}")

    print(f"Sleeping {SCAN_INTERVAL_MINUTES} min...\n")
    time.sleep(SCAN_INTERVAL_MINUTES * 60)
```
