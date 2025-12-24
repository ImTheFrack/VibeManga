import logging
import json
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from rich.console import Console
from rich.prompt import Confirm, Prompt

from .models import Library, Category, Series
from .metadata import SeriesMetadata, get_or_create_metadata
from .ai_api import call_ai
from .constants import ROLE_CONFIG
from .config import get_role_config

logger = logging.getLogger(__name__)
console = Console()

def get_ai_categorization(
    series_name: str,
    metadata: SeriesMetadata,
    available_categories: List[str],
    user_feedback: Optional[str] = None
) -> Dict[str, Any]:
    """
    Orchestrates the AI categorization flow:
    1. Moderator check
    2. Practical suggestion
    3. Creative suggestion
    4. Consensus decision (with validation loop)
    """
    results = {}

    with console.status(f"[bold blue]Analyzing '{series_name}'...[/bold blue]") as status:
        # 1. Moderator
        status.update(f"[bold blue]Step 1/4: Consulting Moderator...[/bold blue]")
        mod_config = get_role_config("MODERATOR")
        mod_prompt = f"Manga Title: {series_name}\nSynopsis: {metadata.synopsis}\nGenres: {metadata.genres}\nTags: {metadata.tags}"
        moderation = call_ai(mod_prompt, mod_config["role_prompt"], provider=mod_config["provider"], model=mod_config["model"])
        if not isinstance(moderation, dict):
            logger.error(f"Moderator AI returned invalid data: {type(moderation)}. Defaulting to SAFE.")
            moderation = {"classification": "SAFE", "reason": f"AI Error: Invalid response ({str(moderation)[:50]}...)"}
        results["moderation"] = moderation
        
        # 2. Practical
        status.update(f"[bold blue]Step 2/4: Consulting Practical Analyst...[/bold blue]")
        prac_config = get_role_config("PRACTICAL")
        prac_prompt = f"Manga: {series_name}\nMetadata: {metadata.to_dict()}\nCategories: {available_categories}"
        practical = call_ai(prac_prompt, prac_config["role_prompt"], provider=prac_config["provider"], model=prac_config["model"])
        if not isinstance(practical, dict):
             logger.error(f"Practical AI returned invalid data. Defaulting.")
             practical = {"category": "Uncategorized/Error", "reason": "AI Error: Invalid response"}
        results["practical"] = practical
        
        # 3. Creative
        status.update(f"[bold blue]Step 3/4: Consulting Creative Director...[/bold blue]")
        crea_config = get_role_config("CREATIVE")
        crea_prompt = f"Manga: {series_name}\nMetadata: {metadata.to_dict()}\nCategories: {available_categories}"
        creative = call_ai(crea_prompt, crea_config["role_prompt"], provider=crea_config["provider"], model=crea_config["model"])
        if not isinstance(creative, dict):
             logger.error(f"Creative AI returned invalid data. Defaulting.")
             creative = {"category": "Uncategorized/Error", "reason": "AI Error: Invalid response"}
        results["creative"] = creative
        
        # 4. Consensus with Validation Loop
        status.update(f"[bold blue]Step 4/4: Reaching Consensus...[/bold blue]")
        cons_config = get_role_config("CONSENSUS")
        
        # Base prompt components
        base_cons_prompt = (
            f"Manga: {series_name}\n"
            f"Genres: {metadata.genres}\n"
            f"Tags: {metadata.tags}\n"
            f"Official Category List: {available_categories}\n"
            f"Moderator View: {moderation}\n"
            f"Pragmatic View: {practical}\n"
            f"Creative View: {creative}\n"
        )

        if user_feedback:
            base_cons_prompt += (
                f"\nUSER FEEDBACK / INSTRUCTION:\n"
                f"The user has explicitly requested: '{user_feedback}'.\n"
                f"IMPORTANT: This feedback overrides previous constraints. "
                f"If the user disputes a Moderation flag, you HAVE AUTHORITY to override the Moderator "
                f"and place the series in a standard category if the user's reasoning is valid.\n"
            )
        
        # Helper to format the prompt request
        def make_prompt(error_context: str = "") -> str:
            p = base_cons_prompt
            if error_context:
                p += f"\n\nIMPORTANT CORRECTION REQUEST:\n{error_context}"
            p += (
                "\n\nYou MUST return a JSON object with fields: "
                "'final_category' (Main Category), 'final_sub_category' (Sub Category), "
                "'reason', and 'confidence_score' (float)."
            )
            return p

        current_prompt = make_prompt()
        attempts = 0
        max_retries = 3
        
        while attempts < max_retries:
            attempts += 1
            if attempts > 1:
                status.update(f"[bold yellow]Step 4/4: Reaching Consensus (Attempt {attempts}/{max_retries})...[/bold yellow]")
            
            consensus = call_ai(
                current_prompt, 
                cons_config["role_prompt"], 
                provider=cons_config["provider"], 
                model=cons_config["model"],
                json_mode=True
            )
            
            # Basic Type Check
            if not isinstance(consensus, dict):
                logger.warning(f"Consensus returned non-dict: {type(consensus)}")
                current_prompt = make_prompt("Last response was not valid JSON. Please return strictly JSON.")
                continue

            # Extract fields
            cat = consensus.get("final_category")
            sub = consensus.get("final_sub_category")
            
            if not cat or not sub:
                logger.warning("Consensus missing category fields")
                current_prompt = make_prompt("Missing 'final_category' or 'final_sub_category' fields.")
                continue

            suggested_full = f"{cat}/{sub}"
            
            # Check 1: Is it in the list?
            if suggested_full in available_categories:
                # Valid match found
                status.stop()
                console.print(f"[green]AI matched existing category:[/green] {suggested_full}")
                status.start()
                results["consensus"] = consensus
                return results
            
            # Check 2: Structure Validation (No path separators allowed in individual names)
            invalid_chars = ['/', '\\', ':']
            if any(char in cat for char in invalid_chars) or any(char in sub for char in invalid_chars):
                logger.warning(f"Consensus returned invalid characters in category name: {suggested_full}")
                current_prompt = make_prompt(
                    f"The category '{suggested_full}' contains invalid characters (slashes or colons). "
                    "Please ensure 'final_category' and 'final_sub_category' are simple names without path separators."
                )
                continue
            
            # Check 3: User Decision on New Category
            status.stop() # Pause spinner for user input
            console.print(f"\n[bold yellow]AI suggested a new category:[/bold yellow] [cyan]{suggested_full}[/cyan]")
            console.print(f"[dim]Reason: {consensus.get('reason')}[/dim]")
            
            if Confirm.ask("Accept this new category?", default=True):
                status.start()
                results["consensus"] = consensus
                return results
            else:
                # User rejected. Force retry with restriction.
                console.print("[yellow]Requesting AI to pick from existing list...[/yellow]")
                status.start()
                current_prompt = make_prompt(
                    f"The user REJECTED the new category '{suggested_full}'. "
                    f"You MUST strictly choose one from the 'Official Category List' provided above."
                )
                
        # If we run out of retries, return the last one but warn log
        logger.warning(f"Consensus validation failed after {max_retries} attempts.")
        results["consensus"] = consensus # Return whatever we have last
        
    return results

def get_category_list(library: Library) -> List[str]:
    """Helper to extract flat list of categories from library."""
    available = []
    for cat in library.categories:
        if cat.name == "Uncategorized":
            continue
        for sub in cat.sub_categories:
            available.append(f"{cat.name}/{sub.name}")
    
    if not available:
        available = ["Manga/Action", "Manga/Romance", "Manga/Comedy", "Adult/Hentai"]
    return available

def suggest_category(
    series: Series,
    library: Library,
    user_feedback: Optional[str] = None,
    custom_categories: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetches metadata and AI suggestions for a single series.
    """
    # Get metadata
    metadata, source = get_or_create_metadata(series.path, series.name)
    
    # Get flat list of current categories (Main/Sub)
    if custom_categories is not None:
        available = custom_categories
    else:
        available = get_category_list(library)
        
    logger.info(f"Requesting AI categorization for '{series.name}'...")
    results = get_ai_categorization(series.name, metadata, available, user_feedback=user_feedback)
    
    # Attach metadata to results for display/use in UI
    results["metadata"] = metadata
    
    return results
