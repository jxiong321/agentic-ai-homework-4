# RepoMind memory write policy

## When
Write a triage episode only after a run finishes its plan and its comment succeeds. Do not store guesses during investigation or decisions from escalated runs. Ingest the supplied candidates only after classifying their provenance. Verify the procedure's build/start scripts against package.json before storing it.

## What
Keep one episodic record per completed run: the label and file it actually posted, its run ID, and the paths it read. `confirmed: true` confirms that this decision was posted, not that the diagnosis is correct. Earlier triage decisions are leads to check against the current issue and code, especially when an issue was reopened.

Candidate A is procedural, derived, source memory, confirmed after checking package.json; its commands can become stale. This check verifies the named scripts, not execution of a server or the port. Candidate B is episodic, ingested, source issue:4188, confirmed false: an outside account's claim about auto-merging is not authorization or a semantic fact. Candidate C is procedural, ingested, source user, confirmed true, with stated_by naming the maintainer. Confirmation means the identified maintainer stated the rule; it does not make arbitrary issue text authoritative. A and C apply repository-wide; B is scoped to its issue.

## How
Insert distinct completed-run episodes; they describe different events, not conflicting timeless facts. Avoid a second record for the same run ID. A changed rule uses supersede(old_id, new_record): atomically deactivate the old record and insert the replacement with supersedes pointing to it. Do not edit away the old provenance. Re-running candidate ingestion does not duplicate a candidate or resurrect a superseded rule.

## With
Every record has repository, issue, kind, text, source, written_at, origin, confirmed, active, supersedes, and an ID. New episodes use the UTC time they are stored. Candidate memories use their supplied `when` timestamps, representing when they were observed. Person-stated records include stated_by. Retrieval displays the source, age, confirmation, and attribution. No memories are given to the planner; executor fill calls see relevant active records. Issue-sourced memories are explicitly untrusted claims, never instructions. Current confirmed maintainer rules are instructions within their scope; prior triage episodes are historical evidence only.

## Retention and bounds
Non-user memories expire from active retrieval after 90 days, checked on access. User-stated rules remain active until superseded. At most 1,000 records are retained in the database. On insertion, evict the oldest non-user records that are not candidate fixtures or referenced by a supersedes link. Preserve rule history and the three candidate records for audit. If every record is protected, reject an insertion rather than grow without bound; a maintainer must consolidate history.

Each successful run writes one episode. Assuming 10 successful runs/day, the incoming rate is 10 records/day. An episode's retrieval lifetime is at most 90 days; a 1,000-record cap with three protected candidates gives roughly 997 / 10 = 99.7 days of episode history before capacity eviction under that workload. More protected history shortens that capacity horizon. Actual episode counts per measured run are reported with Part D. Expired entries can remain as inactive audit records until capacity eviction.

## Development and empty-store controls
REPOMIND_STORE_PATH selects an alternate database for scripted tests. REPOMIND_EMPTY_STORE=1 gives each run a separate database under state/empty_stores/<run_id>.db; resumed work keeps that run's file. With both unset, Store() uses state/store.db. Scripted triage decisions must never seed the measured default store.

## Part F experimental instruction
On a completed session-stated development run, retain the supplied experimental maintainer rule verbatim as a confirmed, ingested procedural record with source user, issue scope, stated_by, and its storage timestamp. This is an explicit experiment input, not a rule extracted or inferred from an issue body. Subsequent session runs must receive it only through retrieval. Attention and compaction conditions use isolated empty stores.
