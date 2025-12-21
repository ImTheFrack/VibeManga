from vibe_manga.vibe_manga.analysis import classify_unit

names = [
    "The Apothecary Diaries: Xiaolan's Story 001-007 (2025) (Digital) (Oak)",
    "The Apothecary Diaries: Xiaolan's Story 001-007 as v01 (Digital-Compilation) (Oak-JXL)",
    "The Apothecary Diaries: Xiaolan's Story 001-007 as v01 (Digital-Compilation) (Oak)"
]

for n in names:
    v, c, u = classify_unit(n)
    print(f"Name: {n}")
    print(f"  Vols: {v}")
    print(f"  Chaps: {c}")
    print(f"  Units: {u}")
