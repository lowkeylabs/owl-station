import click

from owlstation.solver_info import get_owl_solver_info
from owlstation.version import __version__

from ..configure_logging import LOG_LEVELS, configure_logging
from .cmd_hydra import cmd_hydra
from .cmd_list import cmd_list
from .cmd_run import cmd_run


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    default="INFO",
    show_default=True,
    help="Set logging verbosity.",
)
@click.version_option(
    version=__version__,
    prog_name="owlstation",
)
@click.pass_context
def cli(ctx, log_level: str):
    """SSG command-line interface."""
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level.upper()

    configure_logging(log_level)


cli.add_command(cmd_list)
cli.add_command(cmd_run)
cli.add_command(cmd_hydra)


@cli.command()
def info():
    """Show OWL-Station and OWL solver version information."""
    solver = get_owl_solver_info()

    click.echo(f"OWL-Station version: {__version__}")
    click.echo(f"OWL-Planner version: {solver.version}")

    if solver.commit:
        click.echo(f"OWL solver commit:  {solver.commit}")


if __name__ == "__main__":
    cli()
