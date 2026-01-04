"""
Categorize command alias.
This command is deprecated and wraps 'organize'.
"""
import click
from .organize import organize

@click.command()
@click.argument("query", required=False)
@click.option("--auto", is_flag=True, help="Automatically move folders without asking.")
@click.option("--simulate", is_flag=True, help="Dry run.")
@click.option("--no-cache", is_flag=True, help="Force fresh scan.")
@click.option("--model-assign", is_flag=True, help="Configure AI models.")
@click.option("--pause", is_flag=True, help="Pause (Interactive mode).")
@click.option("--newroot", help="Target NEW root (Copy mode).")
@click.option("-v", "--verbose", count=True, help="Verbosity.")
@click.pass_context
def categorize(ctx, query, auto, simulate, no_cache, model_assign, pause, newroot, verbose):
    """
    [DEPRECATED] Use 'organize' instead.
    
    Alias for: organize --source Uncategorized --interactive (unless --auto)
    """
    click.echo("Note: 'categorize' is now an alias for 'organize'.")
    
    # Default to interactive unless auto is specified
    interactive = not auto
    
    # Determine source filter
    # If copying to newroot, we usually want to copy EVERYTHING, so no source filter.
    # If moving (categorizing), we defaults to Uncategorized.
    source_filter = []
    if not newroot:
        source_filter = ["Uncategorized"]

    ctx.invoke(
        organize,
        query=query,
        source=source_filter,
        target=None,
        newroot=newroot,
        auto=auto,
        simulate=simulate,
        no_cache=no_cache,
        model_assign=model_assign,
        interactive=interactive,
        explain=True,
        newonly=False,
        instruct=None,
        tag=[], 
        no_tag=[], 
        genre=[], 
        no_genre=[], 
        no_source=[]
    )