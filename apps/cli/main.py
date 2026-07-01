import typer

from apps.cli.commands.ci_check import ci_check_cmd
from apps.cli.commands.init import init_cmd
from apps.cli.commands.login import login_cmd
from apps.cli.commands.push_suite import push_suite_cmd
from apps.cli.commands.register_version import register_version_cmd
from apps.cli.commands.run import run_cmd

app = typer.Typer(name="agentbench", help="AgentBench Cloud CLI -- RedLine Phase 1")

app.command("login")(login_cmd)
app.command("init")(init_cmd)
app.command("push-suite")(push_suite_cmd)
app.command("register-version")(register_version_cmd)
app.command("run")(run_cmd)
app.command("ci-check")(ci_check_cmd)

if __name__ == "__main__":
    app()