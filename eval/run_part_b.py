"""Run Part B serially: python -m eval.run_part_b [--scripted].

The real matrix archives the tracker first. Scripted evidence stays separate
from LAB_04.json. Every crash is resumed before another run starts.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from harness import ROOT
from harness.formats import parse_triage_comment
from harness.tracker import Tracker
from state.checkpointer import Checkpointer


def trace(run_id):
    return [json.loads(line) for line in (ROOT / 'runs' / f'{run_id}.jsonl').read_text().splitlines()]


def execute(args, env, *, crash=False):
    result = subprocess.run([sys.executable, 'run.py', *args], cwd=ROOT,
                            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end='', flush=True)
    ids = re.findall(r'planned-4201-s\d+-[a-f0-9]+', result.stdout)
    if not ids:
        raise RuntimeError('No run ID returned; inspect the output above.')
    run_id = ids[0]
    lines = trace(run_id)
    if crash:
        if result.returncode not in (-9, 137) or any(line['type'] == 'run_end' for line in lines):
            raise RuntimeError(f'{run_id}: requested crash did not fire; investigate and rerun this case.')
    else:
        ends = [line for line in lines if line['type'] == 'run_end']
        terminal = [line for line in lines if line['type'] == 'end']
        if (result.returncode or not ends or ends[-1].get('error') is not None
                or not terminal or terminal[-1].get('terminal_reason') != 'completed'):
            raise RuntimeError(f'{run_id}: run did not complete successfully.')
    return run_id


def counts(cp, run_id):
    comments = Tracker().comments(run_id, 4201)
    prs = Tracker().prs(run_id, branch='repomind/issue-4201')
    findings = cp.last(run_id)['findings']
    expected = (findings['label'], findings['file'])
    matches = (len(comments) == 1
               and parse_triage_comment(comments[0]['body']) == expected
               and len(prs) == (0 if findings['file'] == 'none' else 1))
    return dict(comments=len(comments), open_prs=len(prs), matches=matches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripted', action='store_true')
    parser.add_argument('--continue', dest='continue_matrix', action='store_true',
                        help='Reuse the saved baseline and completed cases without resetting the tracker')
    args = parser.parse_args()
    destination = ROOT / 'reports' / ('PART_B_SCRIPTED.json' if args.scripted else 'PART_B_MEASURED.json')
    if args.continue_matrix and not destination.exists():
        parser.error('No saved matrix to continue')
    if destination.exists() and not args.continue_matrix:
        parser.error('A saved matrix already exists. Use --continue to preserve its results.')
    env = dict(os.environ, KEY_MODE='derived', FLAKY_WRITES='0', READBACK_FAIL='0', VERIFY='on',
               PYTHONDONTWRITEBYTECODE='1')
    base = ['--way', 'planned', '--issues', '4201', '--jobs', '1']
    if args.scripted:
        base += ['--backend', 'harness.scripted:ScriptedTriage']
    else:
        # Validate configuration/key before archiving anything or starting the matrix.
        subprocess.run([sys.executable, '-m', 'harness.ping'], cwd=ROOT, env=env, check=True)
        if not args.continue_matrix:
            subprocess.run([sys.executable, '-m', 'harness.tracker', 'reset'], cwd=ROOT, env=env, check=True)
    cp = Checkpointer()
    try:
        if args.continue_matrix:
            results = json.loads(destination.read_text())
            baseline = results['uncrashed_run_id']
            for row in results['matrix_derived']:
                assert counts(cp, row['run_id']) == {key: row[key] for key in ('comments', 'open_prs', 'matches')}, 'Saved tracker evidence changed'
        else:
            baseline = execute(base, env)
            results = dict(uncrashed_run_id=baseline, matrix_derived=[], plan_differences=[])
        baseline_lines = trace(baseline)
        steps = list(dict.fromkeys(line['plan_step'] for line in baseline_lines if line['type'] == 'tool_call'))
        baseline_plan = next(line['plan'] for line in baseline_lines if line['type'] == 'plan')
        destination.write_text(json.dumps(results, indent=2) + '\n')
        for step in range(1, len(steps) + 1):
            for when in ('after', 'during'):
                if any(row['step'] == step and row['when'] == when and row['matches'] for row in results['matrix_derived']):
                    print(f'SKIP {when} step {step}: saved passing result.', flush=True)
                    continue
                run_id = execute(base + [f'--die-{when}-step', str(step)], env, crash=True)
                before = cp.last(run_id)
                old = trace(run_id)
                execute(['--resume', run_id], env)
                lines = trace(run_id)
                resume_at = next(i for i, line in enumerate(lines) if line['type'] == 'resume')
                replayed = [line for line in lines[resume_at + 1:] if line['type'] == 'tool_call']
                if before:
                    done = {sid for sid, status in before['step_status'].items() if status == 'done'}
                    assert not any(str(call['plan_step']) in done for call in replayed), 'Repeated completed work'
                    for call in replayed:
                        saved_args = before['findings']['write_args'].get(str(call['plan_step']))
                        if saved_args is not None:
                            assert call['input'] == saved_args, 'Changed replay arguments'
                row = dict(run_id=run_id, step=step, when=when, **counts(cp, run_id))
                results['matrix_derived'].append(row)
                plan = next(line['plan'] for line in old if line['type'] == 'plan')
                if plan != baseline_plan:
                    results['plan_differences'].append(run_id)
                destination.write_text(json.dumps(results, indent=2) + '\n')
                assert row['matches'], f'Tracker result mismatch: {row}'
                print(f'PASS {when} step {step}: one comment, correct PR count, findings match.', flush=True)
        if not args.scripted:
            report_path = ROOT / 'reports' / 'LAB_04.json'
            report = json.loads(report_path.read_text())
            report.update({key: results[key] for key in ('uncrashed_run_id', 'matrix_derived')})
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            markdown_path = ROOT / 'reports' / 'LAB_04.md'
            markdown = markdown_path.read_text()
            start = markdown.index('**The matrix, derived keys.**')
            end = markdown.index('## Part C', start)
            section = f"**The matrix, derived keys.** Uncrashed run: `{baseline}`. Its executed plan had {len(steps)} steps; every position was tested after and during.\n\n"
            section += "| Step | When | run_id | Comments | Open PRs | Matches its findings |\n|---|---|---|---|---|---|\n"
            for row in results['matrix_derived']:
                section += f"| {row['step']} | {row['when']} | {row['run_id']} | {row['comments']} | {row['open_prs']} | {row['matches']} |\n"
            different = ', '.join(results['plan_differences']) or 'none'
            section += f"\nRuns whose initial plan differed from the baseline: {different}. Full plans remain in their traces.\n\n"
            section += "Counts were read from Tracker by run ID, before any Part C reset. Each final comment matched its own last checkpoint's label and file, with a PR exactly when the findings named a file. Recovery repeated no step marked done in the saved checkpoint, and retried saved writes with unchanged arguments.\n\n"
            markdown_path.write_text(markdown[:start] + section + markdown[end:])

        print(f'All {len(results["matrix_derived"])} cases passed. Evidence: {destination}')
    finally:
        cp.close()


if __name__ == '__main__':
    main()
