import os

import click

from owlroost.core.configure_logging import LOG_LEVELS, configure_logging
from owlroost.core.solver_info import get_owl_solver_info
from owlroost.version import __version__

from .cmd_cases import cmd_cases

early_level = os.getenv("OWLSTATION_LOG_LEVEL", "INFO")
if early_level:
    early_level = early_level.upper()
if early_level in LOG_LEVELS:
    configure_logging(early_level)


@click.group(invoke_without_command=True)
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    default=None,
    help="Set logging verbosity.",
)
@click.version_option(version=__version__, prog_name="owlroost")
@click.pass_context
def cli(ctx, log_level: str | None):
    """OWL-ROOST command-line interface."""
    ctx.ensure_object(dict)

    configure_logging(log_level)

    overrides = []
    if log_level:
        overrides.append(f"logging.level={log_level}")

    #    cfg = load_hydra_config(overrides)
    #    hc = HydraConfig.get()
    #    logger.debug("Hydra configuration sources (in precedence order):")
    #    for src in hc.runtime.config_sources:
    #        logger.debug(f"  - {src.provider}: {src.path}")

    #    ctx.obj["cfg"] = cfg

    #    configure_logging(cfg.logging.level)

    #    logger.debug(f"Resolved logging configuration:\n{OmegaConf.to_yaml(cfg.logging, resolve=True)}")

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(cmd_cases)


@cli.command()
@click.pass_context
def info(ctx):
    """Show OWL-Station and OWL solver version information."""
    solver = get_owl_solver_info()

    click.echo(f"OWL-Station version: {__version__}")
    click.echo(f"OWL-Planner version: {solver.version}")

    if solver.commit:
        click.echo(f"OWL-Planner commit:  {solver.commit}")
