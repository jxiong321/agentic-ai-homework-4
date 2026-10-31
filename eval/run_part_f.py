"""Seven Part F conditions: python -m eval.run_part_f [--scripted] [--continue].

Real-model outcomes are measured, never forced. A model may retain a buried
fact or a summary may preserve it; such a result is reported as unproven.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from harness import ROOT
from harness.formats import parse_triage_comment, request_text, squeeze
from harness.roles import tool_for, arg
from harness.tracker import Tracker
from state.store import Store
from ways.planned import F_FACT
from eval.run_part_b import trace

MODES = ['attention_lost', 'attention_fixed', 'compaction_lost', 'compaction_fixed',
         'session_stated', 'session_lost', 'session_fixed']


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def inspect(run_id, mode, store):
    lines = trace(run_id)
    requests = [json.loads(line) for line in (ROOT / 'runs' / f'{run_id}.requests.jsonl').read_text().splitlines()]
    sent = {row['n']: squeeze(request_text(row)) for row in requests}
    fact = squeeze(F_FACT)
    comments = Tracker().comments(run_id, 4192)
    assert len(comments)==1, 'Expected exactly one comment'
    posted = parse_triage_comment(comments[0]['body'])
    post_at = next(i for i, line in enumerate(lines) if line['type']=='tool_call' and line['name']==tool_for('comment'))
    drafts = [(i, line) for i, line in enumerate(lines[:post_at]) if line['type']=='model_call'
              and any(call['name']==tool_for('comment') and parse_triage_comment(call['input'].get(arg('comment','body'),''))==posted
                      for call in line.get('tool_calls', []))]
    assert drafts, 'Cannot identify the posted comment drafting call'
    draft_at, draft = drafts[-1]
    text = sent[draft['request']]
    position = text.find(fact)
    depth = min(position, len(text)-position-len(fact)) if position>=0 else None
    compactions = [i+1 for i, line in enumerate(lines[:draft_at]) if line['type']=='compaction']
    earlier = [(i+1, line['request']) for i, line in enumerate(lines) if line['type']=='model_call'
               and line.get('request') in sent and fact in sent[line['request']]]
    search_at = next(i for i, line in enumerate(lines) if line['type']=='tool_call' and line['name']==tool_for('search'))
    reads = [(i+1,line['records']) for i,line in enumerate(lines[:search_at]) if line['type']=='store_read']
    retrieved = {rid for _, ids in reads for rid in ids}
    rule_ids = [r['id'] for r in store.records() if r['id'] in retrieved and r['active'] and F_FACT in r['text'] and r['source']=='user']
    return dict(run_id=run_id, mode=mode, label=posted[0], file=posted[1], uses_fact=posted[0]=='feature',
                drafting_trace_line=draft_at+1, drafting_request_line=draft['request'],
                fact_in_draft=position>=0, fact_position=position, request_characters=len(text), edge_distance=depth,
                compaction_trace_lines=compactions, fact_sent_calls=earlier,
                store_read_trace_lines=[n for n,_ in reads], retrieved_rule_ids=rule_ids)


def evaluate(results):
    rows = results['conditions']
    a,b = rows['attention_lost'],rows['attention_fixed']
    checks = dict(attention=bool(a['fact_in_draft'] and not a['uses_fact'] and b['fact_in_draft'] and b['uses_fact']
                                and b['edge_distance'] < a['edge_distance']))
    a,b = rows['compaction_lost'], rows['compaction_fixed']
    checks['compaction'] = bool(a['compaction_trace_lines'] and b['compaction_trace_lines']
        and any(n<a['compaction_trace_lines'][0] for n,_ in a['fact_sent_calls'])
        and any(n<b['compaction_trace_lines'][0] for n,_ in b['fact_sent_calls'])
        and not a['fact_in_draft'] and not a['uses_fact'] and b['fact_in_draft'] and b['uses_fact'])
    a,b,c=rows['session_lost'],rows['session_fixed'],rows['session_stated']
    checks['session'] = bool(c['fact_sent_calls'] and not a['fact_sent_calls'] and not a['uses_fact']
                             and b['fact_in_draft'] and b['uses_fact'] and b['retrieved_rule_ids'])
    return checks


def report(results):
    rows = results['conditions']
    path=ROOT/'reports/LAB_04.json'; data=json.loads(path.read_text())
    for case in ('attention','compaction','session'):
        data['forgetting'][case]=dict(fact=F_FACT,effect={'label':'feature'},lost=rows[case+'_lost']['run_id'],fixed=rows[case+'_fixed']['run_id'])
    data['forgetting']['session']['stated']=rows['session_stated']['run_id']
    save(path,data)
    path=ROOT/'reports/LAB_04.md'; text=path.read_text()
    start,end=text.index('## Part F'),text.index('## AI assistance')
    section='## Part F · Find the boundary that lost it\n\n'
    section+=f'Experimental rule attributed to maintainer priya-s: "{F_FACT}" Its only requested effect is `label: feature`; it does not specify a file.\n\n'
    section+='Attention and compaction used separate empty stores. Both attention conditions used the same repository-text corpus, moving the rule from its middle to the end of the request. Compaction summarized tool history at 300 estimated tokens, preserving the issue outside it; the fixed condition also kept the rule in a separate note. The session fixed run received no directly injected rule: it retrieved the attributed rule saved by the stated run.\n\n'
    section+='| Condition | Run | Posted label | Draft trace line | Request line | Fact sent to draft? | Compaction trace lines |\n|---|---|---|---|---|---|---|\n'
    for mode in MODES:
        row=rows[mode]
        section+=f"| {mode} | {row['run_id']} | {row['label']} | {row['drafting_trace_line']} | {row['drafting_request_line']} | {row['fact_in_draft']} | {row['compaction_trace_lines']} |\n"
    section+='\nTrace lines refer to `runs/<run_id>.jsonl`; request lines refer to `runs/<run_id>.requests.jsonl`.\n\n'
    for mode in MODES:
        row=rows[mode]
        section+=f"- {mode}: calls sent the fact (trace line, request line): {row['fact_sent_calls']}. Draft fact position: {row['fact_position']}, normalized request length: {row['request_characters']}, distance from nearest end: {row['edge_distance']}. Store-read trace lines: {row['store_read_trace_lines']}; retrieved maintainer-rule IDs: {row['retrieved_rule_ids']}.\n"
    if results.get('attempts'):
        section += "\nEarlier attempts retained:\n"
        for prior in results['attempts']:
            section += f"- {prior['mode']} run {prior['run_id']}: posted {prior['label']}; fact in drafting request={prior['fact_in_draft']}; trace line {prior['drafting_trace_line']}, request line {prior['drafting_request_line']}.\n"
        section += "The session retry separates retrieved maintainer rules from episodes and explicitly permits their scoped labeling policy to override default label categories. The rule itself still comes only from the store.\n"
    section+='\nObserved boundary checks: '+json.dumps(results['checks'])+'. A false check means this pair did not demonstrate the requested failure and fix; do not claim otherwise.\n\n'
    section+='Fixes: attention needs a shorter context or prominent placement; compaction needs a structured note outside summarized history; the session boundary needs a store. The restart boundary uses the checkpoints tested in Part B. A retrieved triage episode is not the stated rule: the IDs above identify the actual user-sourced rule.\n\n'
    path.write_text(text[:start]+section+text[end:])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripted',action='store_true')
    parser.add_argument('--continue',dest='continuing',action='store_true')
    parser.add_argument('--retry',choices=MODES,help='Rerun one condition; retain the old observation in attempts')
    args=parser.parse_args()
    path=ROOT/'reports'/('PART_F_SCRIPTED.json' if args.scripted else 'PART_F_MEASURED.json')
    if path.exists() != bool(args.continuing or args.retry):
        parser.error('Use --continue for saved results, or --retry CONDITION to rerun one; omit for first run')
    results=json.loads(path.read_text()) if path.exists() else dict(conditions={},attempts=[])
    if args.retry:
        previous=results['conditions'].pop(args.retry,None)
        if previous: results['attempts'].append(previous)
    env=dict(os.environ,KEY_MODE='derived',FLAKY_WRITES='0',READBACK_FAIL='0',VERIFY='on',PYTHONDONTWRITEBYTECODE='1')
    env.pop('REPOMIND_EMPTY_STORE',None); env.pop('REPOMIND_STORE_PATH',None); env.pop('REPOMIND_F_MODE',None)
    store_path=ROOT/'state'/('scripted-f-memory.db' if args.scripted else 'store.db')
    if args.scripted: env['REPOMIND_STORE_PATH']=str(store_path)
    if not args.scripted and len(results['conditions'])<7:
        subprocess.run([sys.executable,'-m','harness.ping'],cwd=ROOT,env=env,check=True)
    save(path,results)
    for mode in MODES:
        if mode in results['conditions']: continue
        run_env=dict(env,REPOMIND_F_MODE=mode)
        empty=mode.startswith(('attention_','compaction_')) or mode=='session_lost'
        if empty: run_env['REPOMIND_EMPTY_STORE']='1'
        command=[sys.executable,'run.py','--way','planned','--issues','4192','--jobs','1']
        if args.scripted: command+=['--backend','harness.scripted:ScriptedTriage']
        result=subprocess.run(command,cwd=ROOT,env=run_env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        print(result.stdout,end='',flush=True)
        ids=re.findall(r'planned-4192-s\d+-[a-f0-9]+',result.stdout)
        if result.returncode or not ids: raise RuntimeError(f'{mode} failed; inspect output and use --continue')
        run_id=ids[0]
        terminal=[line for line in trace(run_id) if line['type']=='end']
        if not terminal or terminal[-1]['terminal_reason']!='completed': raise RuntimeError(f'{mode} did not complete')
        store=Store(ROOT/'state/empty_stores'/f'{run_id}.db') if empty else Store(store_path)
        row=inspect(run_id,mode,store)
        results['conditions'][mode]=row
        save(path,results)
        print(f"{mode}: label={row['label']}; fact in drafting request={row['fact_in_draft']}",flush=True)
    results['checks']=evaluate(results)
    save(path,results)
    if not args.scripted: report(results)
    print('Observed boundary checks:',results['checks'])
    if args.scripted:
        print('Scripted responses do not follow the rule: this tests wiring only, not successful behavioral fixes.')
    elif not all(results['checks'].values()):
        print('Some pairs did not demonstrate forgetting/recovery. Keep this evidence and inspect it before adjusting the experiment.')
    else:
        print('All three real-model failure/fix pairs demonstrated. Reports updated.')


if __name__=='__main__':
    main()
