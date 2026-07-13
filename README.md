# DANDI Cache: `content-id-to-valid-nwb-file`

A one-to-one mapping from content IDs to their NWB validity, restricted to the NWB assets listed in [`content-id-to-nwb-file`](https://github.com/dandi-cache/content-id-to-nwb-file).

For each content ID, the corresponding asset is streamed directly from the DANDI Archive — HDF5 NWB files with [`remfile`](https://github.com/flatironinstitute/remfile), and Zarr NWB stores (`.nwb.zarr`) with [`hdmf-zarr`](https://github.com/hdmf-dev/hdmf-zarr) — and inspected with the [NWB Inspector](https://github.com/NeurodataWithoutBorders/nwbinspector) using the `dandi` configuration at the `CRITICAL` importance threshold. A file is `valid` when it opens successfully and the inspector reports no `CRITICAL` issues; otherwise the record carries either the inspector messages found or the reason the file could not even be opened (e.g. a network/API error).

Updated frequently.

Primarily for use by developers.

Each line of the derivatives is a JSON object of the form:

```json
{"<content_id>": {"valid": <bool>, "messages": ["<NWB Inspector message>", ...]}}
```

or, when the file could not be opened or inspected at all:

```json
{"<content_id>": {"valid": false, "error": "<stage>: <exception>"}}
```



## One-time use

If you only plan to use this cache infrequently or from disparate locations, you can directly download the latest version of the cache as a compressed [JSON Lines](https://jsonlines.org/) file from the `dist` branch:

### Python API (recommended)

```python
import gzip
import json

import requests

url = "https://raw.githubusercontent.com/dandi-cache/content-id-to-valid-nwb-file/refs/heads/dist/derivatives/content_id_to_valid_nwb_file.jsonl.gz"
response = requests.get(url)
lines = gzip.decompress(data=response.content).decode("utf-8").splitlines()
content_id_to_valid_nwb_file = [json.loads(line) for line in lines]
```

### Save to file

```bash
curl https://raw.githubusercontent.com/dandi-cache/content-id-to-valid-nwb-file/refs/heads/dist/derivatives/content_id_to_valid_nwb_file.jsonl.gz -o content_id_to_valid_nwb_file.jsonl.gz
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
