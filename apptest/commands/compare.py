import click
import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Optional, Dict, Any

from ..config import ConfigManager
from ..models import TestRunResult, TestStatus
from ..core import ResultCollector, ResultComparer


console = Console()


@click.command("compare")
@click.argument("result_a", required=False)
@click.argument("result_b", required=False)
@click.option("--file-a", "file_a", type=click.Path(exists=True), default=None, help="版本A结果文件路径")
@click.option("--file-b", "file_b", type=click.Path(exists=True), default=None, help="版本B结果文件路径")
@click.option("--run-a", "run_a", default=None, help="版本A的 Run ID")
@click.option("--run-b", "run_b", default=None, help="版本B的 Run ID")
@click.option("--latest", "use_latest", is_flag=True, help="自动对比最近两次运行结果")
@click.option("--output", "-o", "output_file", default=None, help="输出对比报告路径")
@click.option("--format", "-f", "report_format", type=click.Choice(["html", "json", "console"]), default="html", help="报告格式")
@click.option("--open", "open_report", is_flag=True, help="生成后自动打开HTML报告")
@click.pass_context
def compare_cmd(
    ctx,
    result_a,
    result_b,
    file_a,
    file_b,
    run_a,
    run_b,
    use_latest,
    output_file,
    report_format,
    open_report,
):
    """对比两次运行结果，分析版本差异（通过率变化、回归修复、性能变化等）。

    用法：apptest compare <run_id_a> <run_id_b>
         apptest compare --file-a <path_a> --file-b <path_b>
         apptest compare --latest
    """
    workdir: Path = ctx.obj["workdir"]
    config_manager = ConfigManager(workdir)

    if not config_manager.exists():
        console.print("[red]错误: 项目未初始化[/red]")
        return

    config = config_manager.load()
    report_dir = workdir / config.report_dir
    collector = ResultCollector(report_dir)

    all_files = collector.list_result_files()
    if not all_files:
        console.print("[red]错误: 报告目录中没有运行结果文件，请先执行测试[/red]")
        return

    if result_a and result_b and not file_a and not file_b:
        file_a = report_dir / f"result_{result_a}.json"
        file_b = report_dir / f"result_{result_b}.json"
    elif run_a and run_b:
        file_a = report_dir / f"result_{run_a}.json"
        file_b = report_dir / f"result_{run_b}.json"

    if use_latest:
        if len(all_files) < 2:
            console.print(f"[red]错误: 至少需要两次运行结果，当前只有 {len(all_files)} 个[/red]")
            return
        file_b = all_files[0]
        file_a = all_files[1]
        console.print(f"[dim]自动选择最近两次运行:\n  A (旧): {file_a.name}\n  B (新): {file_b.name}[/dim]")

    if not file_a or not file_b:
        console.print("\n[yellow]请指定对比的两个运行结果。可用选项：[/yellow]")
        console.print("  1. apptest compare --latest        # 对比最近两次")
        console.print("  2. apptest compare <run_id_a> <run_id_b>")
        console.print("  3. apptest compare --file-a <path> --file-b <path>\n")
        console.print("[bold cyan]可用的运行结果:[/bold cyan]")
        for i, f in enumerate(all_files[:10], 1):
            try:
                r = collector.load_run_result(f)
                console.print(f"  {i}. {f.stem.replace('result_', '')} | 版本: {r.version} | 通过率: {r.pass_rate}% | {r.total_cases} 用例")
            except Exception:
                console.print(f"  {i}. {f.name}")
        return

    file_a = Path(file_a) if isinstance(file_a, str) else file_a
    file_b = Path(file_b) if isinstance(file_b, str) else file_b

    if not file_a.exists():
        console.print(f"[red]错误: 文件A不存在: {file_a}[/red]")
        return
    if not file_b.exists():
        console.print(f"[red]错误: 文件B不存在: {file_b}[/red]")
        return

    console.print(f"[dim]加载结果...[/dim]")
    result_a_obj = collector.load_run_result(file_a)
    result_b_obj = collector.load_run_result(file_b)

    console.print(Panel(
        f"[cyan]版本对比分析[/cyan]\n\n"
        f"🅰️  版本A (基线): {result_a_obj.version}\n"
        f"     Run ID: {result_a_obj.run_id}\n"
        f"     用例: {result_a_obj.total_cases} | 通过率: {result_a_obj.pass_rate}%\n\n"
        f"🅱️  版本B (新):   {result_b_obj.version}\n"
        f"     Run ID: {result_b_obj.run_id}\n"
        f"     用例: {result_b_obj.total_cases} | 通过率: {result_b_obj.pass_rate}%",
        title="📊 版本差异对比",
        border_style="magenta",
    ))

    diff = ResultComparer.compare(result_a_obj, result_b_obj)

    if report_format == "console":
        _print_console_diff(diff)
    elif report_format == "json":
        _save_json_diff(diff, output_file, report_dir)
    else:
        html_path = _generate_html_diff(diff, report_dir, output_file)
        if html_path:
            console.print(Panel(
                f"[green]对比报告生成成功！[/green]\n\n"
                f"📄 文件: {html_path.name}\n"
                f"📂 路径: {html_path}",
                title="✅ 对比报告",
                border_style="green",
            ))
            if open_report:
                import webbrowser
                try:
                    webbrowser.open(html_path.resolve().as_uri())
                except Exception:
                    pass

    _print_summary_insights(diff, result_a_obj, result_b_obj)


def _print_console_diff(diff: Dict[str, Any]) -> None:
    console.print("\n[bold]--- 核心指标对比 ---[/bold]")
    metrics_table = Table(border_style="cyan")
    metrics_table.add_column("指标", style="cyan")
    metrics_table.add_column("版本A", justify="right")
    metrics_table.add_column("版本B", justify="right")
    metrics_table.add_column("变化", justify="right")
    metrics_table.add_column("评估")

    display_names = {
        "total_cases": "用例总数",
        "passed": "通过数",
        "failed": "失败数",
        "skipped": "跳过数",
        "errors": "异常数",
        "pass_rate": "通过率(%)",
        "duration_ms": "总耗时(ms)",
        "device_count": "设备数",
    }

    for key, data in diff["metrics_diff"].items():
        delta = data.get("delta")
        delta_str = ""
        eval_str = "-"
        if delta is not None:
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta}"
            if key in ("passed", "pass_rate"):
                eval_str = "[green]↑ 优化[/green]" if delta > 0 else ("[red]↓ 退化[/red]" if delta < 0 else "[dim]持平[/dim]")
            elif key in ("failed", "errors", "duration_ms"):
                eval_str = "[green]↓ 优化[/green]" if delta < 0 else ("[red]↑ 退化[/red]" if delta > 0 else "[dim]持平[/dim]")
            elif delta > 0:
                eval_str = "[yellow]+增加[/yellow]"
            elif delta < 0:
                eval_str = "[yellow]-减少[/yellow]"
        metrics_table.add_row(
            display_names.get(key, key),
            str(data["a"]), str(data["b"]), delta_str, eval_str,
        )
    console.print(metrics_table)

    summary = diff["summary"]
    console.print("\n[bold]--- 变更概览 ---[/bold]")
    summary_table = Table(border_style="blue", show_header=False)
    summary_table.add_column("项", style="bold")
    summary_table.add_column("值")
    summary_table.add_row("新增用例", f"[green]{summary['new_cases']}[/green]")
    summary_table.add_row("移除用例", f"[red]{summary['removed_cases']}[/red]")
    summary_table.add_row("状态变更", f"[yellow]{summary['status_changed']}[/yellow]")
    console.print(summary_table)

    if diff["case_status_diff"]:
        console.print(f"\n[bold]--- 状态变更用例 ({len(diff['case_status_diff'])} 个) ---[/bold]")
        status_table = Table(border_style="yellow")
        status_table.add_column("用例ID", style="bold")
        status_table.add_column("名称")
        status_table.add_column("设备")
        status_table.add_column("A状态")
        status_table.add_column("B状态")
        status_table.add_column("评估")

        for item in diff["case_status_diff"]:
            sa, sb = item["status_a"], item["status_b"]
            if sa in ("failed", "error") and sb == "passed":
                eval_str = "[green]✅ 修复[/green]"
            elif sa == "passed" and sb in ("failed", "error"):
                eval_str = "[red]❌ 回归[/red]"
            elif sa == "skipped" and sb != "skipped":
                eval_str = "[blue]▶️  开始执行[/blue]"
            else:
                eval_str = "[yellow]↔️  变化[/yellow]"
            status_table.add_row(
                item["case_id"], item["name"], item["device"],
                f"[{sa}]{sa}[/{sa}]", f"[{sb}]{sb}[/{sb}]", eval_str,
            )
        console.print(status_table)

    if diff["performance_diff"]:
        console.print(f"\n[bold]--- 性能变化 (≥1s, Top 10) ---[/bold]")
        perf_table = Table(border_style="magenta")
        perf_table.add_column("用例ID", style="bold")
        perf_table.add_column("名称")
        perf_table.add_column("设备")
        perf_table.add_column("A耗时", justify="right")
        perf_table.add_column("B耗时", justify="right")
        perf_table.add_column("差值", justify="right")
        perf_table.add_column("变化率", justify="right")

        for item in diff["performance_diff"][:10]:
            delta_color = "red" if item["delta_ms"] > 0 else "green"
            perf_table.add_row(
                item["case_id"], item["name"], item.get("device", "-"),
                f"{item['duration_a_ms']:,}", f"{item['duration_b_ms']:,}",
                f"[{delta_color}]{'+' if item['delta_ms']>0 else ''}{item['delta_ms']:,}[/{delta_color}]",
                f"[{'red' if item['delta_pct']>0 else 'green'}]{'+' if item['delta_pct']>0 else ''}{item['delta_pct']}%[/]",
            )
        console.print(perf_table)


def _save_json_diff(diff: Dict[str, Any], output_file: Optional[str], report_dir: Path) -> None:
    if output_file:
        path = Path(output_file)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = report_dir / f"compare_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(diff, f, ensure_ascii=False, indent=2)
    console.print(f"[green]✓ JSON 对比结果已保存: {path}[/green]")


def _generate_html_diff(
    diff: Dict[str, Any],
    report_dir: Path,
    output_file: Optional[str],
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
        template_name = "compare_report.html"
        if not any((p / template_name).exists() for p in template_paths):
            raise FileNotFoundError("template not found")
        template = env.get_template(template_name)
        html_content = template.render(diff=diff)
    except Exception as e:
        console.print(f"[yellow]模板加载失败，使用备用方案: {e}[/yellow]")
        return _generate_html_diff_fallback(diff, report_dir, output_file)

    if output_file:
        output_path = Path(output_file)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = report_dir / f"compare_{ts}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return output_path


def _generate_html_diff_fallback(
    diff: Dict[str, Any],
    report_dir: Path,
    output_file: Optional[str],
) -> Path:
    display_names = {
        "total_cases": "用例总数", "passed": "通过数", "failed": "失败数",
        "skipped": "跳过数", "errors": "异常数", "pass_rate": "通过率 (%)",
        "duration_ms": "总耗时 (ms)", "device_count": "设备数",
    }
    metrics_html = ""
    for key, data in diff["metrics_diff"].items():
        delta = data.get("delta")
        delta_class = "flat"
        delta_text = ""
        if delta is not None:
            sign = "+" if delta >= 0 else ""
            delta_text = f"{sign}{delta}"
            if key in ("passed", "pass_rate"):
                delta_class = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            elif key in ("failed", "errors", "duration_ms"):
                delta_class = "up" if delta < 0 else ("down" if delta > 0 else "flat")
        metrics_html += f"""<div class="compare-card">
<div class="label">{display_names.get(key, key)}</div>
<div class="compare-row"><div><div style="font-size:11px;color:#95a5a6">版本A</div><div class="val-a">{data['a']}</div></div>
<div><div style="font-size:11px;color:#95a5a6">版本B</div><div class="val-b">{data['b']}</div></div></div>
<div style="text-align:center;margin-top:8px"><span class="delta {delta_class}">{delta_text}</span></div></div>"""

    status_rows = ""
    for item in diff["case_status_diff"]:
        sa, sb = item["status_a"], item["status_b"]
        if sa in ("failed", "error") and sb == "passed":
            change = '<span style="color:#27ae60;font-weight:600">✅ 修复</span>'
        elif sa == "passed" and sb in ("failed", "error"):
            change = '<span style="color:#e74c3c;font-weight:600">❌ 回归</span>'
        else:
            change = '<span style="color:#f39c12;font-weight:600">↔️ 状态变化</span>'
        status_rows += f"<tr><td><code>{item['case_id']}</code></td><td>{item['name']}</td><td>{item['device']}</td><td><span class='badge {sa}'>{sa}</span></td><td><span class='badge {sb}'>{sb}</span></td><td>{change}</td></tr>"

    perf_rows = ""
    for item in diff["performance_diff"]:
        color = "#e74c3c" if item["delta_ms"] > 0 else "#27ae60"
        pct_color = "up" if item["delta_pct"] < 0 else ("down" if item["delta_pct"] > 0 else "flat")
        perf_rows += f"<tr><td><code>{item['case_id']}</code></td><td>{item['name']}</td><td>{item.get('device', '-')}</td><td>{item['duration_a_ms']:,}</td><td>{item['duration_b_ms']:,}</td><td style='font-weight:600;color:{color}'>{'+' if item['delta_ms']>0 else ''}{item['delta_ms']:,}</td><td><span class='delta {pct_color}'>{'+' if item['delta_pct']>0 else ''}{item['delta_pct']}%</span></td></tr>"

    s = diff["summary"]
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>版本差异对比报告</title>
<style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#f5f7fa;color:#2c3e50;padding:20px;}}
.container{{max-width:1400px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#f093fb,#f5576c);color:white;padding:30px;border-radius:16px;margin-bottom:24px;}}
.header h1{{font-size:28px;margin-bottom:8px;}}
.metrics-compare{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px;margin-bottom:24px;}}
.compare-card{{background:white;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.06);}}
.label{{font-size:13px;color:#7f8c8d;margin-bottom:12px;}}
.compare-row{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}}
.val-a{{color:#2980b9;font-weight:600;font-size:18px;}}
.val-b{{color:#27ae60;font-weight:600;font-size:18px;}}
.delta{{padding:2px 8px;border-radius:6px;font-size:12px;font-weight:600;}}
.delta.up{{background:#d4efdf;color:#186a3b;}}
.delta.down{{background:#fadbd8;color:#922b21;}}
.delta.flat{{background:#ecf0f1;color:#566573;}}
.card{{background:white;border-radius:12px;padding:24px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,0.06);}}
.card h2{{font-size:18px;margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid #ecf0f1;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{padding:12px 14px;text-align:left;border-bottom:1px solid #ecf0f1;}}
th{{background:#f8f9fa;font-weight:600;color:#566573;}}
.badge{{display:inline-block;padding:4px 10px;border-radius:12px;font-size:12px;}}
.badge.passed{{background:#d4efdf;color:#186a3b;}}
.badge.failed{{background:#fadbd8;color:#922b21;}}
.badge.skipped{{background:#fdebd0;color:#9c640c;}}
.summary-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px;}}
.summary-item{{padding:16px;border-radius:8px;text-align:center;}}
.summary-item.new{{background:#eaf2f8;color:#2874a6;}}
.summary-item.removed{{background:#fadbd8;color:#922b21;}}
.summary-item.changed{{background:#fef9e7;color:#9c640c;}}
.summary-item .num{{font-size:28px;font-weight:700;}}
.summary-item .txt{{font-size:12px;margin-top:4px;}}
</style></head><body><div class="container">
<div class="header"><h1>📊 版本差异对比报告</h1>
<div><strong>版本A:</strong> {diff['version_a']} ({diff['run_id_a']}) &nbsp;&nbsp; <strong>版本B:</strong> {diff['version_b']} ({diff['run_id_b']})</div>
</div>
<div class="metrics-compare">{metrics_html}</div>
<div class="card"><h2>📈 变更概览</h2><div class="summary-grid">
<div class="summary-item new"><div class="num">{s['new_cases']}</div><div class="txt">新增用例</div></div>
<div class="summary-item removed"><div class="num">{s['removed_cases']}</div><div class="txt">移除用例</div></div>
<div class="summary-item changed"><div class="num">{s['status_changed']}</div><div class="txt">状态变更</div></div>
</div></div>
"""
    if diff["case_status_diff"]:
        html += f"""<div class="card"><h2>🔄 状态变更用例</h2><table><thead><tr>
<th>用例ID</th><th>名称</th><th>设备</th><th>版本A</th><th>版本B</th><th>变化</th>
</tr></thead><tbody>{status_rows}</tbody></table></div>"""
    if diff["performance_diff"]:
        html += f"""<div class="card"><h2>⚡ 性能变化 (≥1s)</h2><table><thead><tr>
<th>用例ID</th><th>名称</th><th>设备</th><th>A耗时(ms)</th><th>B耗时(ms)</th><th>差值</th><th>变化率</th>
</tr></thead><tbody>{perf_rows}</tbody></table></div>"""
    html += "</div></body></html>"

    if output_file:
        output_path = Path(output_file)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = report_dir / f"compare_{ts}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _print_summary_insights(
    diff: Dict[str, Any],
    result_a: TestRunResult,
    result_b: TestRunResult,
) -> None:
    console.print("\n[bold]💡 差异洞察:[/bold]")
    insights = []
    pass_delta = (diff["metrics_diff"]["pass_rate"]["delta"] or 0)
    if pass_delta > 5:
        insights.append(("[green]✓[/green]", f"通过率显著提升 {pass_delta:+.2f}%，版本质量明显改善"))
    elif pass_delta < -5:
        insights.append(("[red]![/red]", f"通过率下降 {pass_delta:+.2f}%，建议排查回归问题"))
    else:
        insights.append(("[dim]i[/dim]", f"通过率变化 {pass_delta:+.2f}%，整体质量平稳"))

    fixed_count = sum(
        1 for s in diff["case_status_diff"]
        if s["status_a"] in ("failed", "error") and s["status_b"] == "passed"
    )
    regressed_count = sum(
        1 for s in diff["case_status_diff"]
        if s["status_a"] == "passed" and s["status_b"] in ("failed", "error")
    )
    if fixed_count > 0:
        insights.append(("[green]✓[/green]", f"有 {fixed_count} 个用例被修复"))
    if regressed_count > 0:
        insights.append(("[red]![/red]", f"发现 {regressed_count} 个回归用例，需要关注"))

    perf_regress = sum(1 for p in diff["performance_diff"] if p["delta_ms"] > 5000)
    if perf_regress > 0:
        insights.append(("[yellow]⚠[/yellow]", f"{perf_regress} 个用例性能下降超过 5 秒"))

    if diff["summary"]["new_cases"] > 0:
        insights.append(("[blue]i[/blue]", f"新增了 {diff['summary']['new_cases']} 个测试用例，测试覆盖面扩大"))

    for icon, msg in insights:
        console.print(f"  {icon} {msg}")
