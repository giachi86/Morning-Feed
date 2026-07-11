#!/usr/bin/env python3
"""Generate local audio and a podcast RSS feed using only macOS tools."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def generate_audio(text_file: Path, output: Path, voice: str, rate: str) -> None:
    with tempfile.TemporaryDirectory(prefix="morning-feed-") as temp_dir:
        temporary_audio = Path(temp_dir) / f"episode{output.suffix}"
        for attempt in range(3):
            temporary_audio.unlink(missing_ok=True)
            edge_tts = ROOT.parent / ".venv" / "bin" / "edge-tts"
            subprocess.run(
                [
                    str(edge_tts), "--voice", voice, f"--rate={rate}",
                    "--file", str(text_file), "--write-media", str(temporary_audio),
                ],
                check=True,
            )
            probe = subprocess.run(
                ["afinfo", str(temporary_audio)], capture_output=True, text=True
            )
            if (
                probe.returncode == 0
                and temporary_audio.stat().st_size > 4096
                and "Num Tracks:     1" in probe.stdout
            ):
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(temporary_audio, output)
                return
            if attempt < 2:
                time.sleep(2)
    output.unlink(missing_ok=True)
    raise RuntimeError("macOS non ha generato un file audio valido dopo 3 tentativi")


def rebuild_feed(show: str, config: dict) -> Path:
    show_cfg = config["shows"][show]
    show_dir = ROOT / "public" / show
    episodes_dir = show_dir / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    base_url = config["base_url"].rstrip("/")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = show_cfg["title"]
    ET.SubElement(channel, "description").text = show_cfg["description"]
    ET.SubElement(channel, "language").text = "it-IT"
    ET.SubElement(channel, "link").text = f"{base_url}/{show}/"

    metadata_files = sorted(episodes_dir.glob("*.json"), reverse=True)
    keep = metadata_files[: int(config["retention"])]
    for old_meta in metadata_files[int(config["retention"]):]:
        old_audio = old_meta.with_suffix(".m4a")
        old_meta.unlink(missing_ok=True)
        old_audio.unlink(missing_ok=True)

    for meta_path in keep:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        audio_path = meta_path.with_suffix(meta.get("audio_suffix", ".m4a"))
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = meta["title"]
        ET.SubElement(item, "description").text = meta["description"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = meta["guid"]
        published = datetime.fromisoformat(meta["published_at"])
        ET.SubElement(item, "pubDate").text = format_datetime(published)
        audio_url = f"{base_url}/{show}/episodes/{audio_path.name}"
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": audio_url,
                "length": str(audio_path.stat().st_size),
                "type": "audio/mpeg" if audio_path.suffix == ".mp3" else "audio/mp4",
            },
        )

    feed = show_dir / "feed.xml"
    ET.indent(rss)
    ET.ElementTree(rss).write(feed, encoding="utf-8", xml_declaration=True)
    return feed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("show", choices=("ai", "mercati"))
    parser.add_argument("text_file", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    args = parser.parse_args()

    config = load_config()
    if not config["base_url"]:
        raise SystemExit("Imposta base_url in podcast/config.json prima di pubblicare.")

    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d-%H%M")
    episodes = ROOT / "public" / args.show / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    suffix = "." + config.get("audio_format", "m4a")
    audio = episodes / f"{stamp}{suffix}"
    generate_audio(args.text_file, audio, config["voice"], config.get("voice_rate", "+0%"))
    metadata = {
        "title": args.title,
        "description": args.description,
        "guid": f"{args.show}-{stamp}",
        "published_at": now.isoformat(),
        "audio_suffix": suffix,
    }
    audio.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(rebuild_feed(args.show, config))


if __name__ == "__main__":
    main()
