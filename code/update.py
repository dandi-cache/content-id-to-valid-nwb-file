import argparse
import datetime
import itertools
import pathlib

import dandi.dandiapi
import nwbinspector
from _pipeline_common import inspect_content_id, load_records, stage_to_log_file_path, write_records


def _run(base_directory: pathlib.Path, limit: int | None) -> None:
    input_file_path = (
        base_directory / "sourcedata" / "content-id-to-nwb-file" / "derivatives" / "content_id_to_nwb_file.jsonl"
    )
    content_id_to_nwb_file = load_records(file_path=input_file_path)

    derivatives_directory = base_directory / "derivatives"
    derivatives_directory.mkdir(parents=True, exist_ok=True)
    validity_file_path = derivatives_directory / "content_id_to_valid_nwb_file.jsonl"
    checked_at_file_path = derivatives_directory / "content_id_to_checked_at.jsonl"
    messages_file_path = derivatives_directory / "content_id_to_messages.jsonl"
    content_id_to_validity = load_records(file_path=validity_file_path)
    content_id_to_checked_at = load_records(file_path=checked_at_file_path)
    content_id_to_messages = load_records(file_path=messages_file_path)

    logs_dir = base_directory / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stage_log_paths = stage_to_log_file_path(logs_dir=logs_dir)
    unexpected_errors_log_file_path = logs_dir / "unexpected_errors.txt"

    # Already-processed content IDs are exactly the keys already recorded in the output file
    # (success or failure both count), so re-runs skip them and only pick up new content IDs.
    # Re-assessing previously processed IDs against newer NWB Inspector releases is the job of
    # the separate `refresh.py` script, not this one.
    content_ids_to_process = content_id_to_nwb_file.keys() - content_id_to_validity.keys()

    client = dandi.dandiapi.DandiAPIClient()  # Run tokenless to ensure only public dandisets are accessed
    dandi_config = nwbinspector.load_config("dandi")
    for content_id in itertools.islice(content_ids_to_process, limit):
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
        content_id_to_validity[content_id] = record["valid"]
        content_id_to_checked_at[content_id] = datetime.datetime.now(tz=datetime.timezone.utc).date().isoformat()
        if not record["valid"]:
            content_id_to_messages[content_id] = {
                key: value for key, value in record.items() if key in ("messages", "error")
            }
        else:
            content_id_to_messages.pop(content_id, None)

    write_records(file_path=validity_file_path, records=content_id_to_validity)
    write_records(file_path=checked_at_file_path, records=content_id_to_checked_at)
    write_records(file_path=messages_file_path, records=content_id_to_messages)


if __name__ == "__main__":
    default_base_directory = pathlib.Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Update the content-id-to-valid-nwb-file DANDI cache.")
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
        help="Optional cap on the number of new content IDs to process in this run.",
    )
    args = parser.parse_args()

    _run(base_directory=args.base_directory, limit=args.limit)
