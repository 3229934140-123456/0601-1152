import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree

from ..config import ConfigManager, AppTestConfig


console = Console()


@click.command("init")
@click.option("--name", "-n", default="apptest-project", help="项目名称")
@click.option("--force", "-f", is_flag=True, help="强制重新初始化（覆盖已有配置）")
@click.option("--interactive", "-i", is_flag=True, help="交互式配置")
@click.pass_context
def init_cmd(ctx, name, force, interactive):
    """初始化自动化测试项目配置。

    创建默认的 apptest.yaml 配置文件和项目目录结构。
    """
    workdir: Path = ctx.obj["workdir"]
    config_manager = ConfigManager(workdir)

    if config_manager.exists() and not force:
        console.print(Panel(
            "[yellow]检测到已存在的配置文件 apptest.yaml。\n"
            "使用 [bold]--force/-f[/bold] 覆盖，或 [bold]--interactive/-i[/bold] 进入交互式配置。[/yellow]",
            title="⚠️  项目已初始化",
            border_style="yellow",
        ))
        config = config_manager.load()
        _display_config_summary(config, workdir)
        return

    if interactive:
        config = _interactive_init(name, config_manager)
    else:
        config = config_manager.init_default(name)

    console.print(Panel(
        f"[green]项目 [bold]{config.project_name}[/bold] 初始化成功！[/green]\n\n"
        f"📄 配置文件: apptest.yaml\n"
        f"📁 工作目录: {workdir}\n\n"
        f"[dim]下一步:\n"
        f"  1. 编辑 apptest.yaml 配置测试账号和设备\n"
        f"  2. 运行 [bold]apptest record[/bold] 录制测试步骤\n"
        f"  3. 运行 [bold]apptest run[/bold] 执行冒烟测试[/dim]",
        title="✅ 初始化完成",
        border_style="green",
    ))

    _display_config_summary(config, workdir)
    _generate_sample_cases(config_manager, workdir)


def _interactive_init(name: str, config_manager: ConfigManager) -> AppTestConfig:
    console.print(Panel(
        "[cyan]欢迎使用 apptest 交互式配置向导[/cyan]",
        title="🚀 项目初始化向导",
        border_style="cyan",
    ))

    if not name or name == "apptest-project":
        project_name = click.prompt("请输入项目名称", default="apptest-project")
    else:
        project_name = name

    version = click.prompt("请输入被测 App 版本", default="1.0.0")
    retry = click.prompt("默认重试次数", default=2, type=int)
    report_dir = click.prompt("报告输出目录", default="reports")

    config = config_manager.init_default(project_name)
    config.version = version
    config.retry_count = retry
    config.report_dir = report_dir

    if click.confirm("是否配置测试账号？", default=True):
        accounts = []
        while True:
            username = click.prompt("  账号用户名 (输入 q 退出)")
            if username.lower() == "q":
                break
            password = click.prompt("  账号密码", hide_input=True)
            role = click.prompt("  账号角色 (normal/vip/admin)", default="normal")
            description = click.prompt("  账号描述", default="")
            from ..config import TestAccount
            accounts.append(TestAccount(
                username=username,
                password=password,
                role=role,
                description=description,
            ))
            if not click.confirm("  继续添加账号？", default=False):
                break
        if accounts:
            config.accounts = accounts

    if click.confirm("是否配置测试设备？", default=True):
        from ..config import DeviceConfig
        devices = []
        while True:
            console.print("\n  [dim]--- 添加新设备 ---[/dim]")
            device_name = click.prompt("  设备名称 (输入 q 退出)")
            if device_name.lower() == "q":
                break
            platform = click.prompt("  平台 (iOS/Android)", default="Android", type=click.Choice(["iOS", "Android"]))
            device_id = click.prompt("  设备ID (UDID 或 adb 设备号)")
            app_package = click.prompt("  App 包名 (Bundle ID/Package)")
            app_activity = click.prompt("  启动 Activity", default=".MainActivity")
            platform_version = click.prompt("  系统版本", default="")
            is_active = click.confirm("  设为默认启用？", default=True)
            devices.append(DeviceConfig(
                name=device_name,
                platform=platform,
                device_id=device_id,
                app_package=app_package,
                app_activity=app_activity,
                platform_version=platform_version,
                app_version=version,
                is_active=is_active,
            ))
            if not click.confirm("  继续添加设备？", default=False):
                break
        if devices:
            config.devices = devices

    config_manager.save(config)
    return config


def _display_config_summary(config: AppTestConfig, workdir: Path) -> None:
    table = Table(title="📋 当前配置概览", border_style="cyan")
    table.add_column("配置项", style="cyan", no_wrap=True)
    table.add_column("值", style="white")

    table.add_row("项目名称", config.project_name)
    table.add_row("App 版本", config.version)
    table.add_row("重试次数", str(config.retry_count))
    table.add_row("报告目录", config.report_dir)
    table.add_row("用例目录", config.cases_dir)
    table.add_row("截图目录", config.screenshots_dir)
    table.add_row("日志目录", config.logs_dir)
    table.add_row("仅高风险", "✅ 是" if config.only_high_risk else "❌ 否")
    table.add_row("配置标签", ", ".join(config.tags) if config.tags else "无")

    console.print(table)

    if config.accounts:
        acc_table = Table(title="👤 测试账号", border_style="blue")
        acc_table.add_column("#", style="dim")
        acc_table.add_column("用户名", style="bold")
        acc_table.add_column("角色")
        acc_table.add_column("描述")
        for i, acc in enumerate(config.accounts, 1):
            acc_table.add_row(str(i), acc.username, acc.role, acc.description)
        console.print(acc_table)

    if config.devices:
        dev_table = Table(title="📱 测试设备", border_style="magenta")
        dev_table.add_column("#", style="dim")
        dev_table.add_column("名称", style="bold")
        dev_table.add_column("平台")
        dev_table.add_column("设备ID")
        dev_table.add_column("系统版本")
        dev_table.add_column("启用", justify="center")
        for i, dev in enumerate(config.devices, 1):
            dev_table.add_row(
                str(i), dev.name, dev.platform, dev.device_id,
                dev.platform_version or "-",
                "✅" if dev.is_active else "❌",
            )
        console.print(dev_table)

    tree = Tree("[green]📂 项目目录结构[/green]")
    root = tree.add(f"[bold]{workdir.name}/[/bold]")
    root.add("[cyan]apptest.yaml[/cyan]  (配置文件)")
    root.add(f"[blue]{config.cases_dir}/[/blue]  (测试用例)")
    root.add(f"[magenta]{config.report_dir}/[/magenta]  (测试报告)")
    root.add(f"[yellow]{config.screenshots_dir}/[/yellow]  (失败截图)")
    root.add(f"[green]{config.logs_dir}/[/green]  (执行日志)")
    root.add(f"[dim]{config.recordings_dir}/[/dim]  (录制数据)")
    console.print(tree)


def _generate_sample_cases(config_manager: ConfigManager, workdir: Path) -> None:
    from ..models import TestCase, TestStep, TestCategory, RiskLevel
    from ..core import TestCaseLoader

    config = config_manager.load()
    loader = TestCaseLoader(workdir / config.cases_dir)

    samples = [
        TestCase(
            name="用户登录 - 正确凭证",
            description="验证使用正确的用户名密码可以成功登录",
            category=TestCategory.LOGIN.value,
            risk_level=RiskLevel.CRITICAL.value,
            tags=["smoke", "login", "auth"],
            priority=10,
            steps=[
                TestStep(step_type="click", target="我的Tab", description="点击底部我的 Tab", selector="id/tab_profile"),
                TestStep(step_type="click", target="登录按钮", description="点击登录/注册按钮", selector="id/btn_login"),
                TestStep(step_type="input", target="用户名输入框", value="{username}", description="输入用户名", selector="id/et_username"),
                TestStep(step_type="input", target="密码输入框", value="{password}", description="输入密码", selector="id/et_password"),
                TestStep(step_type="click", target="登录提交", description="点击登录按钮提交", selector="id/btn_submit"),
                TestStep(step_type="wait", value="2000", description="等待登录完成"),
                TestStep(step_type="assert", target="用户昵称", value="已登录", description="验证用户昵称已显示", selector="id/tv_nickname"),
            ],
            expected_result="成功登录并显示用户昵称",
            author="qa-team",
        ),
        TestCase(
            name="用户登录 - 错误凭证",
            description="验证使用错误密码时登录失败并提示",
            category=TestCategory.LOGIN.value,
            risk_level=RiskLevel.HIGH.value,
            tags=["login", "auth", "negative"],
            priority=9,
            steps=[
                TestStep(step_type="click", target="我的Tab", description="点击我的 Tab"),
                TestStep(step_type="click", target="登录按钮", description="进入登录页"),
                TestStep(step_type="input", target="用户名", value="test_user_001", description="输入正确用户名"),
                TestStep(step_type="input", target="密码", value="wrong_password", description="输入错误密码"),
                TestStep(step_type="click", target="提交登录", description="点击登录"),
                TestStep(step_type="wait", value="1000"),
                TestStep(step_type="assert", target="错误提示", value="密码错误", description="验证错误提示出现"),
            ],
            expected_result="显示密码错误提示",
            author="qa-team",
        ),
        TestCase(
            name="商品下单流程",
            description="验证从商品浏览到提交订单的完整流程",
            category=TestCategory.ORDER.value,
            risk_level=RiskLevel.CRITICAL.value,
            tags=["smoke", "order", "ecommerce"],
            priority=8,
            prerequisites=["用户已登录"],
            steps=[
                TestStep(step_type="home", description="回到首页"),
                TestStep(step_type="click", target="商品分类", description="点击第一个商品分类", selector="id/category_1"),
                TestStep(step_type="click", target="第一个商品", description="点击列表第一个商品", selector="id/product_item_0"),
                TestStep(step_type="wait", value="1000", description="等待商品详情加载"),
                TestStep(step_type="screenshot", description="截图商品详情页"),
                TestStep(step_type="click", target="加入购物车", description="点击加入购物车", selector="id/btn_add_cart"),
                TestStep(step_type="click", target="购物车", description="进入购物车页面", selector="id/tab_cart"),
                TestStep(step_type="click", target="全选", description="全选商品", selector="id/checkbox_all"),
                TestStep(step_type="click", target="去结算", description="点击结算按钮", selector="id/btn_checkout"),
                TestStep(step_type="assert", target="确认订单页", value="确认订单", description="验证进入确认订单页"),
                TestStep(step_type="click", target="提交订单", description="点击提交订单", selector="id/btn_submit_order"),
                TestStep(step_type="assert", target="订单提交成功", value="支付页面", description="验证进入支付页面"),
            ],
            expected_result="订单提交成功并跳转至支付页",
            author="qa-team",
        ),
        TestCase(
            name="支付模拟 - 微信支付",
            description="模拟微信支付流程验证",
            category=TestCategory.PAYMENT.value,
            risk_level=RiskLevel.CRITICAL.value,
            tags=["smoke", "payment", "wechat"],
            priority=7,
            prerequisites=["有待支付订单"],
            steps=[
                TestStep(step_type="click", target="我的Tab", description="进入我的页面"),
                TestStep(step_type="click", target="我的订单", description="点击我的订单", selector="id/my_orders"),
                TestStep(step_type="click", target="待支付订单", description="点击第一条待支付订单"),
                TestStep(step_type="click", target="立即支付", description="点击立即支付", selector="id/btn_pay"),
                TestStep(step_type="click", target="微信支付", description="选择微信支付方式", selector="id/radio_wechat"),
                TestStep(step_type="click", target="确认支付", description="点击确认支付", selector="id/btn_confirm_pay"),
                TestStep(step_type="wait", value="3000", description="等待支付处理"),
                TestStep(step_type="assert", target="支付成功", value="支付成功", description="验证支付成功提示"),
                TestStep(step_type="screenshot", description="截图支付结果"),
            ],
            expected_result="支付成功并显示支付完成页面",
            author="qa-team",
        ),
        TestCase(
            name="消息中心查看",
            description="验证消息列表和详情页功能",
            category=TestCategory.MESSAGE.value,
            risk_level=RiskLevel.MEDIUM.value,
            tags=["smoke", "message", "notification"],
            priority=5,
            steps=[
                TestStep(step_type="home", description="回到首页"),
                TestStep(step_type="click", target="消息图标", description="点击顶部消息图标", selector="id/iv_message"),
                TestStep(step_type="assert", target="消息中心", value="消息中心", description="验证进入消息中心"),
                TestStep(step_type="wait", value="1000"),
                TestStep(step_type="swipe", target="消息列表", description="向下滑动加载更多"),
                TestStep(step_type="click", target="第一条消息", description="点击第一条系统消息"),
                TestStep(step_type="assert", target="消息详情", value="消息详情", description="验证消息详情显示"),
                TestStep(step_type="back", description="返回消息列表"),
            ],
            expected_result="消息列表和详情页正常显示",
            author="qa-team",
        ),
        TestCase(
            name="设置页面检查",
            description="验证设置页面各入口正常跳转",
            category=TestCategory.SETTINGS.value,
            risk_level=RiskLevel.MEDIUM.value,
            tags=["smoke", "settings"],
            priority=4,
            steps=[
                TestStep(step_type="click", target="我的Tab", description="进入我的页面"),
                TestStep(step_type="click", target="设置图标", description="点击设置齿轮图标", selector="id/iv_settings"),
                TestStep(step_type="assert", target="设置页面", value="设置", description="验证设置页标题"),
                TestStep(step_type="click", target="账号安全", description="点击账号安全", selector="id/item_account_security"),
                TestStep(step_type="screenshot", description="截图账号安全页"),
                TestStep(step_type="back", description="返回设置"),
                TestStep(step_type="click", target="隐私设置", description="点击隐私设置"),
                TestStep(step_type="back", description="返回设置"),
                TestStep(step_type="click", target="关于我们", description="点击关于我们"),
                TestStep(step_type="assert", target="版本号", value="显示正确", description="验证App版本号显示"),
                TestStep(step_type="back", description="返回设置"),
                TestStep(step_type="swipe", target="设置页", description="滑动到底部"),
                TestStep(step_type="click", target="退出登录", description="点击退出登录按钮", selector="id/btn_logout"),
                TestStep(step_type="click", target="确认退出", description="在弹窗点击确认退出"),
            ],
            expected_result="所有设置子页面正常访问，退出登录成功",
            author="qa-team",
        ),
    ]

    console.print(f"\n[dim]💡 正在生成 {len(samples)} 个示例冒烟用例...[/dim]")
    for case in samples:
        path = loader.save_case(case)
        console.print(f"  [green]✓[/green] 生成: {path.name}")
