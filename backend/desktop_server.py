import argparse
import multiprocessing
import os
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
