import click
import uuid
import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import List, Optional

from ..config import ConfigManager
from ..models import TestCase, TestStatus, RiskLevel, TestCategory
from ..core import (
    TestCaseLoader,
    DeviceManager,
    TestExecutor,
    ResultCollector,
    Logger,
)


console = Console()


@click.command("run")
@click.option("--retry", "-r", type=int, default=None, help="失败重试次数（覆盖配置文件）")
@click.option("--report-dir", "report_dir", type=click.Path(), default=None, help="报告输出目录（覆盖配置文件）")
@click.option("--tags", "-t", "tags_str", default=None, help="用例标签过滤，逗号分隔（如 smoke,login）")
@click.option("--category", "-c", "categories_str", default=None, help="用例分类过滤，逗号分隔（login,order,payment,message,settings）")
@click.option("--risk", "risk_str", default=None, help="风险等级过滤，逗号分隔（critical,high,medium,low）")
@click.option("--high-risk", "only_high_risk", is_flag=True, help="只执行高风险用例（critical + high）")
@click.option("--device", "-d", "device_name", default=None, help="指定运行设备名称")
@click.option("--case-id", "case_ids_str", default=None, help="指定用例ID执行，逗号分隔")
@click.option("--dry-run", is_flag=True, help="仅展示将要执行的用例，不实际执行")
@click.option("--version", "-v", "app_version", default=None, help="被测App版本号")
@click.option("--no-report", is_flag=True, help="执行后不自动生成报告")
@click.pass_context
def run_cmd(
    ctx,
    retry,
    report_dir,
    tags_str,
    categories_str,
    risk_str,
    only_high_risk,
    device_name,
    case_ids_str,
    dry_run,
    app_version,
    no_report,
):
    """批量执行测试用例（登录、下单、支付、消息、设置等冒烟检查）。

    支持参数指定重试次数、报告目录、标签过滤和只跑高风险用例。
    """
    workdir: Path = ctx.obj["workdir"]
    config_manager = ConfigManager(workdir)

    if not config_manager.exists():
        console.print("[red]错误: 项目未初始化，请先运行 [bold]apptest init[/bold][/red]")
        return

    config = config_manager.load()

    _retry = retry if retry is not None else config.retry_count
    _only_high_risk = only_high_risk or config.only_high_risk
    _report_dir = Path(report_dir) if report_dir else workdir / config.report_dir
    _screenshots_dir = workdir / config.screenshots_dir
    _logs_dir = workdir / config.logs_dir
    _version = app_version or config.version

    tags: List[str] = []
    if tags_str:
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    elif config.tags:
        tags = config.tags

    categories: List[str] = []
    if categories_str:
        categories = [c.strip() for c in categories_str.split(",") if c.strip()]

    risk_levels: List[str] = []
    if risk_str:
        risk_levels = [r.strip() for r in risk_str.split(",") if r.strip()]

    specified_case_ids: List[str] = []
    if case_ids_str:
        specified_case_ids = [c.strip() for c in case_ids_str.split(",") if c.strip()]

    console.print(Panel(
        f"[cyan]准备执行冒烟测试[/cyan]\n\n"
        f"📌 App 版本: {_version}\n"
        f"🔁 重试次数: {_retry}\n"
        f"🏷️  标签过滤: {', '.join(tags) if tags else '全部'}\n"
        f"📂 分类过滤: {', '.join(categories) if categories else '全部'}\n"
        f"⚠️  风险等级: {', '.join(risk_levels) if risk_levels else ('仅高风险' if _only_high_risk else '全部')}\n"
        f"📱 指定设备: {device_name or '全部启用设备'}\n"
        f"📝 指定用例: {', '.join(specified_case_ids) if specified_case_ids else '全部'}\n"
        f"📂 报告目录: {_report_dir}",
        title="🚀 测试执行",
        border_style="cyan",
    ))

    loader = TestCaseLoader(workdir / config.cases_dir)
    all_cases = loader.load_all_cases()
    if not all_cases:
        console.print("[red]错误: 未找到任何测试用例，请先运行 [bold]apptest record[/bold] 创建[/red]")
        return

    if specified_case_ids:
        filtered_cases = [c for c in all_cases if c.id in specified_case_ids]
        if not filtered_cases:
            console.print(f"[yellow]警告: 指定的用例ID未找到: {specified_case_ids}[/yellow]")
            return
    else:
        filtered_cases = loader.filter_cases(
            all_cases,
            tags=tags if tags else None,
            categories=categories if categories else None,
            risk_levels=risk_levels if risk_levels else None,
            only_high_risk=_only_high_risk,
        )

    if device_name:
        target_devices = [d for d in config.devices if d.name == device_name and d.is_active]
        if not target_devices:
            console.print(f"[red]错误: 未找到启用的设备 '{device_name}'[/red]")
            return
    else:
        target_devices = [d for d in config.devices if d.is_active]

    if not target_devices:
        console.print("[red]错误: 没有启用的测试设备，请在 apptest.yaml 中配置或使用 --device 指定[/red]")
        return

    if not filtered_cases:
        console.print("[yellow]提示: 根据过滤条件未匹配到任何用例[/yellow]")
        return

    total_executions = len(filtered_cases) * len(target_devices)
    console.print(f"\n[green]匹配到 {len(filtered_cases)} 个用例，{len(target_devices)} 台设备，共 {total_executions} 次执行[/green]")

    preview_table = Table(title="📋 待执行用例预览", border_style="blue", show_lines=False)
    preview_table.add_column("ID", style="dim")
    preview_table.add_column("用例名称", style="bold")
    preview_table.add_column("分类")
    preview_table.add_column("风险")
    preview_table.add_column("标签")
    preview_table.add_column("步骤", justify="right")
    preview_table.add_column("优先级", justify="right")
    for c in filtered_cases[:20]:
        preview_table.add_row(
            c.id, c.name, c.category, c.risk_level,
            ", ".join(c.tags[:3]), str(len(c.steps)), str(c.priority),
        )
    if len(filtered_cases) > 20:
        preview_table.add_row("...", f"... 还有 {len(filtered_cases) - 20} 个用例", "", "", "", "", "")
    console.print(preview_table)

    dev_table = Table(title="📱 运行设备", border_style="magenta")
    dev_table.add_column("名称", style="bold")
    dev_table.add_column("平台")
    dev_table.add_column("设备ID")
    dev_table.add_column("系统版本")
    dev_table.add_column("App包名")
    for d in target_devices:
        dev_table.add_row(d.name, d.platform, d.device_id, d.platform_version or "-", d.app_package)
    console.print(dev_table)

    if dry_run:
        console.print(Panel("[yellow]Dry Run 模式，未实际执行[/yellow]", title="✅ 预览完成", border_style="yellow"))
        return

    run_id = f"RUN_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"

    logger = Logger(_logs_dir)
    logger.info(f"===== 测试执行开始 | Run ID: {run_id} | 版本: {_version} =====")
    logger.info(f"用例数: {len(filtered_cases)} | 设备数: {len(target_devices)} | 重试: {_retry}")

    device_manager = DeviceManager(config_manager)
    collector = ResultCollector(_report_dir)
    executor = TestExecutor(
        config_manager=config_manager,
        device_manager=device_manager,
        logger=logger,
        screenshots_dir=_screenshots_dir,
        retry_count=_retry,
    )

    console.print(f"\n[bold cyan]开始执行测试 Run ID: {run_id}[/bold cyan]\n")
    result = executor.execute_run(filtered_cases, run_id, _version)
    result.only_high_risk = _only_high_risk
    logger.info(f"===== 测试执行完成 | 通过率: {result.pass_rate}% =====")

    result_path = collector.save_run_result(result)
    console.print(f"\n[dim]💾 运行结果已保存: {result_path}[/dim]")

    _print_run_summary(result, _report_dir)

    if not no_report:
        from .report import _generate_html_report
        _generate_html_report(result, collector, _report_dir, logger)

    if result.pass_rate < 100:
        console.print("\n[yellow]💡 提示: 使用 [bold]apptest report[/bold] 查看详细报告，[bold]apptest compare[/bold] 对比历史版本[/yellow]")


def _print_run_summary(result, report_dir: Path) -> None:
    console.print("\n")
    passed_color = "green" if result.pass_rate >= 90 else ("yellow" if result.pass_rate >= 70 else "red")
    console.print(Panel(
        f"[{passed_color}][bold]通过率: {result.pass_rate}%[/bold][/{passed_color}]\n\n"
        f"✅ 通过: [green]{result.passed}[/green]\n"
        f"❌ 失败: [red]{result.failed}[/red]\n"
        f"⏭️  跳过: [yellow]{result.skipped}[/yellow]\n"
        f"⚠️  异常: [bold red]{result.errors}[/bold red]\n"
        f"📊 总计: {result.total_cases}\n\n"
        f"⏱️  总耗时: {(result.duration_ms / 1000):.2f}s ({(result.duration_ms / 1000 / 60):.2f}min)\n"
        f"📱 设备数: {result.device_count}",
        title="📊 执行结果汇总",
        border_style=passed_color,
    ))

    if result.failed > 0 or result.errors > 0:
        failed_table = Table(title="❌ 失败/异常用例", border_style="red")
        failed_table.add_column("用例ID", style="bold")
        failed_table.add_column("用例名称")
        failed_table.add_column("设备")
        failed_table.add_column("分类")
        failed_table.add_column("风险")
        failed_table.add_column("状态")
        failed_table.add_column("错误信息", overflow="fold")

        from ..core import ResultCollector
        collector = ResultCollector(report_dir)
        failed_cases = collector.get_failed_cases(result)
        for c in failed_cases[:15]:
            failed_table.add_row(
                c.case_id, c.case_name, c.device_name, c.category, c.risk_level,
                f"[red]{c.status}[/red]", c.error_message[:80] if c.error_message else "-",
            )
        if len(failed_cases) > 15:
            failed_table.add_row("...", f"... 还有 {len(failed_cases) - 15} 个", "", "", "", "", "")
        console.print(failed_table)

    slowest_10 = sorted(result.case_results, key=lambda c: c.duration_ms, reverse=True)[:10]
    slow_table = Table(title="⏱️  耗时排行 Top 10", border_style="blue")
    slow_table.add_column("#", style="dim", justify="right")
    slow_table.add_column("用例ID")
    slow_table.add_column("用例名称")
    slow_table.add_column("设备")
    slow_table.add_column("耗时(ms)", justify="right")
    slow_table.add_column("状态")
    for i, c in enumerate(slowest_10, 1):
        status_color = "green" if c.status == TestStatus.PASSED.value else "red"
        slow_table.add_row(
            str(i), c.case_id, c.case_name, c.device_name,
            f"[{status_color}]{c.duration_ms:,}[/{status_color}]", c.status,
        )
    console.print(slow_table)
