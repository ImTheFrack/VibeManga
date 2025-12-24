# Refactor Plan: Jikan/MAL as the Source of Truth

**Objective:**  
Move the VibeManga system from a **Path-Based Identity** system (where the folder name is the sole authority) to a **Metadata-Based Identity** system (where the MAL ID and Jikan metadata serve as the source of truth). This will significantly improve matching accuracy for torrents, handling of alternate titles (English vs. Japanese), and overall library consistency.

---

## Core Philosophy
1.  **Identity Resolution:** A Series is defined by its Unique ID (MAL ID), not its folder string.
2.  **Synonym Awareness:** A Series has multiple valid names (Folder Name, English Title, Japanese Title, Synonyms).
3.  **Metadata First:** Metadata should be loaded/hydrated *before* matching operations occur.

---

## Phase 1: Models & Indexing

### 1. Update `models.py`
Currently, `Series.metadata` is a raw `Dict`. It must be upgraded to use the strong schema from `metadata.py`.

*   **Task:** Import `SeriesMetadata` in `models.py`.
*   **Task:** Change `Series.metadata` type hint from `Dict[str, Any]` to `SeriesMetadata`.
*   **Task:** Add a property `@property def identities(self) -> Set[str]` to `Series`.
    *   This should return a set containing:
        *   The Folder Name.
        *   `metadata.title`
        *   `metadata.title_english`
        *   `metadata.title_japanese`
        *   All entries in `metadata.tags` (if they act as synonyms) or distinct synonyms list if added.
    *   *Note:* All strings returned should be raw (normalization happens in the Indexer).

### 2. Create `indexer.py`
Instead of passing a simple list of tuples to the `matcher`, we need a dedicated Indexer class to handle lookups.

*   **Class:** `LibraryIndex`
*   **Attributes:**
    *   `id_map`: `Dict[int, Series]` (Maps MAL ID -> Series Object).
    *   `title_map`: `Dict[str, List[Series]]` (Maps *Normalized* Title String -> List of Series Objects).
*   **Methods:**
    *   `build(library: Library)`: Iterates the library and populates maps.
    *   `search(query: str) -> List[Series]`: Returns exact normalized matches.
    *   `get_by_id(mal_id: int) -> Optional[Series]`: Fast lookup.

---

## Phase 2: Metadata Hydration

We cannot index what we don't have. We need a mechanism to ensure `series.json` exists for every folder.

### 1. Update `scanner.py`
*   Ensure `Series.from_dict` correctly re-hydrates the `SeriesMetadata` object.

### 2. New Command: `hydrate`
*   **Logic:** Iterate through all Series in the Library.
*   **Check:** If `series.metadata.mal_id` is None:
    *   Call `metadata.get_or_create_metadata(series.path, series.name)`.
    *   Save the result to `series.json`.
*   **Progress:** Use `rich` progress bar to show hydration status.

---

## Phase 3: Robust Matching (`matcher.py`)

Refactor `match_single_entry` to utilize the `LibraryIndex`.

### New Matching Strategy
1.  **ID Check (Future Proofing):** If the input entry (torrent) has a known MAL ID (e.g., from Nyaa description parsing), lookup directly in `LibraryIndex.id_map`.
2.  **Synonym Lookup:** 
    *   Normalize input name.
    *   Lookup in `LibraryIndex.title_map`.
    *   *Benefit:* Matches "Nanatsu no Taizai" to "The Seven Deadly Sins" instantly if Jikan lists it as an alternative title.
3.  **Fuzzy Match (Enhanced):**
    *   Instead of Fuzzy Matching `Input` vs `Folder Name`, Fuzzy Match `Input` vs `All Identities` of every series.
    *   This increases the surface area for a positive match.

---

## Phase 4: Standardization (Optional)

### New Command: `rename`
*   **Goal:** Rename local folders to match the Jikan "English Title" (or User Preference) to ensure filesystem consistency.
*   **Logic:**
    *   Iterate Library.
    *   Compare `Series.path.name` vs `Series.metadata.title`.
    *   If distinct (and confidence is high/trusted):
        *   Rename folder.
        *   Update `Series.path`.
        *   Update `Library` state.

---

## Implementation Prompt for AI

*Copy and paste the following prompt to an AI agent to begin implementation:*

```text
I need to implement Phase 1 of the "Source of Truth" refactor for VibeManga.

Context: We are shifting from folder-name matching to metadata-based matching using Jikan/MAL data.

Tasks:
1. Modify `vibe_manga/models.py`:
   - Import `SeriesMetadata` from `.metadata`.
   - Update the `Series` dataclass so the `metadata` field is of type `SeriesMetadata` (defaulting to an empty instance).
   - Update `Series.to_dict` and `Series.from_dict` to handle serialization of this nested object correctly.
   - Add a property `identities` to `Series` that returns a Set[str] of all valid titles (folder name, title, english, japanese, synonyms).

2. Create `vibe_manga/indexer.py`:
   - Create a class `LibraryIndex`.
   - Implement a `build(library: Library)` method that populates:
     - `self.mal_id_map`: Dict[int, Series]
     - `self.title_map`: Dict[str, List[Series]] (Keys must be processed via `analysis.semantic_normalize`).
   - Implement `search(query: str)` which normalizes the query and looks it up in `title_map`.

3. Existing Constraints:
   - Use existing `semantic_normalize` from `.analysis`.
   - Maintain compatibility with `dataclasses`.

Please implement these changes now.
```
