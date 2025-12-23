import re
import difflib

# Copied from analysis.py
def semantic_normalize(name: str) -> str:
    """
    Highly aggressive normalization for semantic matching.
    Strips articles, tags, punctuation, and whitespace.
    """
    if not name: return ""
    # 1. Strip tags [...] (...) {...}
    # Using hex codes to avoid tool escape issues: [ = \x5B, ] = \x5D, ( = \x28, ) = \x29, { = \x7B, } = \x7D
    name = re.sub(r"\x5B.*?\x5D|\x28.*?\x29|\x7B.*?\x7D", " ", name)
    # 2. Strip articles
    name = re.sub(r"\b(The|A|An|Le|La|Les|Un|Une)\b", " ", name, flags=re.IGNORECASE)
    
    # 2b. Expand common symbols to alphanumeric equivalents
    name = name.replace("½", "1 2")
    name = name.replace("⅓", "1 3")
    name = name.replace("¼", "1 4")
    # Handle '&' (often 'and' or 'to')
    # If it's Yotsuba&! -> Yotsubato
    name = re.sub(r"(?<=\w)&(?!\w|\s)", "to", name)
    name = name.replace("&", " and ")

    # 3. Strip non-alphanumeric
    name = re.sub(r"[^a-zA-Z0-9]", "", name)
    # 4. Lowercase
    return name.lower()

def test_normalization():
    print("--- Test Normalization ---")
    
    t1 = "Bungo Stray Dogs: Wan!"
    t2 = "Bungo Stray Dogs： Wan!" # Full width colon
    t3 = "Bungo Stray Dogs - The Official Comic Anthology"
    t4 = "Bungo Stray Dogs"

    n1 = semantic_normalize(t1)
    n2 = semantic_normalize(t2)
    n3 = semantic_normalize(t3)
    n4 = semantic_normalize(t4)

    print(f'\' {t1} \' -> \' {n1} \'')
    print(f'\' {t2} \' -> \' {n2} \'')
    print(f'\' {t3} \' -> \' {n3} \'')
    print(f'\' {t4} \' -> \' {n4} \'')

    print(f"\nMatch 1 (ASCII vs FullWidth): '\'{n1}\' == '\'{n2}\' -> {n1 == n2}")
    
    ratio_false_pos = difflib.SequenceMatcher(None, n3, n4).ratio() * 100
    print(f"\nMatch 2 (Anthology vs Original) Ratio: {ratio_false_pos:.2f}%")

    print("\n--- Additional Check ---")
    # Check if maybe the user has "Bungo Stray Dogs" and matched "Bungo Stray Dogs - The Official Comic Anthology" 
    # via some other mechanism?
    
    # Is n4 in n3?
    print(f"Is '\'{n4}\' in '\'{n3}\'? {'Yes' if n4 in n3 else 'No'}")

if __name__ == "__main__":
    test_normalization()
