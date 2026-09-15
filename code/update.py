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

# The NWB Inspector's checks change over time, so an assessment is only as current as the release
# it was made against. Re-assessing this fraction per refresh cycles the whole cache through a
# recent release about once a month when run daily, however large the cache grows.
REFRESH_FRACTION_PER_RUN = 1 / 30


def main(*, operation: str = "update") -> None:
    dataset, arguments = dandi_cache.open_dataset(operation=operation)
    nwb_files = dataset.read_input()

    validity = dataset.read_output_lookup()
    checked_at = dataset.read_output_lookup(CHECKED_AT)
    messages = dataset.read_output_lookup(MESSAGES)

    resolver = dandi_cache.api.AssetResolver()
    inspector_config = dandi_cache.nwb.inspector_config()

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

        item.stage = "opening the NWB file"
        nwbfile, _io = dandi_cache.nwb.open_nwbfile(url, path)

        item.stage = "running the NWB Inspector"
        critical_messages = dandi_cache.nwb.inspect_nwbfile_object(nwbfile, config=inspector_config)

        record_assessment(content_id, reason={"messages": critical_messages} if critical_messages else None)
        return not critical_messages

    limit = dandi_cache.effective_limit(testing=dataset.testing, limit=arguments.limit)
    if operation == "refresh":
        # What is already recorded and still listed upstream. Picking up new content IDs is the
        # update's job, and an asset the upstream has since dropped is left alone rather than
        # re-fetched.
        batch = dandi_cache.select_stale(
            validity.keys() & nwb_files.keys(),
            checked_at,
            limit=limit,
            fraction_per_run=REFRESH_FRACTION_PER_RUN,
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
