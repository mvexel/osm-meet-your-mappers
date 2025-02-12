#!/bin/sh
set -e
# Forward all arguments to the archive loader script.
python /app/archive_loader.py "$@"
