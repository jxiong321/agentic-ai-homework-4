"""Measure memory: python -m eval.run_part_d [--scripted] [--continue]."""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import yaml
from harness import ROOT
from harness.formats import parse_triage_comment
from harness.roles import tool_for, arg
from harness.tracker import Tracker
from state.store import Store
from eval.seed_memories import seed
from eval.check_triage import check
from eval.run_part_b import trace


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def run_one(env, scripted):
    command = [sys.executable, 'run.py', '--way', 'planned', '--issues', '4207', '--jobs', '1']
    if scripted:
        command += ['--backend', 'harness.scripted:ScriptedTriage']
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end='', flush=True)
    ids = re.findall(r'planned-4207-s\d+-[a-f0-9]+', result.stdout)
    if not ids:
        raise RuntimeError('No run ID; inspect output')
    lines = trace(ids[0])
    terminal = [line for line in lines if line['type'] == 'end']
    if result.returncode or not terminal or terminal[-1]['terminal_reason'] != 'completed':
        raise RuntimeError(f'{ids[0]} did not complete; inspect it before continuing')
    return ids[0]


def measure(run_id, store, answer, with_memory):
    lines = trace(run_id)
    tools = [line for line in lines if line['type'] == 'tool_call']
    search_at = next(i for i, line in enumerate(lines) if line['type'] == 'tool_call' and line['name'] == tool_for('search'))
    reads = [line for line in lines[:search_at] if line['type'] == 'store_read']
    assert reads and (bool(reads[0]['records']) if with_memory else not reads[0]['records']), 'Incorrect memory condition'
    episodes = [r for r in store.records() if r.get('run_id') == run_id]
    assert len(episodes) == 1, 'Expected one completed-run episode'
    comments = Tracker().comments(run_id, 4207)
    label, file = parse_triage_comment(comments[0]['body'])
    paths = [line['input'].get(arg('read_file', 'path')) for line in tools if line['name'] == tool_for('read_file') and not line['is_error']]
    retrieved_ids = reads[0]['records']
    recalled_files = [r.get('file') for r in store.records() if r['id'] in retrieved_ids]
    origin = 'read in this run' if file in paths else 'present in retrieved memory, not read this run' if file in recalled_files else 'not read and not identified in retrieved memory'
    return dict(run_id=run_id, passed=check(Tracker(), run_id, 4207, answer), tool_calls=len(tools),
                tokens=next(line['totals']['total_tokens'] for line in reversed(lines) if line['type']=='run_end'),
                label=label, file=file, file_evidence=origin, episodes_written=len(episodes))


def finish(results, store):
    path = ROOT / 'reports/LAB_04.json'
    report = json.loads(path.read_text())
    for group in ('with_store', 'empty_store'):
        rows = results[group]
        report['reopened'][group] = dict(runs=len(rows), passes=sum(r['passed'] for r in rows),
            mean_tool_calls=statistics.mean(r['tool_calls'] for r in rows),
            mean_tokens=statistics.mean(r['tokens'] for r in rows), run_ids=[r['run_id'] for r in rows])
    save(path, report)
    path = ROOT / 'reports/LAB_04.md'; text = path.read_text()
    start, end = text.index('## Part D'), text.index('## Part E')
    a, b = report['reopened']['with_store'], report['reopened']['empty_store']
    section = '''## Part D · A memory that can say where it came from

Policy: remember one completed-run decision as an episode after the comment succeeds. Confirmation records that the decision was posted, not that it is correct. Preserve each memory's source, observed/stored time, origin and confirmation. Use atomic supersession for changed rules; keep the old record inactive. Retrieved memories show source and age. The planner receives no store records. Details: `state/write_policy.md`.

| Candidate | Stored? | Kind | source | origin | confirmed | Invites |
|---|---|---|---|---|---|---|
| A | Yes | procedural | memory | derived | true | Staleness as scripts change |
| B | Yes | episodic | issue:4188 | ingested | false | Poisoning if promoted to a fact |
| C | Yes | procedural | user | ingested | true | Contradiction if a rule changes |

A's script names were checked against package.json; no server was launched to verify the port. B remains only a record of an outside account's claim. C preserves the maintainer's words and name; that attribution confirms who stated the instruction. Candidate timestamps are their supplied observation times. A and C apply repository-wide; B is scoped to issue 4188.

Retention: non-user memories expire from retrieval after 90 days. Rules remain until superseded. The database is capped at 1,000 records; oldest eligible non-user records are evicted, preserving candidate records and referenced supersession history. If all records are protected, insertion fails pending consolidation. These measured successful runs each wrote one episode. At an assumed 10 runs/day, that is 10 records/day: up to 90 days in retrieval and approximately (1,000 - 3) / 10 = 99.7 days of retained episodes before capacity eviction, with less room as protected history grows.

'''
    section += f"Seed run (excluded from measurements): `{results['seed_run_id']}`. Five runs in each group were made sequentially; each empty-store run used its own new database.\n\n"
    section += '| Issue 4207, five runs each | With store | Empty store |\n|---|---|---|\n'
    for title, key in [('Passes','passes'),('Mean tool calls','mean_tool_calls'),('Mean tokens','mean_tokens')]:
        section += f'| {title} | {a[key]} | {b[key]} |\n'
    section += '\n| Condition | Run | Label | File | File evidence |\n|---|---|---|---|---|\n'
    for group in ('with_store','empty_store'):
        for row in results[group]:
            section += f"| {group} | {row['run_id']} | {row['label']} | {row['file']} | {row['file_evidence']} |\n"
    section += f"\nObserved differences (with minus empty): {a['passes']-b['passes']} passes out of five, {a['mean_tool_calls']-b['mean_tool_calls']:.2f} mean tool calls, {a['mean_tokens']-b['mean_tokens']:.1f} mean tokens. These small samples show this experiment's outcome, not a general benefit of memory. A file appearing both in memory and in a current read does not establish which caused the model's decision.\n\n"
    section += 'Candidate IDs: ' + ', '.join(f"{r['candidate']}={r['id']}" for r in store.records() if r.get('candidate')) + '.\n\n'
    updated = text[:start] + section + text[end:]
    updated = updated.replace('Real-model Part D measurements are pending.', 'The real-model seed and ten comparison runs completed; results are in Part D.')
    path.write_text(updated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripted', action='store_true')
    parser.add_argument('--continue', dest='continuing', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'reports' / ('PART_D_SCRIPTED.json' if args.scripted else 'PART_D_MEASURED.json')
    if args.continuing != path.exists():
        parser.error('Use --continue for existing results; omit it for a fresh comparison')
    env = dict(os.environ, KEY_MODE='derived', FLAKY_WRITES='0', READBACK_FAIL='0', VERIFY='on', PYTHONDONTWRITEBYTECODE='1')
    env.pop('REPOMIND_EMPTY_STORE', None)
    env.pop('REPOMIND_STORE_PATH', None)
    store_path = ROOT / 'state' / ('scripted-memory.db' if args.scripted else 'store.db')
    if args.scripted:
        env['REPOMIND_STORE_PATH'] = str(store_path)
    store = Store(store_path)
    if not args.scripted:
        for record in store.records():
            if record.get('run_id'):
                assert not trace(record['run_id'])[0]['backend'].startswith('harness.scripted'), 'Default store contains scripted decisions'
    seed(store)
    results = json.loads(path.read_text()) if args.continuing else dict(seed_run_id=None, with_store=[], empty_store=[])
    if not args.scripted and sum(len(results[g]) for g in ('with_store','empty_store')) < 10:
        subprocess.run([sys.executable, '-m', 'harness.ping'], cwd=ROOT, env=env, check=True)
    save(path, results)
    if results['seed_run_id'] is None:
        run_id = run_one(env, args.scripted)
        assert any(r.get('run_id') == run_id for r in store.records()), 'Seed did not write a decision'
        results['seed_run_id'] = run_id
        save(path, results)
    # Ground truth is used only here, for evaluation after execution; never by the agent.
    answer = yaml.safe_load((ROOT / 'fixtures/answers.yaml').read_text())['eval'][4207]
    for group in ('with_store','empty_store'):
        while len(results[group]) < 5:
            run_env = dict(env)
            if group == 'empty_store':
                run_env['REPOMIND_EMPTY_STORE'] = '1'
            run_id = run_one(run_env, args.scripted)
            run_store = store if group == 'with_store' else Store(ROOT / 'state/empty_stores' / f'{run_id}.db')
            results[group].append(measure(run_id, run_store, answer, group=='with_store'))
            save(path, results)
            print(f'{group}: {len(results[group])}/5 recorded', flush=True)
    if not args.scripted:
        finish(results, store)
    print(f'Completed seed + ten runs. Evidence: {path}')


if __name__ == '__main__':
    main()
