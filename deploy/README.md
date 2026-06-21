# Deploy to an always-on host (Oracle Always-Free VM, or any Ubuntu box)

Runs the whole bot — commands **and** the 60s monitor loop — as a systemd
service, 24/7, for free. This replaces the GitHub Actions cron (whose free
scheduler fires too rarely for timely alerts).

## 1. Create the VM (Oracle Cloud, Always Free)
- **Shape:** `VM.Standard.E2.1.Micro` (x86, always available) or
  `VM.Standard.A1.Flex` (ARM, more headroom — if not "out of capacity").
- **Image:** Ubuntu 22.04.
- **SSH key:** add your public key, or let Oracle generate a key pair and
  download the private key.
- **Ports:** none needed inbound — the bot is outbound-only (Telegram long-poll +
  RPC + Merkl).

## 2. Set it up
```bash
ssh -i <your-key> ubuntu@<vm-public-ip>
git clone https://github.com/fung93/katana-lp-bot.git
cd katana-lp-bot
bash deploy/setup.sh        # installs Python 3.12 + deps, creates .env
nano .env                   # paste your 5 secrets
bash deploy/setup.sh        # installs + starts the 24/7 service
```

## 3. Manage
```bash
sudo systemctl status katana-lp-bot --no-pager
journalctl -u katana-lp-bot -f      # live logs / alerts
sudo systemctl restart katana-lp-bot
```

The service sets `INPROCESS_MONITOR=1`, so this single process handles both
commands and the alert loop. Once it's live: **disable the GitHub Actions cron**
(redundant) and don't run a second `python -m app.bot` anywhere else — two
long-pollers conflict on Telegram.
