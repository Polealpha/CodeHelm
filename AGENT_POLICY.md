# AGENT_POLICY

## Mode
- zero_ask: `true`
- auto_resolve_duplicate_feature_ids: `true`
- retry_failed_commands_once: `true`
- enable_parallel_teams: `true`
- default_parallel_teams: `2`
- max_parallel_features_per_iteration: `4`
- require_parallel_safe_flag: `true`

## Stop Criteria
- max_iterations_per_run: `20`
- max_no_progress_iterations: `3`
- stop_when_all_features_pass: `true`
- stop_on_quality_gate_failure: `true`
- require_browser_validation_before_stop: `false`

## Browser Validation
- browser_validation_enabled: `false`
- browser_validation_backend: `auto`
- browser_validation_url: `None`
- browser_validation_steps_file: `.caasys/browser_steps.json`
- browser_validation_headless: `true`
- browser_validation_open_system_browser: `false`

## OSWorld Mode
- osworld_mode_enabled: `true`
- osworld_action_backend: `auto`
- osworld_steps_file: `.caasys/osworld_steps.json`
- osworld_headless: `true`
- osworld_screenshot_dir: `.caasys/osworld_artifacts`
- osworld_enable_desktop_control: `false`

## Auto Handoff
- auto_handoff_enabled: `true`
- handoff_after_iterations: `4`
- handoff_on_no_progress_iterations: `2`
- handoff_context_char_threshold: `16000`
- handoff_max_tail_lines: `20`
- handoff_summary_file: `.caasys/handoff_summary.json`

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
