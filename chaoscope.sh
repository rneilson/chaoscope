#!/bin/bash

while true; do
    # TODO: parameterize
    /usr/bin/python3 ~/chaoscope/chaoscope.py
    if [[ $? -eq 0 ]]; then
        echo "Exiting..."
        break
    fi
    echo "Restarting..."
done

echo "Shutting down..."
sudo poweroff
