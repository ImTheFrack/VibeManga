from dotenv import load_dotenv, find_dotenv
# Load environment variables before any other imports
load_dotenv(find_dotenv())

from vibe_manga.vibe_manga.main import cli

if __name__ == "__main__":
    cli()
