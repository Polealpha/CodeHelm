"""Browser validation utilities for autonomous web-flow checks."""

from __future__ import annotations

import json
import os
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from .models import BrowserValidationReport, CommandResult, OSWorldActionResult, OSWorldRunReport


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


class OSWorldRunner:
    """Runs OSWorld-style action scripts using browser/desktop/http backends."""

    def run(
        self,
        *,
        backend: str = "auto",
        steps_file: str | None = None,
        url: str | None = None,
        headless: bool = True,
        screenshot_dir: str = ".caasys/osworld_artifacts",
        enable_desktop_control: bool = False,
        dry_run: bool = False,
        timeout_seconds: int = 30,
    ) -> OSWorldRunReport:
        resolved_backend = self._resolve_backend(backend, enable_desktop_control=enable_desktop_control)
        steps = self._load_steps(steps_file)
        artifacts: list[str] = []
        actions: list[OSWorldActionResult] = []
        command_results: list[CommandResult] = []

        if dry_run:
            for step in steps:
                action = str(step.get("action", "unknown"))
                actions.append(
                    OSWorldActionResult(
                        action=action,
                        success=True,
                        message=f"dry-run: skipped {action}",
                        details=dict(step),
                    )
                )
            command_results.append(
                _command_result(
                    command=f"osworld run backend={resolved_backend}",
                    phase="osworld",
                    exit_code=0,
                    stdout="dry-run: osworld steps skipped",
                    stderr="",
                )
            )
            return OSWorldRunReport(
                success=True,
                backend=resolved_backend,
                message="Dry-run OSWorld execution completed.",
                actions=actions,
                command_results=command_results,
                artifacts=artifacts,
            )

        if resolved_backend == "desktop" and not enable_desktop_control:
            return OSWorldRunReport(
                success=False,
                backend=resolved_backend,
                message="Desktop control is disabled by policy.",
                actions=[],
                command_results=[
                    _command_result(
                        command="osworld desktop disabled",
                        phase="osworld",
                        exit_code=1,
                        stdout="",
                        stderr="Desktop control disabled",
                    )
                ],
                artifacts=[],
            )

        if resolved_backend == "playwright":
            return self._run_playwright_steps(
                steps=steps,
                url=url,
                headless=headless,
                screenshot_dir=screenshot_dir,
                timeout_seconds=timeout_seconds,
            )
        if resolved_backend == "desktop":
            return self._run_desktop_steps(
                steps=steps,
                url=url,
                screenshot_dir=screenshot_dir,
            )
        return self._run_http_steps(
            steps=steps,
            url=url,
            timeout_seconds=timeout_seconds,
        )

    def _resolve_backend(self, backend: str, *, enable_desktop_control: bool) -> str:
        normalized = (backend or "auto").strip().lower()
        if normalized in {"playwright", "desktop", "http"}:
            return normalized

        if normalized != "auto":
            return "http"

        try:
            import playwright.sync_api  # noqa: F401

            return "playwright"
        except Exception:
            if enable_desktop_control:
                try:
                    import pyautogui  # noqa: F401

                    return "desktop"
                except Exception:
                    return "http"
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

    def _run_playwright_steps(
        self,
        *,
        steps: list[dict[str, Any]],
        url: str | None,
        headless: bool,
        screenshot_dir: str,
        timeout_seconds: int,
    ) -> OSWorldRunReport:
        actions: list[OSWorldActionResult] = []
        errors: list[str] = []
        artifacts: list[str] = []
        command_results: list[CommandResult] = []
        started = time.perf_counter()
        final_url = url or ""

        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                page = browser.new_page()
                if url:
                    page.goto(url, wait_until="load", timeout=timeout_seconds * 1000)
                    actions.append(
                        OSWorldActionResult(
                            action="goto",
                            success=True,
                            message=f"goto passed: {url}",
                            details={"url": url},
                        )
                    )

                for idx, step in enumerate(steps, start=1):
                    action = str(step.get("action", "")).strip().lower()
                    selector = step.get("selector")
                    value = step.get("value")
                    try:
                        if action == "goto":
                            target = str(step.get("url", url or ""))
                            page.goto(target, wait_until="load", timeout=timeout_seconds * 1000)
                            actions.append(
                                OSWorldActionResult(
                                    action=action,
                                    success=True,
                                    message=f"goto passed: {target}",
                                    details={"url": target},
                                )
                            )
                        elif action == "click":
                            page.locator(str(selector)).first.click(timeout=timeout_seconds * 1000)
                            actions.append(
                                OSWorldActionResult(
                                    action=action,
                                    success=True,
                                    message=f"click passed: {selector}",
                                    details={"selector": selector},
                                )
                            )
                        elif action == "fill":
                            page.locator(str(selector)).first.fill(str(value), timeout=timeout_seconds * 1000)
                            actions.append(
                                OSWorldActionResult(
                                    action=action,
                                    success=True,
                                    message=f"fill passed: {selector}",
                                    details={"selector": selector, "value": value},
                                )
                            )
                        elif action == "press":
                            page.locator(str(selector)).first.press(str(value), timeout=timeout_seconds * 1000)
                            actions.append(
                                OSWorldActionResult(
                                    action=action,
                                    success=True,
                                    message=f"press passed: {selector} -> {value}",
                                    details={"selector": selector, "value": value},
                                )
                            )
                        elif action == "expect_text":
                            target = str(value or "")
                            content = page.content() if not selector else page.locator(str(selector)).first.inner_text()
                            if target in content:
                                actions.append(
                                    OSWorldActionResult(
                                        action=action,
                                        success=True,
                                        message=f"expect_text passed: {target}",
                                        details={"selector": selector, "value": target},
                                    )
                                )
                            else:
                                actions.append(
                                    OSWorldActionResult(
                                        action=action,
                                        success=False,
                                        message=f"expect_text failed: {target}",
                                        details={"selector": selector, "value": target},
                                    )
                                )
                                errors.append(f"expect_text failed: {target}")
                        elif action == "expect_url_contains":
                            target = str(value or "")
                            if target in page.url:
                                actions.append(
                                    OSWorldActionResult(
                                        action=action,
                                        success=True,
                                        message=f"expect_url_contains passed: {target}",
                                        details={"value": target},
                                    )
                                )
                            else:
                                actions.append(
                                    OSWorldActionResult(
                                        action=action,
                                        success=False,
                                        message=f"expect_url_contains failed: {target}",
                                        details={"value": target, "actual": page.url},
                                    )
                                )
                                errors.append(f"expect_url_contains failed: {target}")
                        elif action == "wait":
                            seconds = float(step.get("seconds", 1))
                            time.sleep(max(0.0, seconds))
                            actions.append(
                                OSWorldActionResult(
                                    action=action,
                                    success=True,
                                    message=f"wait executed: {seconds}s",
                                    details={"seconds": seconds},
                                )
                            )
                        elif action == "screenshot":
                            path = str(step.get("path") or os.path.join(screenshot_dir, f"shot_{idx}.png"))
                            page.screenshot(path=path, full_page=True)
                            artifacts.append(path)
                            actions.append(
                                OSWorldActionResult(
                                    action=action,
                                    success=True,
                                    message=f"screenshot saved: {path}",
                                    details={"path": path},
                                )
                            )
                        else:
                            actions.append(
                                OSWorldActionResult(
                                    action=action or "unknown",
                                    success=False,
                                    message=f"unsupported action: {action}",
                                    details=dict(step),
                                )
                            )
                            errors.append(f"unsupported action: {action}")
                    except Exception as exc:
                        actions.append(
                            OSWorldActionResult(
                                action=action or "unknown",
                                success=False,
                                message=f"action failed: {action} :: {exc}",
                                details=dict(step),
                            )
                        )
                        errors.append(f"{action} failed: {exc}")

                final_url = page.url
                browser.close()

        except PlaywrightTimeoutError as exc:
            errors.append(f"Playwright timeout: {exc}")
        except Exception as exc:
            errors.append(f"Playwright OSWorld run failed: {exc}")

        duration = time.perf_counter() - started
        command_results.append(
            CommandResult(
                command="osworld playwright run",
                exit_code=0 if not errors else 1,
                stdout=f"actions={len(actions)}; final_url={final_url}",
                stderr="; ".join(errors),
                duration_seconds=duration,
                phase="osworld",
            )
        )
        return OSWorldRunReport(
            success=not errors and all(item.success for item in actions),
            backend="playwright",
            message="OSWorld Playwright run passed." if not errors else "OSWorld Playwright run failed.",
            actions=actions,
            command_results=command_results,
            artifacts=artifacts,
        )

    def _run_http_steps(
        self,
        *,
        steps: list[dict[str, Any]],
        url: str | None,
        timeout_seconds: int,
    ) -> OSWorldRunReport:
        actions: list[OSWorldActionResult] = []
        errors: list[str] = []
        command_results: list[CommandResult] = []
        if not url:
            return OSWorldRunReport(
                success=False,
                backend="http",
                message="HTTP backend requires url.",
                actions=[],
                command_results=[
                    _command_result(
                        command="osworld http run",
                        phase="osworld",
                        exit_code=1,
                        stdout="",
                        stderr="missing url",
                    )
                ],
                artifacts=[],
            )

        started = time.perf_counter()
        body_text = ""
        status = 0
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                body_text = response.read().decode("utf-8", errors="replace")
            actions.append(
                OSWorldActionResult(
                    action="goto",
                    success=True,
                    message=f"http get passed: {url} status={status}",
                    details={"url": url, "status": status},
                )
            )
        except Exception as exc:
            actions.append(
                OSWorldActionResult(
                    action="goto",
                    success=False,
                    message=f"http get failed: {exc}",
                    details={"url": url},
                )
            )
            errors.append(str(exc))

        for step in steps:
            action = str(step.get("action", "")).strip().lower()
            if action == "expect_text":
                value = str(step.get("value", ""))
                if value and value in body_text:
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"expect_text passed: {value}",
                            details={"value": value},
                        )
                    )
                else:
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=False,
                            message=f"expect_text failed: {value}",
                            details={"value": value},
                        )
                    )
                    errors.append(f"expect_text failed: {value}")
            elif action:
                actions.append(
                    OSWorldActionResult(
                        action=action,
                        success=False,
                        message=f"unsupported by http backend: {action}",
                        details=dict(step),
                    )
                )
                errors.append(f"unsupported by http backend: {action}")

        duration = time.perf_counter() - started
        command_results.append(
            CommandResult(
                command=f"osworld http run {url}",
                exit_code=0 if not errors else 1,
                stdout=f"status={status}; body_length={len(body_text)}; actions={len(actions)}",
                stderr="; ".join(errors),
                duration_seconds=duration,
                phase="osworld",
            )
        )
        return OSWorldRunReport(
            success=not errors and all(item.success for item in actions),
            backend="http",
            message="OSWorld HTTP run passed." if not errors else "OSWorld HTTP run failed.",
            actions=actions,
            command_results=command_results,
            artifacts=[],
        )

    def _run_desktop_steps(
        self,
        *,
        steps: list[dict[str, Any]],
        url: str | None,
        screenshot_dir: str,
    ) -> OSWorldRunReport:
        actions: list[OSWorldActionResult] = []
        errors: list[str] = []
        command_results: list[CommandResult] = []
        artifacts: list[str] = []
        started = time.perf_counter()
        try:
            import pyautogui
        except Exception as exc:
            return OSWorldRunReport(
                success=False,
                backend="desktop",
                message=f"Desktop backend unavailable: {exc}",
                actions=[],
                command_results=[
                    _command_result(
                        command="osworld desktop backend load",
                        phase="osworld",
                        exit_code=1,
                        stdout="",
                        stderr=f"{exc}",
                    )
                ],
                artifacts=[],
            )

        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
        if url:
            opened = webbrowser.open(url)
            actions.append(
                OSWorldActionResult(
                    action="open_url",
                    success=bool(opened),
                    message=f"open_url {'passed' if opened else 'failed'}: {url}",
                    details={"url": url},
                )
            )
            if not opened:
                errors.append(f"failed to open url: {url}")

        for idx, step in enumerate(steps, start=1):
            action = str(step.get("action", "")).strip().lower()
            try:
                if action == "move":
                    x = int(step.get("x", 0))
                    y = int(step.get("y", 0))
                    duration = float(step.get("duration", 0.1))
                    pyautogui.moveTo(x, y, duration=duration)
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"move passed: ({x},{y})",
                            details={"x": x, "y": y, "duration": duration},
                        )
                    )
                elif action == "click":
                    x = step.get("x")
                    y = step.get("y")
                    if x is not None and y is not None:
                        pyautogui.click(int(x), int(y))
                        details = {"x": int(x), "y": int(y)}
                    else:
                        pyautogui.click()
                        details = {"position": "current"}
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message="click passed",
                            details=details,
                        )
                    )
                elif action == "double_click":
                    pyautogui.doubleClick()
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message="double_click passed",
                            details={},
                        )
                    )
                elif action == "type":
                    text = str(step.get("text", ""))
                    pyautogui.write(text, interval=float(step.get("interval", 0.02)))
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"type passed ({len(text)} chars)",
                            details={"text": text},
                        )
                    )
                elif action == "press":
                    key = str(step.get("key", "enter"))
                    pyautogui.press(key)
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"press passed: {key}",
                            details={"key": key},
                        )
                    )
                elif action == "hotkey":
                    keys = step.get("keys", [])
                    if not isinstance(keys, list) or not keys:
                        raise ValueError("hotkey requires non-empty keys list")
                    pyautogui.hotkey(*[str(k) for k in keys])
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"hotkey passed: {keys}",
                            details={"keys": keys},
                        )
                    )
                elif action == "wait":
                    seconds = float(step.get("seconds", 1))
                    time.sleep(max(0.0, seconds))
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"wait executed: {seconds}s",
                            details={"seconds": seconds},
                        )
                    )
                elif action == "screenshot":
                    path = str(step.get("path") or os.path.join(screenshot_dir, f"desktop_{idx}.png"))
                    image = pyautogui.screenshot()
                    image.save(path)
                    artifacts.append(path)
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=True,
                            message=f"screenshot saved: {path}",
                            details={"path": path},
                        )
                    )
                elif action:
                    actions.append(
                        OSWorldActionResult(
                            action=action,
                            success=False,
                            message=f"unsupported desktop action: {action}",
                            details=dict(step),
                        )
                    )
                    errors.append(f"unsupported desktop action: {action}")
            except Exception as exc:
                actions.append(
                    OSWorldActionResult(
                        action=action or "unknown",
                        success=False,
                        message=f"action failed: {action} :: {exc}",
                        details=dict(step),
                    )
                )
                errors.append(f"{action} failed: {exc}")

        duration = time.perf_counter() - started
        command_results.append(
            CommandResult(
                command="osworld desktop run",
                exit_code=0 if not errors else 1,
                stdout=f"actions={len(actions)}; artifacts={len(artifacts)}",
                stderr="; ".join(errors),
                duration_seconds=duration,
                phase="osworld",
            )
        )
        return OSWorldRunReport(
            success=not errors and all(item.success for item in actions),
            backend="desktop",
            message="OSWorld desktop run passed." if not errors else "OSWorld desktop run failed.",
            actions=actions,
            command_results=command_results,
            artifacts=artifacts,
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
