# Assignment 4 · Kill it and resume: state, keys and a memory with provenance

Model: Google Gemini, `gemini-3.5-flash-lite` through the OpenAI-compatible API, the same for every measured run. Scripted development tests are separate.

## Part A · Mark the plan, place the checkpoints

| Step | Tool | Kind | Checkpoint |
|---|---|---|---|
| 1 | issues_read | read | none |
| 2 | code_search | read | after |
| 3 | code_read_file | read | none |
| 4 | pulls_open | keyed_write | before |
| 5 | issues_comment | keyed_write | before |

I save after search so a crash does not make the agent repeat the search and the model work behind it. The save before the PR includes the file read, so I do not need another save right after that read. I also save when the plan finishes.

- **Durability:** I use sync for the whole run because it includes writes. Each save reaches disk before the agent continues. It holds the five required fields, including the exact arguments for the next write, but no conversation. This leaves at most one write to retry; the stable key prevents a duplicate.
- **Weaker write:** the comment. If its key changes, it can be posted twice. The PR has a backup check for an existing PR on the same branch.

## Part B · Kill it at every step

**Prediction, written before crash testing:** the worst case is a crash during step 5 after the comment commits but before acknowledgement. Its last checkpoint is the sync save immediately before step 5, containing the comment arguments and completed results for steps 1–4. Only step 5 is in the replay window, including the running step. Its comment is already posted but has no recorded result. Retrying with the saved arguments and stable key should find the existing comment. I predict one comment and one PR; the checkpoint alone cannot prevent duplication.

**The matrix, derived keys.** Uncrashed run: `planned-4201-s01-83fa54`. Its executed plan had 5 steps; every position was tested after and during.

| Step | When | run_id | Comments | Open PRs | Matches its findings |
|---|---|---|---|---|---|
| 1 | after | planned-4201-s01-daa6c7 | 1 | 1 | True |
| 1 | during | planned-4201-s01-b37c5f | 1 | 1 | True |
| 2 | after | planned-4201-s01-d410c6 | 1 | 1 | True |
| 2 | during | planned-4201-s01-90d272 | 1 | 1 | True |
| 3 | after | planned-4201-s01-497f9e | 1 | 1 | True |
| 3 | during | planned-4201-s01-2aa547 | 1 | 1 | True |
| 4 | after | planned-4201-s01-715b83 | 1 | 1 | True |
| 4 | during | planned-4201-s01-698b0c | 1 | 1 | True |
| 5 | after | planned-4201-s01-6266d2 | 1 | 1 | True |
| 5 | during | planned-4201-s01-0c3233 | 1 | 1 | True |

All ten initial plans differed from the baseline; the traces keep each plan. The script counted results in the tracker by run ID before Part C's reset. Every final comment matched its saved findings and had the expected PR count. On resume, the agent skipped saved completed work and reused the write arguments.

## Part C · Break it on purpose

The tracker was archived before this matrix; Part B evidence remains in its archive. These runs use `KEY_MODE=uuid`, with the same checkpoint placement and resume logic as Part B.

| Step | When | run_id | Comments | Comment IDs | Open PRs |
|---|---|---|---|---|---|
| 1 | after | planned-4201-s01-fa9c8e | 1 | 1 | 1 |
| 1 | during | planned-4201-s01-f81291 | 1 | 2 | 1 |
| 2 | after | planned-4201-s01-bc54ec | 1 | 3 | 1 |
| 2 | during | planned-4201-s01-3b36f9 | 1 | 4 | 1 |
| 3 | after | planned-4201-s01-ce2d1f | 1 | 5 | 1 |
| 3 | during | planned-4201-s01-0adceb | 1 | 6 | 1 |
| 4 | after | planned-4201-s01-a208e9 | 1 | 7 | 1 |
| 4 | during | planned-4201-s01-11486b | 1 | 8 | 1 |
| 5 | after | planned-4201-s01-c3dc1c | 2 | 9, 10 | 1 |
| 5 | during | planned-4201-s01-96dbc8 | 2 | 11, 12 | 1 |

The checkpoint saved the agent's progress and write arguments, but the crash happened before it could save the write's result. With a random key, the retry looked like a new comment, so the tracker posted it again. The PR's branch check still stopped duplicates. This showed me why Part B needed stable keys as well as checkpoints.

Duplicate IDs: `planned-4201-s01-c3dc1c`: 9, 10; `planned-4201-s01-96dbc8`: 11, 12. These cases have `matches: false` because they contain two comments. All initial plans differed from Part B's baseline; the matrix covers that baseline's five executed step positions.

## Part D · A memory that can say where it came from

My policy stores one episode after a comment succeeds. “Confirmed” means the comment was posted, not that its diagnosis was correct. Each memory keeps its source, time, origin and confirmation. When a rule changes, the store adds its replacement and marks the old one inactive in one transaction. The executor sees each memory’s source and age; the planner gets no memories. Full policy: `state/write_policy.md`.

| Candidate | Stored? | Kind | source | origin | confirmed | Invites |
|---|---|---|---|---|---|---|
| A | Yes | procedural | memory | derived | true | Staleness as scripts change |
| B | Yes | episodic | issue:4188 | ingested | false | Poisoning if promoted to a fact |
| C | Yes | procedural | user | ingested | true | Contradiction if a rule changes |

A's script names were checked against package.json, but the server and port were not tested. B only records what someone claimed; it does not give permission to auto-merge. C keeps the maintainer's exact words and name. All three keep the time they were observed. A and C apply to the repository; B applies only to its issue.

**Retention:** non-user memories expire from retrieval after 90 days; rules persist until superseded. The 1,000-record cap evicts oldest eligible records, protecting candidates and referenced history. Insertion fails if all records are protected. Measured runs wrote one episode each. At 10 runs/day, retrieval lasts at most 90 days; capacity allows about (1,000 − 3) / 10 = **99.7 days** of episode history, less as protected history grows.

Seed run (excluded from measurements): `planned-4207-s01-17a85a`. Five runs in each group were made sequentially; each empty-store run used its own new database.

| Issue 4207, five runs each | With store | Empty store |
|---|---|---|
| Passes | 0 | 5 |
| Mean tool calls | 5 | 5 |
| Mean tokens | 16108.6 | 14385.6 |

| Condition | Run | Label | File | File evidence |
|---|---|---|---|---|
| with_store | planned-4207-s01-290a89 | bug | src/worker/scheduled.ts | not read and not identified in retrieved memory |
| with_store | planned-4207-s01-a614f5 | bug | src/worker/scheduled.ts | present in retrieved memory, not read this run |
| with_store | planned-4207-s01-8c5435 | bug | src/worker/scheduler.ts | present in retrieved memory, not read this run |
| with_store | planned-4207-s01-9367e6 | bug | src/worker/scheduled.ts | present in retrieved memory, not read this run |
| with_store | planned-4207-s01-d8176e | bug | src/worker/scheduled.ts | present in retrieved memory, not read this run |
| empty_store | planned-4207-s01-134b97 | bug | src/export/scheduler.ts | not read and not identified in retrieved memory |
| empty_store | planned-4207-s01-61d22e | bug | src/export/scheduler.ts | not read and not identified in retrieved memory |
| empty_store | planned-4207-s01-dabe52 | bug | src/export/scheduler.ts | not read and not identified in retrieved memory |
| empty_store | planned-4207-s01-8d0b3b | bug | src/export/scheduler.ts | not read and not identified in retrieved memory |
| empty_store | planned-4207-s01-4d3971 | bug | src/export/scheduler.ts | not read and not identified in retrieved memory |

Memory did worse here: **0/5 correct results versus 5/5** without memory. It also used 1,723 more tokens per run on average, with the same number of tool calls. Four memory runs named files they had retrieved from memory but had not read. They may have relied on earlier mistakes, although this small experiment does not prove that memory caused the difference.

## Part E · Answer from your own runs

1. **Prediction:** my prediction held. All ten Part B cases ended with one comment and one PR matching the saved findings. Crashes before the first checkpoint restarted the work; resumes at the write steps used zero model tokens. One run failed on malformed plan arguments before the intended crash. We kept its trace, fixed validation and reran that case. Part C showed that changing the keys brought duplicate comments back.

2. **Contradiction:** Part D first stored the old rule (`1d65497f483740c58d2b0d0356d40a99`). A separate process replaced it with the test rule “close duplicates after 14 days,” attributed to the same maintainer. A third process retrieved only `e6af9e492a7f493f917ef192ab92177f`. The new record points to the old one, which is now inactive. Evidence: `eval/contradiction_test.py` and `reports/CONTRADICTION_TEST.json`.

3. **Size:** run `planned-4191-s01-b8c621` saved four checkpoints: **24,388 bytes** for structured state and **219,447 bytes** with conversation added. These are totals per run, averaged over **one run**. I measured UTF-8 JSON sizes, excluding database overhead and newlines. The conversation copies include every message sent so far, including repeated context. They are saved separately in `reports/checkpoint_samples/planned-4191-s01-b8c621.jsonl`; the real checkpoint database has no conversation. The run used the normal saves and trace events.

4. **Durable execution:** I would call this a manual recovery aid. It does not automatically detect crashes or restart the agent, but it does skip work recorded as completed. Saved call results act as a journal, and stable keys protect writes with unknown outcomes. Full automatic recovery would need a persistent queue, a supervisor that detects crashes, bounded retries and reliable call journaling. The experiment script starts resumes explicitly; it is not that supervisor.

5. **Abstraction:** the steps and order are known, so a graph-style workflow fits. Runs need to survive process restarts, so checkpoints belong on disk. Writes need stable keys, plus supervised durable execution if the run must finish on its own. This assignment uses a custom harness because we implement the loop; a ready-made harness would fit if we did not want to maintain it. Our design combines the planned executor, checkpoints, saved call results, keyed writes and a memory store. A framework still cannot decide for us what to save, remember, expire or keep through compaction.

## Part F · Find the boundary that lost it

Experimental rule attributed to maintainer priya-s: "Ledgerline's maintainers label every report about the Export button feature: they plan its fixes on the feature board." Its only requested effect is `label: feature`; it does not specify a file.

I used empty stores for attention and compaction so memory could not bring the rule back. For attention, I moved the rule from the middle of repository text to the end of the request. For compaction, I summarized tool history at 300 estimated tokens and kept the issue separate. The fixed version also kept the rule in a separate note. In the session test, the later run had to get the rule from the store.

| Condition | Run | Posted label | Draft trace line | Request line | Fact sent to draft? | Compaction trace lines |
|---|---|---|---|---|---|---|
| attention_lost | planned-4192-s01-4f9a76 | bug | 15 | 5 | True | [] |
| attention_fixed | planned-4192-s01-455f96 | feature | 15 | 5 | True | [] |
| compaction_lost | planned-4192-s01-354fea | bug | 18 | 6 | False | [17] |
| compaction_fixed | planned-4192-s01-b17183 | feature | 22 | 8 | True | [17, 21] |
| session_stated | planned-4192-s01-fba1a0 | feature | 18 | 6 | True | [] |
| session_lost | planned-4192-s01-bc5e38 | bug | 18 | 6 | False | [] |
| session_fixed | planned-4192-s01-8696c8 | feature | 18 | 6 | True | [] |

Trace lines refer to `runs/<run_id>.jsonl`; request lines refer to `runs/<run_id>.requests.jsonl`.

Evidence beyond the table:

- **Attention:** the rule's distance from the nearest request edge changed from 26,898 characters to 0. It was present in both drafting requests; only the prominent version produced `feature`.
- **Compaction:** lost-run request 2 contained the rule before trace line 17 compacted history; drafting request 6 lacked it. Fixed-run request 3 contained it before compaction, and drafting request 8 retained it in the separate note.
- **Session:** the lost run never received the rule. The fixed run's store read at trace line 8 retrieved user-sourced record `c9df516867674fdeba3ca9d374943ecf`; drafting request 6 contained its verbatim rule.

The first session-fixed attempt (`planned-4192-s01-b73727`, trace line 13/request 4) received the rule but still posted `bug`. I kept that result. We then separated maintainer rules from past decisions and clarified that those rules can override the default labels. The retry posted `feature`, using the rule retrieved from memory.

All three pairs eventually showed the expected failure and fix. The main lesson is to find where the fact was lost: attention needs better placement, compaction needs a separate note, a new session needs memory, and a crash needs a checkpoint. Full evidence and the earlier attempt are in `reports/PART_F_MEASURED.json`.

## AI assistance

I used OpenAI Codex to help write and debug the code, generate results tables, and run automated checks. For the written answers, AI helped me understand what the questions were asking, break down the concepts, interpret my results and their implications, and brainstorm and draft some responses. I reviewed the code and explanations, ran the live experiments, and checked and revised the written answers to reflect my understanding.
