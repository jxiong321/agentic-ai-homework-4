"""Part C: python -m eval.run_part_c [--scripted] [--continue]."""
import argparse
import json
import os
import subprocess
import sys

from harness import ROOT
from harness.formats import parse_triage_comment
from harness.tracker import Tracker
from state.checkpointer import Checkpointer
from eval.run_part_b import counts, execute, trace


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def write_report(results):
    path = ROOT / 'reports' / 'LAB_04.json'
    report = json.loads(path.read_text())
    report['matrix_uuid'] = results['matrix_uuid']
    report['duplicate_comment_ids'] = results['duplicate_comment_ids']
    save(path, report)
    path = ROOT / 'reports' / 'LAB_04.md'
    text = path.read_text()
    start, end = text.index('## Part C'), text.index('## Part D')
    section = '## Part C · Break it on purpose\n\n'
    section += 'The tracker was archived before this matrix; Part B evidence remains in its archive. These runs use `KEY_MODE=uuid`, with the same checkpoint placement and resume logic as Part B.\n\n'
    section += '| Step | When | run_id | Comments | Comment IDs | Open PRs |\n|---|---|---|---|---|---|\n'
    for row in results['matrix_uuid']:
        ids = ', '.join(str(i) for i in results['comment_ids'][row['run_id']])
        section += f"| {row['step']} | {row['when']} | {row['run_id']} | {row['comments']} | {ids} | {row['open_prs']} |\n"
    section += '\nWhat the checkpoint did, and what the key did: checkpoints preserved completed work and the exact write arguments, limiting replay to the uncertain write. They could not record a result that had not returned before the crash. A new random key on replay makes an already-posted comment look like a new write, so it is posted again. The PR still has its branch-based existence check, which prevents a second open PR even when the key changes. Part B’s stable keys prevented duplicate comments; checkpoint placement alone did not.\n\n'
    duplicates = '; '.join(f"{run_id}: {ids}" for run_id, ids in results['duplicate_comment_ids'].items())
    section += f'Duplicate comment IDs, read from the tracker by run ID: {duplicates}.\n\n'
    section += 'A duplicate case has `matches: false` because the required final result is exactly one comment, even when both comments contain the saved findings.\n\n'
    differences = ', '.join(results['plan_differences']) or 'none'
    section += f'Initial plans differing from Part B’s baseline: {differences}. The matrix covers the executed step positions of that baseline; each run’s full plan is retained in its trace.\n\n'
    path.write_text(text[:start] + section + text[end:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripted', action='store_true')
    parser.add_argument('--continue', dest='continuing', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'reports' / ('PART_C_SCRIPTED.json' if args.scripted else 'PART_C_MEASURED.json')
    if args.continuing != path.exists():
        parser.error('Use --continue when saved Part C results exist; omit it for a new matrix.')
    part_b = json.loads((ROOT / 'reports' / ('PART_B_SCRIPTED.json' if args.scripted else 'PART_B_MEASURED.json')).read_text())
    baseline = trace(part_b['uncrashed_run_id'])
    steps = len({line['plan_step'] for line in baseline if line['type'] == 'tool_call'})
    baseline_plan = next(line['plan'] for line in baseline if line['type'] == 'plan')
    assert len(part_b['matrix_derived']) == steps * 2 and all(r['matches'] for r in part_b['matrix_derived']), 'Complete Part B first'
    env = dict(os.environ, KEY_MODE='uuid', VERIFY='on', FLAKY_WRITES='0', READBACK_FAIL='0', PYTHONDONTWRITEBYTECODE='1')
    base = ['--way', 'planned', '--issues', '4201', '--jobs', '1']
    if args.scripted:
        base += ['--backend', 'harness.scripted:ScriptedTriage']
    cp = Checkpointer()
    try:
        results = json.loads(path.read_text()) if args.continuing else dict(matrix_uuid=[], duplicate_comment_ids={}, comment_ids={}, plan_differences=[])
        if args.continuing:
            for row in results['matrix_uuid']:
                assert counts(cp, row['run_id']) == {key: row[key] for key in ('comments', 'open_prs', 'matches')}, 'Tracker evidence changed; do not reset during a matrix'
        if len(results['matrix_uuid']) < steps * 2 and not args.scripted:
            subprocess.run([sys.executable, '-m', 'harness.ping'], cwd=ROOT, env=env, check=True)
            if not args.continuing:
                for row in part_b['matrix_derived']:
                    assert counts(cp, row['run_id'])['matches'], 'Part B tracker evidence missing before archive'
                subprocess.run([sys.executable, '-m', 'harness.tracker', 'reset'], cwd=ROOT, env=env, check=True)
        save(path, results)
        for step in range(1, steps + 1):
            for when in ('after', 'during'):
                if any(r['step'] == step and r['when'] == when for r in results['matrix_uuid']):
                    print(f'SKIP {when} step {step}: already measured.', flush=True)
                    continue
                pending = results.get('pending')
                if pending:
                    assert (pending['step'], pending['when']) == (step, when)
                    run_id, before = pending['run_id'], pending['checkpoint']
                else:
                    run_id = execute(base + [f'--die-{when}-step', str(step)], env, crash=True)
                    before = cp.last(run_id)
                    results['pending'] = dict(run_id=run_id, step=step, when=when, checkpoint=before)
                    save(path, results)
                if not any(line['type'] == 'run_end' for line in trace(run_id)):
                    execute(['--resume', run_id], env)
                lines = trace(run_id)
                assert lines[0]['switches']['key_mode'] == 'uuid'
                terminal = [line for line in lines if line['type'] == 'end']
                assert terminal[-1]['terminal_reason'] == 'completed', 'Resume did not complete'
                resume_at = next(i for i, line in enumerate(lines) if line['type'] == 'resume')
                if before:
                    for call in (line for line in lines[resume_at+1:] if line['type'] == 'tool_call'):
                        assert before['step_status'].get(str(call['plan_step'])) != 'done', 'Repeated completed work'
                        saved_args = before['findings']['write_args'].get(str(call['plan_step']))
                        if saved_args is not None:
                            assert call['input'] == saved_args, 'Replay changed arguments'
                row = dict(run_id=run_id, step=step, when=when, **counts(cp, run_id))
                comments = Tracker().comments(run_id, 4201)
                findings = cp.last(run_id)['findings']
                assert comments and all(parse_triage_comment(c['body']) == (findings['label'], findings['file']) for c in comments)
                assert row['open_prs'] == (0 if findings['file'] == 'none' else 1)
                ids = [c['id'] for c in comments]
                results['comment_ids'][run_id] = ids
                if len(ids) > 1:
                    results['duplicate_comment_ids'][run_id] = ids
                results['matrix_uuid'].append(row)
                if next(line['plan'] for line in lines if line['type'] == 'plan') != baseline_plan:
                    results['plan_differences'].append(run_id)
                del results['pending']
                save(path, results)
                print(f"RECORDED {when} step {step}: {len(ids)} comment(s), {row['open_prs']} PR(s).", flush=True)
        assert results['duplicate_comment_ids'], 'No duplicate observed; inspect cases before completing Part C'
        if not args.scripted:
            write_report(results)
        print(f'Part C: {len(results["matrix_uuid"])} cases measured; {len(results["duplicate_comment_ids"])} runs with duplicate comments. Evidence: {path}')
    finally:
        cp.close()


if __name__ == '__main__':
    main()
