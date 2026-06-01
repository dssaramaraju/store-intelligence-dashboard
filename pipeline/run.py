import argparse
from pathlib import Path

from pipeline.detect import detect_from_inputs
from pipeline.emit import write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CCTV detection pipeline and emit structured events.")
    parser.add_argument("--input", default="./data", help="Directory containing challenge input files")
    parser.add_argument("--output", default="./events.jsonl", help="JSONL output path")
    parser.add_argument("--quiet", action="store_true", help="Suppress CCTV progress messages")
    args = parser.parse_args()

    events = detect_from_inputs(Path(args.input), verbose=not args.quiet)
    count = write_jsonl(events, Path(args.output))
    print(f"emitted_events={count} output={args.output}")


if __name__ == "__main__":
    main()
