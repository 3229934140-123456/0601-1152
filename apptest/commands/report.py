import click
import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from jinja2 import Environment, FileSystemLoader, PackageLoader, select_autoescape
from typing import Optional

from ..config import ConfigManager
from ..models import TestRunResult, TestStatus
from ..core import ResultCollector, Logger


console = Console()


@click.command("report")
@click.option("--run-id", "run_id", default=None, help="指定 Run ID 生成报告（默认最新一次）")
@click.option("--result-file", "result_file", type=click.Path(exists=True), default=None, help="指定结果 JSON 文件路径")
@click.option("--output", "-o", "output_file", default=None, help="输出 HTML 报告路径")
@click.option("--format", "-f", "report_format", type=click.Choice(["html", "json", "console"]), default="html", help="报告格式")
@click.option("--show-logs", is_flag=True, help="控制台输出时显示详细日志")
@click.option("--open", "open_report", is_flag=True, help="生成后自动打开报告")
@click.pass_context
def report_cmd(ctx, run_id, result_file, output_file, report_format, show_logs, open_report):
    """生成测试报告（通过率、失败截图、耗时排行、关键日志）。

    默认读取最新一次运行结果生成 HTML 报告。
    """
    workdir: Path = ctx.obj["workdir"]
    config_manager = ConfigManager(workdir)

    if not config_manager.exists():
        console.print("[red]错误: 项目未初始化[/red]")
        return

    config = config_manager.load()
    report_dir = workdir / config.report_dir
    collector = ResultCollector(report_dir)

    result_path: Optional[Path] = None
    if result_file:
        result_path = Path(result_file)
    elif run_id:
        result_path = report_dir / f"result_{run_id}.json"
        if not result_path.exists():
            console.print(f"[red]错误: 未找到 Run ID '{run_id}' 的结果文件[/red]")
            return
    else:
        result_path = collector.get_latest_result()
        if not result_path:
            console.print("[red]错误: 报告目录中未找到任何运行结果，请先执行 [bold]apptest run[/bold][/red]")
            return

    console.print(f"[dim]📄 加载结果: {result_path}[/dim]")
    result = collector.load_run_result(result_path)

    if report_format == "console":
        _print_console_report(result, collector, show_logs)
    elif report_format == "json":
        _print_json_report(result, output_file, report_dir)
    else:
        logger = Logger(workdir / config.logs_dir)
        html_path = _generate_html_report(result, collector, report_dir, logger, output_file)
        if html_path:
            console.print(Panel(
                f"[green]报告生成成功！[/green]\n\n"
                f"📄 文件: {html_path.name}\n"
                f"📂 路径: {html_path}\n\n"
                f"[dim]在浏览器中打开即可查看完整报告[/dim]",
                title="✅ HTML 报告",
                border_style="green",
            ))
            if open_report:
                import webbrowser
                try:
                    webbrowser.open(html_path.resolve().as_uri())
                except Exception:
                    pass


def _print_console_report(result: TestRunResult, collector: ResultCollector, show_logs: bool) -> None:
    console.print(Panel(
        f"📌 版本: {result.version} | Run ID: {result.run_id}\n"
        f"⏰ 开始: {result.start_time}\n"
        f"⏰ 结束: {result.end_time}",
        title="📊 测试报告 (控制台模式)",
        border_style="cyan",
    ))

    metrics_table = Table(title="核心指标", border_style="blue")
    metrics_table.add_column("指标", style="cyan")
    metrics_table.add_column("数值", justify="right", style="bold")
    pass_rate_color = "green" if result.pass_rate >= 90 else ("yellow" if result.pass_rate >= 70 else "red")
    metrics_table.add_row("用例总数", str(result.total_cases))
    metrics_table.add_row("通过", f"[green]{result.passed}[/green]")
    metrics_table.add_row("失败", f"[red]{result.failed}[/red]")
    metrics_table.add_row("跳过", f"[yellow]{result.skipped}[/yellow]")
    metrics_table.add_row("异常", f"[bold red]{result.errors}[/bold red]")
    metrics_table.add_row("通过率", f"[{pass_rate_color}]{result.pass_rate}%[/{pass_rate_color}]")
    metrics_table.add_row("总耗时(秒)", f"{(result.duration_ms / 1000):.2f}")
    metrics_table.add_row("重试次数", str(result.retry_count))
    metrics_table.add_row("设备数", str(result.device_count))
    console.print(metrics_table)

    if result.devices:
        dev_table = Table(title="运行设备", border_style="magenta", show_header=False)
        for d in result.devices:
            dev_table.add_row("📱", d)
        console.print(dev_table)

    failed = collector.get_failed_cases(result)
    if failed:
        failed_table = Table(title=f"❌ 失败用例 ({len(failed)} 个)", border_style="red", show_lines=True)
        failed_table.add_column("ID", style="bold")
        failed_table.add_column("名称")
        failed_table.add_column("设备")
        failed_table.add_column("风险")
        failed_table.add_column("错误信息", overflow="fold")
        failed_table.add_column("截图")
        for c in failed:
            ss = Path(c.screenshot_path).name if c.screenshot_path else "-"
            failed_table.add_row(c.case_id, c.case_name, c.device_name, c.risk_level,
                                 c.error_message or "-", ss)
        console.print(failed_table)

    slowest = collector.get_slowest_cases(result, 10)
    if slowest:
        slow_table = Table(title="⏱️  耗时排行 Top 10", border_style="yellow")
        slow_table.add_column("#", justify="right", style="dim")
        slow_table.add_column("ID")
        slow_table.add_column("名称")
        slow_table.add_column("设备")
        slow_table.add_column("耗时(ms)", justify="right")
        slow_table.add_column("状态")
        for i, c in enumerate(slowest, 1):
            color = "green" if c.status == TestStatus.PASSED.value else "red"
            slow_table.add_row(str(i), c.case_id, c.case_name, c.device_name,
                               f"[{color}]{c.duration_ms:,}[/{color}]", c.status)
        console.print(slow_table)

    if show_logs:
        logs = collector.extract_key_logs(result)
        if logs:
            console.print(Panel("[bold]📝 关键日志[/bold]", title="日志", border_style="green"))
            for log in logs:
                console.print(f"\n[cyan]--- {log['case_id']} - {log['case_name']} @ {log['device']} ---[/cyan]")
                if log.get("failed_step"):
                    console.print(f"  [red]失败步骤: {log['failed_step']}[/red]")
                if log.get("step_error"):
                    console.print(f"  [red]步骤错误: {log['step_error']}[/red]")
                if log.get("error"):
                    console.print(f"  [red]错误: {log['error']}[/red]")
                if log.get("log_path"):
                    console.print(f"  [dim]日志文件: {log['log_path']}[/dim]")


def _print_json_report(result: TestRunResult, output_file: Optional[str], report_dir: Path) -> None:
    data = result.to_dict()
    if output_file:
        path = Path(output_file)
    else:
        path = report_dir / f"report_{result.run_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    console.print(f"[green]✓ JSON 报告已保存: {path}[/green]")
    console.print(f"[dim]{json.dumps({k: v for k, v in data.items() if k != 'case_results'}, ensure_ascii=False, indent=2)}[/dim]")


def _generate_html_report(
    result: TestRunResult,
    collector: ResultCollector,
    report_dir: Path,
    logger: Logger,
    output_file: Optional[str] = None,
) -> Optional[Path]:
    try:
        template_paths = [
            Path(__file__).parent.parent / "templates",
            Path.cwd() / "apptest" / "templates",
        ]
        env = Environment(
            loader=FileSystemLoader([str(p) for p in template_paths if p.exists()]),
            autoescape=select_autoescape(["html", "xml"]),
        )
        env.globals["enumerate"] = enumerate
    except Exception as e:
        console.print(f"[yellow]警告: 模板加载失败: {e}，使用备用报告生成[/yellow]")
        return _generate_html_report_fallback(result, collector, report_dir, output_file)

    template_name = "report.html"
    if not any((p / template_name).exists() for p in template_paths):
        console.print("[yellow]警告: 未找到 report.html 模板[/yellow]")
        return _generate_html_report_fallback(result, collector, report_dir, output_file)

    template = env.get_template(template_name)

    if output_file:
        output_path = Path(output_file)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = report_dir / f"report_{result.run_id}_{timestamp}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failed_cases = collector.get_failed_cases(result)
    slowest_cases = collector.get_slowest_cases(result, 10)
    key_logs = collector.extract_key_logs(result)

    def _augment_case(case):
        d = case if isinstance(case, dict) else case.__dict__.copy()
        raw_path = d.get("screenshot_path") or ""
        exists = False
        display_src = ""
        if raw_path:
            p = Path(raw_path)
            if p.exists():
                exists = True
                try:
                    rel_p = p.resolve().relative_to(output_path.resolve().parent)
                    display_src = str(rel_p).replace("\\", "/")
                except Exception:
                    display_src = p.resolve().as_uri()
        d["screenshot_exists"] = exists
        d["screenshot_display_src"] = display_src
        d["screenshot_name"] = Path(raw_path).name if raw_path else ""
        d_obj = type("CaseView", (), d)
        d_obj._d = d
        return d_obj

    augmented_failed = [_augment_case(c) for c in failed_cases]
    augmented_slowest = [_augment_case(c) for c in slowest_cases]

    html_content = template.render(
        run_result=result,
        failed_cases=augmented_failed,
        slowest_cases=augmented_slowest,
        key_logs=key_logs,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"HTML 报告已生成: {output_path}")
    return output_path


def _generate_html_report_fallback(
    result: TestRunResult,
    collector: ResultCollector,
    report_dir: Path,
    output_file: Optional[str] = None,
) -> Optional[Path]:
    if output_file:
        output_path = Path(output_file)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = report_dir / f"report_{result.run_id}_{timestamp}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failed_cases = collector.get_failed_cases(result)
    slowest_cases = collector.get_slowest_cases(result, 10)
    key_logs = collector.extract_key_logs(result)

    pass_rate_color = "#27ae60" if result.pass_rate >= 90 else ("#f39c12" if result.pass_rate >= 70 else "#e74c3c")

    html_parts = [f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>自动化测试报告 - {result.version}</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", sans-serif; background:#f5f7fa; padding:20px; color:#2c3e50; }}
.container {{ max-width: 1400px; margin: 0 auto; }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:white; padding:30px; border-radius:16px; margin-bottom:24px; }}
.header h1 {{ margin:0 0 8px 0; }}
.metrics {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:16px; margin-bottom:24px; }}
.metric-card {{ background:white; padding:20px; border-radius:12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.metric-label {{ font-size:13px; color:#7f8c8d; margin-bottom:8px; }}
.metric-value {{ font-size:32px; font-weight:700; }}
.card {{ background:white; padding:24px; border-radius:12px; margin-bottom:24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.card h2 {{ font-size:18px; margin-bottom:16px; padding-bottom:12px; border-bottom:2px solid #ecf0f1; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th, td {{ padding:12px 14px; text-align:left; border-bottom:1px solid #ecf0f1; }}
th {{ background:#f8f9fa; }}
.badge {{ display:inline-block; padding:4px 10px; border-radius:12px; font-size:12px; }}
.badge.passed {{ background:#d4efdf; color:#186a3b; }}
.badge.failed {{ background:#fadbd8; color:#922b21; }}
.badge.critical {{ background:#f1948a; color:#78281f; }}
.badge.high {{ background:#f5cba7; color:#7e5109; }}
.ss-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:16px; }}
.ss-item {{ border:1px solid #ecf0f1; border-radius:8px; overflow:hidden; }}
.ss-placeholder {{ aspect-ratio:9/16; background:linear-gradient(135deg,#f093fb,#f5576c); display:flex; align-items:center; justify-content:center; color:white; flex-direction:column; }}
.ss-meta {{ padding:10px 12px; font-size:12px; background:#fafafa; }}
.log-item {{ padding:12px; background:#2c3e50; color:#ecf0f1; border-radius:8px; font-family:monospace; font-size:13px; margin-bottom:10px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1>📱 移动 App 自动化测试报告</h1>
<div>版本: <strong>{result.version}</strong> | Run ID: {result.run_id}</div>
<div>开始: {result.start_time} | 结束: {result.end_time}</div>
</div>

<div class="metrics">
<div class="metric-card"><div class="metric-label">通过率</div><div class="metric-value" style="color:{pass_rate_color}">{result.pass_rate}%</div></div>
<div class="metric-card"><div class="metric-label">用例总数</div><div class="metric-value">{result.total_cases}</div></div>
<div class="metric-card"><div class="metric-label">通过</div><div class="metric-value" style="color:#27ae60">{result.passed}</div></div>
<div class="metric-card"><div class="metric-label">失败</div><div class="metric-value" style="color:#e74c3c">{result.failed}</div></div>
<div class="metric-card"><div class="metric-label">跳过</div><div class="metric-value" style="color:#f39c12">{result.skipped}</div></div>
<div class="metric-card"><div class="metric-label">异常</div><div class="metric-value" style="color:#c0392b">{result.errors}</div></div>
<div class="metric-card"><div class="metric-label">总耗时(分钟)</div><div class="metric-value" style="color:#8e44ad">{(result.duration_ms/1000/60):.2f}</div></div>
</div>
"""]

    if failed_cases:
        html_parts.append("""<div class="card"><h2>❌ 失败用例 & 截图</h2><div class="ss-grid">""")
        for c in failed_cases:
            ss_name = Path(c.screenshot_path).name if c.screenshot_path else "未捕获"
            ss_block = ""
            if c.screenshot_path and Path(c.screenshot_path).exists():
                try:
                    try:
                        rel_p = Path(c.screenshot_path).resolve().relative_to(output_path.resolve().parent)
                        src = str(rel_p).replace("\\", "/")
                    except Exception:
                        src = Path(c.screenshot_path).resolve().as_uri()
                    ss_block = f'<a href="{src}" target="_blank"><img src="{src}" style="width:100%;aspect-ratio:9/16;object-fit:cover;display:block;"></a>'
                except Exception:
                    ss_block = f'<div class="ss-placeholder"><div style="font-size:32px">📸</div><div>失败截图</div><div style="font-size:11px;opacity:0.8">{ss_name}</div></div>'
            else:
                ss_block = f'<div class="ss-placeholder"><div style="font-size:32px">📷</div><div>未捕获</div><div style="font-size:11px;opacity:0.8">{ss_name or "无截图文件"}</div></div>'
            html_parts.append(f"""<div class="ss-item">
{ss_block}
<div class="ss-meta"><div style="font-weight:600">{c.case_id} - {c.case_name}</div>
<div><span class="badge {c.risk_level}">{c.risk_level}</span> <span class="badge {c.status}">{c.status}</span></div>
<div>设备: {c.device_name}</div>
<div style="color:#e74c3c">{c.error_message[:100]}</div></div></div>""")
        html_parts.append("</div></div>")

    html_parts.append("""<div class="card"><h2>⏱️ 耗时排行 Top 10</h2><table><thead><tr>
<th>#</th><th>用例ID</th><th>名称</th><th>分类</th><th>风险</th><th>设备</th><th>状态</th><th>耗时(ms)</th></tr></thead><tbody>""")
    for i, c in enumerate(slowest_cases, 1):
        html_parts.append(f"<tr><td>#{i}</td><td><code>{c.case_id}</code></td><td>{c.case_name}</td><td>{c.category}</td><td><span class='badge {c.risk_level}'>{c.risk_level}</span></td><td>{c.device_name}</td><td><span class='badge {c.status}'>{c.status}</span></td><td><strong>{c.duration_ms:,}</strong></td></tr>")
    html_parts.append("</tbody></table></div>")

    html_parts.append("""<div class="card"><h2>📋 全部结果</h2><table><thead><tr>
<th>用例ID</th><th>名称</th><th>分类</th><th>风险</th><th>设备</th><th>状态</th><th>重试</th><th>耗时(ms)</th></tr></thead><tbody>""")
    for c in result.case_results:
        html_parts.append(f"<tr><td><code>{c.case_id}</code></td><td>{c.case_name}</td><td>{c.category}</td><td><span class='badge {c.risk_level}'>{c.risk_level}</span></td><td>{c.device_name}</td><td><span class='badge {c.status}'>{c.status}</span></td><td>{c.retry_count}</td><td>{c.duration_ms:,}</td></tr>")
    html_parts.append("</tbody></table></div>")

    if key_logs:
        html_parts.append("""<div class="card"><h2>📝 关键日志</h2>""")
        for log in key_logs:
            log_content = f"[用例] {log['case_id']} - {log['case_name']} | [设备] {log['device']}"
            if log.get("failed_step"):
                log_content += f"\n[失败步骤] {log['failed_step']}"
            if log.get("step_error"):
                log_content += f"\n[步骤错误] {log['step_error']}"
            if log.get("error"):
                log_content += f"\n[错误] {log['error']}"
            log_content = log_content.replace("\n", "<br>").replace(" ", "&nbsp;")
            html_parts.append(f'<div class="log-item">{log_content}</div>')
        html_parts.append("</div>")

    html_parts.append("</div></body></html>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))
    return output_path
