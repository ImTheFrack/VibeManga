import logging
import json
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Callable

from .models import Library, Category, Series
from .metadata import SeriesMetadata, get_or_create_metadata
from .ai_api import call_ai
from .constants import ROLE_CONFIG
from .config import get_ai_role_config, get_ai_config  # Import from config.py

logger = logging.getLogger(__name__)

def _fetch_agent_opinion(
    role_name: str, 
    base_prompt: str, 
    update_status: Optional[Callable[[str], None]],
    default_response: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Helper to fetch AI response with smart retries for JSON errors.
    """
    config = get_ai_role_config(role_name)
    current_prompt = base_prompt
    max_retries = 2
    
    for attempt in range(max_retries + 1):
        if attempt > 0 and update_status:
            update_status(f"Step: {role_name} (Retry {attempt})...")
            
        response = call_ai(
            current_prompt, 
            config["role_prompt"], 
            provider=config["provider"], 
            model=config["model"],
            json_mode=True
        )
        
        if isinstance(response, dict):
            return response
            
        # Failed to get dict
        logger.warning(f"{role_name} returned invalid data: {type(response)}")
        current_prompt = base_prompt + f"\n\nERROR: Your last response was not valid JSON. Please return strictly JSON object."

    logger.error(f"{role_name} failed after {max_retries} retries. Defaulting.")
    return default_response

def get_ai_categorization(
    series_name: str,
    metadata: SeriesMetadata,
    available_categories: List[str],
    user_feedback: Optional[str] = None,
    current_category: Optional[str] = None,
    quiet: bool = False,
    status_callback: Optional[Callable[[str], None]] = None,
    confirm_callback: Optional[Callable[[str, str], bool]] = None
) -> Dict[str, Any]:
    """
    Orchestrates the AI categorization flow:
    1. Moderator check
    2. Practical suggestion
    3. Creative suggestion
    4. Consensus decision (with validation loop)
    """
    results = {}

    def update_status(msg):
        if status_callback:
            status_callback(msg)
        elif not quiet:
            logger.info(msg)

    # 1. Moderator
    update_status(f"Step 1/4: Consulting Moderator...")
    mod_prompt = f"Manga Title: {series_name}\nSynopsis: {metadata.synopsis}\nGenres: {metadata.genres}\nTags: {metadata.tags}"
    results["moderation"] = _fetch_agent_opinion(
        "MODERATOR", 
        mod_prompt, 
        update_status, 
        default_response={"classification": "SAFE", "reason": "AI Error: Invalid response"}
    )
    
    # 2. Practical
    update_status(f"Step 2/4: Consulting Practical Analyst...")
    prac_prompt = f"Manga: {series_name}\nMetadata: {metadata.to_dict()}\nCategories: {available_categories}"
    results["practical"] = _fetch_agent_opinion(
        "PRACTICAL",
        prac_prompt,
        update_status,
        default_response={"category": "Uncategorized/Error", "reason": "AI Error: Invalid response"}
    )
    
    # 3. Creative
    update_status(f"Step 3/4: Consulting Creative Director...")
    crea_prompt = f"Manga: {series_name}\nMetadata: {metadata.to_dict()}\nCategories: {available_categories}"
    results["creative"] = _fetch_agent_opinion(
        "CREATIVE",
        crea_prompt,
        update_status,
        default_response={"category": "Uncategorized/Error", "reason": "AI Error: Invalid response"}
    )
    
    # 4. Consensus with Validation Loop
    update_status(f"Step 4/4: Reaching Consensus...")
    cons_config = get_ai_role_config("CONSENSUS")
    
    # Base prompt components
    base_cons_prompt = (
        f"Manga: {series_name}\n"
        f"Genres: {metadata.genres}\n"
        f"Tags: {metadata.tags}\n"
        f"Official Category List: {available_categories}\n"
        f"Moderator View: {results['moderation']}\n"
        f"Pragmatic View: {results['practical']}\n"
        f"Creative View: {results['creative']}\n"
    )

    # Inject Current Category if known
    if current_category:
        base_cons_prompt += f"Current Location: {current_category}\n"

    # Inject User Narrative Rules
    narrative_rules = get_ai_config().get_narrative_content()
    if narrative_rules:
        base_cons_prompt += (
            f"\n### USER NARRATIVE & CATEGORIZATION RULES (PRIMARY AUTHORITY):\n"
            f"The user has provided the following narrative design rules which MUST take precedence over standard logic and agent views:\n"
            f"{narrative_rules}\n"
        )

    if user_feedback:
        base_cons_prompt += (
            f"\nUSER FEEDBACK / INSTRUCTION:\n"
            f"The user has explicitly requested or added the following details: '{user_feedback}'.\n"
            f"IMPORTANT: This feedback overrides previous constraints. "
            f"You are to use your own judgment but the User's feedback overrides the moderator, pragmatic, and creative views. \n"
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
            update_status(f"Step 4/4: Reaching Consensus (Attempt {attempts}/{max_retries})...")
        
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
        # If confirm_callback provided, ask it. 
        # If NOT provided (Auto/Batch mode), we default to REJECTING new categories to prevent hallucinations,
        # forcing the AI to retry and pick from the official list.
        accepted = False
        rejection_msg = f"The suggested category '{suggested_full}' is NOT in the Official Category List."
        
        if confirm_callback:
            reason = consensus.get('reason', 'No reason provided')
            if confirm_callback(suggested_full, reason):
                accepted = True
            else:
                accepted = False
                rejection_msg = f"The user REJECTED the new category '{suggested_full}'."
        
        if accepted:
            results["consensus"] = consensus
            return results
        else:
            # User rejected or Auto-rejected. Force retry with restriction.
            update_status("Invalid/New category suggested. Requesting AI to pick from official list...")
            current_prompt = make_prompt(
                f"{rejection_msg} "
                f"You MUST strictly choose one from the 'Official Category List' provided above."
            )
            
    # If we run out of retries, return the last one but warn log
    logger.warning(f"Consensus validation failed after {max_retries} attempts.")
    results["consensus"] = consensus # Return whatever we have last
    
    return results

def get_category_list(library: Library, restrict_to_main: Optional[str] = None) -> List[str]:
    """Helper to extract flat list of categories from library."""
    available = []
    for cat in library.categories:
        if restrict_to_main and cat.name != restrict_to_main:
            continue
            
        if cat.name == "Uncategorized":
            continue
        for sub in cat.sub_categories:
            available.append(f"{cat.name}/{sub.name}")
    
    if not available and not restrict_to_main:
        available = ["Manga/Action", "Manga/Romance", "Manga/Comedy", "Adult/Hentai"]
    return available

def suggest_category(
    series: Series,
    library: Library,
    user_feedback: Optional[str] = None,
    custom_categories: Optional[List[str]] = None,
    restrict_to_main: Optional[str] = None,
    quiet: bool = False,
    status_callback: Optional[Callable[[str], None]] = None,
    confirm_callback: Optional[Callable[[str, str], bool]] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetches metadata and AI suggestions for a single series.
    """
    # Get metadata
    metadata, source = get_or_create_metadata(series.path, series.name)
    
    # Get flat list of current categories (Main/Sub)
    if custom_categories is not None:
        available = custom_categories
        if restrict_to_main:
            available = [c for c in available if c.startswith(f"{restrict_to_main}/")]
    else:
        available = get_category_list(library, restrict_to_main=restrict_to_main)
        
    # Determine Current Category from path (e.g. .../Manga/Action/Naruto -> Manga/Action)
    current_cat = "Uncategorized"
    try:
        # Assuming path structure: Root/Main/Sub/Series
        # Relative to library root is easiest if possible, but series.path is absolute.
        # We can try to grab the parent and grandparent names.
        parent = series.path.parent.name
        grandparent = series.path.parent.parent.name
        # Simple heuristic check if grandparent is a category-like folder or root
        # Ideally we'd map this back to library structure, but this is a decent guess for the AI prompt
        current_cat = f"{grandparent}/{parent}"
    except Exception:
        pass

    logger.info(f"Requesting AI categorization for '{series.name}'...")
    results = get_ai_categorization(
        series.name, 
        metadata, 
        available, 
        user_feedback=user_feedback, 
        current_category=current_cat,
        quiet=quiet,
        status_callback=status_callback,
        confirm_callback=confirm_callback
    )
    
    # Attach metadata to results for display/use in UI
    results["metadata"] = metadata
    
    return results