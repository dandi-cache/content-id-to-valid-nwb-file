import argparse
import datetime
import itertools
import math
import pathlib

import dandi.dandiapi
import nwbinspector
from _pipeline_common import inspect_content_id, load_records, stage_to_log_file_path, write_records

# When no explicit --limit is given, re-assess this fraction of the already-processed cache per
# run. Run daily, this cycles the entire cache through re-assessment roughly once a month, in
# small bites, rather than trying to reprocess everything at once.
DEFAULT_FRACTION_PER_RUN = 1 / 30

# Content IDs from before this field existed have no recorded `checked_at` and are treated as
# the most overdue for refresh, so they naturally sort first.
MISSING_CHECKED_AT = "0000-00-00"


def _run(base_directory: pathlib.Path, limit: int | None) -> None:
    input_file_path = (
        base_directory / "sourcedata" / "content-id-to-nwb-file" / "derivatives" / "content_id_to_nwb_file.jsonl"
    )
    content_id_to_nwb_file = load_records(file_path=input_file_path)

    derivatives_directory = base_directory / "derivatives"
    derivatives_directory.mkdir(parents=True, exist_ok=True)
    output_file_path = derivatives_directory / "content_id_to_valid_nwb_file.jsonl"
    content_id_to_validity = load_records(file_path=output_file_path)

    logs_dir = base_directory / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stage_log_paths = stage_to_log_file_path(logs_dir=logs_dir)
    unexpected_errors_log_file_path = logs_dir / "unexpected_errors.txt"

    # Refresh only re-assesses content IDs that are both already processed and still present in
    # the current input (assets `content-id-to-nwb-file` has since dropped are left alone here).
    # Picking up brand-new content IDs is `update.py`'s job, not this one.
    candidate_content_ids = content_id_to_validity.keys() & content_id_to_nwb_file.keys()
    content_ids_oldest_first = sorted(
        candidate_content_ids,
        key=lambda content_id: content_id_to_validity[content_id].get("checked_at", MISSING_CHECKED_AT),
    )

    if limit is None:
        # Scale to the current cache size so the whole cache cycles through re-assessment on
        # about a monthly cadence, however large the cache grows.
        limit = math.ceil(len(content_ids_oldest_first) * DEFAULT_FRACTION_PER_RUN)

    client = dandi.dandiapi.DandiAPIClient()  # Run tokenless to ensure only public dandisets are accessed
    dandi_config = nwbinspector.load_config("dandi")
    for content_id in itertools.islice(content_ids_oldest_first, limit):
        dandiset_id, path = next(iter(content_id_to_nwb_file[content_id].items()))

        record = inspect_content_id(
            client=client,
            dandi_config=dandi_config,
            content_id=content_id,
            dandiset_id=dandiset_id,
            path=path,
            stage_to_log_file_path=stage_log_paths,
            unexpected_errors_log_file_path=unexpected_errors_log_file_path,
        )
        record["checked_at"] = datetime.datetime.now(tz=datetime.timezone.utc).date().isoformat()
        content_id_to_validity[content_id] = record

    write_records(file_path=output_file_path, records=content_id_to_validity)


if __name__ == "__main__":
    default_base_directory = pathlib.Path(__file__).parent.parent

    parser = argparse.ArgumentParser(
        description=(
            "Re-assess already-processed entries of the content-id-to-valid-nwb-file DANDI cache, "
            "oldest-checked first. Unlike update.py, this revisits content IDs that already have a "
            "recorded result, since the NWB Inspector itself evolves over time."
        )
    )
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
        help=(
            "Optional cap on the number of content IDs to re-assess in this run. Defaults to "
            f"~{DEFAULT_FRACTION_PER_RUN:.0%} of the already-processed cache, so a daily run "
            "cycles through the entire cache roughly once a month."
        ),
    )
    args = parser.parse_args()

    _run(base_directory=args.base_directory, limit=args.limit)
