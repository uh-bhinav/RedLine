import typer

from apps.cli.commands.ci_check import ci_check_cmd
from apps.cli.commands.diff import diff_cmd
from apps.cli.commands.init import init_cmd
from apps.cli.commands.load import load_cmd
from apps.cli.commands.login import login_cmd
from apps.cli.commands.mine import (
    candidates_approve_cmd,
    candidates_list_cmd,
    candidates_reject_cmd,
    mine_cmd,
)
from apps.cli.commands.push_suite import push_suite_cmd
from apps.cli.commands.register_version import register_version_cmd
from apps.cli.commands.run import run_cmd

app = typer.Typer(
    name="agentbench",
    help=(
        "AgentBench — agent reliability engineering. Register agents, push eval "
        "suites, run evaluations, and gate deployments on the result."
    ),
)

app.command("login")(login_cmd)
app.command("init")(init_cmd)
app.command("push-suite")(push_suite_cmd)
app.command("register-version")(register_version_cmd)
app.command("run")(run_cmd)
app.command("diff")(diff_cmd)
app.command("load")(load_cmd)
app.command("mine")(mine_cmd)
app.command("candidates-list")(candidates_list_cmd)
app.command("candidates-approve")(candidates_approve_cmd)
app.command("candidates-reject")(candidates_reject_cmd)
app.command("ci-check")(ci_check_cmd)

if __name__ == "__main__":
    app()