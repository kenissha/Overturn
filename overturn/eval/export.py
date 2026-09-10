"""Write the evaluation corpus to disk, so the letters can be read, uploaded and diffed.

    python -m overturn.eval.export corpus/samples

Each letter becomes ``<id>.txt`` — its pages separated by form feeds, exactly what the
upload endpoint accepts, invisible characters included where a letter plants them — and
``<id>.json``, its answer key and expectations. The files are generated; the source of
truth is overturn/eval/corpus.py, and a test holds the two in step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from overturn.eval.corpus import Sample, build_corpus

ROOT = Path(__file__).resolve().parents[2]
PAGE_BREAK = "\f"


def letter_text(sample: Sample) -> str:
    return PAGE_BREAK.join(sample.pages)


def answer_key(sample: Sample) -> dict:
    data = sample.model_dump(exclude={"pages"})
    data["gold"] = {name: gold for name, gold in data["gold"].items()}
    return data


def export(samples: list[Sample], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        (out_dir / f"{sample.sample_id}.txt").write_text(
            letter_text(sample), encoding="utf-8", newline="\n"
        )
        (out_dir / f"{sample.sample_id}.json").write_text(
            json.dumps(answer_key(sample), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return len(samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m overturn.eval.export")
    parser.add_argument("out_dir", type=Path, nargs="?", default=ROOT / "corpus" / "samples")
    args = parser.parse_args(argv)
    count = export(build_corpus(), args.out_dir)
    print(f"Wrote {count} letters and answer keys to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
