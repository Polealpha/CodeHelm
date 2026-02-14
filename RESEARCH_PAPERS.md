# Research Papers and Mapping

This file records the papers and primary sources used to design the current system upgrades.

## 1) Long-running software iteration loop

1. Effective harnesses for long-running agents (Anthropic Engineering, 2025-11-26)  
   Link: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents  
   Applied to system:
   - initializer + coding-session split,
   - persistent progress artifacts (`AGENT_STATUS.md`, `feature_list.json`, `progress.log`),
   - start-of-session bootstrap + sanity checks.

2. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? (arXiv:2310.06770)  
   Link: https://arxiv.org/abs/2310.06770  
   Applied to system:
   - completion tied to executable validation and issue-resolution style criteria,
   - stop decisions emphasize test/verification outcomes over narrative status.

## 2) Multi-agent role decomposition and coding-as-action

1. CoAct-1: Computer-using Agents with Coding as Actions (arXiv:2508.03923)  
   Link: https://arxiv.org/abs/2508.03923  
   Applied to system:
   - role structure (`Orchestrator`, `Programmer`, `Operator`),
   - mixed strategy: command-driven implementation and operation-time validation.

2. ReAct: Synergizing Reasoning and Acting in Language Models (arXiv:2210.03629)  
   Link: https://arxiv.org/abs/2210.03629  
   Applied to system:
   - explicit reasoning/action loop reflected in:
     `PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> NEXT`.

## 3) Browser-level web-task validation

1. WebArena: A Realistic Web Environment for Building Autonomous Agents (arXiv:2307.13854)  
   Link: https://arxiv.org/abs/2307.13854  
   Applied to system:
   - end-to-end web interaction as part of validation,
   - browser checks integrated into stop criteria (optional).

2. Playwright Python docs (official)  
   Link: https://playwright.dev/python/docs/intro  
   Applied to system:
   - automated web actions (`goto`, `click`, `fill`, `press`, assertions),
   - optional real browser opening and fallback to non-browser HTTP checks.

## 4) Project-loop stop criteria now implemented

The loop now stops on one of:

- `all_features_passed`
- `quality_gate_failed`
- `stagnation_no_progress`
- `max_iterations_reached`
- `browser_validation_failed` (when browser validation is required before stop)
