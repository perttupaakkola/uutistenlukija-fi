"""Small cutover authorization and offline crontab transformations."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone

PREFIX = '# news-mvp cutover: '
BUNDLE = Path('/home/pertt/.hermes/plans/lean-news-reboot-20260912')
STATE = Path('/home/pertt/.local/share/uutistenlukija/cutover')


def output(*command, cwd=None):
    return subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()


def approved_cutover(root, review):
    """A descendant may add step5 source, but every reviewed cutover blob stays exact."""
    ref = review.get('candidate_ref', '')
    if review.get('step') != 4 or review.get('verdict') != 'approved' or not re.fullmatch('[0-9a-f]{40}', ref):
        return False
    try:
        output('git', 'merge-base', '--is-ancestor', ref, 'HEAD', cwd=root)
        entries = output('git', 'ls-tree', '-r', ref, '--', 'cutover', cwd=root).splitlines()
        if not entries:
            return False
        for entry in entries:
            identity, name = entry.split('\t', 1)
            mode, kind, blob = identity.split()
            file = Path(root)/name
            if kind != 'blob' or mode not in ('100644','100755') or file.is_symlink():
                return False
            if output('git','ls-tree','HEAD','--',name,cwd=root) != entry:
                return False
            if file.read_bytes() != subprocess.check_output(['git','cat-file','blob',blob],cwd=root):
                return False
            if bool(file.stat().st_mode & 0o111) != (mode == '100755'):
                return False
        return True
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def released(control, review, root, now=None):
    now = now or datetime.now(timezone.utc)
    return (control['authorized_step'] == 5 and control['predecessor_review'] == 'reviews/04.json'
            and control['run_state'] == 'running' and not control['stop_requested']
            and now < datetime.fromisoformat(control['deadline_utc'])
            and approved_cutover(root, review))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def legacy_workflows(plan, expected_state):
    """Bind restored workflow enablement to the OLD executor, not a step5 replacement."""
    repo = plan['repository']
    workflows = json.loads(output('gh','api',f'repos/{repo}/actions/workflows'))['workflows']
    blobs = {}
    for identity in plan['disable_workflow_ids']:
        row = next(w for w in workflows if w['id'] == identity)
        if row['state'] != expected_state:
            raise ValueError('Workflow state drift')
        blobs[str(identity)] = output('gh','api',f"repos/{repo}/contents/{row['path']}?ref=main",'--jq','.sha')
    return blobs


def stopped_receipt(root, state, review):
    started = json.loads((state/'stop.started').read_text())
    if started['approved_candidate'] != review['candidate_ref'] or not approved_cutover(root, review):
        raise ValueError('Stop candidate changed')
    plan = json.loads((root/'cutover/routes.json').read_text())
    before, after = (state/'crontab.before').read_text(), (state/'crontab.stopped').read_text()
    if crontab_change(before, plan['crontab_lines']) != after:
        raise ValueError('Stop crontab evidence changed')
    return {'completed':True,'approved_candidate':review['candidate_ref'],
            'started_sha256':sha(state/'stop.started'),'before_sha256':sha(state/'crontab.before'),
            'stopped_sha256':sha(state/'crontab.stopped'),'legacy_workflow_blobs':started['legacy_workflow_blobs']}


def restorative(root, state, review):
    """Only the inverse of a completed stop; expiry/stop flags cannot bar restoration."""
    try:
        if (state/'repoint.started').exists() or not approved_cutover(root, review):
            return False
        receipt = json.loads((state/'stop.finished').read_text())
        if receipt != stopped_receipt(root, state, review):
            return False
        if json.loads((root/'config.json').read_text())['enabled'] is not False:
            return False
        for unit in ('uutistenlukija-mvp.service','uutistenlukija-mvp.timer'):
            props = dict(line.split('=',1) for line in output('systemctl','--user','show',unit,
                         '--property=LoadState,ActiveState,UnitFileState').splitlines())
            if props.get('LoadState') not in ('loaded','not-found') or props.get('ActiveState') not in ('inactive','failed'):
                return False
            if props.get('UnitFileState','') not in ('','disabled','static','masked','masked-runtime'):
                return False
        plan = json.loads((root/'cutover/routes.json').read_text())
        return legacy_workflows(plan, 'disabled_manually') == receipt['legacy_workflow_blobs']
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError):
        return False


def crontab_change(current, selected, rollback=False):
    lines = current.splitlines(keepends=True)
    for original in selected:
        before, after = original, PREFIX + original
        if rollback:
            before, after = after, before
        matches = [i for i, line in enumerate(lines) if line.rstrip('\n') == before]
        if len(matches) != 1:
            raise ValueError('Selected crontab line changed or missing; review drift')
        i = matches[0]
        lines[i] = after + ('\n' if lines[i].endswith('\n') else '')
    return ''.join(lines)


if __name__ == '__main__':
    import sys
    root = Path(__file__).resolve().parent.parent
    if sys.argv[1:] in (['gate'], ['rollback-gate'], ['record-start'], ['record-finish']):
        operation = sys.argv[1]
        review_path = BUNDLE/'reviews/04.json'
        review = json.loads(review_path.read_text()) if review_path.exists() else {}
        if operation == 'rollback-gate':
            if not restorative(root, STATE, review):
                raise SystemExit('Exact completed stop, reviewed rollback code and no new publisher required; no changes made')
        elif operation == 'record-finish':
            # Recording successful completion remains possible if the stop crossed expiry.
            (STATE/'stop.finished').write_text(json.dumps(stopped_receipt(root,STATE,review),indent=2)+'\n')
        else:
            if not released(json.loads((BUNDLE/'CONTROL.json').read_text()),review,root):
                raise SystemExit('Step 5 and unchanged Hermes-approved cutover files required; no changes made')
            if operation == 'record-start':
                plan = json.loads((root/'cutover/routes.json').read_text())
                record = {'approved_candidate':review['candidate_ref'],'legacy_workflow_blobs':legacy_workflows(plan,'active')}
                with (STATE/'stop.started').open('x') as file:
                    file.write(json.dumps(record,indent=2)+'\n')
    else:
        # File-to-file only. Installation is an explicit later script step.
        operation, source, destination = sys.argv[1:]
        if operation not in ('stop', 'rollback'):
            raise SystemExit('Expected stop or rollback')
        plan = json.loads((root/'cutover/routes.json').read_text())
        Path(destination).write_text(crontab_change(Path(source).read_text(),plan['crontab_lines'],operation == 'rollback'))
