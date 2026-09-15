"""Re-assess content IDs this cache has already recorded, oldest-checked first.

The NWB Inspector is a living resource: a file assessed against one release can assess differently
against the next. `code/update.py` never revisits what it has recorded, so this entry point does,
in daily batches sized from the cache itself.

It is the same operation over a different batch, which is all that `operation="refresh"` selects.
"""

import update

if __name__ == "__main__":
    update.main(operation="refresh")
