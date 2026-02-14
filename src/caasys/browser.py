"""Browser validation utilities for autonomous web-flow checks."""

from __future__ import annotations

import json
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from .models import BrowserValidationReport, CommandResult


class BrowserValidator:
    """Runs browser-level validation via Playwright/system browser/HTTP fallback."""

    def validate(
        self,
        *,
        url: str,
        backend: str = "auto",
        steps_file: str | None = None,
        expect_text: str | None = None,
        headless: bool = True,
        open_system_browser: bool = False,
        dry_run: bool = False,
        timeout_seconds: int = 30,
    ) -> BrowserValidationReport:
        resolved_backend = self._resolve_backend(backend)
        steps = self._load_steps(steps_file)
        checks: list[str] = []
        errors: list[str] = []
        command_results: list[CommandResult] = []

        if dry_run:
            checks.append("dry-run: browser validation skipped")
            command_results.append(
                _command_result(
                    command=f"browser validate {url}",
                    phase="browser-validate",
                    exit_code=0,
                    stdout="dry-run: browser validation skipped",
                    stderr="",
                )
            )
            return BrowserValidationReport(
                success=True,
                backend=resolved_backend,
                url=url,
                message="Dry-run browser validation completed.",
                checks=checks,
                errors=errors,
                command_results=command_results,
            )

        if resolved_backend == "system":
            opened = webbrowser.open(url)
            if not opened:
                errors.append("Failed to open system browser for target URL.")
            else:
                checks.append("System browser open request sent.")
            if open_system_browser and not opened:
                errors.append("open_system_browser=true but browser open returned false.")
            if steps:
                checks.append("Steps file ignored in system backend (no automation channel).")
            if expect_text:
                checks.append("expect_text ignored in system backend.")

            success = not errors
            command_results.append(
                _command_result(
                    command=f"webbrowser.open({url})",
                    phase="browser-validate",
                    exit_code=0 if success else 1,
                    stdout="system browser open requested" if success else "",
                    stderr="; ".join(errors),
                )
            )
            return BrowserValidationReport(
                success=success,
                backend=resolved_backend,
                url=url,
                message="System browser open executed." if success else "System browser open failed.",
                checks=checks,
                errors=errors,
                command_results=command_results,
            )

        if resolved_backend == "http":
            return self._validate_http(
                url=url,
                steps=steps,
                expect_text=expect_text,
                timeout_seconds=timeout_seconds,
            )

        # playwright
        return self._validate_playwright(
            url=url,
            steps=steps,
            expect_text=expect_text,
            headless=headless,
            timeout_seconds=timeout_seconds,
            open_system_browser=open_system_browser,
        )

    def _resolve_backend(self, backend: str) -> str:
        normalized = backend.strip().lower()
        if normalized in {"system", "http", "playwright"}:
            return normalized
        if normalized != "auto":
            return "http"
        try:
            import playwright.sync_api  # noqa: F401

            return "playwright"
        except Exception:
            return "http"

    def _load_steps(self, steps_file: str | None) -> list[dict[str, Any]]:
        if not steps_file:
            return []
        path = Path(steps_file)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _validate_http(
        self,
        *,
        url: str,
        steps: list[dict[str, Any]],
        expect_text: str | None,
        timeout_seconds: int,
    ) -> BrowserValidationReport:
        checks: list[str] = []
        errors: list[str] = []
        command_results: list[CommandResult] = []
        started = time.perf_counter()
        body_text = ""
        status_code = 0

        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", 200))
                raw = response.read()
                body_text = raw.decode("utf-8", errors="replace")
            checks.append(f"HTTP GET succeeded with status {status_code}.")
        except Exception as exc:
            errors.append(f"HTTP request failed: {exc}")

        for step in steps:
            action = str(step.get("action", "")).strip().lower()
            value = str(step.get("value", ""))
            if action == "expect_text":
                if value and value in body_text:
                    checks.append(f"Step expect_text passed: {value}")
                else:
                    errors.append(f"Step expect_text failed: {value}")
            elif action:
                checks.append(f"Step '{action}' not supported by http backend; skipped.")

        if expect_text:
            if expect_text in body_text:
                checks.append(f"expect_text passed: {expect_text}")
            else:
                errors.append(f"expect_text failed: {expect_text}")

        duration = time.perf_counter() - started
        command_results.append(
            CommandResult(
                command=f"HTTP GET {url}",
                exit_code=0 if not errors else 1,
                stdout=f"status={status_code}; body_length={len(body_text)}",
                stderr="; ".join(errors),
                duration_seconds=duration,
                phase="browser-validate",
            )
        )

        success = not errors
        return BrowserValidationReport(
            success=success,
            backend="http",
            url=url,
            message="HTTP validation passed." if success else "HTTP validation failed.",
            checks=checks,
            errors=errors,
            command_results=command_results,
        )

    def _validate_playwright(
        self,
        *,
        url: str,
        steps: list[dict[str, Any]],
        expect_text: str | None,
        headless: bool,
        timeout_seconds: int,
        open_system_browser: bool,
    ) -> BrowserValidationReport:
        checks: list[str] = []
        errors: list[str] = []
        command_results: list[CommandResult] = []
        started = time.perf_counter()
        current_url = url
        last_content = ""

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                page = browser.new_page()
                page.goto(url, wait_until="load", timeout=timeout_seconds * 1000)
                checks.append(f"Navigated to {url}")
                for step in steps:
                    action = str(step.get("action", "")).strip().lower()
                    selector = step.get("selector")
                    value = step.get("value")
                    if action == "goto":
                        target = str(step.get("url", url))
                        page.goto(target, wait_until="load", timeout=timeout_seconds * 1000)
                        checks.append(f"goto passed: {target}")
                    elif action == "click":
                        page.locator(str(selector)).first.click(timeout=timeout_seconds * 1000)
                        checks.append(f"click passed: {selector}")
                    elif action == "fill":
                        page.locator(str(selector)).first.fill(str(value), timeout=timeout_seconds * 1000)
                        checks.append(f"fill passed: {selector}")
                    elif action == "press":
                        page.locator(str(selector)).first.press(str(value), timeout=timeout_seconds * 1000)
                        checks.append(f"press passed: {selector} -> {value}")
                    elif action == "wait_for_selector":
                        page.locator(str(selector)).first.wait_for(timeout=timeout_seconds * 1000)
                        checks.append(f"wait_for_selector passed: {selector}")
                    elif action == "expect_text":
                        target = str(value)
                        if selector:
                            content = page.locator(str(selector)).first.inner_text(timeout=timeout_seconds * 1000)
                        else:
                            content = page.content()
                        if target in content:
                            checks.append(f"expect_text passed: {target}")
                        else:
                            errors.append(f"expect_text failed: {target}")
                    elif action == "expect_url_contains":
                        target = str(value)
                        if target in page.url:
                            checks.append(f"expect_url_contains passed: {target}")
                        else:
                            errors.append(f"expect_url_contains failed: {target} (actual={page.url})")
                    elif action == "sleep":
                        delay = float(step.get("seconds", 1))
                        time.sleep(max(0.0, delay))
                        checks.append(f"sleep executed: {delay}s")
                    elif action == "screenshot":
                        screenshot_path = str(step.get("path", "browser_validation.png"))
                        page.screenshot(path=screenshot_path, full_page=True)
                        checks.append(f"screenshot saved: {screenshot_path}")
                    elif action:
                        checks.append(f"unsupported step action '{action}', skipped")

                current_url = page.url
                last_content = page.content()
                if expect_text:
                    if expect_text in last_content:
                        checks.append(f"expect_text passed: {expect_text}")
                    else:
                        errors.append(f"expect_text failed: {expect_text}")

                if open_system_browser:
                    webbrowser.open(current_url)
                    checks.append("System browser open requested after playwright validation.")
                browser.close()

        except PlaywrightTimeoutError as exc:
            errors.append(f"Playwright timeout: {exc}")
        except Exception as exc:
            errors.append(f"Playwright validation failed: {exc}")

        duration = time.perf_counter() - started
        command_results.append(
            CommandResult(
                command=f"playwright validate {url}",
                exit_code=0 if not errors else 1,
                stdout=f"final_url={current_url}; html_length={len(last_content)}",
                stderr="; ".join(errors),
                duration_seconds=duration,
                phase="browser-validate",
            )
        )

        success = not errors
        return BrowserValidationReport(
            success=success,
            backend="playwright",
            url=current_url,
            message="Playwright validation passed." if success else "Playwright validation failed.",
            checks=checks,
            errors=errors,
            command_results=command_results,
        )


def _command_result(command: str, phase: str, exit_code: int, stdout: str, stderr: str) -> CommandResult:
    return CommandResult(
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.0,
        phase=phase,
    )
