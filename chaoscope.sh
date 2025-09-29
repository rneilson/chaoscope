#!/bin/bash

BASE_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Run application
echo "Starting application..."
/usr/bin/labwc -S "/usr/bin/python3 ${BASE_DIR}/chaoscope.py" 1>${BASE_DIR}/labwc.log 2>&1

do_shutdown=""
if [[ -f "${XDG_RUNTIME_DIR}/chaoscope-shutdown" ]]; then
    do_shutdown=$(cat "${XDG_RUNTIME_DIR}/chaoscope-shutdown")
fi

if [[ "$do_shutdown" == "1" ]]; then
    echo "Shutting down..."
    sudo poweroff
else
    echo "Exiting application..."
fi
