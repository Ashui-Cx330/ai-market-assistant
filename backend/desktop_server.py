import argparse
import multiprocessing
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# Parse the data root before importing backend.main. PyInstaller's one-file
# bootstrap can otherwise import database.py before the inherited environment
# is fully available, leaving that process attached to its temporary seed DB.
_bootstrap_parser = argparse.ArgumentParser(add_help=False)
_bootstrap_parser.add_argument("--data-dir")
_bootstrap_args, _ = _bootstrap_parser.parse_known_args()
if _bootstrap_args.data_dir:
    os.environ["TRADING_AI_DATA_DIR"] = str(Path(_bootstrap_args.data_dir).resolve())


def migrate_codex_virtualized_data(data_dir: Path) -> None:
    """Merge records written through Windows MSIX file virtualization once."""
    marker = data_dir / "migration-codex-msix-v1.done"
    target = data_dir / "database" / "trading_ai.db"
    if marker.exists() or not target.exists():
        return
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = list((local / "Packages").glob("OpenAI.Codex_*/LocalCache/Roaming/AI行情助手/database/trading_ai.db"))
    sources = [item for item in candidates if item.exists() and item.resolve() != target.resolve()]
    if not sources:
        return
    backup = target.with_name(f"trading_ai.pre-msix-merge-{datetime.now().strftime('%Y%m%d%H%M%S')}.db")
    shutil.copy2(target, backup)
    with sqlite3.connect(target) as conn:
        conn.execute("ATTACH DATABASE ? AS legacy", (str(max(sources, key=lambda item: item.stat().st_mtime)),))
        main_tables = {row[0] for row in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        legacy_tables = {row[0] for row in conn.execute("SELECT name FROM legacy.sqlite_master WHERE type='table'")}
        for table in sorted((main_tables & legacy_tables) - {"sqlite_sequence"}):
            safe_table = table.replace('"', '""')
            main_columns = [row[1] for row in conn.execute(f'PRAGMA main.table_info("{safe_table}")')]
            legacy_columns = {row[1] for row in conn.execute(f'PRAGMA legacy.table_info("{safe_table}")')}
            columns = [column for column in main_columns if column in legacy_columns]
            if not columns:
                continue
            quoted = ",".join(f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns)
            conn.execute(f'INSERT OR IGNORE INTO main."{safe_table}" ({quoted}) SELECT {quoted} FROM legacy."{safe_table}"')
        conn.commit()
    marker.write_text(f"merged={datetime.now(timezone.utc).isoformat()}\nbackup={backup}\n", encoding="utf-8")


if _bootstrap_args.data_dir:
    try:
        migrate_codex_virtualized_data(Path(_bootstrap_args.data_dir))
    except Exception:
        # The target DB remains protected by its pre-merge backup; startup must
        # continue even if a developer-only legacy source is malformed.
        pass


BOOT_LOG = Path(os.environ.get("TRADING_AI_DATA_DIR") or os.environ.get("TEMP") or ".") / "backend-boot.log"


def boot(stage: str) -> None:
    try:
        BOOT_LOG.parent.mkdir(parents=True,exist_ok=True)
        with BOOT_LOG.open("a",encoding="utf-8") as stream:stream.write(f"{datetime.now(timezone.utc).isoformat()} {stage}\n")
    except OSError:pass


boot("bootstrap")

import uvicorn
boot("uvicorn-imported")
from backend.main import app
boot("application-imported")


def main():
    boot("main-entered")
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    boot(f"server-starting port={args.port}")
    try:
        # A windowless PyInstaller executable has no sys.stderr. Uvicorn's
        # default colour formatter probes that stream and can abort startup.
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False,log_config=None)
        boot("server-returned")
    except BaseException as exc:
        boot(f"fatal {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
