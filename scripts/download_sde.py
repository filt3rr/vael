"""
Download and decompress the Fuzzwork SDE SQLite mirror.

Run:
    python scripts/download_sde.py

Downloads sqlite-latest.sqlite.bz2 (~130 MB compressed),
decompresses to data/sde.sqlite (~528 MB), and removes the archive.
"""

import bz2
import shutil
import sys
import urllib.request
from pathlib import Path

SDE_URL = "https://www.fuzzwork.co.uk/dump/sqlite-latest.sqlite.bz2"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
BZ2_PATH = DATA_DIR / "sqlite-latest.sqlite.bz2"
SDE_PATH = DATA_DIR / "sde.sqlite"


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if SDE_PATH.exists():
        size_mb = SDE_PATH.stat().st_size / (1024 * 1024)
        print(f"SDE already exists at {SDE_PATH} ({size_mb:.0f} MB).")
        resp = input("Re-download? [y/N] ").strip().lower()
        if resp != "y":
            print("Skipping download.")
            return 0
        SDE_PATH.unlink()

    print(f"Downloading SDE from {SDE_URL}")
    print("This is ~130 MB compressed. Progress is shown below.")
    print()

    def _progress(block_count, block_size, total_size):
        downloaded = block_count * block_size
        if total_size > 0:
            pct = min(100, downloaded / total_size * 100)
            mb = downloaded / (1024 * 1024)
            print(f"\r  {pct:.0f}%  {mb:.0f} MB", end="", flush=True)

    try:
        urllib.request.urlretrieve(SDE_URL, BZ2_PATH, reporthook=_progress)
    except Exception as e:
        print(f"\nDownload failed: {e}")
        if BZ2_PATH.exists():
            BZ2_PATH.unlink()
        return 1

    print(f"\nDecompressing to {SDE_PATH}...")

    try:
        with bz2.open(BZ2_PATH, "rb") as src, open(SDE_PATH, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except Exception as e:
        print(f"Decompression failed: {e}")
        return 1

    BZ2_PATH.unlink()

    size_mb = SDE_PATH.stat().st_size / (1024 * 1024)
    print(f"Done. SDE at {SDE_PATH} ({size_mb:.0f} MB)")

    # Quick sanity check
    import sqlite3
    conn = sqlite3.connect(str(SDE_PATH))
    count = conn.execute("SELECT COUNT(*) FROM invTypes").fetchone()[0]
    conn.close()
    print(f"Sanity check: {count:,} item types in database.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
