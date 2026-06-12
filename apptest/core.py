import os
import sys
import json
import time
import random
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.syntax import Syntax

from .config import ConfigManager, DeviceConfig, TestAccount
from .models import TestCase, TestStep, TestCaseResult, TestRunResult, StepResult, TestStatus, TestCategory


console = Console()


class Logger:
    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file: Optional[Path] = None
        self._init_log_file()

    def _init_log_file(self) -> None:
        if self.log_dir:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_file = self.log_dir / f"run_{timestamp}.log"

    def _write(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] [{level}] {message}\n"
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def debug(self, message: str) -> None:
        self._write("DEBUG", message)

    def get_log_path(self) -> Optional[str]:
        return str(self.log_file) if self.log_file else None


class DeviceManager:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.active_devices: Dict[str, DeviceConfig] = {}

    def list_devices(self) -> List[DeviceConfig]:
        return self.config_manager.get_active_devices()

    def connect_device(self, device: DeviceConfig) -> bool:
        console.print(f"[cyan]正在连接设备:[/cyan] {device.name} ({device.platform})")
        time.sleep(0.3)
        if random.random() > 0.05:
            self.active_devices[device.device_id] = device
            console.print(f"[green]✓ 设备连接成功:[/green] {device.name}")
            return True
        else:
            console.print(f"[red]✗ 设备连接失败:[/red] {device.name}")
            return False

    def disconnect_device(self, device_id: str) -> None:
        if device_id in self.active_devices:
            del self.active_devices[device_id]

    def get_device(self, device_id: str) -> Optional[DeviceConfig]:
        return self.active_devices.get(device_id)

    def launch_app(self, device_id: str) -> bool:
        device = self.get_device(device_id)
        if not device:
            return False
        console.print(f"  [dim]在 {device.name} 上启动应用: {device.app_package}[/dim]")
        time.sleep(0.2)
        return True

    def close_app(self, device_id: str) -> None:
        device = self.get_device(device_id)
        if device:
            console.print(f"  [dim]关闭 {device.name} 上的应用[/dim]")

    def take_screenshot(self, device_id: str, output_path: Path) -> str:
        device = self.get_device(device_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._generate_mock_screenshot(output_path, device)
        except Exception as e:
            self.logger and hasattr(self, "logger")
            console.print(f"  [yellow]警告: 生成截图失败 {e}[/yellow]")
        if device:
            console.print(f"  [dim]截图保存至: {output_path.name}[/dim]")
        return str(output_path)

    @staticmethod
    def _generate_mock_screenshot(output_path: Path, device: Optional[DeviceConfig]) -> None:
        width, height = 1080, 1920
        title = "FAILED"
        subtitle = "AppTest Screenshot"
        device_name = device.name if device else "Unknown Device"
        platform = device.platform if device else "Unknown"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        import struct
        import zlib

        def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + chunk_type
                + data
                + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
            )

        def color(x: int, y: int) -> tuple:
            t = y / height
            r = int(60 + 180 * t)
            g = int(20 + 60 * (1 - t))
            b = int(80 + 120 * (1 - t))
            if 80 <= y <= 180:
                return (255, 80, 80)
            if 900 <= y <= 1020 and 200 <= x <= 880:
                return (255, 255, 255)
            if 1100 <= y <= 1200 and 300 <= x <= 780:
                return (30, 30, 30)
            return (min(r, 255), min(g, 255), min(b, 255))

        raw = bytearray()
        for y in range(height):
            raw.append(0)
            for x in range(width):
                r, g, b = color(x, y)
                raw.append(r)
                raw.append(g)
                raw.append(b)

        png_header = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        idat = zlib.compress(bytes(raw), 6)

        with open(output_path, "wb") as f:
            f.write(png_header)
            f.write(make_chunk(b"IHDR", ihdr))
            title_bytes = f"Title: {title}\nDevice: {device_name}\nPlatform: {platform}\nTime: {timestamp}\nSubtitle: {subtitle}".encode("utf-8")
            f.write(make_chunk(b"tEXt", b"Description\x00" + title_bytes))
            f.write(make_chunk(b"IDAT", idat))
            f.write(make_chunk(b"IEND", b""))


class TestCaseLoader:
    def __init__(self, cases_dir: Path):
        self.cases_dir = cases_dir
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def list_case_files(self) -> List[Path]:
        return list(self.cases_dir.glob("**/*.yaml")) + list(self.cases_dir.glob("**/*.yml"))

    def load_all_cases(self) -> List[TestCase]:
        cases = []
        for file_path in self.list_case_files():
            try:
                case = self.load_case(file_path)
                if case:
                    cases.append(case)
            except Exception as e:
                console.print(f"[yellow]警告: 加载用例 {file_path} 失败: {e}[/yellow]")
        return cases

    def load_case(self, file_path: Path) -> Optional[TestCase]:
        import yaml
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return None
        return TestCase.from_dict(data)

    def save_case(self, case: TestCase, filename: Optional[str] = None) -> Path:
        import yaml
        if not filename:
            filename = f"{case.id}_{case.category}_{case.name[:30]}.yaml"
        filename = filename.replace("/", "_").replace("\\", "_").replace(" ", "_")
        file_path = self.cases_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(case.to_dict(), f, allow_unicode=True, default_flow_style=False)
        return file_path

    def filter_cases(
        self,
        cases: List[TestCase],
        tags: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        risk_levels: Optional[List[str]] = None,
        only_high_risk: bool = False,
    ) -> List[TestCase]:
        filtered = [c for c in cases if c.enabled]
        if only_high_risk:
            risk_levels = ["critical", "high"]
        if risk_levels:
            filtered = [c for c in filtered if c.risk_level in risk_levels]
        if tags:
            filtered = [c for c in filtered if any(t in c.tags for t in tags)]
        if categories:
            filtered = [c for c in filtered if c.category in categories]
        filtered.sort(key=lambda c: (-c.priority, c.risk_level == "critical", c.id))
        return filtered


class TestExecutor:
    def __init__(
        self,
        config_manager: ConfigManager,
        device_manager: DeviceManager,
        logger: Logger,
        screenshots_dir: Path,
        retry_count: int = 2,
    ):
        self.config_manager = config_manager
        self.device_manager = device_manager
        self.logger = logger
        self.screenshots_dir = screenshots_dir
        self.retry_count = retry_count
        self._step_handlers = {
            "click": self._handle_click,
            "input": self._handle_input,
            "swipe": self._handle_swipe,
            "assert": self._handle_assert,
            "wait": self._handle_wait,
            "screenshot": self._handle_screenshot,
            "long_press": self._handle_long_press,
            "back": self._handle_back,
            "home": self._handle_home,
        }
        self._init_account_pool()

    def _init_account_pool(self) -> None:
        config = self.config_manager.load()
        self.account_pool = list(config.accounts)

    def _resolve_account_placeholders(self, step: TestStep, case: TestCase, device: DeviceConfig) -> Dict[str, str]:
        placeholders = {}
        value = step.value or ""
        target = step.target or ""
        if "{username}" in value or "{password}" in value or "{username}" in target or "{password}" in target:
            accounts = self.account_pool
            if not accounts:
                self.logger.warn("步骤使用了 {username}/{password} 占位符，但未配置测试账号")
                return {}
            account_index = 0
            if case.category == "login" and len(accounts) > 1:
                if device.platform == "iOS":
                    account_index = 0
                elif device.platform == "Android":
                    account_index = 1 % len(accounts)
            account = accounts[account_index % len(accounts)]
            placeholders["{username}"] = account.username
            placeholders["{password}"] = account.password
            placeholders["{role}"] = account.role
            self.logger.info(
                f"账号占位符替换 -> 用户名: {account.username} (角色: {account.role})"
                + f" | 用例: {case.id} | 设备: {device.name}"
            )
        return placeholders

    def _apply_placeholders(self, text: str, placeholders: Dict[str, str]) -> str:
        if not text:
            return text
        for k, v in placeholders.items():
            text = text.replace(k, v)
        return text

    def execute_run(
        self,
        cases: List[TestCase],
        run_id: str,
        version: str,
        target_devices: Optional[List[DeviceConfig]] = None,
    ) -> TestRunResult:
        start_time = datetime.now()
        run_result = TestRunResult(
            run_id=run_id,
            version=version,
            start_time=start_time.isoformat(),
            retry_count=self.retry_count,
        )
        if target_devices is None:
            devices = self.device_manager.list_devices()
        else:
            devices = target_devices
        connected_devices = []
        for device in devices:
            if self.device_manager.connect_device(device):
                connected_devices.append(device)
        run_result.devices = [d.name for d in connected_devices]
        run_result.device_count = len(connected_devices)
        if not connected_devices:
            console.print("[red]错误: 没有可用的连接设备[/red]")
            end_time = datetime.now()
            run_result.end_time = end_time.isoformat()
            run_result.duration_ms = int((end_time - start_time).total_seconds() * 1000)
            return run_result

        def _case_ok_for_device(case: TestCase, device: DeviceConfig) -> bool:
            if not case.device_requirements:
                return True
            return device.name in case.device_requirements

        execution_plan = []
        for device in connected_devices:
            for case in cases:
                if _case_ok_for_device(case, device):
                    execution_plan.append((device, case))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]执行测试用例...", total=len(execution_plan))
            for device, case in execution_plan:
                progress.update(task, description=f"[cyan]{device.name} | {case.name}")
                case_result = self._execute_case_with_retry(case, device)
                run_result.case_results.append(case_result)
                progress.advance(task)

        end_time = datetime.now()
        run_result.end_time = end_time.isoformat()
        run_result.duration_ms = int((end_time - start_time).total_seconds() * 1000)
        run_result.calculate_metrics()
        for device in connected_devices:
            self.device_manager.close_app(device.device_id)
        return run_result

    def _execute_case_with_retry(
        self, case: TestCase, device: DeviceConfig
    ) -> TestCaseResult:
        final_result = None
        max_attempts = self.retry_count + 1
        for attempt in range(1, max_attempts + 1):
            self.logger.info(f"执行用例: {case.id} | {case.name} | 设备: {device.name} | 尝试: {attempt}/{max_attempts}")
            result = self._execute_case(case, device)
            result.retry_count = attempt - 1
            final_result = result
            if result.status in (TestStatus.PASSED.value, TestStatus.SKIPPED.value):
                break
            if attempt < max_attempts:
                self.logger.warn(f"用例失败，准备重试: {case.id} | 状态: {result.status}")
                time.sleep(0.5)
        return final_result

    def _execute_case(self, case: TestCase, device: DeviceConfig) -> TestCaseResult:
        start_time = datetime.now()
        result = TestCaseResult(
            case_id=case.id,
            case_name=case.name,
            category=case.category,
            risk_level=case.risk_level,
            device_name=device.name,
            status=TestStatus.RUNNING.value,
            tags=case.tags,
        )
        self.device_manager.launch_app(device.device_id)
        case_passed = True
        for idx, step in enumerate(case.steps):
            step_result = self._execute_step(idx, step, device, case)
            result.step_results.append(step_result)
            if step_result.status not in (TestStatus.PASSED.value, TestStatus.SKIPPED.value):
                case_passed = False
                result.error_message = step_result.error_message
                if step.screenshot_on_fail:
                    ss_filename = f"{case.id}_{device.name}_{start_time.strftime('%H%M%S')}_fail.png"
                    ss_path = self.screenshots_dir / ss_filename
                    result.screenshot_path = self.device_manager.take_screenshot(device.device_id, ss_path)
                    step_result.screenshot_path = result.screenshot_path
                break

        end_time = datetime.now()
        result.start_time = start_time.isoformat()
        result.end_time = end_time.isoformat()
        result.duration_ms = int((end_time - start_time).total_seconds() * 1000)
        if case_passed:
            result.status = TestStatus.PASSED.value
        elif result.error_message and "skip" in result.error_message.lower():
            result.status = TestStatus.SKIPPED.value
        else:
            result.status = TestStatus.FAILED.value
        result.log_path = self.logger.get_log_path() or ""
        return result

    def _execute_step(
        self, idx: int, step: TestStep, device: DeviceConfig, case: TestCase
    ) -> StepResult:
        start_time = datetime.now()
        placeholders = self._resolve_account_placeholders(step, case, device)
        effective_value = self._apply_placeholders(step.value, placeholders)
        effective_target = self._apply_placeholders(step.target, placeholders)
        effective_description = step.description or f"步骤 {idx + 1}"
        if placeholders and effective_value:
            effective_description = f"{effective_description} (值: {effective_value})"
        step_result = StepResult(
            step_index=idx,
            step_type=step.step_type,
            description=effective_description,
            status=TestStatus.RUNNING.value,
        )
        effective_step = TestStep(
            step_type=step.step_type,
            target=effective_target,
            value=effective_value,
            description=effective_description,
            selector=step.selector,
            timeout=step.timeout,
            screenshot_on_fail=step.screenshot_on_fail,
            extra=step.extra,
        )
        handler = self._step_handlers.get(step.step_type)
        try:
            if handler:
                handler(effective_step, device, case)
            else:
                self.logger.warn(f"未知步骤类型: {step.step_type}")
            status = TestStatus.PASSED.value
        except AssertionError as e:
            status = TestStatus.FAILED.value
            step_result.error_message = str(e)
            self.logger.error(f"断言失败: {effective_description} - {e}")
        except Exception as e:
            status = TestStatus.ERROR.value
            step_result.error_message = str(e)
            self.logger.error(f"步骤执行异常: {effective_description} - {e}")

        end_time = datetime.now()
        step_result.start_time = start_time.isoformat()
        step_result.end_time = end_time.isoformat()
        step_result.duration_ms = int((end_time - start_time).total_seconds() * 1000)
        step_result.status = status
        if placeholders:
            for k, v in placeholders.items():
                step_result.logs.append(f"[账号占位符] {k} -> {v}")
        return step_result

    def _handle_click(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        target = step.target or step.selector or "未指定元素"
        self.logger.debug(f"点击: {target}")
        time.sleep(random.uniform(0.1, 0.4))
        self._random_failure("click", step, device)

    def _handle_input(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        target = step.target or step.selector
        value = step.value
        self.logger.debug(f"输入 [{target}]: {value}")
        time.sleep(random.uniform(0.15, 0.5))
        self._random_failure("input", step, device)

    def _handle_swipe(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        self.logger.debug(f"滑动: {step.description}")
        time.sleep(random.uniform(0.2, 0.6))

    def _handle_assert(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        self.logger.debug(f"断言: {step.description} | 期望: {step.value}")
        time.sleep(random.uniform(0.05, 0.2))
        self._random_failure("assert", step, device)
        assert True, step.value

    def _handle_wait(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        wait_ms = step.timeout * 1000
        if step.value:
            try:
                wait_ms = int(step.value)
            except ValueError:
                pass
        self.logger.debug(f"等待: {wait_ms}ms")
        time.sleep(wait_ms / 1000)

    def _handle_screenshot(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        timestamp = datetime.now().strftime("%H%M%S")
        ss_path = self.screenshots_dir / f"manual_{case.id}_{device.name}_{timestamp}.png"
        self.device_manager.take_screenshot(device.device_id, ss_path)

    def _handle_long_press(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        target = step.target or step.selector
        self.logger.debug(f"长按: {target}")
        time.sleep(random.uniform(0.4, 0.8))

    def _handle_back(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        self.logger.debug("返回上一页")
        time.sleep(random.uniform(0.2, 0.4))

    def _handle_home(self, step: TestStep, device: DeviceConfig, case: TestCase) -> None:
        self.logger.debug("回到首页")
        time.sleep(random.uniform(0.3, 0.5))

    def _random_failure(self, action: str, step: TestStep, device: DeviceConfig) -> None:
        fail_rate_map = {
            "iOS": {"click": 0.03, "input": 0.04, "assert": 0.02},
            "Android": {"click": 0.05, "input": 0.06, "assert": 0.03},
        }
        rates = fail_rate_map.get(device.platform, {"click": 0.05, "input": 0.06, "assert": 0.03})
        rate = rates.get(action, 0.05)
        if random.random() < rate:
            error_msg = f"{action} 失败: 元素未找到或超时"
            if step.description:
                error_msg = f"{step.description} - {error_msg}"
            raise AssertionError(error_msg)


class ResultCollector:
    def __init__(self, report_dir: Path):
        self.report_dir = report_dir
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def save_run_result(self, result: TestRunResult) -> Path:
        result_file = self.report_dir / f"result_{result.run_id}.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        return result_file

    def load_run_result(self, file_path: Path) -> TestRunResult:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        case_results = []
        for cr in data.get("case_results", []):
            step_results = [StepResult(**sr) for sr in cr.get("step_results", [])]
            cr_data = {k: v for k, v in cr.items() if k != "step_results"}
            case_results.append(TestCaseResult(**cr_data, step_results=step_results))
        data_clean = {k: v for k, v in data.items() if k != "case_results"}
        return TestRunResult(**data_clean, case_results=case_results)

    def list_result_files(self) -> List[Path]:
        return sorted(self.report_dir.glob("result_*.json"), reverse=True)

    def get_latest_result(self) -> Optional[Path]:
        files = self.list_result_files()
        return files[0] if files else None

    def get_slowest_cases(self, result: TestRunResult, top_n: int = 10) -> List[TestCaseResult]:
        sorted_cases = sorted(
            result.case_results,
            key=lambda c: c.duration_ms,
            reverse=True,
        )
        return sorted_cases[:top_n]

    def get_failed_cases(self, result: TestRunResult) -> List[TestCaseResult]:
        return [
            c for c in result.case_results
            if c.status in (TestStatus.FAILED.value, TestStatus.ERROR.value)
        ]

    def extract_key_logs(self, result: TestRunResult) -> List[Dict[str, Any]]:
        logs = []
        for case in result.case_results:
            if case.status in (TestStatus.FAILED.value, TestStatus.ERROR.value):
                logs.append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "device": case.device_name,
                    "error": case.error_message,
                    "log_path": case.log_path,
                })
                for step in case.step_results:
                    if step.status in (TestStatus.FAILED.value, TestStatus.ERROR.value):
                        logs[-1]["failed_step"] = step.description
                        logs[-1]["step_error"] = step.error_message
        return logs


class ResultComparer:
    @staticmethod
    def compare(
        result_a: TestRunResult,
        result_b: TestRunResult,
    ) -> Dict[str, Any]:
        diff = {
            "version_a": result_a.version,
            "version_b": result_b.version,
            "run_id_a": result_a.run_id,
            "run_id_b": result_b.run_id,
            "metrics_diff": {},
            "case_status_diff": [],
            "performance_diff": [],
            "summary": {},
        }
        for key in ["total_cases", "passed", "failed", "skipped", "errors", "pass_rate", "duration_ms", "device_count"]:
            val_a = getattr(result_a, key, 0)
            val_b = getattr(result_b, key, 0)
            diff["metrics_diff"][key] = {
                "a": val_a,
                "b": val_b,
                "delta": (val_b - val_a) if isinstance(val_a, (int, float)) else None,
            }
        def _compound_key(c):
            return f"{c.case_id}@{c.device_name}"

        cases_a = {_compound_key(c): c for c in result_a.case_results}
        cases_b = {_compound_key(c): c for c in result_b.case_results}
        all_keys = set(cases_a.keys()) | set(cases_b.keys())
        new_cases = []
        removed_cases = []
        status_changed = []
        for key in all_keys:
            ca = cases_a.get(key)
            cb = cases_b.get(key)
            cid, _, device = key.rpartition("@")
            if ca and not cb:
                removed_cases.append({"case_id": cid, "name": ca.case_name, "device": device})
            elif cb and not ca:
                new_cases.append({"case_id": cid, "name": cb.case_name, "device": device})
            elif ca and cb and ca.status != cb.status:
                status_changed.append({
                    "case_id": cid,
                    "name": ca.case_name,
                    "device": device,
                    "status_a": ca.status,
                    "status_b": cb.status,
                })
        diff["case_status_diff"] = status_changed
        diff["summary"]["new_cases"] = len(new_cases)
        diff["summary"]["removed_cases"] = len(removed_cases)
        diff["summary"]["status_changed"] = len(status_changed)
        for key in all_keys:
            ca = cases_a.get(key)
            cb = cases_b.get(key)
            if ca and cb:
                delta = cb.duration_ms - ca.duration_ms
                if abs(delta) >= 1000:
                    cid, _, device = key.rpartition("@")
                    diff["performance_diff"].append({
                        "case_id": cid,
                        "name": ca.case_name,
                        "device": device,
                        "duration_a_ms": ca.duration_ms,
                        "duration_b_ms": cb.duration_ms,
                        "delta_ms": delta,
                        "delta_pct": round((delta / ca.duration_ms) * 100, 2) if ca.duration_ms > 0 else 0,
                    })
        diff["performance_diff"].sort(key=lambda x: abs(x["delta_ms"]), reverse=True)
        return diff
