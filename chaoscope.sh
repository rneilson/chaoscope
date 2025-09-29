#!/bin/bash

do_shutdown=0

while true; do
    # TODO: parameterize
    /usr/bin/python3 ~/chaoscope/chaoscope.py
    if [[ $? -eq 2 ]]; then
        do_shutdown=1
        break
    fi
    echo "Restarting application..."
done

if [[ $do_shutdown -eq 1 ]]; then
    echo "Shutting down..."
    sudo poweroff
else
    echo "Exiting application..."
fi
