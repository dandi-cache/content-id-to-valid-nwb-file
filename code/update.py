import argparse
import json
import pathlib


def _run(base_directory: pathlib.Path, limit: int | None) -> None:
    # TODO: implement the update logic for this cache.
    # Read the inputs, compute the cache, and write the result into
    # `base_directory / "derivatives"` as JSON Lines (one JSON value per line).
    # `limit` is an optional batch size for incremental, resumable runs: process at most
    # `limit` new items per invocation and skip those already recorded in the derivatives.
    #
    # The setup checklist — input modes, whether to keep `--limit`, and lessons for
    # fetching inputs from the public DANDI S3 bucket — lives in the plain-Markdown
    # skills .claude/skills/setup-cache/SKILL.md and
    # .claude/skills/dandi-s3-network-inputs/SKILL.md.

    records: list = []

    derivatives_directory = base_directory / "derivatives"
    derivatives_directory.mkdir(parents=True, exist_ok=True)

    output_file_path = derivatives_directory / "<cache_name>.jsonl"
    with output_file_path.open(mode="w") as file_stream:
        file_stream.writelines(f"{json.dumps(record)}\n" for record in records)


if __name__ == "__main__":
    default_base_directory = pathlib.Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Update the <cache-name> DANDI cache.")
    parser.add_argument(
        "--base-directory",
        type=pathlib.Path,
        default=default_base_directory,
        help=(
            "The directory containing the `sourcedata` and `derivatives` directories. "
            "Set to the mounted dataset path when run inside the pipeline container; "
            "defaults to the repository root."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of new items to process in this run.",
    )
    args = parser.parse_args()

    _run(base_directory=args.base_directory, limit=args.limit)
