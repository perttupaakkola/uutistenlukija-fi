## Bridge Sync Protected Files (.bridge-sync-exclude)

When doing rsync from workspace-alex to main project, ALWAYS use --exclude-from=.bridge-sync-exclude:

    rsync -av --exclude-from=.bridge-sync-exclude /home/pertt/.openclaw/workspace-alex/... /home/pertt/.openclaw/workspace/projects/uutistenlukija/

Protected files (never overwrite from Alex's sandbox):
- pipeline/auto_publish.sh  (contains --max-articles, has been reverted 4 times)
- pipeline/scanner.py       (feed list differs between sandbox and host)
- pipeline/firehose_cron.sh
