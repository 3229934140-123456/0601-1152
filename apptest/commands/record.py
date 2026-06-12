import click
import json
import yaml
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from typing import List, Optional

from ..config import ConfigManager, TestAccount, DeviceConfig
from ..models import TestCase, TestStep, TestCategory, RiskLevel
from ..core import TestCaseLoader


console = Console()

STEP_TYPES = [
    ("click", "点击元素"),
    ("input", "输入文本"),
    ("swipe", "滑动屏幕"),
    ("assert", "断言验证"),
    ("wait", "等待"),
    ("screenshot", "截图"),
    ("long_press", "长按"),
    ("back", "返回"),
    ("home", "回到首页"),
]

CATEGORIES = [
    ("login", "登录认证"),
    ("order", "下单流程"),
    ("payment", "支付模拟"),
    ("message", "消息查看"),
    ("settings", "设置检查"),
    ("smoke", "冒烟测试"),
    ("other", "其他"),
]

RISK_LEVELS = [
    ("critical", "严重"),
    ("high", "高"),
    ("medium", "中"),
    ("low", "低"),
]


@click.command("record")
@click.option("--list", "-l", "list_mode", is_flag=True, help="列出已录制的用例")
@click.option("--edit", "-e", "edit_case", metavar="CASE_ID", help="编辑指定用例ID")
@click.option("--accounts", "-a", "manage_accounts", is_flag=True, help="管理测试账号")
@click.option("--devices", "-d", "manage_devices", is_flag=True, help="管理测试设备")
@click.option("--template", "-t", type=click.Choice(["login", "order", "payment", "message", "settings"]), help="基于模板快速创建")
@click.pass_context
def record_cmd(ctx, list_mode, edit_case, manage_accounts, manage_devices, template):
    """录制测试步骤、配置测试账号/设备、管理测试用例。

    交互式地创建和编辑测试用例，支持点击、输入、滑动、断言等步骤类型。
    """
    workdir: Path = ctx.obj["workdir"]
    config_manager = ConfigManager(workdir)

    if not config_manager.exists():
        console.print("[red]错误: 项目未初始化，请先运行 [bold]apptest init[/bold][/red]")
        return

    config = config_manager.load()
    loader = TestCaseLoader(workdir / config.cases_dir)
    recordings_dir = workdir / config.recordings_dir
    recordings_dir.mkdir(parents=True, exist_ok=True)

    if manage_accounts:
        _manage_accounts(config_manager)
        return
    if manage_devices:
        _manage_devices(config_manager)
        return
    if list_mode:
        _list_cases(loader)
        return
    if edit_case:
        _edit_case(loader, edit_case, config_manager)
        return

    console.print(Panel(
        "[cyan]测试用例录制模式[/cyan]\n"
        "按照提示填写用例信息和步骤，完成后自动保存为 YAML 文件。",
        title="🎬 用例录制器",
        border_style="cyan",
    ))

    if template:
        case = _create_from_template(template, config)
    else:
        case = _interactive_record(config)

    saved_path = loader.save_case(case)
    _save_recording_session(case, recordings_dir)

    console.print(Panel(
        f"[green]用例录制完成并保存！[/green]\n\n"
        f"📄 用例ID: {case.id}\n"
        f"📝 用例名称: {case.name}\n"
        f"📂 分类: {case.category}\n"
        f"⚠️  风险等级: {case.risk_level}\n"
        f"🔢 步骤数: {len(case.steps)}\n"
        f"💾 保存路径: {saved_path.relative_to(workdir)}\n\n"
        f"[dim]编辑用例: apptest record --edit {case.id}\n"
        f"执行用例: apptest run --tags {','.join(case.tags[:2]) if case.tags else 'smoke'}[/dim]",
        title="✅ 录制成功",
        border_style="green",
    ))


def _interactive_record(config) -> TestCase:
    console.print("\n[bold cyan]--- 步骤 1: 基本信息 ---[/bold cyan]")
    name = click.prompt("用例名称", default="冒烟测试用例")
    description = click.prompt("用例描述", default="")
    category = _select_from_list("用例分类", CATEGORIES, default_index=5)
    risk_level = _select_from_list("风险等级", RISK_LEVELS, default_index=2)

    console.print("\n[bold cyan]--- 步骤 2: 标签配置 ---[/bold cyan]")
    default_tags = config.tags or ["smoke"]
    console.print(f"[dim]可用标签: {', '.join(default_tags)}[/dim]")
    tags_input = click.prompt("输入用例标签（逗号分隔）", default="smoke")
    tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    priority = click.prompt("优先级（数字越大越优先）", default=5, type=int)
    author = click.prompt("作者", default="qa-team")

    prerequisites = []
    if Confirm.ask("是否添加前置条件？", default=False):
        while True:
            prereq = click.prompt("  输入前置条件 (空行结束)", default="")
            if not prereq:
                break
            prerequisites.append(prereq)

    device_req = []
    active_devices = [d for d in config.devices if d.is_active]
    if active_devices and Confirm.ask("是否限定运行设备？", default=False):
        for d in active_devices:
            if Confirm.ask(f"  包含设备 {d.name} ({d.platform})？", default=True):
                device_req.append(d.name)

    console.print("\n[bold cyan]--- 步骤 3: 录制测试步骤 ---[/bold cyan]")
    console.print("[dim]支持的步骤类型:[/dim]")
    for idx, (stype, sdesc) in enumerate(STEP_TYPES, 1):
        console.print(f"  {idx}. [cyan]{stype}[/cyan] - {sdesc}")
    console.print("")

    steps: List[TestStep] = []
    step_num = 1
    while True:
        console.print(f"\n[bold]步骤 {step_num}[/bold] (输入 q 完成录制)")

        stype_idx = click.prompt("  选择步骤类型编号", default="1")
        if stype_idx.lower() == "q":
            break
        try:
            idx = int(stype_idx) - 1
            if idx < 0 or idx >= len(STEP_TYPES):
                console.print("[yellow]  无效编号，使用默认 (1 - click)[/yellow]")
                idx = 0
        except ValueError:
            console.print("[yellow]  输入无效，使用默认 (1 - click)[/yellow]")
            idx = 0

        step_type, _ = STEP_TYPES[idx]
        description = click.prompt("  步骤描述", default=f"执行{step_type}操作")
        target = click.prompt("  目标元素名称", default="")
        selector = click.prompt("  元素选择器 (id/xpath等)", default="")

        value = ""
        if step_type in ("input", "wait", "assert"):
            if step_type == "input":
                value = click.prompt("  输入值", default="")
            elif step_type == "wait":
                value = click.prompt("  等待毫秒数", default="1000")
            elif step_type == "assert":
                value = click.prompt("  断言期望值", default="显示正确")

        timeout = click.prompt("  超时时间(秒)", default=10, type=int)
        screenshot_on_fail = Confirm.ask("  失败时自动截图？", default=True)

        steps.append(TestStep(
            step_type=step_type,
            target=target,
            value=value,
            description=description,
            selector=selector,
            timeout=timeout,
            screenshot_on_fail=screenshot_on_fail,
        ))
        step_num += 1

        if not Confirm.ask("继续添加步骤？", default=True):
            break

    expected_result = click.prompt("\n期望结果", default="步骤全部执行成功")

    return TestCase(
        name=name,
        description=description,
        category=category,
        risk_level=risk_level,
        tags=tags,
        device_requirements=device_req,
        prerequisites=prerequisites,
        steps=steps,
        expected_result=expected_result,
        author=author,
        priority=priority,
    )


def _create_from_template(template_type: str, config) -> TestCase:
    console.print(f"[cyan]正在基于模板创建用例: {template_type}[/cyan]")

    templates = {
        "login": {
            "name": "用户登录冒烟测试",
            "description": "验证登录流程正常工作",
            "category": TestCategory.LOGIN.value,
            "risk_level": RiskLevel.CRITICAL.value,
            "tags": ["smoke", "login", "auth"],
            "priority": 10,
            "steps": [
                ("click", "我的Tab", "id/tab_profile", "", "点击底部我的 Tab"),
                ("click", "登录按钮", "id/btn_login", "", "进入登录页面"),
                ("input", "用户名输入框", "id/et_username", "{username}", "输入测试账号"),
                ("input", "密码输入框", "id/et_password", "{password}", "输入测试密码"),
                ("click", "登录提交", "id/btn_submit", "", "点击登录按钮"),
                ("wait", "", "", "2000", "等待登录处理完成"),
                ("assert", "用户昵称", "id/tv_nickname", "已登录", "验证登录成功"),
                ("screenshot", "", "", "", "登录完成截图"),
            ],
            "expected_result": "成功登录，用户昵称正确显示",
        },
        "order": {
            "name": "商品下单冒烟测试",
            "description": "验证商品浏览到提交订单流程",
            "category": TestCategory.ORDER.value,
            "risk_level": RiskLevel.CRITICAL.value,
            "tags": ["smoke", "order", "ecommerce"],
            "priority": 9,
            "prerequisites": ["用户已登录"],
            "steps": [
                ("home", "", "", "", "回到首页"),
                ("click", "商品分类", "id/category_hot", "", "进入热门分类"),
                ("click", "第一个商品", "id/product_0", "", "进入商品详情"),
                ("wait", "", "", "1500", "等待加载"),
                ("click", "加入购物车", "id/btn_cart", "", "加入购物车"),
                ("click", "购物车Tab", "id/tab_cart", "", "进入购物车"),
                ("click", "全选", "id/select_all", "", "全选商品"),
                ("click", "去结算", "id/btn_checkout", "", "点击结算"),
                ("assert", "确认订单页", "id/title_confirm", "确认订单", "进入确认订单页"),
                ("click", "提交订单", "id/btn_submit_order", "", "提交订单"),
                ("assert", "跳转支付", "id/title_pay", "支付页面", "进入支付页面"),
            ],
            "expected_result": "订单提交成功，正常跳转支付页",
        },
        "payment": {
            "name": "支付模拟冒烟测试",
            "description": "模拟多种支付方式流程",
            "category": TestCategory.PAYMENT.value,
            "risk_level": RiskLevel.CRITICAL.value,
            "tags": ["smoke", "payment"],
            "priority": 8,
            "prerequisites": ["有待支付的订单"],
            "steps": [
                ("click", "我的Tab", "id/tab_profile", "", "进入我的页面"),
                ("click", "我的订单", "id/my_orders", "", "进入订单列表"),
                ("click", "待支付订单", "id/order_pending_0", "", "打开待支付订单"),
                ("click", "立即支付", "id/btn_pay", "", "点击立即支付"),
                ("click", "选择微信支付", "id/pay_wechat", "", "选择微信支付"),
                ("screenshot", "", "", "", "支付前截图"),
                ("click", "确认支付", "id/btn_confirm_pay", "", "确认支付"),
                ("wait", "", "", "3000", "等待支付处理"),
                ("assert", "支付成功", "id/pay_success", "支付成功", "验证支付成功页"),
                ("screenshot", "", "", "", "支付结果截图"),
            ],
            "expected_result": "支付成功，订单状态变更为已支付",
        },
        "message": {
            "name": "消息中心冒烟测试",
            "description": "验证消息列表和详情查看功能",
            "category": TestCategory.MESSAGE.value,
            "risk_level": RiskLevel.MEDIUM.value,
            "tags": ["smoke", "message"],
            "priority": 5,
            "steps": [
                ("home", "", "", "", "回到首页"),
                ("click", "消息入口", "id/btn_message", "", "点击消息图标"),
                ("assert", "消息中心", "id/msg_center_title", "消息中心", "进入消息中心"),
                ("wait", "", "", "1000", "等待消息加载"),
                ("swipe", "消息列表", "", "", "向下滑动加载更多"),
                ("click", "第一条消息", "id/msg_item_0", "", "打开第一条消息"),
                ("assert", "消息详情", "id/msg_detail_title", "显示", "验证消息详情内容"),
                ("back", "", "", "", "返回消息列表"),
                ("screenshot", "", "", "", "消息中心截图"),
            ],
            "expected_result": "消息列表正常加载，详情可正常查看",
        },
        "settings": {
            "name": "设置页面冒烟测试",
            "description": "验证设置各入口跳转及退出登录",
            "category": TestCategory.SETTINGS.value,
            "risk_level": RiskLevel.MEDIUM.value,
            "tags": ["smoke", "settings"],
            "priority": 4,
            "steps": [
                ("click", "我的Tab", "id/tab_profile", "", "进入我的页面"),
                ("click", "设置图标", "id/btn_settings", "", "进入设置页"),
                ("assert", "设置页面", "id/settings_title", "设置", "验证设置页标题"),
                ("click", "账号安全", "id/item_security", "", "进入账号安全"),
                ("screenshot", "", "", "", "账号安全页截图"),
                ("back", "", "", "", "返回设置"),
                ("click", "隐私设置", "id/item_privacy", "", "进入隐私设置"),
                ("back", "", "", "", "返回设置"),
                ("click", "关于我们", "id/item_about", "", "进入关于我们"),
                ("assert", "App版本", "id/app_version", "显示", "验证App版本号"),
                ("back", "", "", "", "返回设置"),
                ("swipe", "设置页面", "", "", "滑动到底部"),
                ("click", "退出登录", "id/btn_logout", "", "点击退出登录"),
                ("click", "确认退出", "id/dialog_confirm", "", "确认退出弹窗"),
                ("assert", "退出成功", "id/btn_login", "显示登录按钮", "验证已退出登录"),
            ],
            "expected_result": "所有设置入口可正常访问，退出登录成功",
        },
    }

    tpl = templates.get(template_type)
    if not tpl:
        console.print(f"[red]未知模板: {template_type}[/red]")
        return _interactive_record(config)

    steps = [
        TestStep(
            step_type=st,
            target=target,
            selector=selector,
            value=val,
            description=desc,
        )
        for (st, target, selector, val, desc) in tpl["steps"]
    ]

    console.print(f"[dim]  已添加 {len(steps)} 个默认步骤，可选择进一步编辑[/dim]")
    if Confirm.ask("是否在模板基础上编辑步骤？", default=False):
        steps = _edit_steps_interactive(steps)

    custom_name = click.prompt("确认用例名称", default=tpl["name"])

    return TestCase(
        name=custom_name,
        description=tpl["description"],
        category=tpl["category"],
        risk_level=tpl["risk_level"],
        tags=tpl["tags"],
        prerequisites=tpl.get("prerequisites", []),
        steps=steps,
        expected_result=tpl["expected_result"],
        priority=tpl["priority"],
        author="qa-team",
    )


def _edit_steps_interactive(steps: List[TestStep]) -> List[TestStep]:
    while True:
        console.print("\n当前步骤列表:")
        for i, s in enumerate(steps, 1):
            status_icon = "✅"
            console.print(f"  {i}. [{s.step_type}] {s.description}")
        console.print("\n操作: [a]添加  [d]删除  [m]修改  [q]完成")
        action = click.prompt("选择操作", default="q").lower()
        if action == "q":
            break
        elif action == "a":
            step_type = click.prompt("步骤类型", default="click")
            description = click.prompt("步骤描述", default="")
            target = click.prompt("目标元素", default="")
            value = click.prompt("值", default="")
            steps.append(TestStep(step_type=step_type, target=target, value=value, description=description))
        elif action == "d":
            idx = click.prompt("删除步骤编号", type=int)
            if 1 <= idx <= len(steps):
                steps.pop(idx - 1)
                console.print(f"[green]已删除步骤 {idx}[/green]")
        elif action == "m":
            idx = click.prompt("修改步骤编号", type=int)
            if 1 <= idx <= len(steps):
                s = steps[idx - 1]
                s.description = click.prompt("新描述", default=s.description)
                s.target = click.prompt("新目标", default=s.target)
                s.value = click.prompt("新值", default=s.value)
    return steps


def _manage_accounts(config_manager: ConfigManager) -> None:
    while True:
        config = config_manager.load()
        console.print("\n[bold]=== 测试账号管理 ===[/bold]")
        if config.accounts:
            table = Table()
            table.add_column("#", style="dim")
            table.add_column("用户名", style="bold")
            table.add_column("密码", style="dim")
            table.add_column("角色")
            table.add_column("描述")
            for i, a in enumerate(config.accounts, 1):
                table.add_row(str(i), a.username, a.password, a.role, a.description)
            console.print(table)
        else:
            console.print("[dim]暂无账号配置[/dim]")

        console.print("\n操作: [a]添加  [d]删除  [e]编辑  [q]退出")
        action = click.prompt("选择操作", default="q").lower()
        if action == "q":
            break
        elif action == "a":
            username = click.prompt("用户名")
            password = click.prompt("密码")
            role = click.prompt("角色", default="normal")
            description = click.prompt("描述", default="")
            config.accounts.append(TestAccount(
                username=username, password=password, role=role, description=description
            ))
            config_manager.save(config)
            console.print("[green]账号已添加[/green]")
        elif action == "d":
            idx = click.prompt("删除账号编号", type=int)
            if 1 <= idx <= len(config.accounts):
                removed = config.accounts.pop(idx - 1)
                config_manager.save(config)
                console.print(f"[green]已删除账号: {removed.username}[/green]")
        elif action == "e":
            idx = click.prompt("编辑账号编号", type=int)
            if 1 <= idx <= len(config.accounts):
                a = config.accounts[idx - 1]
                a.username = click.prompt("用户名", default=a.username)
                a.password = click.prompt("密码", default=a.password)
                a.role = click.prompt("角色", default=a.role)
                a.description = click.prompt("描述", default=a.description)
                config_manager.save(config)
                console.print("[green]账号已更新[/green]")


def _manage_devices(config_manager: ConfigManager) -> None:
    while True:
        config = config_manager.load()
        console.print("\n[bold]=== 测试设备管理 ===[/bold]")
        if config.devices:
            table = Table()
            table.add_column("#", style="dim")
            table.add_column("名称", style="bold")
            table.add_column("平台")
            table.add_column("设备ID")
            table.add_column("包名")
            table.add_column("Activity")
            table.add_column("启用")
            for i, d in enumerate(config.devices, 1):
                table.add_row(
                    str(i), d.name, d.platform, d.device_id,
                    d.app_package, d.app_activity,
                    "✅" if d.is_active else "❌",
                )
            console.print(table)
        else:
            console.print("[dim]暂无设备配置[/dim]")

        console.print("\n操作: [a]添加  [d]删除  [e]编辑  [t]切换启用  [q]退出")
        action = click.prompt("选择操作", default="q").lower()
        if action == "q":
            break
        elif action == "a":
            name = click.prompt("设备名称")
            platform = click.prompt("平台 (iOS/Android)", default="Android")
            device_id = click.prompt("设备ID")
            app_package = click.prompt("App 包名", default=config.devices[0].app_package if config.devices else "com.example.app")
            app_activity = click.prompt("启动 Activity", default=".MainActivity")
            platform_version = click.prompt("系统版本", default="")
            config.devices.append(DeviceConfig(
                name=name, platform=platform, device_id=device_id,
                app_package=app_package, app_activity=app_activity,
                platform_version=platform_version, app_version=config.version,
                is_active=True,
            ))
            config_manager.save(config)
            console.print("[green]设备已添加[/green]")
        elif action == "d":
            idx = click.prompt("删除设备编号", type=int)
            if 1 <= idx <= len(config.devices):
                removed = config.devices.pop(idx - 1)
                config_manager.save(config)
                console.print(f"[green]已删除设备: {removed.name}[/green]")
        elif action == "e":
            idx = click.prompt("编辑设备编号", type=int)
            if 1 <= idx <= len(config.devices):
                d = config.devices[idx - 1]
                d.name = click.prompt("名称", default=d.name)
                d.platform = click.prompt("平台", default=d.platform)
                d.device_id = click.prompt("设备ID", default=d.device_id)
                d.app_package = click.prompt("包名", default=d.app_package)
                d.app_activity = click.prompt("Activity", default=d.app_activity)
                d.platform_version = click.prompt("系统版本", default=d.platform_version)
                config_manager.save(config)
                console.print("[green]设备已更新[/green]")
        elif action == "t":
            idx = click.prompt("切换启用编号", type=int)
            if 1 <= idx <= len(config.devices):
                config.devices[idx - 1].is_active = not config.devices[idx - 1].is_active
                config_manager.save(config)
                console.print(f"[green]设备状态已切换: {config.devices[idx-1].name} -> {config.devices[idx-1].is_active}[/green]")


def _list_cases(loader: TestCaseLoader) -> None:
    cases = loader.load_all_cases()
    if not cases:
        console.print("[dim]暂无录制的测试用例，请使用 [bold]apptest record[/bold] 创建[/dim]")
        return

    table = Table(title=f"📋 测试用例列表 (共 {len(cases)} 个)", border_style="cyan")
    table.add_column("ID", style="bold")
    table.add_column("名称")
    table.add_column("分类")
    table.add_column("风险")
    table.add_column("标签")
    table.add_column("步骤数")
    table.add_column("优先级")
    table.add_column("启用")

    for c in cases:
        table.add_row(
            c.id, c.name, c.category, c.risk_level,
            ", ".join(c.tags[:3]), str(len(c.steps)),
            str(c.priority), "✅" if c.enabled else "❌",
        )
    console.print(table)

    console.print(f"\n[dim]编辑用例: apptest record --edit <CASE_ID>\n删除文件: 删除 cases 目录下对应 YAML 文件[/dim]")


def _edit_case(loader: TestCaseLoader, case_id: str, config_manager: ConfigManager) -> None:
    cases = loader.load_all_cases()
    target = None
    for c in cases:
        if c.id == case_id or case_id in c.id:
            target = c
            break
    if not target:
        console.print(f"[red]未找到用例: {case_id}[/red]")
        return

    console.print(Panel(f"[cyan]编辑用例: {target.name}[/cyan]\n[dim]按回车保留原值[/dim]", title="✏️  用例编辑", border_style="cyan"))
    target.name = click.prompt("用例名称", default=target.name)
    target.description = click.prompt("描述", default=target.description)
    target.category = _select_from_list("分类", CATEGORIES, default_value=target.category)
    target.risk_level = _select_from_list("风险等级", RISK_LEVELS, default_value=target.risk_level)
    tags_input = click.prompt("标签 (逗号分隔)", default=",".join(target.tags))
    target.tags = [t.strip() for t in tags_input.split(",") if t.strip()]
    target.priority = click.prompt("优先级", default=target.priority, type=int)
    target.enabled = Confirm.ask("是否启用该用例？", default=target.enabled)

    if Confirm.ask("是否编辑步骤？", default=False):
        target.steps = _edit_steps_interactive(target.steps)

    target.updated_at = datetime.now().isoformat()
    loader.save_case(target)
    console.print(f"[green]✓ 用例已更新: {target.id}[/green]")


def _save_recording_session(case: TestCase, recordings_dir: Path) -> None:
    session = {
        "recorded_at": datetime.now().isoformat(),
        "case_id": case.id,
        "case_name": case.name,
        "steps_count": len(case.steps),
    }
    session_file = recordings_dir / f"session_{case.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def _select_from_list(title: str, options: List[tuple], default_index: int = 0, default_value: Optional[str] = None) -> str:
    if default_value:
        for i, (val, _) in enumerate(options):
            if val == default_value:
                default_index = i
                break
    console.print(f"\n[bold]{title}:[/bold]")
    for i, (val, desc) in enumerate(options, 1):
        mark = "  "
        if i - 1 == default_index:
            mark = "🔸"
        console.print(f"  {mark}{i}. [cyan]{val}[/cyan] - {desc}")
    choice = click.prompt(f"  选择编号 (默认 {default_index + 1})", default=str(default_index + 1))
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
    except ValueError:
        pass
    return options[default_index][0]
