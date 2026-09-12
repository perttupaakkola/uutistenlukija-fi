import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .controller import ingest, load_config, single_tick, tick
from .editorial import ROOT
from .intake import collect
from .site import atomic_write, render_site
from .store import database


def main():
    parser = argparse.ArgumentParser(description="Fresh news MVP — local private workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "ingest", "collect", "tick", "live-tick", "render", "status", "stop"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        if name == "ingest":
            p.add_argument("packet", type=Path)
        if name == "collect":
            p.add_argument("recipe", type=Path)
            p.add_argument("--revise-rejected", action="store_true", help="Explicit evidence amendment; retain saved draft and archive prior rejection")
    p = sub.add_parser("demo", help="Run a clearly labelled fabricated local example, no model/network")
    p.add_argument("--output", type=Path, default=Path(".demo"))
    args = parser.parse_args()
    try:
        if args.command == "demo":
            root = args.output.resolve()
            root.mkdir(parents=True, exist_ok=True)
            config_path = root / "config.json"
            # Refuse to overwrite an existing operator configuration.
            if not config_path.exists():
                atomic_write(config_path, json.dumps({"enabled": True, "backend": "fixture",
                                                      "state_dir": "state", "output_dir": "site"}))
            config = load_config(config_path)
            if config["backend"] != "fixture":
                raise ValueError("Demo requires a dedicated fixture configuration")
            packet = json.loads((ROOT / "fixtures/source-packet.json").read_text())
            # Fixture clock is explicitly synthetic/current; never a real source timestamp.
            for source in packet["sources"]:
                source["published_at"] = datetime.now(timezone.utc).isoformat()
            admission = ingest(config, packet)
            result = {"fixture": True, "admission": admission, "tick": tick(config_path),
                      "private_site": str(config["output_dir"] / "index.html")}
        elif args.command == "stop":
            config = json.loads(args.config.read_text())
            config["enabled"] = False
            atomic_write(args.config, json.dumps(config, indent=2) + "\n")
            result = {"status": "stopped"}
        else:
            config = load_config(args.config)
            if args.command == "collect":
                if config["backend"] != "hermes":
                    raise ValueError("Real source collection requires a live configuration, never fixture mode")
                packet, receipt = collect(json.loads(args.recipe.read_text()), config["state_dir"])
                if args.revise_rejected:
                    from .intake import revise_rejected
                    admission = revise_rejected(config, packet)
                else:
                    admission = ingest(config, packet)
                result = {"intake": receipt, "admission": admission}
            elif args.command == "ingest":
                result = ingest(config, json.loads(args.packet.read_text()))
            elif args.command == "live-tick":
                from .live import live_tick
                result = live_tick(args.config)
            elif args.command == "tick":
                result = tick(args.config)
            elif args.command == "render":
                with single_tick(config["state_dir"]) as locked:
                    if not locked:
                        raise ValueError("Another tick is running")
                    with database(config["state_dir"]) as store:
                        result = {"articles": render_site(store, config["output_dir"], config["state_dir"])}
            else:
                with database(config["state_dir"]) as store:
                    result = {"jobs": store.status()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
