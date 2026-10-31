"""Sessions 2 and 3 of Part E; session 1 was Part D's candidate ingestion.
Run each action in a separate process: --replace, then --retrieve.
"""
import argparse
import json
from datetime import datetime, timezone
from harness import ROOT
from state.store import Store

NEW_RULE = 'For duplicates: label them duplicate and link the original; close duplicates after 14 days.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--replace', action='store_true')
    group.add_argument('--retrieve', action='store_true')
    args = parser.parse_args()
    store = Store()
    path = ROOT / 'reports/CONTRADICTION_TEST.json'
    if args.replace:
        original = next(r for r in store.records() if r.get('candidate') == 'C')
        existing = [r for r in store.records() if r['supersedes'] == original['id'] and r['text'] == NEW_RULE]
        if existing:
            replacement = existing[0]['id']
        else:
            replacement = store.supersede(original['id'], dict(repository=original['repository'], issue=original['issue'],
                kind=original['kind'], text=NEW_RULE, source='user', origin='ingested', confirmed=True,
                written_at=datetime.now(timezone.utc).isoformat(), stated_by=original['stated_by']))
        data = dict(original_id=original['id'], replacement_id=replacement,
                    original_text=original['text'], replacement_text=NEW_RULE,
                    session_one='Part D: python -m eval.seed_memories',
                    session_two='python -m eval.contradiction_test --replace')
        if path.exists():
            old=json.loads(path.read_text())
            if old.get('replacement_id')==replacement: data.update(old)
        path.write_text(json.dumps(data,indent=2)+'\n')
        print(json.dumps(data))
    else:
        data=json.loads(path.read_text())
        # Retrieve only the maintainer's duplicates rule, not unrelated memories.
        rules=[r for r in store.active('ledgerline') if r['source']=='user' and 'duplicates' in r['text'].lower()]
        assert len(rules)==1 and rules[0]['id']==data['replacement_id']
        assert rules[0]['supersedes']==data['original_id']
        assert not next(r for r in store.records() if r['id']==data['original_id'])['active']
        data.update(retrieved_ids=[r['id'] for r in rules], session_three='python -m eval.contradiction_test --retrieve')
        path.write_text(json.dumps(data,indent=2)+'\n')
        report_path=ROOT/'reports/LAB_04.json'; report=json.loads(report_path.read_text())
        report['contradiction_test']=data['retrieved_ids']
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(data))


if __name__=='__main__': main()
