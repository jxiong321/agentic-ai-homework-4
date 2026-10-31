"""Classify and ingest the three supplied candidates under our write policy."""
import json
from pathlib import Path
import yaml
from harness import ROOT
from state.store import Store


def seed(store=None):
    store = store or Store()
    existing = {r.get('candidate'): r['id'] for r in store.records() if r.get('candidate')}
    scripts = json.loads((ROOT / 'fixtures/repo/package.json').read_text())['scripts']
    assert all(name in scripts for name in ('build', 'start', 'test', 'lint')) and 'serve' not in scripts
    specs = {'A': ('procedural', 'memory', 'derived', True),
             'B': ('episodic', 'issue:4188', 'ingested', False),
             'C': ('procedural', 'user', 'ingested', True)}
    for path in sorted((ROOT / 'fixtures/memory').glob('*.yaml')):
        candidate = yaml.safe_load(path.read_text())
        letter = candidate['candidate']
        if letter in existing:
            continue
        kind, source, origin, confirmed = specs[letter]
        row = dict(repository=candidate['repository'], issue=candidate['issue'] if letter == 'B' else None,
                   kind=kind, text=candidate['seen'], source=source, written_at=candidate['when'],
                   origin=origin, confirmed=confirmed, candidate=letter,
                   stated_by=candidate['who'], observed_at=candidate['where'])
        existing[letter] = store.write(row)
    return existing


if __name__ == '__main__':
    print(json.dumps(seed(), indent=2))
