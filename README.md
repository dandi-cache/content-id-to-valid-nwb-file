# DANDI Cache: `content-id-to-valid-nwb-file`

A one-to-one mapping from content IDs to their NWB validity, restricted to the NWB assets listed in [`content-id-to-nwb-file`](https://github.com/dandi-cache/content-id-to-nwb-file).

For each content ID, the corresponding asset is streamed directly from the DANDI Archive — HDF5 NWB files with [`remfile`](https://github.com/flatironinstitute/remfile), and Zarr NWB stores (`.nwb.zarr`) with [`hdmf-zarr`](https://github.com/hdmf-dev/hdmf-zarr) — and inspected with the [NWB Inspector](https://github.com/NeurodataWithoutBorders/nwbinspector) using the `dandi` configuration at the `CRITICAL` importance threshold.
A file is `valid` when it opens successfully and the inspector reports no `CRITICAL` issues; otherwise the record carries either the inspector messages found or the reason the file could not even be opened (e.g. a network/API error).

The NWB Inspector is a living resource — its checks change over time — so this cache is kept fresh two ways:

- **Update** (`code/update.py`, every four hours): assesses content IDs that have never been processed.
- **Refresh** (`code/refresh.py`, daily): re-assesses already-processed content IDs, oldest-checked first, in a fixed daily batch.

Both run inside a pinned container image (see `containers/Dockerfile`) that is itself rebuilt monthly (and on every dependency-affecting change), so refreshed entries are checked against a recent NWB Inspector release.

Updated frequently.

Primarily for use by developers.

The cache is three outputs, each a Zarr store of JSON Lines text with one `{"<content_id>": <value>}` object per line.

`derivatives/content_id_to_valid_nwb_file.zarr` — the main cache, a plain content ID to validity mapping:

```json
{"<content_id>": <bool>}
```

`derivatives/content_id_to_checked_at.zarr` — the UTC date of the most recent assessment (initial or refreshed) for every content ID:

```json
{"<content_id>": "<YYYY-MM-DD>"}
```

Content IDs missing from this file have never been checked against a `checked_at` date, and are treated as the most overdue for refresh.

`derivatives/content_id_to_messages.zarr` — details for content IDs that are `false` in the main cache only; valid content IDs have no entry here:

```json
{"<content_id>": {"messages": ["<NWB Inspector message>", ...]}}
```

or, when the file could not be opened or inspected at all:

```json
{"<content_id>": {"error": "<stage>: <exception>"}}
```



## One-time use

`dist` publishes each output as a [Zarr](https://zarr.dev/) store: the cache itself is `derivatives/content_id_to_valid_nwb_file.zarr/`, with the cache's other outputs beside it as stores of the same kind (`derivatives/content_id_to_checked_at.zarr/`, `derivatives/content_id_to_messages.zarr/`).
A store is one array of [JSON Lines](https://jsonlines.org/) text cut into chunk files, each holding whole lines and gzip-compressed.
Where a key appears more than once, the last line is its current entry, and the published copy has no repeats.
It can be read with the standard library alone, or opened remotely with any Zarr library.

### Python API (recommended)

Fetch `stream/zarr.json` for the array's length and chunk size, then each chunk in order:

```python
import gzip
import json
import math
import urllib.request

store = "https://raw.githubusercontent.com/dandi-cache/content-id-to-valid-nwb-file/refs/heads/dist/derivatives/content_id_to_valid_nwb_file.zarr"


def fetch(path):
    with urllib.request.urlopen(f"{store}/{path}") as response:
        return response.read()


array = json.loads(fetch("stream/zarr.json"))
length = array["shape"][0]
chunk_bytes = array["chunk_grid"]["configuration"]["chunk_shape"][0]

content_id_to_valid_nwb_file = {}
for index in range(math.ceil(length / chunk_bytes)):
    for line in gzip.decompress(fetch(f"stream/c/{index}")).decode("utf-8").splitlines():
        if line.strip():
            content_id_to_valid_nwb_file.update(json.loads(line))
```

An entry is not filed under its key: the chunks hold the entries in the order they were recorded, so looking up one means reading through them.
To look up many, read it once as above, or clone the `derivatives` branch.

### Remote Zarr store

Anything that opens Zarr can open the store over HTTP, reading only the chunks it needs.
The group's `zarr.json` carries the array's metadata, so opening it takes one request:

```bash
pip install "zarr>=3" fsspec aiohttp
```

```python
import json

import zarr

url = "https://raw.githubusercontent.com/dandi-cache/content-id-to-valid-nwb-file/refs/heads/dist/derivatives/content_id_to_valid_nwb_file.zarr"
stream = zarr.open_group(url, mode="r")["stream"]
print(stream.shape, stream.chunks)  # Bytes in all, and bytes per chunk.

# The first chunk, fetched and decompressed on its own: whole lines, each `{"<key>": <value>}`.
first_chunk = stream[: stream.chunks[0]].tobytes().decode("utf-8")
for line in first_chunk.splitlines():
    if line.strip():
        print(json.loads(line))
        break
```

Reading `stream[:]` returns the whole text; to read it in pieces, step through it by `stream.chunks[0]`, as each chunk is fetched whole.

### Save to file

A raw URL cannot be listed, so to fetch every chunk at once clone the `dist` branch, which holds nothing else:

```bash
git clone --branch dist --depth 1 https://github.com/dandi-cache/content-id-to-valid-nwb-file.git
```



## Repeated use

If you plan on using this cache regularly, clone the `dist` branch of this repository:

```bash
git clone --branch dist https://github.com/dandi-cache/content-id-to-valid-nwb-file.git
```

Or, if you prefer [DataLad](https://www.datalad.org/):

```bash
datalad clone https://github.com/dandi-cache/content-id-to-valid-nwb-file.git --branch derivatives
```

Then set up a CRON on your system to pull the latest version of the cache at your desired frequency.

For example, through `crontab -e`, add:

```bash
0 0 * * * git -C /path/to/content-id-to-valid-nwb-file pull
```

This will minimize data overhead by only loading the most recent changes.

Each output is a store in the clone, with every chunk gzip-compressed:

```python
import gzip
import json
import pathlib

chunks = pathlib.Path("content-id-to-valid-nwb-file/derivatives/content_id_to_valid_nwb_file.zarr/stream/c")
content_id_to_valid_nwb_file = {}
for chunk in sorted(chunks.iterdir(), key=lambda path: int(path.name)):
    for line in gzip.decompress(chunk.read_bytes()).decode("utf-8").splitlines():
        if line.strip():
            content_id_to_valid_nwb_file.update(json.loads(line))
```


## Reading the `derivatives` branch

Each output is kept on the `derivatives` branch as a [Zarr](https://zarr.dev/) v3 store of JSON Lines: a one-dimensional `uint8` array whose bytes are the lines, padded with newlines to the end of its last chunk.
A key recorded more than once keeps its last line, which the dictionary below does by itself.

```python
import json

import zarr  # zarr>=3, with fsspec and aiohttp to read over HTTP

url = "https://raw.githubusercontent.com/dandi-cache/content-id-to-valid-nwb-file/derivatives/derivatives/content_id_to_valid_nwb_file.zarr"
stream = zarr.open_group(url, mode="r")["stream"]
lines = stream[:].tobytes().decode("utf-8").splitlines()
content_id_to_valid_nwb_file = {key: value for line in lines if line for key, value in json.loads(line).items()}
```

The other outputs, `content_id_to_checked_at.zarr` and `content_id_to_messages.zarr`, are stores beside it under the same `derivatives/` path.

Without Zarr, each chunk is a plain file of whole lines at `derivatives/content_id_to_valid_nwb_file.zarr/stream/c/<n>`, read in order of `n`.
