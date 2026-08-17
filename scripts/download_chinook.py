"""Download the official Chinook SQLite sample database."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path


SOURCE = (
    "https://raw.githubusercontent.com/lerocha/chinook-database/master/"
    "ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"
)
TARGET = Path(__file__).resolve().parents[1] / "data" / "Chinook_Sqlite.sqlite"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".download")
    print(f"正在从官方仓库下载 Chinook：{SOURCE}")
    try:
        with urllib.request.urlopen(SOURCE, timeout=30) as response:
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
        temporary.replace(TARGET)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"已保存到：{TARGET}")


if __name__ == "__main__":
    main()
