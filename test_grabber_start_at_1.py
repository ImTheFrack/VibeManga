
def test_logic(case_name, l_v_set, f_data):
    print(f"\nTesting: {case_name}")
    # Mock context
    l_c_set = set() 
    new_v = set()
    new_c = set()
    max_local_vol = max(l_v_set) if l_v_set else 0
    cutoff_chapter = max_local_vol * 6
    print(f"  Local Vols: {l_v_set}, Cutoff: {cutoff_chapter}")

    # --- LOGIC COPY START ---
    f = f_data
    v_s, v_e = f.get("volume_begin"), f.get("volume_end")
    file_has_vols = False
    all_vols_known = True

    if v_s is not None:
        file_has_vols = True
        try:
            s, e = float(v_s), float(v_e or v_s)
            if s.is_integer() and e.is_integer():
                for n in range(int(s), int(e) + 1):
                    if float(n) not in l_v_set: 
                        new_v.add(float(n))
                        all_vols_known = False
            else:
                if s not in l_v_set: 
                    new_v.add(s)
                    all_vols_known = False
                if e not in l_v_set: 
                    new_v.add(e)
                    all_vols_known = False
        except (ValueError, TypeError): 
            all_vols_known = False

    skipped = False
    
    # Block 1: Redundant Chapters in Volume File
    if file_has_vols and all_vols_known:
        c_s_check = f.get("chapter_begin")
        try:
            if c_s_check:
                s_check = float(c_s_check)
                v_e_val = float(v_e or v_s) if v_s else 0
                if s_check <= v_e_val * 5:
                    skipped = True
        except (ValueError, TypeError): pass

    # Block 2: Start at 1 Heuristic (The New Fix)
    if not skipped:
        if l_v_set and not file_has_vols:
            c_s_check = f.get("chapter_begin")
            try:
                if c_s_check and float(c_s_check) <= 1.0:
                    skipped = True
            except (ValueError, TypeError): pass

    if skipped:
        print("  ACTION: Skipped (Redundant)")
    else:
        print("  ACTION: Processing chapters...")
        c_s, c_e = f.get("chapter_begin"), f.get("chapter_end")
        if c_s is not None:
            try:
                s, e = float(c_s), float(c_e or c_s)
                if s.is_integer() and e.is_integer():
                    for n in range(int(s), int(e) + 1):
                        if float(n) not in l_c_set and float(n) > cutoff_chapter:
                            new_c.add(float(n))
            except (ValueError, TypeError): pass
    
    # --- LOGIC END ---
    print(f"  Result New Chaps: {new_c}")
    return new_c

# Case 1: Angel Next Door File 3 (The Problem)
# Local: v1-2. File: c001-025.
# Expected: Skipped by Start-at-1 heuristic.
test_logic("Angel Next Door (File 3)", {1.0, 2.0}, {
    "chapter_begin": "1", "chapter_end": "25"
})

# Case 2: Legit New Chapters
# Local: v1-2. File: c026-030.
# Expected: Processed.
test_logic("Legit New Chapters", {1.0, 2.0}, {
    "chapter_begin": "26", "chapter_end": "30"
})

# Case 3: Chapter Only Series (No volumes locally)
# Local: {}. File: c001-025.
# Expected: Processed (l_v_set is empty, heuristic skipped).
test_logic("Chapter Only Series", set(), {
    "chapter_begin": "1", "chapter_end": "25"
})
