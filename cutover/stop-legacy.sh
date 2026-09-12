#!/usr/bin/env bash
set -euo pipefail
cd /home/pertt/work/uutistenlukija
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py gate

mkdir -p /home/pertt/.local/share/uutistenlukija/cutover
test ! -e /home/pertt/.local/share/uutistenlukija/cutover/stop.started
crontab -l > /home/pertt/.local/share/uutistenlukija/cutover/crontab.before
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py stop /home/pertt/.local/share/uutistenlukija/cutover/crontab.before /home/pertt/.local/share/uutistenlukija/cutover/crontab.stopped
# Reject a known prior partial installation before touching any route.
for unit in openclaw-contract-mirrors.service openclaw-linear-ope-watchdog.service uutistenlukija-image-pipeline-codex-goal.service uutistenlukija-staged-pipeline-recovery.service; do
  test ! -e "/home/pertt/.config/systemd/user/$unit.d/90-news-mvp-cutover.conf"
done
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py record-start
gh workflow disable 318792330 --repo perttupaakkola/uutistenlukija-fi
gh workflow disable 246481423 --repo perttupaakkola/uutistenlukija-fi
gh workflow disable 318792331 --repo perttupaakkola/uutistenlukija-fi
gh workflow disable 318982239 --repo perttupaakkola/uutistenlukija-fi
crontab /home/pertt/.local/share/uutistenlukija/cutover/crontab.stopped
/home/pertt/.openclaw/bin/openclaw cron disable f240bc1c-6ebc-4d02-9a93-67e16cc2e58b
/home/pertt/.openclaw/bin/openclaw cron disable 0e2e5a04-7009-4ff2-9746-10c332afe091
/home/pertt/.openclaw/bin/openclaw cron disable 18a7af38-fdb7-4381-a699-9b925f0183a2
/home/pertt/.openclaw/bin/openclaw cron disable 02cb6258-5790-4fca-9c82-192e1b1a1db6
/home/pertt/.openclaw/bin/openclaw cron disable aabc5ef4-9baf-4c17-b16e-09b471079af8
/home/pertt/.openclaw/bin/openclaw cron disable efc6551f-9b24-49b2-83f1-b25a92366b7b
/home/pertt/.openclaw/bin/openclaw cron disable c3d3c7fe-eb94-4d86-ab99-78cdd3d76e99
/home/pertt/.openclaw/bin/openclaw cron disable f730687e-9f22-41f0-bc98-c0b9eaf82880
/home/pertt/.openclaw/bin/openclaw cron disable 68ffa188-19c5-4c70-886c-1cf2ea006d2c
/home/pertt/.openclaw/bin/openclaw cron disable 87744da0-9e41-490b-bb18-9af15ca69ef0
/home/pertt/.openclaw/bin/openclaw cron disable af0f0e47-8d26-472c-88ee-a99f4244c0f0
/home/pertt/.openclaw/bin/openclaw cron disable 8f6e2aeb-565c-4aca-8e0d-5fa113e64130
test ! -e /home/pertt/.config/systemd/user/openclaw-contract-mirrors.service.d/90-news-mvp-cutover.conf
mkdir -p /home/pertt/.config/systemd/user/openclaw-contract-mirrors.service.d
printf '[Unit]\nConditionPathExists=!/home/pertt/.local/share/uutistenlukija/legacy-news.disabled\n' > /home/pertt/.config/systemd/user/openclaw-contract-mirrors.service.d/90-news-mvp-cutover.conf
test ! -e /home/pertt/.config/systemd/user/openclaw-linear-ope-watchdog.service.d/90-news-mvp-cutover.conf
mkdir -p /home/pertt/.config/systemd/user/openclaw-linear-ope-watchdog.service.d
printf '[Unit]\nConditionPathExists=!/home/pertt/.local/share/uutistenlukija/legacy-news.disabled\n' > /home/pertt/.config/systemd/user/openclaw-linear-ope-watchdog.service.d/90-news-mvp-cutover.conf
test ! -e /home/pertt/.config/systemd/user/uutistenlukija-image-pipeline-codex-goal.service.d/90-news-mvp-cutover.conf
mkdir -p /home/pertt/.config/systemd/user/uutistenlukija-image-pipeline-codex-goal.service.d
printf '[Unit]\nConditionPathExists=!/home/pertt/.local/share/uutistenlukija/legacy-news.disabled\n' > /home/pertt/.config/systemd/user/uutistenlukija-image-pipeline-codex-goal.service.d/90-news-mvp-cutover.conf
test ! -e /home/pertt/.config/systemd/user/uutistenlukija-staged-pipeline-recovery.service.d/90-news-mvp-cutover.conf
mkdir -p /home/pertt/.config/systemd/user/uutistenlukija-staged-pipeline-recovery.service.d
printf '[Unit]\nConditionPathExists=!/home/pertt/.local/share/uutistenlukija/legacy-news.disabled\n' > /home/pertt/.config/systemd/user/uutistenlukija-staged-pipeline-recovery.service.d/90-news-mvp-cutover.conf
touch /home/pertt/.local/share/uutistenlukija/legacy-news.disabled
systemctl --user daemon-reload
systemctl --user disable --now openclaw-contract-mirrors.timer
systemctl --user disable --now openclaw-linear-ope-watchdog.timer
systemctl --user disable --now uutistenlukija-staged-pipeline-recovery.timer
systemctl --user stop openclaw-contract-mirrors.service openclaw-linear-ope-watchdog.service uutistenlukija-image-pipeline-codex-goal.service uutistenlukija-staged-pipeline-recovery.service
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py record-finish
echo 'News schedules stopped. Drain existing news processes and Actions runs before repointing. No deployment performed.'
