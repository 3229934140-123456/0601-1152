from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime
import uuid


class StepType(Enum):
    CLICK = "click"
    INPUT = "input"
    SWIPE = "swipe"
    ASSERT = "assert"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    LONG_PRESS = "long_press"
    BACK = "back"
    HOME = "home"


class TestStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    RUNNING = "running"


class RiskLevel(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestCategory(Enum):
    LOGIN = "login"
    ORDER = "order"
    PAYMENT = "payment"
    MESSAGE = "message"
    SETTINGS = "settings"
    SMOKE = "smoke"
    OTHER = "other"


@dataclass
class TestStep:
    step_type: str
    target: str = ""
    value: str = ""
    description: str = ""
    selector: str = ""
    timeout: int = 10
    screenshot_on_fail: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "target": self.target,
            "value": self.value,
            "description": self.description,
            "selector": self.selector,
            "timeout": self.timeout,
            "screenshot_on_fail": self.screenshot_on_fail,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestStep":
        return cls(
            step_type=data.get("step_type", ""),
            target=data.get("target", ""),
            value=data.get("value", ""),
            description=data.get("description", ""),
            selector=data.get("selector", ""),
            timeout=data.get("timeout", 10),
            screenshot_on_fail=data.get("screenshot_on_fail", True),
            extra=data.get("extra", {}),
        )


@dataclass
class TestCase:
    id: str = ""
    name: str = ""
    description: str = ""
    category: str = "smoke"
    risk_level: str = "medium"
    tags: List[str] = field(default_factory=list)
    device_requirements: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    steps: List[TestStep] = field(default_factory=list)
    expected_result: str = ""
    created_at: str = ""
    updated_at: str = ""
    author: str = ""
    priority: int = 0
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = f"TC_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "tags": self.tags,
            "device_requirements": self.device_requirements,
            "prerequisites": self.prerequisites,
            "steps": [s.to_dict() for s in self.steps],
            "expected_result": self.expected_result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author": self.author,
            "priority": self.priority,
            "enabled": self.enabled,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCase":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=data.get("category", "smoke"),
            risk_level=data.get("risk_level", "medium"),
            tags=data.get("tags", []),
            device_requirements=data.get("device_requirements", []),
            prerequisites=data.get("prerequisites", []),
            steps=[TestStep.from_dict(s) for s in data.get("steps", [])],
            expected_result=data.get("expected_result", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            author=data.get("author", ""),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            extra=data.get("extra", {}),
        )

    def add_step(self, step: TestStep) -> None:
        self.steps.append(step)
        self.updated_at = datetime.now().isoformat()


@dataclass
class StepResult:
    step_index: int
    step_type: str
    description: str
    status: str
    start_time: str = ""
    end_time: str = ""
    duration_ms: int = 0
    error_message: str = ""
    screenshot_path: str = ""
    logs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestCaseResult:
    case_id: str
    case_name: str
    category: str
    risk_level: str
    device_name: str
    status: str
    start_time: str = ""
    end_time: str = ""
    duration_ms: int = 0
    retry_count: int = 0
    step_results: List[StepResult] = field(default_factory=list)
    error_message: str = ""
    screenshot_path: str = ""
    log_path: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestRunResult:
    run_id: str
    version: str
    start_time: str
    end_time: str = ""
    duration_ms: int = 0
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    retry_count: int = 0
    only_high_risk: bool = False
    device_count: int = 0
    devices: List[str] = field(default_factory=list)
    case_results: List[TestCaseResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def calculate_metrics(self) -> None:
        self.total_cases = len(self.case_results)
        self.passed = sum(1 for r in self.case_results if r.status == TestStatus.PASSED.value)
        self.failed = sum(1 for r in self.case_results if r.status == TestStatus.FAILED.value)
        self.skipped = sum(1 for r in self.case_results if r.status == TestStatus.SKIPPED.value)
        self.errors = sum(1 for r in self.case_results if r.status == TestStatus.ERROR.value)
        if self.total_cases > 0:
            self.pass_rate = round((self.passed / self.total_cases) * 100, 2)
