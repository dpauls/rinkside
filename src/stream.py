#!/usr/bin/env python3
"""
Stream manager: associate YouTube livestream URLs with games.

Usage:
    python3 src/stream.py <game_id> <youtube_url>
    python3 src/stream.py --list
    python3 src/stream.py --remove <game_id>
"""
import argparse
import json
import os
import sys
from pathlib import Path

STREAMS_FILE = Path('data/streams.json')


def load_streams():
    if STREAMS_FILE.exists():
        try:
            with open(STREAMS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: could not read {STREAMS_FILE}: {e}", file=sys.stderr)
    return {}


def save_streams(streams):
    STREAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STREAMS_FILE, 'w') as f:
        json.dump(streams, f, indent=2)
    print(f"Saved streams to {STREAMS_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Manage live stream URLs for games.")
    parser.add_argument('game_id', nargs='?', help="Game ID (e.g. 45722)")
    parser.add_argument('url', nargs='?', help="YouTube or streaming URL")
    parser.add_argument('--list', action='store_true', help="List all configured streams")
    parser.add_argument('--remove', help="Remove stream URL for a specific game ID")
    parser.add_argument('--no-generate', action='store_true', help="Skip auto-generating state.json")

    args = parser.parse_args()
    streams = load_streams()

    if args.list:
        if not streams:
            print("No active streams configured.")
        else:
            print("Configured Streams:")
            for gid, url in streams.items():
                print(f"  Game #{gid} -> {url}")
        return

    if args.remove:
        gid = str(args.remove)
        if gid in streams:
            del streams[gid]
            save_streams(streams)
            print(f"Removed stream for game #{gid}")
        else:
            print(f"Game #{gid} had no stream configured.")
        return

    if not args.game_id or not args.url:
        parser.print_help()
        sys.exit(1)

    gid = str(args.game_id)
    url = args.url.strip()
    streams[gid] = url
    save_streams(streams)
    print(f"Attached stream to game #{gid}: {url}")

    if not args.no_generate:
        print("Regenerating tournament state...")
        try:
            # Add src to sys.path so generate can import its dependencies
            src_dir = str(Path(__file__).resolve().parent)
            if src_dir not in sys.path:
                sys.path.insert(0, src_dir)
            from generate import generate
            generate(skip_narrative=True)
            print("✓ State updated with stream URL.")
        except Exception as e:
            print(f"Note: Run 'python3 src/generate.py' to update state ({e})")


if __name__ == '__main__':
    main()
