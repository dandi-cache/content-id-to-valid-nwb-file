"""Shared helpers for update.py and refresh.py.

Both scripts stream the same NWB assets and run the same NWB Inspector checks; they differ
only in *which* content IDs they select for a given run (unprocessed vs. due-for-refresh).
"""

import json
import pathlib
import traceback

import dandi.dandiapi
import h5py
import hdmf_zarr
import nwbinspector
import pynwb
import remfile

# Each processing stage routes its failures to a dedicated log; anything unmapped (e.g. a
# failure before the first labelled stage) falls back to the catch-all `unexpected_errors.txt`.
STAGE_LOG_NAMES = {
    "retrieving asset information from the DANDI API": "dandi_api_errors.txt",
    "opening the NWB file": "file_open_errors.txt",
    "running the NWB Inspector": "nwb_inspector_errors.txt",
}
UNEXPECTED_ERRORS_LOG_NAME = "unexpected_errors.txt"


def load_records(file_path: pathlib.Path) -> dict:
    """Load a `{content_id: value}` mapping from a JSONL file, or an empty dict if missing."""
    if not file_path.exists():
        return {}

    records: dict = {}
    with file_path.open(mode="r") as file_stream:
        for line in file_stream:
            if line.strip():
                records.update(json.loads(line))
    return records


def write_records(file_path: pathlib.Path, records: dict) -> None:
    """Write a `{content_id: value}` mapping to a JSONL file, one sorted content ID per line."""
    with file_path.open(mode="w") as file_stream:
        file_stream.writelines(f"{json.dumps({content_id: records[content_id]})}\n" for content_id in sorted(records))


def log_error(log_file_path: pathlib.Path, message: str) -> None:
    """Append a single error report to the given error log, separated by a blank line."""
    with log_file_path.open(mode="a") as file_stream:
        file_stream.write(f"{message}\n\n")


def stage_to_log_file_path(logs_dir: pathlib.Path) -> dict:
    """Build the stage-name -> log-file-path mapping, rooted at the given logs directory."""
    return {stage: logs_dir / name for stage, name in STAGE_LOG_NAMES.items()}


def inspect_content_id(
    client: dandi.dandiapi.DandiAPIClient,
    dandi_config,
    content_id: str,
    dandiset_id: str,
    path: str,
    stage_to_log_file_path: dict,
    unexpected_errors_log_file_path: pathlib.Path,
) -> dict:
    """Stream one NWB asset, run the NWB Inspector on it, and return its validity record."""
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
        log_error(
            log_file_path=stage_to_log_file_path.get(stage, unexpected_errors_log_file_path),
            message=(
                f"Error while {stage} for `{content_id=}` "
                f"(dandiset ID {dandiset_id}, path {path}, URL {s3_url})!\n\n"
                f"{type(exception)}: {exception}\n\n"
                f"{traceback.format_exc()}"
            ),
        )
        return {"valid": False, "error": f"{stage}: {type(exception).__name__}: {exception}"}

    formatted_messages = [str(inspector_message) for inspector_message in inspector_messages]
    return {"valid": not formatted_messages, "messages": formatted_messages}
