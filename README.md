# Slack reminder bot (local run)

Quick setup to run this script on your local computer.

## 1) Prepare config

1. Copy `config.example.json` to `config.json`.
2. Add `SLACK_BOT_TOKEN` in `config.json` and update other values (`CHANNEL_ID`, hashtag, message, ignore users, optional run times).

`CHANNEL_ID` is optional. If set, script checks only that one channel. If empty or missing, script checks all channels where bot is a member.

`TEST_RECIPIENTS` is optional. If set (for example with one user ID), reminders are sent only to those users. Useful for testing.

## 2) Run once (safe test)

```cmd
run_local.bat
```

This runs with `--dry-run` first (no DM is sent).

## 3) Real run

After dry-run looks correct:

```cmd
python slack_remind.py
```

## 4) Optional: schedule mode (local clock)

```cmd
python slack_remind.py --daemon
```

Schedule times come from `RUN_TIMES` in `config.json` (example: `08:00`, `14:00`).

## 5) Raspberry Pi auto mode (recommended)

Start once, then it runs automatically by `RUN_TIMES` from `config.json`:

```bash
docker compose up -d --build
```

Useful commands:

```bash
docker compose logs -f slack-reminder
docker compose restart slack-reminder
docker compose down
```

`restart: unless-stopped` is enabled, so service comes back after Raspberry Pi reboot.

## 6) Alternative: Raspberry Pi + Docker Compose + cron

Build image once:

```bash
docker compose build
```

Test run:

```bash
docker compose run --rm slack-reminder
```

Add cron entries on Raspberry Pi (`crontab -e`) to run at 09:00 and 14:00 every day:

```cron
0 9 * * * cd /home/pi/slackbot_svarigazina && /usr/bin/docker compose run --rm slack-reminder >> /home/pi/slackbot_svarigazina/cron.log 2>&1
0 14 * * * cd /home/pi/slackbot_svarigazina && /usr/bin/docker compose run --rm slack-reminder >> /home/pi/slackbot_svarigazina/cron.log 2>&1
```

Replace `/home/pi/slackbot_svarigazina` with your real project path.
