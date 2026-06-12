import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


DEFAULT_CONFIG_NAME = "apptest.yaml"
DEFAULT_CASES_DIR = "testcases"
DEFAULT_REPORTS_DIR = "reports"
DEFAULT_SCREENSHOTS_DIR = "screenshots"
DEFAULT_LOGS_DIR = "logs"
DEFAULT_RECORDINGS_DIR = "recordings"


@dataclass
class TestAccount:
    username: str
    password: str
    role: str = "user"
    description: str = ""


@dataclass
class DeviceConfig:
    name: str
    platform: str
    device_id: str
    app_package: str
    app_activity: str
    platform_version: str = ""
    app_version: str = ""
    is_active: bool = True
    capabilities: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskLevel:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AppTestConfig:
    project_name: str = "apptest-project"
    version: str = "1.0.0"
    retry_count: int = 2
    report_dir: str = DEFAULT_REPORTS_DIR
    screenshots_dir: str = DEFAULT_SCREENSHOTS_DIR
    logs_dir: str = DEFAULT_LOGS_DIR
    cases_dir: str = DEFAULT_CASES_DIR
    recordings_dir: str = DEFAULT_RECORDINGS_DIR
    only_high_risk: bool = False
    tags: List[str] = field(default_factory=list)
    accounts: List[TestAccount] = field(default_factory=list)
    devices: List[DeviceConfig] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "version": self.version,
            "retry_count": self.retry_count,
            "report_dir": self.report_dir,
            "screenshots_dir": self.screenshots_dir,
            "logs_dir": self.logs_dir,
            "cases_dir": self.cases_dir,
            "recordings_dir": self.recordings_dir,
            "only_high_risk": self.only_high_risk,
            "tags": self.tags,
            "accounts": [asdict(a) for a in self.accounts],
            "devices": [asdict(d) for d in self.devices],
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppTestConfig":
        accounts = [
            TestAccount(**a) for a in data.get("accounts", [])
        ]
        devices = [
            DeviceConfig(**d) for d in data.get("devices", [])
        ]
        return cls(
            project_name=data.get("project_name", "apptest-project"),
            version=data.get("version", "1.0.0"),
            retry_count=data.get("retry_count", 2),
            report_dir=data.get("report_dir", DEFAULT_REPORTS_DIR),
            screenshots_dir=data.get("screenshots_dir", DEFAULT_SCREENSHOTS_DIR),
            logs_dir=data.get("logs_dir", DEFAULT_LOGS_DIR),
            cases_dir=data.get("cases_dir", DEFAULT_CASES_DIR),
            recordings_dir=data.get("recordings_dir", DEFAULT_RECORDINGS_DIR),
            only_high_risk=data.get("only_high_risk", False),
            tags=data.get("tags", []),
            accounts=accounts,
            devices=devices,
            extra=data.get("extra", {}),
        )


class ConfigManager:
    def __init__(self, workdir: Optional[Path] = None):
        self.workdir = workdir or Path.cwd()
        self.config_path = self.workdir / DEFAULT_CONFIG_NAME

    def exists(self) -> bool:
        return self.config_path.exists()

    def load(self) -> AppTestConfig:
        if not self.exists():
            return AppTestConfig()
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return AppTestConfig.from_dict(data)

    def save(self, config: AppTestConfig) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config.to_dict(), f, allow_unicode=True, default_flow_style=False)

    def init_default(self, project_name: str = "apptest-project") -> AppTestConfig:
        default_accounts = [
            TestAccount(
                username="test_user_001",
                password="password123",
                role="normal",
                description="普通测试账号"
            ),
            TestAccount(
                username="test_vip_001",
                password="password123",
                role="vip",
                description="VIP 测试账号"
            ),
            TestAccount(
                username="admin",
                password="admin123",
                role="admin",
                description="管理员测试账号"
            ),
        ]
        default_devices = [
            DeviceConfig(
                name="iPhone-15-Pro",
                platform="iOS",
                device_id="00008110-0012345ABCDEF",
                app_package="com.example.app",
                app_activity="MainActivity",
                platform_version="17.0",
                app_version="2.5.0",
                is_active=True,
                capabilities={"automationName": "XCUITest", "noReset": True}
            ),
            DeviceConfig(
                name="Pixel-8-Pro",
                platform="Android",
                device_id="emulator-5554",
                app_package="com.example.app",
                app_activity=".MainActivity",
                platform_version="14",
                app_version="2.5.0",
                is_active=True,
                capabilities={"automationName": "UiAutomator2", "noReset": True}
            ),
        ]
        config = AppTestConfig(
            project_name=project_name,
            accounts=default_accounts,
            devices=default_devices,
            tags=["smoke", "critical", "order", "payment", "message", "settings"],
        )
        self._create_dirs(config)
        self.save(config)
        return config

    def _create_dirs(self, config: AppTestConfig) -> None:
        dirs = [
            self.workdir / config.cases_dir,
            self.workdir / config.report_dir,
            self.workdir / config.screenshots_dir,
            self.workdir / config.logs_dir,
            self.workdir / config.recordings_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def add_account(self, account: TestAccount) -> None:
        config = self.load()
        config.accounts.append(account)
        self.save(config)

    def add_device(self, device: DeviceConfig) -> None:
        config = self.load()
        config.devices.append(device)
        self.save(config)

    def get_active_devices(self) -> List[DeviceConfig]:
        config = self.load()
        return [d for d in config.devices if d.is_active]

    def get_accounts_by_role(self, role: str) -> List[TestAccount]:
        config = self.load()
        return [a for a in config.accounts if a.role == role]
