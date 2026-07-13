import argparse
import itertools
import json
import pathlib
import traceback

import dandi.dandiapi
import h5py
import hdmf_zarr
import nwbinspector
import pynwb
import remfile


def _load_records(file_path: pathlib.Path) -> dict:
    """Load a `{content_id: value}` mapping from a JSONL file, or an empty dict if missing."""
    if not file_path.exists():
        return {}

    records: dict = {}
    with file_path.open(mode="r") as file_stream:
        for line in file_stream:
            if line.strip():
                records.update(json.loads(line))
    return records


def _log_error(log_file_path: pathlib.Path, message: str) -> None:
    """Append a single error report to the given error log, separated by a blank line."""
    with log_file_path.open(mode="a") as file_stream:
        file_stream.write(f"{message}\n\n")


def _run(base_directory: pathlib.Path, limit: int | None) -> None:
    input_file_path = (
        base_directory / "sourcedata" / "content-id-to-nwb-file" / "derivatives" / "content_id_to_nwb_file.jsonl"
    )
    content_id_to_nwb_file = _load_records(file_path=input_file_path)

    derivatives_directory = base_directory / "derivatives"
    derivatives_directory.mkdir(parents=True, exist_ok=True)
    output_file_path = derivatives_directory / "content_id_to_valid_nwb_file.jsonl"
    content_id_to_validity = _load_records(file_path=output_file_path)

    logs_dir = base_directory / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    dandi_api_errors_log_file_path = logs_dir / "dandi_api_errors.txt"
    file_open_errors_log_file_path = logs_dir / "file_open_errors.txt"
    nwb_inspector_errors_log_file_path = logs_dir / "nwb_inspector_errors.txt"
    unexpected_errors_log_file_path = logs_dir / "unexpected_errors.txt"

    # Each processing stage routes its failures to a dedicated log; anything unmapped (e.g. a
    # failure before the first labelled stage) falls back to the catch-all `unexpected_errors.txt`.
    stage_to_log_file_path = {
        "retrieving asset information from the DANDI API": dandi_api_errors_log_file_path,
        "opening the NWB file": file_open_errors_log_file_path,
        "running the NWB Inspector": nwb_inspector_errors_log_file_path,
    }

    # Already-processed content IDs are exactly the keys already recorded in the output file
    # (success or failure both count), so re-runs skip them and only pick up new content IDs.
    content_ids_to_process = content_id_to_nwb_file.keys() - content_id_to_validity.keys()

    client = dandi.dandiapi.DandiAPIClient()  # Run tokenless to ensure only public dandisets are accessed
    dandi_config = nwbinspector.load_config("dandi")
    for content_id in itertools.islice(content_ids_to_process, limit):
        dandiset_id, path = next(iter(content_id_to_nwb_file[content_id].items()))

        stage = "retrieving asset information from the DANDI API"
        s3_url = None
        try:
            dandiset = client.get_dandiset(dandiset_id=dandiset_id)
            asset = dandiset.get_asset_by_path(path=path)
            s3_url = asset.get_content_url(follow_redirects=1, strip_query=True)

            # Streaming-only: HDF5 assets are backed by remfile via h5py; Zarr assets (`.nwb.zarr`)
            # are opened directly by hdmf_zarr, which streams the store over HTTP(S)/S3 itself.
            stage = "opening the NWB file"
            if ".zarr" in pathlib.PurePosixPath(path).suffixes:
                io = hdmf_zarr.NWBZarrIO(s3_url, mode="r")
                nwbfile = io.read()
            else:
                rem_file = remfile.File(url=s3_url)
                h5py_file = h5py.File(name=rem_file, mode="r")
                io = pynwb.NWBHDF5IO(file=h5py_file, mode="r", load_namespaces=True)
                nwbfile = io.read()

            stage = "running the NWB Inspector"
            inspector_messages = list(
                nwbinspector.inspect_nwbfile_object(
                    nwbfile_object=nwbfile,
                    config=dandi_config,
                    importance_threshold=nwbinspector.Importance.CRITICAL,
                )
            )
        except Exception as exception:
            _log_error(
                log_file_path=stage_to_log_file_path.get(stage, unexpected_errors_log_file_path),
                message=(
                    f"Error while {stage} for `{content_id=}` "
                    f"(dandiset ID {dandiset_id}, path {path}, URL {s3_url})!\n\n"
                    f"{type(exception)}: {exception}\n\n"
                    f"{traceback.format_exc()}"
                ),
            )
            content_id_to_validity[content_id] = {
                "valid": False,
                "error": f"{stage}: {type(exception).__name__}: {exception}",
            }
            continue

        formatted_messages = [str(inspector_message) for inspector_message in inspector_messages]
        content_id_to_validity[content_id] = {"valid": not formatted_messages, "messages": formatted_messages}

    with output_file_path.open(mode="w") as file_stream:
        file_stream.writelines(
            f"{json.dumps({content_id: content_id_to_validity[content_id]})}\n"
            for content_id in sorted(content_id_to_validity)
        )


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
