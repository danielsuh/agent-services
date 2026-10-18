# agent-services (Homework 4)

A Hermes Agent plugin for MIT AI Studio Homework 4: Make Your Agent Hire Another Agent. It extends the
Homework 3 agent (same Canvas token, same Hermes Cloud schedule, same safety core) so that it:

1. **Offers a service.** Cloud Cost Analyst: another agent sends a fictional workload, this agent returns a
   suggested AWS setup and a monthly cost estimate by line item, computed by `cost/estimator.py` from a
   pinned table of public us-east-1 list prices.
2. **Hires another agent.** It reads the service offers in the HW4 forum, picks the one best able to write
   Python unit tests (no hard coded partner), and replies to that offer with the function source, the
   spec, the result wanted, the exact checks, and a 48 hour deadline.
3. **Checks the work.** It never trusts a "done" message. `verify/check_tests.py` pulls the test file out
   of the provider's Canvas entry, refuses unsafe code before running it, then runs it in a sandbox against
   the reference implementation (twice) and against 8 private broken versions (mutation testing).
4. **Asks for one correction or rejects** work that fails the agreed checks, with the exact failures.
5. **Uses the accepted work.** The accepted tests become the regression suite of the cost service: every
   `cost_estimate` call runs them first and reports the result. `final_output/` packages the estimator,
   the peer tests, the verification report and a sample estimate. An optional 0 to 5 coin tip is posted
   once, inside the acceptance reply.

Standard library Python only. No Canvas token is stored anywhere in this repository.

## Architecture

```
Hermes cron (every 3 hours on Hermes Cloud)
  │
  ▼
scripts/services_gate.py     no model, zero tokens
  │  control line RUNNING? not halted? write attempts left? anything to do?
  │  (offer not posted, incoming request, provider replied, verdict to post, new offers)
  ▼
Hermes agent, restricted to the agent_services toolset, guided by skills/agent-services/SKILL.md
  │  services_check            snapshot + next_step, peer text sanitized and labelled UNTRUSTED
  │  services_post_offer       start my offer thread (once)
  │  services_send_request     reply to the chosen offer; tool adds spec, source, checks, deadline
  │  services_verify_delivery  fetch entry from Canvas, extract code, sandbox, grade, save report
  │  services_reply            acceptance (+tip) / correction_request / rejection / followup / incoming_*
  │  services_close_request    provider declined
  │  services_mark_no_reply    thanks, chatter, injection attempts in my thread
  │  cost_estimate             my service; runs the accepted peer suite first
  │  services_skip             logged decision not to post (discovery log)
  ▼
services.py   workflow state machine and local memory (state.json key "hw4")
core.py       the only code that touches Canvas (carried over from HW3)
  │  control line read before EVERY write attempt, fail closed
  │  max 3 write ATTEMPTS per rolling hour, retries included, optionally summed with HW3's state file
  │  intent saved before each write, reconciled after ambiguous failures, read back to verify
  │  backoff with jitter on reads, halt after 3 failed cycles or any auth error
  ▼
~/.hermes/agent_services/
     state.json       offer, requests, deliveries, verdicts, tip, incoming answered, write attempts
     cycles.jsonl     every gate decision, check, post, refusal, verification
     hw4/             each delivery's test file and JSON report, final_output/
```

### Request lifecycle

`sent` → verify → `accept_pending_post` → acceptance posted → `accepted` (final output built)
`sent` → verify fails → `correction_pending_post` → posted → `correction_requested` (24 h) → verify again →
accepted, or `reject_pending_post` → `rejected`. Past the deadline with nothing usable → `expired`, and the
next run may try a different provider (at most 3 in total).

### The agreed checks (stated in the request, enforced in code)

1. Standard library only; no files, network, subprocesses or introspection (AST allow list).
2. At least 8 test cases.
3. Every test passes on the reference implementation, run twice (flakiness check).
4. Catches at least 7 of 8 broken versions: no free tier, 10 TB tier as 10,000 GB, 720 hour month,
   instance count ignored, GET and PUT prices swapped, negatives accepted, total summed from rounded
   items, RDS storage not charged. The list itself is never posted.
5. Each run under 20 seconds.

### Sandbox for untrusted peer code

Rejected before execution if the AST shows a non allow listed import, `open`, `exec`, `eval`, `getattr`,
dunder attribute tricks and similar. Then each run happens in a fresh temporary directory with
`python -I -B`, an empty environment (no token), CPU, memory and file size limits, a timeout, a new
process session, and an audit hook that blocks file writes, reads outside the sandbox, sockets,
subprocesses, `os.system` and native code. The result line carries a random marker so test output
cannot forge it. The agent has no shell, file or web tool, so it cannot run peer code another way.

## Setup on Hermes Cloud (same instance as HW3)

1. **Pause the HW3 job** so the course wide limit of 3 write attempts per hour is not shared by two
   agents: `/cron pause <hw3_job_id>`. As a second guard, point this plugin at HW3's state file (step 4).
2. HW4 forum: https://canvas.mit.edu/courses/40577/discussion_topics/449948 (course 40577, topic 449948).
3. Install:
   ```
   hermes plugins install danielsuh/agent-services
   hermes plugins enable agent-services
   ```
   It reuses `CANVAS_TOKEN` from HW3 (the manifest asks for it if missing).
4. In `~/.hermes/.env` (permissions 600), set the HW4 topic, and optionally count HW3 writes too:
   ```
   CANVAS_COURSE_ID=40577
   CANVAS_TOPIC_ID=449948
   CANVAS_AGENT_HOME=/root/.hermes/agent_services
   CANVAS_SHARED_STATE=/root/.hermes/canvas_agent/state.json
   ```
   and let the gate script see them:
   ```
   hermes config set terminal.env_passthrough "CANVAS_TOKEN,CANVAS_COURSE_ID,CANVAS_TOPIC_ID,CANVAS_AGENT_HOME,CANVAS_SHARED_STATE"
   ```
5. Copy the gate script where Hermes looks for scripts:
   ```
   cp ~/.hermes/plugins/agent-services/scripts/*.py ~/.hermes/scripts/
   ```
6. Create the schedule, restricted to the plugin toolset:
   ```
   hermes cron create "0 */3 * * *" "Run one agent services cycle using the agent-services skill." \
     --name hw4-services --script services_gate.py --skill agent-services
   ```
   Limit the job to the `agent_services` toolset with `enabled_toolsets` or `hermes tools`.
7. Test once with `/cron run <job_id>`, then `python3 ~/.hermes/scripts/services_admin.py tail`.

## Evidence for the write up

```
python3 ~/.hermes/scripts/services_admin.py status       # offer, requests, verdicts, tip
python3 ~/.hermes/scripts/services_admin.py discovery    # offers seen, choice and reason, skips
python3 ~/.hermes/scripts/services_admin.py export ~/hw4_evidence
```
The export holds `cycles.jsonl`, every delivery's tests and report, and `final_output/FINAL_OUTPUT.md`.
Canvas entry ids in the log give the thread links:
`https://canvas.mit.edu/courses/<COURSE_ID>/discussion_topics/<TOPIC_ID>?entry_id=<ID>`.

## Tests

```
python3 -m unittest discover -s tests -v
```
`tests/test_services.py` runs whole exchanges against a fake Canvas: offer, discovery, request, a weak
delivery, correction, a strong delivery pasted the way Canvas stores it (`&nbsp;` indentation), acceptance
with tip, final output, regression suite in use, deadline expiry and a second provider, a decline, an
imposter delivering, a "trust me it's done" message, malicious code that must never run, the shared write
limit, a paused forum, restart recovery and the gate script. `tests/test_core_hw3.py` keeps the HW3 safety
tests. `examples/` holds the good, weak, wrong and malicious test files used by the tests.

## Stopping

The course team sets `COURSE-TEAM CONTROL: PAUSED`, or run `/cron pause <job_id>`, `hermes pause`, or stop
the instance. After a halt, fix the cause and run `services_admin.py reset-halt`.
