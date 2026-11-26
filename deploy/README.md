# Deploying the live side to the Raspberry Pi

A checklist for going from a blank Pi to unattended **paper** trading. It takes about an hour. Everything here was prepared and tested on a laptop with a simulated broker; the only new things on the Pi are the real paper keys and the schedule.

**Hard rules**
- Paper keys only.
- The keys live **only on the Pi**. The research machine never has them.
- The Pi only *pulls* code; nothing pushes to it.

---

## 0. Before you start (phone or research machine, ~15 min)

1. **Private GitHub repo.** The repo has no remote yet.
   ```bash
   git remote add origin git@github.com:<you>/<private-repo>.git
   git push -u origin main
   git tag live-v1 && git push origin live-v1      # the first approved release
   ```
   A `live-v*` tag means "approved for the Pi". The Pi only ever runs tagged versions.
2. **Alpaca paper keys.**
   - In the Alpaca dashboard, switch to **Paper Trading**, then generate new API keys.
   - Close any open paper positions, or reset the paper account. Reconciliation assumes the account starts flat.
3. **Telegram alerts (optional but recommended).**
   - In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
   - Send your new bot any message.
   - Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}`.
4. **Watchdog (runs off the Pi).**
   - On healthchecks.io (free), create a check with schedule type **Cron** `45 16 * * 1-5`, timezone `America/New_York`, grace 2 hours.
   - Add your Telegram or email as the alert channel, and copy the ping URL.
   - If the Pi dies, loses power or loses network, the ping stops and healthchecks.io tells you.

## 1. Set up the Pi (~20 min)

1. Use **Raspberry Pi Imager** to install **Raspberry Pi OS Lite (64-bit)**. In its settings, set the hostname, your SSH public key and the network.
2. Boot, SSH in, then:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y git python3-venv sqlite3
   python3 --version            # needs 3.11 or newer
   timedatectl                  # "System clock synchronized: yes"
   ```
3. **Read-only access to the repo** (part of the one-way channel):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/repo_deploy -N ""
   cat ~/.ssh/repo_deploy.pub    # GitHub repo -> Settings -> Deploy keys -> add, leave "write access" OFF
   printf 'Host github.com\n  IdentityFile ~/.ssh/repo_deploy\n' >> ~/.ssh/config
   git clone git@github.com:<you>/<private-repo>.git ~/trading
   cd ~/trading && git checkout --detach live-v1
   ```

## 2. Secrets: the Pi's own `.env` (~2 min)

```bash
cd ~/trading
nano .env
```
```
ALPACA_API_KEY=<paper key id>
ALPACA_SECRET_KEY=<paper secret>
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<chat id>
HEALTHCHECK_URL=https://hc-ping.com/<uuid>
```
`.env` is gitignored, and the install script sets it to `chmod 600`.

## 3. Install and test (~10 min)

```bash
bash deploy/install_pi.sh
```
This creates `.venv`, installs `deploy/requirements-pi.txt`, downloads price history, runs the Pi test suite (failure cases, risk layer, parity, operations) and installs the systemd units. **The timers stay off.**

## 4. Check the broker connection, then a dry run

```bash
.venv/bin/python -m live.check_broker                       # read-only: equity, cash, positions
.venv/bin/python -m live.engine.daily --broker alpaca --dry-run
```
- Run the dry run **after the US close**, which is 8:00 am or later in Sydney during US daylight time, or 9:00 am in the northern winter.
- It prints the target weights and the orders it *would* send, and changes nothing.
- A real run started during US market hours is refused on purpose: orders would fill mid-day instead of at the open.

**What to trade:** `live/approved.json` lists the approved strategies and their share of the account. It starts as 100% `buy_hold_index`. Change it on the research machine, commit, then tag a new `live-v*` release; never edit it on the Pi.

## 5. Go live (paper)

```bash
bash deploy/install_pi.sh --enable
systemctl list-timers 'trading-*'
```
| Timer | When (New York time) | Does |
|---|---|---|
| `trading-daily` | Mon–Fri 16:45 | Reconcile yesterday's fills → run the engine → alert if anything's wrong → heartbeat |
| `trading-weekly` | Sat 10:00 | Weekly report to Telegram |
| `trading-update` | Sun 12:00 | Pull the newest `live-v*` tag, test it in a separate copy, switch only if all tests pass |

The engine skips market holidays by itself. If the Pi was off at 16:45, it catches up when it boots, unless the market is open at that point.

## 6. Clean up the old setup (do this the same day)

1. On the Windows laptop, open an **admin** PowerShell:
   `schtasks /Change /TN "Trading - Buy" /DISABLE` and `schtasks /Change /TN "Trading - Sell" /DISABLE`
2. Delete the laptop's old `.env` (in the project folder), then revoke those old keys in the Alpaca dashboard. After this, only the Pi holds keys.

## Day-to-day

| Need | Command (on the Pi, in `~/trading`) |
|---|---|
| Stop all trading now | `.venv/bin/python -m live.kill` |
| Start again | `.venv/bin/python -m live.kill --clear` |
| Resume after a drawdown pause (after reviewing) | `.venv/bin/python -m live.kill --resume` |
| Re-enable after a hard stop | `.venv/bin/python -m live.kill --reset-hard-stop --confirm` |
| Status | `.venv/bin/python -m live.kill --status` |
| Today's log | `journalctl -u trading-daily --since today` |
| Report now | `.venv/bin/python -m live.report` |
| Back up the ledger (also your tax record) | `sqlite3 live/state/ledger.db ".backup '/media/usb/ledger-$(date +%F).db'"` |

## The 4-week exit checklist (proposal, end of Stage E)

- [ ] 4 weeks of unattended runs: no missed heartbeats that weren't explained.
- [ ] No `reconcile_mismatch` events: the ledger matches the broker.
- [ ] The Pi's target weights match the backtest code for the same days. The code-level proof is `tests/test_live_parity.py`. For a spot check, compare `SELECT * FROM targets ORDER BY run_date DESC LIMIT 20;` in `live/state/ledger.db` with a backtest run on the research machine.
- [ ] Every alert was understood and, if needed, acted on.
