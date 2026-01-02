"""
Tree command for VibeManga CLI.

Visualizes the library structure.
"""
import click
import logging
from typing import Optional
from rich.tree import Tree

from .base import console, get_library_root, run_scan_with_progress, perform_deep_analysis
from ..metadata import load_local_metadata

logger = logging.getLogger(__name__)

@click.command()
@click.option("--depth", default=3, help="How deep to show the tree (1=Main, 2=Sub, 3=Series, 4=SubGroups).")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts).")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow).")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
@click.option("--xml", required=False, is_flag=False, flag_value="stdout", help="Output as XML. Provide a filename to save, or omit to print to console.")
@click.option("--skinny", is_flag=True, help="Minimize XML output size (no paths, counts, or sizes).")
def tree(depth: int, deep: bool, verify: bool, no_cache: bool, xml: Optional[str], skinny: bool) -> None:
    """Visualizes the library structure."""
    logger.info(f"Tree command started (depth={depth}, deep={deep}, verify={verify}, no_cache={no_cache}, xml={xml}, skinny={skinny})")
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Building Tree...",
        use_cache=not no_cache
    )

    if deep or verify:
        # For tree, we analyze everything in the library since there is no query filter
        perform_deep_analysis([library], deep, verify)

    if xml:
        import xml.etree.ElementTree as ET
        
        if skinny:
            root_elem = ET.Element("Library")
        else:
            root_elem = ET.Element("Library", path=str(library.path))
        
        for main_cat in library.categories:
            if skinny:
                main_node = ET.SubElement(root_elem, "Category", name=main_cat.name)
            else:
                main_node = ET.SubElement(root_elem, "Category", name=main_cat.name, type="Main", series_count=str(main_cat.total_series_count))
            
            if depth >= 2:
                for sub_cat in main_cat.sub_categories:
                    if skinny:
                        sub_node = ET.SubElement(main_node, "Subcategory", name=sub_cat.name)
                    else:
                        sub_node = ET.SubElement(main_node, "Category", name=sub_cat.name, type="Sub", series_count=str(sub_cat.total_series_count))
                    
                    if depth >= 3:
                        for series in sub_cat.series:
                            if skinny:
                                attrs = {"name": series.name}
                                try:
                                    meta = load_local_metadata(series.path)
                                    if meta:
                                        if meta.genres:
                                            attrs["genres"] = ", ".join(meta.genres)
                                        if meta.tags:
                                            attrs["tags"] = ", ".join(meta.tags)
                                except Exception:
                                    pass # Ignore metadata load errors in tree view
                            else:
                                attrs = {
                                    "name": series.name,
                                    "path": str(series.path),
                                    "volume_count": str(series.total_volume_count),
                                    "size_bytes": str(series.total_size_bytes)
                                }
                                if deep:
                                    attrs["page_count"] = str(series.total_page_count)
                                
                            s_node = ET.SubElement(sub_node, "Series", **attrs)
                            
                            if depth >= 4:
                                for sg in series.sub_groups:
                                    if skinny:
                                        sg_attrs = {"name": sg.name}
                                    else:
                                        sg_attrs = {
                                            "name": sg.name,
                                            "volume_count": str(len(sg.volumes))
                                        }
                                    ET.SubElement(s_node, "SubGroup", **sg_attrs)

        # Python 3.9+ support for indentation
        if hasattr(ET, "indent"):
            ET.indent(root_elem, space="  ", level=0)
            
        tree_str = ET.tostring(root_elem, encoding="unicode")
        
        if xml == "stdout":
            # Print plain text to avoid rich formatting interpretation of tags
            print(tree_str)
        else:
            try:
                with open(xml, "w", encoding="utf-8") as f:
                    f.write(tree_str)
                console.print(f"[green]XML tree saved to {xml}[/green]")
            except Exception as e:
                console.print(f"[red]Error saving XML to {xml}: {e}[/red]")
        return

    root_tree = Tree(f":open_file_folder: [bold]{library.path.name}[/bold]")

    for main_cat in library.categories:
        main_node = root_tree.add(f":file_folder: [yellow]{main_cat.name}[/yellow]")
        
        if depth >= 2:
            for sub_cat in main_cat.sub_categories:
                sub_node = main_node.add(f":file_folder: [cyan]{sub_cat.name}[/cyan] ({sub_cat.total_series_count} series)")
                
                if depth >= 3:
                    for series in sub_cat.series:
                        series_info = f"{series.name}"
                        if series.is_complex:
                            series_info += f" [dim]({len(series.sub_groups)} sub-groups)[/dim]"
                        else:
                            series_info += f" [dim]({len(series.volumes)} vols)[/dim]"
                            
                        series_node = sub_node.add(f":book: {series_info}")
                        
                        if depth >= 4:
                            for sg in series.sub_groups:
                                series_node.add(f":file_folder: [dim]{sg.name}[/dim] ({len(sg.volumes)} vols)")

    console.print(root_tree)
