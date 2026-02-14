# AGENT_POLICY

## Mode
- zero_ask: `true`
- auto_resolve_duplicate_feature_ids: `true`
- retry_failed_commands_once: `true`
- enable_parallel_teams: `true`
- default_parallel_teams: `2`
- max_parallel_features_per_iteration: `4`
- require_parallel_safe_flag: `true`

## Quality Gate
- run_smoke_before_iteration: `true` (auto-disabled when `tests/` is missing in target root)
- smoke_test_command: `python -m unittest discover -s tests -p "test_*.py" -v`

## Hard Blocker Patterns
- permission denied
- access is denied
- api key
- credential
- network is unreachable

## Fallback Chain
- retry_once
- record_blocker
- continue_to_next_feature

## Required Context Files
- AGENT_STATUS.md
- feature_list.json
- progress.log
