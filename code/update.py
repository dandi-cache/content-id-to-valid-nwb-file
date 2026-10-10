"""Assess which of the NWB assets upstream are valid, according to the NWB Inspector.

Each content ID is resolved to an S3 URL through the tokenless DANDI API, streamed rather than
downloaded, and inspected with the `dandi` configuration at the CRITICAL threshold. A file is
valid when it opens and the inspector reports nothing.

`code/refresh.py` is this same operation over a different batch, so it calls `main` below rather
than repeating any of it.

Everything shared with the other caches -- the argument parsing, the logging, the batch cap, the
error logs, the output paths, and testing mode -- comes from `dandi_cache_utils`, which the
runtime image carries.
"""

import datetime
import traceback

import dandi_cache_utils as dandi_cache

CHECKED_AT = "content_id_to_checked_at.jsonl"
MESSAGES = "content_id_to_messages.jsonl"

# Resolving an asset, opening it and inspecting it fail for unrelated reasons, and a week of
# failures is only triageable when each kind has its own log.
STAGES = {
    "retrieving asset information from the DANDI API": "dandi_api_errors.txt",
    "opening the NWB file": "file_open_errors.txt",
    "running the NWB Inspector": "nwb_inspector_errors.txt",
}


# Opening and inspecting a file happens in a child process, one per file. HDF5, pynwb and the
# inspector keep hold of memory that is never given back, about 5 MB for every file inspected in
# one process: a batch of 2500 reached 10 GB and was killed on a 16 GB runner, losing the
# 2200 results it had already checkpointed. A child that exits returns all of it. The slowest file
# in two batches took 155 s, so this leaves a wide margin and only catches a stream that hangs.
FILE_TIMEOUT_SECONDS = 900


def _exception_like(type_name: str, message: str, details: str) -> Exception:
    """An exception named and worded like one raised in a child process, which cannot cross back.

    The error logs and the `{"error": ...}` recorded beside an invalid file are built from the
    exception's type name and message, so they read as they always have. The child's traceback is
    attached as a note, which the logs include and the one-line summary does not.
    """
    error = type(type_name, (Exception,), {})(message)
    error.add_note(f"Raised in the child process:\n{details}")
    return error


def main(*, operation: str = "update") -> None:
    dataset, arguments = dandi_cache.open_dataset(operation=operation)
    nwb_files = dataset.read_input()

    validity = dataset.read_output_lookup()
    checked_at = dataset.read_output_lookup(CHECKED_AT)
    messages = dataset.read_output_lookup(MESSAGES)

    resolver = dandi_cache.api.AssetResolver()
    inspector_config = dandi_cache.nwb.inspector_config()
    # Loaded here, before any child is forked, so each child inherits them rather than importing
    # them again for every file.
    import h5py  # noqa: F401
    import pynwb  # noqa: F401

    try:
        import hdmf_zarr  # noqa: F401
    except ImportError:
        pass

    def open_and_inspect(url: str, path: str, /) -> tuple:
        """Open one remote file and inspect it, in the child process; return plain data.

        Forked, so `inspector_config` and the imported modules come from the parent already loaded.
        A failure is returned with the stage it happened in, since an exception loses that on the
        way back.
        """
        stage = "opening the NWB file"
        try:
            nwbfile, _io = dandi_cache.nwb.open_nwbfile(url, path)
            stage = "running the NWB Inspector"
            return ("ok", dandi_cache.nwb.inspect_nwbfile_object(nwbfile, config=inspector_config))
        except Exception as error:
            return ("failed", stage, type(error).__name__, str(error), traceback.format_exc())

    def record_assessment(content_id: str, /, *, reason: dict | None) -> None:
        """Stamp a content ID as assessed today, keeping the reason it is not valid, if it is not."""
        checked_at[content_id] = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
        if reason is None:
            messages.pop(content_id, None)
        else:
            messages[content_id] = reason

    def assess(content_id, item) -> bool:
        dandiset_id, path = dandi_cache.api.split_location(nwb_files[content_id])
        # Reported with any failure, so an error log names the asset rather than only its content ID.
        item.context.update({"dandiset ID": dandiset_id, "path": path})

        item.stage = "retrieving asset information from the DANDI API"
        url = resolver.content_url(dandiset_id, path)
        item.context["URL"] = url

        # A timeout or a child that died is logged with opening the file, which is where a stream
        # that hangs or a file too large for memory shows up.
        item.stage = "opening the NWB file"
        outcome = dandi_cache.run_isolated(
            open_and_inspect, arguments=(url, path), timeout_seconds=FILE_TIMEOUT_SECONDS
        )
        if outcome[0] == "failed":
            _, item.stage, type_name, message, details = outcome
            raise _exception_like(type_name, message, details)
        critical_messages = outcome[1]

        record_assessment(content_id, reason={"messages": critical_messages} if critical_messages else None)
        return not critical_messages

    limit = dataset.limit(arguments.limit)
    if operation == "refresh":
        # What is already recorded and still listed upstream. Picking up new content IDs is the
        # update's job, and an asset the upstream has since dropped is left alone rather than
        # re-fetched.
        batch = dandi_cache.select_stale(
            validity.keys() & nwb_files.keys(),
            checked_at,
            limit=limit,
        )
    else:
        batch = dandi_cache.select_new(nwb_files, validity, limit=limit)

    dandi_cache.run_incremental_update(
        dataset,
        batch=batch,
        process=assess,
        recorded=validity,
        # A file that cannot be opened or inspected is not a valid file. That is the answer, not a
        # reason to try again, so it is recorded as such and left to the refresh to revisit.
        on_failure=dandi_cache.RECORD,
        failure_value=False,
        on_error=lambda content_id, item: record_assessment(content_id, reason={"error": item.error_summary}),
        on_write=lambda: write_side_outputs(dataset, checked_at=checked_at, messages=messages),
        stages=STAGES,
        describe=lambda valid: "valid" if valid else "not valid",
        checkpoint_every=50,
    )


def write_side_outputs(dataset, /, *, checked_at: dict, messages: dict) -> None:
    """Write the two files that accompany the cache, at the same moments the cache itself is written."""
    dataset.write_output_lookup(checked_at, CHECKED_AT)
    dataset.write_output_lookup(messages, MESSAGES)


if __name__ == "__main__":
    main()
