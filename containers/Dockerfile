# syntax=docker/dockerfile:1

# The pinned runtime environment for this cache.
#
# Everything shared comes from the base image: Debian, git-annex, the virtual environment, the
# `dandi_cache_utils` library that `code/update.py` imports, and the vendored `update_pipeline.sh`
# that CI extracts and runs on the runner.
#
# The `:nwb` tag rather than `:latest`, because this cache streams remote NWB files: that tag
# carries h5py, zarr, hdmf-zarr, remfile, pynwb and the NWB Inspector alongside the DANDI API
# client, which is the whole of what the assessment needs. So there is nothing to install here.
#
# Nothing is version-pinned in the base image either, so the monthly rebuild below picks up newer
# NWB Inspector releases even when nothing in this repository has changed. That is what the refresh
# entry point then re-assesses the cache against.
#
# The image holds only the environment, not this cache's code. The code is mounted at run time, so
# a single image serves any revision of it.
FROM ghcr.io/dandi-cache/dandi-cache-utils:nwb

# The source label associates the image on the GitHub Container Registry with this repository.
LABEL org.opencontainers.image.source="https://github.com/dandi-cache/content-id-to-valid-nwb-file"
LABEL org.opencontainers.image.description="The pinned runtime environment for the DANDI Cache content-id-to-valid-nwb-file update pipeline."

CMD ["python", "--version"]
