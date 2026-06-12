import os
import sys
import traceback
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .commands import init_cmd, record_cmd, run_cmd, report_cmd, compare_cmd
from .config import ConfigManager


console = Console()


class ApptestCLI(click.Group):
    def format_help(self, ctx, formatter):
        super().format_help(ctx, formatter)

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except click.ClickException:
            raise
        except click.Abort:
            console.print("\n[yellow]操作已取消[/yellow]")
            sys.exit(1)
        except Exception as e:
            console.print(Panel(
                f"[red]未预期的错误: {type(e).__name__}: {e}[/red]\n\n"
                f"[dim]{traceback.format_exc()}[/dim]",
                title="❌ 程序异常",
                border_style="red",
            ))
            sys.exit(2)


@click.group(cls=ApptestCLI, invoke_without_command=True)
@click.option("--workdir", "-w", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=Path.cwd(), help="工作目录（默认当前目录）")
@click.option("--verbose", "-v", is_flag=True, help="启用详细输出")
@click.version_option(__version__, "--version", "-V", prog_name="apptest")
@click.pass_context
def main(ctx, workdir, verbose):
    """apptest - 移动 App 自动化测试平台命令行工具

    供移动 App 测试人员做发版前冒烟检查的一站式工具。
    提供 init（初始化）、record（录制）、run（执行）、report（报告）、compare（对比）五类命令。

    快速开始：
      apptest init -n my-project        # 初始化项目
      apptest record -t login           # 录制登录用例（基于模板）
      apptest run --tags smoke --high-risk  # 仅跑高风险冒烟用例
      apptest report                    # 查看测试报告
      apptest compare --latest          # 对比最近两次结果
    """
    ctx.ensure_object(dict)
    ctx.obj["workdir"] = workdir
    ctx.obj["verbose"] = verbose

    if verbose:
        console.print(f"[dim]💡 工作目录: {workdir}[/dim]")

    if ctx.invoked_subcommand is None:
        _print_welcome(workdir, verbose)


def _print_welcome(workdir: Path, verbose: bool):
    cm = ConfigManager(workdir)

    banner = f"""[bold cyan]apptest[/bold cyan] v{__version__}
移动 App 自动化测试平台命令行工具

[dim]五大核心命令:[/dim]
  [bold]init[/bold]     - 初始化项目，生成配置文件和示例用例
  [bold]record[/bold]   - 录制/编辑测试步骤，管理账号和设备
  [bold]run[/bold]      - 批量执行冒烟测试，支持重试、过滤参数
  [bold]report[/bold]   - 生成测试报告（通过率/截图/耗时/日志）
  [bold]compare[/bold]  - 对比两次运行结果，分析版本差异

[dim]常用场景:[/dim]
  • 发版前冒烟检查: [bold]apptest run --high-risk --retry 3[/bold]
  • 仅跑核心流程:   [bold]apptest run -t smoke,login,order[/bold]
  • 生成可视化报告: [bold]apptest report --open[/bold]
  • 对比新旧版本:   [bold]apptest compare --latest[/bold]"""

    console.print(Panel(banner, title="📱 AppTest CLI", border_style="cyan"))

    if cm.exists():
        config = cm.load()
        from .core import TestCaseLoader
        loader = TestCaseLoader(workdir / config.cases_dir)
        cases = loader.load_all_cases()
        active_devices = [d for d in config.devices if d.is_active]

        info_table = Table(show_header=False, border_style="dim")
        info_table.add_column("项", style="dim")
        info_table.add_column("值")
        info_table.add_row("项目名称", f"[bold]{config.project_name}[/bold]")
        info_table.add_row("App 版本", config.version)
        info_table.add_row("测试用例", f"[cyan]{len(cases)}[/cyan] 个")
        info_table.add_row("测试设备", f"[magenta]{len(active_devices)}[/magenta] 台 (启用)")
        info_table.add_row("测试账号", f"[blue]{len(config.accounts)}[/blue] 个")
        console.print(info_table)

        console.print("\n[dim]使用 [bold]apptest --help[/bold] 或 [bold]apptest <command> --help[/bold] 查看详细帮助[/dim]")
    else:
        console.print(Panel(
            "[yellow]⚠️  当前目录尚未初始化[/yellow]\n\n"
            "运行 [bold]apptest init[/bold] 开始创建你的测试项目，\n"
            "或使用 [bold]apptest init -i[/bold] 进入交互式配置向导。",
            title="💡 提示",
            border_style="yellow",
        ))


main.add_command(init_cmd)
main.add_command(record_cmd)
main.add_command(run_cmd)
main.add_command(report_cmd)
main.add_command(compare_cmd)


if __name__ == "__main__":
    main(obj={})
