"""Download a portable PostgreSQL for the local test suite (once). Nothing is installed and no admin rights are needed:
the official binaries are unpacked into backend/.pg/pgsql (gitignored), and the tests start a throwaway server from
them for each run (tests/conftest.py).

Run from backend/:
    .venv\\Scripts\\python.exe scripts/get_test_postgres.py

Windows only (the EDB binaries zip). On macOS / Linux, install PostgreSQL 17 with your package manager instead and set
BEE_PG_BIN to its bin folder, or point TEST_DATABASE_ADMIN_URL at any Postgres the tests may create databases on.
"""

import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "17.7-1"   # the major version Neon runs by default
URL = f"https://get.enterprisedb.com/postgresql/postgresql-{VERSION}-windows-x64-binaries.zip"
ROOT = Path(__file__).resolve().parent.parent / ".pg"


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit(__doc__)
    target = ROOT / "pgsql" / "bin" / "initdb.exe"
    if target.exists():
        print(f"Already there: {target.parent}")
        return
    download = ROOT / "download"
    download.mkdir(parents=True, exist_ok=True)
    zip_path = download / URL.rsplit("/", 1)[1]
    if not zip_path.exists():
        print(f"Downloading {URL} (about 300 MB)...")
        urllib.request.urlretrieve(URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/"))]
        z.extractall(ROOT, names)
    print(f"Unpacked {len(names)} files into {ROOT / 'pgsql'}. Run the tests with: python -m pytest")


if __name__ == "__main__":
    main()
