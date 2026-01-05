import os
import re

"""
Constants used throughout the VibeManga application.
"""

# File Extensions
VALID_MANGA_EXTENSIONS = {'.cbz', '.cbr', '.zip', '.rar', '.pdf', '.epub'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.avif'}

# Analysis & Metadata
VALID_DEMOGRAPHICS = {'Shounen', 'Seinen', 'Shoujo', 'Josei', 'Shonen'}
CLEAN_WORD_RE = re.compile(r'[^a-z]')

# Common English stop words for synopsis analysis
STOP_WORDS = {
    # Articles & Conjunctions
    'the', 'and', 'to', 'of', 'in', 'is', 'it', 'with', 'for', 'that', 'as', 'on', 'was', 'at', 'by',
    'an', 'be', 'this', 'which', 'from', 'but', 'not', 'or', 'nor', 'yet', 'so', 'if', 'than', 'then',
    'although', 'because', 'since', 'unless', 'until', 'while', 'whether', 'though',
    # Pronouns
    'his', 'her', 'their', 'they', 'she', 'he', 'him', 'them', 'its', 'their', 'theirs', 'himself',
    'herself', 'themselves', 'itself', 'myself', 'yourself', 'ourselves', 'yourselves', 'mine', 'yours',
    'ours', 'who', 'whom', 'whose', 'which', 'what', 'whatever', 'whichever', 'whoever', 'whomever',
    'this', 'that', 'these', 'those', 'each', 'every', 'any', 'all', 'both', 'few', 'many', 'most',
    'other', 'another', 'some', 'such', 'neither', 'either', 'someone', 'anyone', 'everyone', 'nobody',
    'no', 'yes', 'own', 'me', 'us', 'you', 'my', 'our', 'your', 'hes', 'hers',
    # Prepositions & Adverbs
    'about', 'above', 'across', 'after', 'against', 'along', 'amid', 'among', 'around', 'at', 'before',
    'behind', 'below', 'beneath', 'beside', 'besides', 'between', 'beyond', 'by', 'down', 'during',
    'except', 'from', 'inside', 'into', 'like', 'near', 'off', 'onto', 'out', 'outside', 'over', 'past',
    'since', 'through', 'throughout', 'till', 'toward', 'towards', 'under', 'underneath', 'until', 'up',
    'upon', 'within', 'without', 'very', 'now', 'there', 'where', 'when', 'how', 'always', 'never',
    'often', 'sometimes', 'usually', 'already', 'still', 'just', 'even', 'also', 'only', 'well',
    'almost', 'enough', 'quite', 'rather', 'too', 'fairly', 'nearly', 'again', 'further', 'once',
    'here', 'why', 'somewhere', 'anywhere', 'everywhere', 'nowhere'
    # Verbs (Auxiliary/Common)
    'am', 'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did',
    'doing', 'can', 'could', 'will', 'would', 'shall', 'should', 'may', 'might', 'must', 'get', 'got',
    'go', 'goes', 'went', 'gone', 'come', 'comes', 'came', 'become', 'becomes', 'became', 'find',
    'finds', 'found', 'take', 'takes', 'took', 'taken', 'make', 'makes', 'made', 'see', 'sees', 'saw',
    'seen', 'know', 'knows', 'knew', 'known', 'think', 'thinks', 'thought', 'want', 'wants', 'wanted',
    'look', 'looks', 'looked', 'use', 'uses', 'used', 'give', 'gives', 'gave', 'given', 'keep', 'keeps',
    # Numbers & Ordinals
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
    'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty',
    'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety', 'hundred', 'thousand', 'million',
    'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
    # Meta/Manga Specific Noise
    'source', 'mal', 'written', 'rewrite', 'synopsis', 'background', 'manga', 'series', 'chapter',
    'volume', 'publication', 'publishing', 'published', 'author', 'artist', 'illustration', 'illustrated',
    'serialized', 'magazine', 'adapted', 'adaptation', 'anime', 'tv', 'movie', 'film', 'theatrical',
    'version', 'complete', 'edition', 'special', 'additional', 'includes', 'including', 'containing',
    'however', 'story', 'world', 'life', 'years', 'man', 'time', 'day', 'new', 'way', 'back', 'around',
    # Custom
    'more','despite','begins','shes','hes', 'usa','ever,','soon','away','named','begins','begin',
    'kodansha','girls','girl','boys','boy', 'womens','women','women','called','men','man','mens',
    'suddenly','long','short','meets','meet','decides','next','finally','final','eventually',
    'something','everything','everything','anything','nothing'
}

# Analysis Thresholds
SIMILARITY_THRESHOLD = 0.95  # Threshold for fuzzy matching duplicate detection
FUZZY_MATCH_THRESHOLD = 95  # Threshold for matching scraped names to library series (0-100)
MAX_RANGE_SIZE = 200  # Maximum allowed range size to avoid parsing year ranges like 1-2021
YEAR_RANGE_MIN = 1900  # Minimum year value to filter out from number extraction
YEAR_RANGE_MAX = 2150  # Maximum year value to filter out from number extraction
MIN_VOL_SIZE_MB = 35
MIN_CHAP_SIZE_MB = 3

# Cache Configuration
DEFAULT_CACHE_MAX_AGE_SECONDS = 3000  # 3000 seconds (50 minutes)
CACHE_FILENAME = ".vibe_manga_cache.pkl"
LIBRARY_STATE_FILENAME = "vibe_manga_library.json"

# Display Configuration
DEFAULT_TREE_DEPTH = 2
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024 * 1024 * 1024

# Series Aliases for Matching
SERIES_ALIASES = {
    "100 Girlfriends Who Really, Really, Really, Really, Really Love You, The": [
        "Hyakkano",
        "The 100 Girlfriends Who Really Really Really Really REALLY Love You",
    ],
}

# Progress Display
PROGRESS_REFRESH_RATE = 10  # Refresh per second for progress bars
DEEP_ANALYSIS_REFRESH_RATE = 5  # Refresh per second for deep analysis

# Scraper Configuration
NYAA_BASE_URL = "https://nyaa.si"
NYAA_ENGLISH_TRANSLATED_URL_TEMPLATE = f"{NYAA_BASE_URL}/?f=0&c=3_1&q=&p={{page}}"
NYAA_SEARCH_URL_TEMPLATE = f"{NYAA_BASE_URL}/?f=0&c=3_1&q={{query}}&p={{page}}"
SCRAPER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
SCRAPER_RATE_LIMIT_PER_SECOND = 3
NYAA_DEFAULT_OUTPUT_FILENAME = "nyaa_scrape_results.json"
SCRAPE_HISTORY_FILENAME = "vibe_manga_scrape_history.json"
SCRAPE_QUERY_COOLDOWN_DAYS = 30
SCRAPER_RETRY_COUNT = 3
SCRAPER_RETRY_BACKOFF_FACTOR = 0.5
SCRAPER_TIMEOUT_SECONDS = 15

# qBittorrent API Configuration
QBIT_DEFAULT_TAG = "VibeManga"
QBIT_DEFAULT_CATEGORY = "VibeManga"
QBIT_DEFAULT_SAVEPATH = "VibeManga"
QBIT_DOWNLOAD_ROOT = os.getenv("QBIT_DOWNLOAD_ROOT", "")
PULL_TEMPDIR = os.getenv("PULL_TEMPDIR", "")

# Nyaa.si Scraper Internals
NYAA_DEFAULT_PAGES_TO_SCRAPE = 60
NYAA_TORRENT_TABLE_SELECTOR = "div.table-responsive table.torrent-list tbody tr"
NYAA_MIN_COLUMNS = 8
NYAA_COL_IDX_NAME = 1
NYAA_COL_IDX_LINKS = 2
NYAA_COL_IDX_SIZE = 3
NYAA_COL_IDX_DATE = 4
NYAA_COL_IDX_SEEDERS = 5
NYAA_COL_IDX_LEECHERS = 6
NYAA_COL_IDX_COMPLETED = 7

# AI Configuration
# Remote (Default settings for the provider)
REMOTE_AI_BASE_URL = os.getenv("REMOTE_AI_BASE_URL", "https://openrouter.ai/api/v1")
REMOTE_AI_API_KEY = os.getenv("REMOTE_AI_API_KEY", "")
REMOTE_AI_MODEL = os.getenv("REMOTE_AI_MODEL", "google/gemini-flash-1.5")

# Local (Default settings for the provider)
LOCAL_AI_BASE_URL = os.getenv("LOCAL_AI_BASE_URL", "http://localhost:11434/v1")
LOCAL_AI_API_KEY = os.getenv("LOCAL_AI_API_KEY", "ollama")
LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", "llama3")

# Global Settings
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "3"))

# AI Role Configuration
# This is the central place to edit AI behavior, providers, and models.
ROLE_CONFIG = {
    "METADATA": {
        "provider": "remote",
        "model": "google/gemini-flash-1.5",
        "role_prompt": (
            "You are a metadata extraction specialist. "
            "Your goal is to provide accurate details for a given manga series. "
            "Output: Return ONLY a JSON object matching the schema:\n"
            "{\n"
            "    \"title\": \"str\",\n"
            "    \"authors\": [\"str\"],\n"
            "    \"synopsis\": \"str\",\n"
            "    \"genres\": [\"str\"],\n"
            "    \"tags\": [\"str\"],\n"
            "    \"demographics\": [\"str\"],\n"
            "    \"status\": \"Completed\" | \"Ongoing\" | \"Hiatus\" | \"Cancelled\",\n"
            "    \"total_volumes\": int | null,\n"
            "    \"total_chapters\": int | null,\n"
            "    \"release_year\": int | null,\n"
            "    \"mal_id\": int | null,\n"
            "    \"anilist_id\": int | null\n"
            "}"
        )
    },
    "SUPERVISOR": {
        "provider": "remote",
        "model": "google/gemini-flash-1.5",
        "role_prompt": (
            "You are a Metadata Quality Supervisor. "
            "Inputs: 'User Query' (folder name) and 'API Metadata' (from Jikan/MAL).\n"
            "Tasks:\n"
            "1. VERIFY: Does the API Metadata match the User Query? Be extremely strict with spinoffs, fanbooks, and subtitles. "
            "If the User Query contains a specific subtitle (e.g., 'Corps Records', 'Gaiden', 'Side Story') that is NOT present in the API Metadata titles, you MUST set is_match=false.\n"
            "2. ENRICH: If is_match=true, fill in missing (null) fields using your own knowledge. "
            "If is_match=false, provide the CORRECT metadata for the User Query in the 'metadata' field, including the correct MAL ID and titles if you know them.\n"
            "Output: Return ONLY a JSON object:\n"
            "{\n"
            "    \"is_match\": true/false,\n"
            "    \"reason\": \"explanation\",\n"
            "    \"metadata\": { ... same schema as METADATA ... }\n"
            "}"
        )
    },
    "MODERATOR": {
        "provider": "local",
        "model": LOCAL_AI_MODEL,
        "role_prompt": (
            "You are a strict content safety moderator for a US-based manga library. Violence, perversion, etc. does not make something ADULT, even if it's for teens or adults. ONLY explicit sexual content qualifies as ADULT. Illegal content MUST be flagged as ILLEGAL. "
            "Classify content as: \n"
            "1. SAFE: Standard manga (includes gore/ecchi).\n"
            "2. ADULT: Explicit Hentai/Pornography.\n"
            "3. ILLEGAL: CP/CSAM/Hate Speech.\n"
            "Output: Return ONLY a JSON object: {\"classification\": \"SAFE|ADULT|ILLEGAL\", \"reason\": \"str\"}."
        )
    },
    "PRACTICAL": {
        "provider": "local",
        "model": LOCAL_AI_MODEL,
        "role_prompt": (
            "You are a Pragmatic Librarian. Suggest the best category based on Genre/Demographics. "
            "Prioritize structural fit. Do not invent categories. "
            "Output: Return ONLY a JSON object: {\"category\": \"Main/Sub\", \"reason\": \"str\"}."
        )
    },
    "CREATIVE": {
        "provider": "remote",
        "model": "openrouter.google/gemini-3-flash-preview",
        "role_prompt": (
            "You are a Creative Literary Analyst. Suggest the best category based on Synopsis/Vibe/Themes. "
            "Look beyond technical tags for the 'soul' of the series. "
            "Output: Return ONLY a JSON object: {\"category\": \"Main/Sub\", \"reason\": \"str\"}."
        )
    },
    "CONSENSUS": {
        "provider": "remote",
        "model": "openrouter.google/gemini-3-flash-preview",
        "role_prompt": (
            """You are the Head Librarian. Reach a final decision based on metadata and agent views. \n
            ### GUIDELINES:\n
            A. **Balance:** Weigh the Practical (Structure) and Creative (Vibe) suggestions to find the best fit.\n
            B. **Structure:** We are picking a single category and subcategory, so we need to be very judicious. You MUST prioritize the 'Official Category List' provided in the input. Below under HIERARCHY is a detailed description of why we put things where we do into each category.\n
                1. "Adult, Ecchi & Fanservice" ("ADULT" for short): IT IS CRITICAL AND OF PARAMOUNT IMPORTANCE that adult, ecchi and fanservice content should generally go into this ADULT category unless there is a compelling reason otherwise.\n
                    a. Strongly scrutinize series with 'Ecchi', 'Smut', or 'Mature' tags, or an 'ADULT' moderator flag, or that contain sexual content, for placement in this ADULT category.\n
                    b. Once you have determined it belongs in this category, sub-classify series based on primary genre and narrative intent using these specific benchmarks:
                      i. Use ADULT's 'Action & Supernatural Ecchi' subcategory for battle-heavy or high-stakes plots (e.g., 'Freezing', 'Highschool of the Dead').\n
                      ii. Use ADULT's 'Comedy, Harem & Rom-Com' subcategory for humor-driven or 'lucky pervert' scenarios (e.g., 'To Love Ru', 'Uzaki-chan').\n
                      iii.Use ADULT's 'Fantasy, Isekai & Monster Girls' subcategory for magic, other worlds, or species-focused titles (e.g., 'Interspecies Reviewers', 'Parallel Paradise').\n
                      iv. Truly Explicit content is sorted by plot depth in the ADULT category:
                        - Place serialized, character-driven erotic dramas and intense romances in 'Mature Romance & Erotic Drama (e.g., 'Nana to Kaoru', 'Nozoki Ana', 'Fire in His Fingertips')\n
                        - Reserving 'Adult Anthology & Short Series (18+)' for plot-light, short-form, or pure pornography (e.g., 'Bible Black', 'Elf Who Likes To Be Humiliated').\n
                      v. Finally, strictly separate LGBTQ+ themes in the ADULT category as follows as 'Boys' Love (BL) & Omegaverse' (e.g., 'Titan's Bride') or 'Girls' Love (GL) & Yuri' (e.g., 'Murciélago').\n
                2. "Action, Adventure & Adrenaline" ("ACTION" for short): Use for high-energy, plot-driven series with significant action, adventure, or suspense elements.  Prioritize narrative drive and conflict type over the specific setting.\n
                    a. Use ACTION's 'Battle Shonen & Supernatural Powers' for protagonists with supernatural abilities (ki, magic, quirks) fighting in escalated battles. **CRITICAL:** This includes "Fantasy Battle" series (e.g., 'Fairy Tail', 'Black Clover', 'Radiant') and "Space Battle" series (e.g., 'Edens Zero') IF they follow the standard Shonen formula (Guilds, Tournaments, Power Scaling). **Only** exclude fantasy series if they are slow-paced, atmospheric adventures (e.g., 'Frieren') or generic Isekai.\n
                    b. Move all structured physical competitions, including traditional sports, martial arts tournaments, and non-lethal rivalries, into ACTION's 'Sports, Combat & Competition' (e.g., 'Blue Lock', 'Hinomaru Sumo', 'Kengan Ashura').\n
                    c. Crucially, distinguish those from ACTION's 'Survival Games & Dystopia', which is reserved for death games, battle royales, and post-apocalyptic scenarios where loss equals death (e.g., 'Alice in Borderland', 'Zatch Bell!').\n
                    d. Use ACTION's 'Dark Fantasy & Gore' for visceral, bleak, or horror-adjacent action (e.g., 'Chainsaw Man', 'Berserk').\n
                    e. Differentiate grounded violence by setting:\n
                      i. Place criminal hierarchies and delinquents in ACTION's 'Crime, Yakuza & Underworld' (e.g., 'Tokyo Revengers')\n
                      ii. Place tactical espionage and warfare in ACTION's 'Guns, Spies & Military' (e.g., 'Spy x Family')\n
                      iii. Place historical swordplay in ACTION's 'Samurai, Period Pieces & Historical' (e.g., 'Kingdom', 'Vagabond').\n
                    f. Finally, assign ACTION's 'Mystery, Detective & Thriller' when deduction or suspense outweighs the physical combat (e.g., 'Death Note', 'Bungo Stray Dogs').\n
                3. "Adaptations and Compilations" ("ADAPTATIONS" for short): This category serves as the primary destination for any manga series that is explicitly an adaptation of another media property (books, comics, games, movies, TV) or a compilation/supplementary material to an existing manga franchise.\n
                    a. **CRITICALLY, if a series is an adaptation of non-manga media and could fit into another non-adult genre category (e.g., a game adaptation with action), it MUST be placed in this ADAPTATIONS category instead.**\n
                    b. Use ADAPTATIONS' 'Artbooks and Compilations' for non-narrative supplementary materials such as art books, guidebooks, and short story collections directly related to an existing manga series (e.g., 'Demon Slayer: Kimetsu no Yaiba - Corps Records', 'Vagabond Art Books').\n
                    c. Use ADAPTATIONS' 'Books & Comics' for manga adaptations of literature (non-Japanese novels) or non-manga comic books (e.g., 'Spider-Man - Fake Red', 'Anne of Green Gables').\n
                    d. Use ADAPTATIONS' 'Games' for manga directly based on video game franchises, regardless of genre (e.g., 'Elden Ring: The Road to the Erdtree', 'Persona 5', 'Legend of Zelda: Twilight Princess').\n
                    e. Use ADAPTATIONS' 'Movies & TV' for manga directly adapted from film or television series, whether live-action or animated, that originated as screen media (e.g., 'Star Wars: v. 1', 'Sherlock: The Great Game', 'Blame!').\n
                4. "Comedy, Drama & Slice of Life" ("SLICE" for short): Use this category for stories driven by character interaction, emotional growth, humor, or daily routines rather than physical combat or high-stakes adventure.\n
                    a. Use SLICE's 'Gag, Parody & Sketch' for series where humor is the primary goal, including 4-koma, absurdist comedy, and parodies. Even if there is fighting, if the intent is satire (e.g., 'Mashle', 'One-Punch Man', 'Nichijou'), place it here.\n
                    b. Use SLICE's 'Hobby, Food & Performing Arts' for series focused on the intricacies of a specific activity, craft, or art form (e.g., 'Blue Period' [Art], 'Bocchi the Rock!' [Music], 'Delicious in Dungeon' [Cooking]). **CRITICAL EXCEPTION:** If the series focuses on **competitive** athletics or winning tournaments (e.g., 'Haikyu!!', 'Slam Dunk', 'Ace of the Diamond'), it MUST go to ACTION's 'Sports, Combat & Competition'. Keep only non-competitive or artistic club activities here.\n
                    c. Use SLICE's 'Human Drama & Psychological' for serious, character-driven narratives focused on emotional depth, trauma, societal critique, or the entertainment industry (e.g., '[Oshi no Ko]', 'March Comes in Like a Lion', 'Beastars').  **However, if the drama focuses on athletes or professional sports, prefer ACTION's 'Sports, Combat & Competition'.**\n
                    d. Use SLICE's 'Iyashikei (Healing) & Comfort' for low-stakes, low-tension atmospheric series designed to relax the reader. This includes "Cute Girls Doing Cute Things," pet ownership, and slow-life stories (e.g., 'Yotsuba&!', 'Laid-Back Camp', 'Aria').\n
                    e. Use SLICE's 'School Life & Coming of Age (Non-Romance)' for stories set in school that focus on friendship, growing up, or student council life *without* a primary focus on romance or competitive sports (e.g., 'Skip and Loafer', 'Azumanga Daioh'). If the plot is primarily about who dates whom, move to ROMANCE.\n
                5. "Isekai, Systems & Transmigration" ("ISEKAI" for short): Use this category for series where the protagonist is transported to another world (Isekai), reincarnated (Tensei), or lives in a world governed by explicit "Game Systems" (Leveling, Status Screens). **CRITICAL:** Do not place generic High Fantasy (Elves/Dwarves native to their own world) here; they must have an Earth-origin protagonist or explicit Game UI elements.\n
                    a. Use ISEKAI's 'Dungeons, Towers & Modern Systems' for series set on Earth or a modern setting where dungeons/towers appear, and the protagonist uses a "System" to level up (e.g., 'Solo Leveling', 'Dungeon Dive: Aim for the Deepest Level').\n
                    b. Use ISEKAI's 'Power Fantasy & Leveling Systems' for standard Isekai where the primary focus is becoming overpowered (OP), collecting skills, and fighting demon lords (e.g., 'Arifureta', 'That Time I Got Reincarnated as a Slime', 'Rising of the Shield Hero').\n
                    c. Use ISEKAI's 'Reincarnation, Regression & Second Chances' for stories focusing on "Redoing Life" or being reborn as a child/baby to live a better life, often with knowledge of the future (e.g., 'Mushoku Tensei', 'The Eminence in Shadow').\n
                    d. Use ISEKAI's 'Slow Life, Management, Farming & Nation Building' for series where the protagonist opts out of fighting to build a town, run a shop, farm, or cook. Prioritize "Crafting/Building" over "Fighting" here (e.g., 'Farming Life in Another World', 'Ascendance of a Bookworm', 'Campfire Cooking in Another World').\n
                    e. Use ISEKAI's 'Villainess, Court Intrigue & Otome Games' for stories where the protagonist is reincarnated into a Dating Sim (Otome Game) or novel, usually as the villainess or rival character, focusing on social maneuvering and romance over combat (e.g., 'My Next Life as a Villainess', 'Trapped in a Dating Sim'). **EXCEPTION:** If the story is a historical drama without reincarnation or game knowledge (e.g., 'The Apothecary Diaries'), place it in ACTION's 'Historical' or MYSTERY.\n
                6. "New Worlds, Sci-Fi, Fantasy & Myth" ("WORLDS" for short): Use this category for series where the *setting itself* is the primary draw—whether it's a secondary fantasy world, outer space, or a world infused with folklore. **CRITICAL EXCLUSION:** If the series is primarily a "Battle Shonen" (fighting tournaments, power escalation, guilds) disguised as fantasy (e.g., 'Fairy Tail', 'Black Clover', 'Radiant'), it MUST go to ACTION.\n
                    a. Use WORLDS' 'High Fantasy, Magic Worlds & Adventure' for traditional adventures in secondary worlds involving elves, dwarves, dragons, and magic. The focus should be on *exploration* and *world-building* rather than non-stop fighting tournaments (e.g., 'Frieren: Beyond Journey's End', 'Witch Hat Atelier', 'Drifting Dragons').\n
                    b. Use WORLDS' 'Horror, Ghosts, Zombies & Occult' for series intended to scare or unsettle the reader. This includes ghost stories, zombie outbreaks, and body horror (e.g., 'Junji Ito', 'Mieruko-chan', 'Zom 100'). **EXCEPTION:** If the zombies/monsters are just fodder for an overpowered hero to slaughter coolly (e.g., 'Chainsaw Man'), consider ACTION's 'Dark Fantasy'.\n
                    c. Use WORLDS' 'Mythology, Yokai & Folklore' for series heavily rooted in real-world myths (Japanese Yokai, Greek Gods) or atmospheric supernatural tales that are more "mystical" than "action-packed" (e.g., 'The Ancient Magus' Bride', 'Mushishi', 'Natsume's Book of Friends').\n
                    d. Use WORLDS' 'Sci-Fi, Cyberpunk, Mecha & Space' for futuristic settings, space operas, robots, and advanced technology (e.g., 'Ghost in the Shell', 'Mobile Suit Gundam', 'Planetes'). **EXCEPTION:** If it is a "Battle Shonen in Space" (e.g., 'Edens Zero'), move to ACTION.\n
                    e. Use WORLDS' 'Urban Fantasy & Modern Supernatural' for stories set in the modern world where magic/monsters exist but are hidden or integrated. The tone is often mystery or drama (e.g., 'Call of the Night', 'Bakemonogatari'). **EXCEPTION:** If it is a high-octane battle series between exorcists/sorcerers (e.g., 'Blue Exorcist', 'A Certain Scientific Railgun'), move to ACTION's 'Battle Shonen'.\n
                                7. "Romance & Relationships" ("ROMANCE" for short): Use this category for series where the development of a romantic relationship is the central plot engine. **CRITICAL:** While many genres contain romance, only place series here if the relationship *is* the plot.\n
                    a. Use ROMANCE's 'BL, GL, & LGBTQ+ Connections' for any series primarily focused on same-sex relationships (Yuri/Yaoi/Danmei). **Priority Rule:** If a series is LGBTQ+, place it here regardless of setting (e.g., 'Grandmaster of Demonic Cultivation', 'Bloom Into You'), unless it is sexually explicit porn (then ADULT).\n
                    b. Use ROMANCE's 'Fantasy & Historical Romance' for romances set in other worlds or eras. **CRITICAL EXCLUSION:** Do not place "Villainess," "Otome Game," or "Saint Reincarnation" plots here; they MUST go to ISEKAI. Do not place "Adventure" focused High Fantasy here (e.g., 'Yona of the Dawn'); send to WORLDS.\n
                    c. Use ROMANCE's 'Love Triangles, Workplace & Josei' for mature (non-pornographic) stories about adults, office life, and complex relationship tangles (e.g., 'Wotakoi', 'Honey and Clover').\n
                    d. Use ROMANCE's 'RomCom & Fluff' for humor-focused romance, lighthearted plots, and Harem comedies (e.g., 'Kaguya-sama', 'The 100 Girlfriends...', 'Yamada-kun and the Seven Witches').\n
                    e. Use ROMANCE's 'School Romance & First Love' for drama-focused stories set in high school involving first loves and emotional growth (e.g., 'Horimiya', 'Kimi ni Todoke'). **EXCEPTION:** If the series features sports but the plot is driven by the relationship (e.g., 'Blue Box'), keep it here. If the plot is about winning the championship, send to ACTION's 'Sports'.\n
            C. **Confidence Scoring:** Assign a confidence score (0.0-1.0) based on how well the series fits the chosen category.\n
            D. **Justification:** Provide a brief reason for your final decision, highlighting key factors from the metadata and agent suggestions.\n
            E. **Strict fit:** If neither agent provides a suitable category, select the closest match from the 'Official Category List' provided in the input, and explain your choice, but you MUST pick a single category and subcategory combination that exists in the Official Category List.\n
            F. **Output**: Return ONLY a JSON object: {\"final_category\": \"Main\", \"final_sub_category\": \"Sub\", \"confidence_score\": 0.0-1.0, \"reason\": \"str\"}."""
        )
    }
}
