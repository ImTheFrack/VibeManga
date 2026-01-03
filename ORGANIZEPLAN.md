# Implementation Plan: `organize` Command

**Objective:** Create a granular, filter-based command for **restructuring** (Move) or **selective export** (Copy) of the manga library.
**Status:** Updated to align with Phase 2 CLI Refactoring architecture.

## 1. Core Logic (`vibe_manga/categorizer.py`)

*   **Goal:** Enable "Directed Categorization" and schema adaptation.
*   **Changes:**
    *   Update `get_category_list` function signature to accept an optional `restrict_to_main` string parameter.
    *   Update `suggest_category` function signature to accept:
        *   `custom_categories` (List[str]): For supporting `--newroot` schemas.
        *   `restrict_to_main` (str): For limiting AI choices to a specific parent category.
    *   **Logic:** If `restrict_to_main` is present, filter the available category list (whether from library or custom_categories) to only include paths starting with that main category.

## 2. The New Command (`vibe_manga/cli/organize.py`)

*   **File:** `vibe_manga/vibe_manga/cli/organize.py` (New File)
*   **Registration:** Import in `vibe_manga/vibe_manga/main.py` to expose as `organize`.
*   **Default Behavior:** **Filesystem MOVE** within the current library.
*   **Newroot Behavior:** **Filesystem COPY** from current library to new root.

### Dependencies
*   From `..base`: `console`, `run_scan_with_progress`, `get_library_root`
*   From `..config`: `get_config`
*   From `..logging`: `get_logger`
*   From `..indexer`: `LibraryIndex`
*   From `..categorizer`: `suggest_category`

### Options

**Arguments:** `[QUERY]` (Optional name search).

**Filters (Multi-Value Allowed):**
*   `--tag [TAG]` / `--no-tag [TAG]`: Include/Exclude series based on tags.
*   `--genre [GENRE]` / `--no-genre [GENRE]`: Include/Exclude series based on genres.
*   `--source [CATEGORY]` / `--no-source [CATEGORY]`: Include/Exclude based on current location (Main or Sub category name).

**Actions:**
*   `--target [DESTINATION]`:
    *   **Specific (Main/Sub):** (e.g., `Manga/Action`) Direct operation. No AI.
    *   **Main Only:** (e.g., `Manga`) AI Assisted.
        *   *Standard:* AI picks sub-category from current library schema restricted to "Manga".
        *   *Newroot:* AI picks sub-category from **NEW ROOT's** schema (if exists) restricted to "Manga".
    *   **Omitted:** Full AI.
        *   *Standard:* AI picks from entire current library schema.
        *   *Newroot:* AI picks from entire **NEW ROOT's** schema.

**Safety & Overrides:**
*   `--auto`: Skip confirmation prompts.
*   `--simulate`: Dry run (Show what would happen without modifying files).
*   `--newroot [PATH]`: **THE ONLY COPY MODE.** Switches operation from Move to Copy. Content is duplicated to the new path, preserving source.

## 3. Logic Flow

### Phase 1: Setup
1.  **Scan Library:** Use `run_scan_with_progress` (from `cli.base`) to get the current library state.
2.  **Build Index:** Initialize and build `LibraryIndex` from the scanned library to ensure fast lookups and identity resolution.
3.  **Determine Mode & Schema:**
    *   **IF `--newroot` provided:**
        *   Check if path exists (create if needed/prompt).
        *   Scan new root folder for existing folder structure to build `custom_schema`.
        *   Set **Mode = COPY**.
        *   Set **Base Destination = New Root Path**.
    *   **ELSE:**
        *   Use `get_library_root()` (from `cli.base`) for default path.
        *   Set `custom_schema = None`.
        *   Set **Mode = MOVE**.
        *   Set **Base Destination = Current Library Path**.

### Phase 2: Filter
1.  **Hydration Check:** Iterate through series. If `series.metadata.mal_id` is None, trigger a lightweight hydration warning or prompt (since accurate filtering requires metadata).
2.  **Apply Filters:**
    *   **Inclusion Logic:** If any inclusion flags (`--tag`, `--genre`, `--source`) are set, the series MUST match *at least one* of them. 
        *   *Note:* Checks `Series.metadata.tags` and `Series.metadata.genres`. `--source` checks `Series.parent.name`.
    *   **Exclusion Logic:** If any exclusion flags (`--no-tag`, etc.) are set, the series MUST NOT match *any* of them.
    *   **Query Logic:** If `[QUERY]` arg is present, resolve target series using `LibraryIndex.search(query)` (matches titles, synonyms, IDs) instead of raw string matching.

### Phase 3: Execution
1.  **Iterate Candidates:** Loop through filtered list.
2.  **Determine Target Path:**
    *   **Case A (Direct):** User provided "Main/Sub". Target is fixed.
    *   **Case B (AI):** User provided "Main" or nothing.
        *   Call `suggest_category(series, ..., custom_categories=custom_schema, restrict_to_main=target_main)`.
        *   Get consensus result.
        *   Construct target path from result.
3.  **Perform Operation:**
    *   **Simulate:** Print "[SIMULATE] Would Move/Copy X to Y".
    *   **Real:**
        *   Ensure destination parent exists.
        *   **IF Mode == COPY:** `shutil.copytree` / `shutil.copy2`.
        *   **IF Mode == MOVE:** `shutil.move`.
        *   **Cleanup:** If Move, remove empty source directories.

## 4. Example Scenarios

*   **Standard Cleanup:**
    `organize --tag "Isekai" --target "Manga"`
    *   *Action:* **MOVES** all Isekai series to `Manga/[AI-Selected-Sub]` in current drive.

*   **Selective Export:**
    `organize --newroot "D:/Backups" --genre "Romance"`
    *   *Action:* **COPIES** all Romance series to `D:/Backups/[AI-Selected-Main]/[AI-Selected-Sub]`. The AI aligns with whatever folder structure exists on D:.

## 5. Relationship with `categorize`
The `organize` command is designed as a strict superset of the existing `categorize` command (now located at `vibe_manga/cli/categorize.py`).
*   **Equivalence:** Running `organize --source "Uncategorized"` is functionally identical to running `categorize`.
*   **Strategy:**
    1.  Implement `organize` as a standalone command in `vibe_manga/cli/organize.py`.
    2.  Retain `vibe_manga/cli/categorize.py` as-is for now to ensure stability.
    3.  Once `organize` is fully tested and verified, `vibe_manga/cli/categorize.py` can be refactored to simply call `organize` logic or be deprecated.