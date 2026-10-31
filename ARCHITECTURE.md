# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 42 to 44):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below describes the completed Assignment 4 implementation. Recovery is explicit: no service automatically detects crashes and restarts the agent.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called through the metered client; experimental message capture delegates to that same client | `harness/client.py:150`, `ways/planned.py:94` | present |
| Harness | A validated plan and bounded revisions; an executor follows its steps, restores saved progress, and compacts tool history in the Part F experiments while retaining the issue separately | `ways/planned.py:163`, `ways/planned.py:235`, `ways/planned.py:265`, `ways/planned.py:368`, `ways/planned.py:520` | partial: manual restart, no crash supervisor |
| Tools | Five namespaced tools behind a validating registry; stable derived write keys, existence checks before writes, read-back after timeouts, and a call record | `tools/__init__.py:155`, `tools/__init__.py:245`, `tools/__init__.py:284`, `tools/__init__.py:291`, `tools/__init__.py:313` | present |
| Memory & State | SQLite checkpoints preserve the plan, statuses, call results/keys, findings and current step; resume restores them. A separate SQLite store shares sourced, dated memories across runs, replaces contradicted rules atomically, expires old entries and bounds storage | `state/checkpointer.py:78`, `state/checkpointer.py:119`, `ways/planned.py:235`, `ways/planned.py:486`, `state/store.py:57`, `state/store.py:83`, `state/store.py:95`, `state/store.py:104`, `state/store.py:120`, `ways/planned.py:455` | present |
| Control & Policy | Reject malformed plan arguments; save synchronously before each write; reuse saved write arguments; escalate unverifiable writes; constrain memory provenance and issue claims; hold drafts failing the second pass | `ways/planned.py:134`, `ways/planned.py:303`, `ways/planned.py:317`, `state/store.py:57`, `ways/planned.py:599`, `tools/__init__.py:221` | partial: the general tool hook still allows every call; maintainer-rule interpretation depends on the model |
| Observability | Trace plans, model/tool calls, saves and restores, memory reads and compactions; record actual development-issue requests for the forgetting experiments | `harness/trace.py:73`, `harness/trace.py:96`, `harness/trace.py:114`, `harness/trace.py:125`, `harness/client.py:136`, `ways/planned.py:185`, `ways/planned.py:486` | partial: stored evidence, no operational alerts |
| Evaluation | Grounded triage checks read tracker results; crash matrices count actual writes; memory comparisons and forgetting experiments inspect outcomes and request evidence | `eval/check_triage.py:7`, `eval/run_part_b.py:45`, `eval/run_part_c.py:43`, `eval/run_part_d.py:40`, `eval/run_part_f.py:28`, `eval/run_part_f.py:59` | partial: offline experiments, not continuous production evaluation |

**Empty layers: 0 of 7; partial layers: 4 of 7.** A present memory layer does not guarantee accurate memories: the measured Part D memory condition performed worse than the empty-store condition.
