#!/usr/bin/env bash
set -euo pipefail
cd /home/pertt/work/uutistenlukija
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py rollback-gate

test -e /home/pertt/.local/share/uutistenlukija/cutover/stop.finished
test ! -e /home/pertt/.local/share/uutistenlukija/cutover/repoint.started
crontab -l > /home/pertt/.local/share/uutistenlukija/cutover/crontab.rollback-input
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py rollback /home/pertt/.local/share/uutistenlukija/cutover/crontab.rollback-input /home/pertt/.local/share/uutistenlukija/cutover/crontab.restored
crontab /home/pertt/.local/share/uutistenlukija/cutover/crontab.restored
rm -- /home/pertt/.config/systemd/user/openclaw-contract-mirrors.service.d/90-news-mvp-cutover.conf
rm -- /home/pertt/.config/systemd/user/openclaw-linear-ope-watchdog.service.d/90-news-mvp-cutover.conf
rm -- /home/pertt/.config/systemd/user/uutistenlukija-image-pipeline-codex-goal.service.d/90-news-mvp-cutover.conf
rm -- /home/pertt/.config/systemd/user/uutistenlukija-staged-pipeline-recovery.service.d/90-news-mvp-cutover.conf
systemctl --user daemon-reload
systemctl --user enable --now openclaw-contract-mirrors.timer
systemctl --user enable --now openclaw-linear-ope-watchdog.timer
systemctl --user enable --now uutistenlukija-staged-pipeline-recovery.timer
/home/pertt/.openclaw/bin/openclaw cron enable f240bc1c-6ebc-4d02-9a93-67e16cc2e58b
/home/pertt/.openclaw/bin/openclaw cron enable 0e2e5a04-7009-4ff2-9746-10c332afe091
/home/pertt/.openclaw/bin/openclaw cron enable 18a7af38-fdb7-4381-a699-9b925f0183a2
/home/pertt/.openclaw/bin/openclaw cron enable 02cb6258-5790-4fca-9c82-192e1b1a1db6
/home/pertt/.openclaw/bin/openclaw cron enable aabc5ef4-9baf-4c17-b16e-09b471079af8
/home/pertt/.openclaw/bin/openclaw cron enable efc6551f-9b24-49b2-83f1-b25a92366b7b
/home/pertt/.openclaw/bin/openclaw cron enable c3d3c7fe-eb94-4d86-ab99-78cdd3d76e99
/home/pertt/.openclaw/bin/openclaw cron enable f730687e-9f22-41f0-bc98-c0b9eaf82880
/home/pertt/.openclaw/bin/openclaw cron enable 68ffa188-19c5-4c70-886c-1cf2ea006d2c
/home/pertt/.openclaw/bin/openclaw cron enable 87744da0-9e41-490b-bb18-9af15ca69ef0
/home/pertt/.openclaw/bin/openclaw cron enable af0f0e47-8d26-472c-88ee-a99f4244c0f0
/home/pertt/.openclaw/bin/openclaw cron enable 8f6e2aeb-565c-4aca-8e0d-5fa113e64130
gh workflow enable 318792330 --repo perttupaakkola/uutistenlukija-fi
gh workflow enable 246481423 --repo perttupaakkola/uutistenlukija-fi
gh workflow enable 318792331 --repo perttupaakkola/uutistenlukija-fi
gh workflow enable 318982239 --repo perttupaakkola/uutistenlukija-fi
echo 'Restored only previously enabled news schedules. No content or personal state restored/deleted.'
