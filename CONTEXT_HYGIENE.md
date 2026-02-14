# Context Hygiene Checklist

Use this checklist every iteration to avoid context corruption:

1. Run bootstrap scan: `python -m caasys.cli --root . bootstrap`
2. Run quality gate: `python -m caasys.cli --root . quality-gate`
3. If gate fails:
   - reproduce failure;
   - record blocker in `AGENT_STATUS.md`;
   - fix base state before new feature work.
4. Work one feature at a time.
5. Mark `passes=true` only after verification command succeeds.
6. Update `AGENT_STATUS.md` and `progress.log` before ending iteration.
7. Create a small commit.

No interactive questions are required in normal flow (`zero_ask=true`).
