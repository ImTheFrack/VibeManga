from vibe_manga.vibe_manga.cli.scrape import generate_search_alternatives

def test_alternatives_generation():
    # Test 1: Simple query with no special chars
    query = "Frieren"
    alts = generate_search_alternatives(query)
    # Should only return original since no special chars or stop words removal changes it significantly
    assert alts == ["Frieren"]

    # Test 2: Special characters
    query = "Re:Zero"
    alts = generate_search_alternatives(query)
    # 1. Re:Zero
    # 2. Re Zero
    # 3. Re Zero (keywords) - Duplicate of 2
    assert "Re:Zero" in alts
    assert "Re Zero" in alts
    assert len(alts) == 2

    # Test 3: Stop words
    query = "Heaven Official's Blessing"
    alts = generate_search_alternatives(query)
    # 1. Heaven Official's Blessing
    # 2. Heaven Official s Blessing
    # 3. Heaven Official Blessing (keywords: Heaven, Official, Blessing) - 's' is stop word
    # 4. Heaven Official (first 2 keywords)
    
    assert "Heaven Official's Blessing" in alts
    assert "Heaven Official s Blessing" in alts
    # Depending on STOP_WORDS, 's' might be removed. 's' IS in STOP_WORDS in constants.py.
    # So "Heaven Official Blessing" should be generated.
    assert "Heaven Official Blessing" in alts
    
    # Check first 2 keywords
    assert "Heaven Official" in alts

    # Test 4: Long title
    query = "The 100 Girlfriends Who Really Really Really Really Really Love You"
    alts = generate_search_alternatives(query)
    
    assert query in alts
    # Sanitized -> The 100 Girlfriends ...
    # Keywords -> 100 Girlfriends Really Really Really Really Really Love (removed The, You, Who)
    # First 2 -> 100 Girlfriends
    
    assert "100 Girlfriends" in alts

    # Test 5: Only stop words?
    query = "The The"
    alts = generate_search_alternatives(query)
    # Should just return original and sanitized
    assert "The The" in alts
