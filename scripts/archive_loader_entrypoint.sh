#!/bin/bash
set -e

# Forward all arguments to the archive loader script
python /app/scripts/archive_loader.py "$@"
