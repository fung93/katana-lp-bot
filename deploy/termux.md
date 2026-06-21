# Run on an old Android phone (Termux) — free, no signup, always-on

Runs the **command bot** 24/7 on a spare phone, so `/commands` work even when your
PC is off. Alerts keep running on GitHub Actions. Only ONE command bot may run at a
time — **stop the bot on your PC once the phone is live** (two would clash on Telegram).

## 1. Install Termux (from F-Droid — NOT the Play Store version, it's broken)
- Install F-Droid: https://f-droid.org
- From F-Droid, install **Termux** and **Termux:Boot**.
- Open Termux and run:
```
pkg update && pkg upgrade -y
```

## 2. Install dependencies
```
pkg install -y python git postgresql
```
(`postgresql` provides `libpq`, which the Postgres driver loads at runtime.)

## 3. Get the bot + your secrets
```
git clone https://github.com/fung93/katana-lp-bot.git
cd katana-lp-bot
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-termux.txt
cp .env.example .env && nano .env
```
In `nano`, paste your 5 values (TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID,
DATABASE_URL, RPC_URL, WALLET_ADDRESS), then save: Ctrl-O, Enter, Ctrl-X.

## 4. Test
```
termux-wake-lock
python -m app.bot
```
Wait for `Application started`, send `/help` in Telegram. Then Ctrl-C.
Now **stop the bot on your PC** (only one command listener at a time).

## 5. Auto-start on boot + keep alive
```
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-bot.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/katana-lp-bot
. .venv/bin/activate
exec python -m app.bot
EOF
chmod +x ~/.termux/boot/start-bot.sh
sh ~/.termux/boot/start-bot.sh &
```
Termux:Boot re-runs that script after a phone reboot.

## 6. Stop Android from killing it
Android Settings → Apps → Termux → Battery → **Unrestricted** (disable optimization).
Leave the phone on its charger.

## Manage
```
ps aux | grep app.bot           # is it running?
pkill -f app.bot                # stop it
cd ~/katana-lp-bot && git pull && . .venv/bin/activate \
  && pip install -r requirements-termux.txt && pkill -f app.bot   # update (Termux:Boot/you restart)
```
