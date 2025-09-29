#!/bin/bash

do_shutdown=0
child_pid=""

handle_term() {
    if [[ -n "$child_pid" ]]; then
        echo "Interrupting child PID $child_pid"
        kill -INT "$child_pid" 2>/dev/null
    else
        echo "No child PID to interrupt"
    fi
}

setup_term() {
    child_pid=""
    # TODO: harder kill for SIGTERM?
    trap 'handle_term' TERM INT
}

echo "Starting application..."

while true; do
    setup_term
    # TODO: parameterize dir
    /usr/bin/python3 ~/chaoscope/chaoscope.py &
    child_pid=$!
    echo "Child PID: ${child_pid:-none}"

    if [[ -n "$child_pid" ]]; then
        # Wait once, will return after trap kill
        wait "$child_pid" 2>/dev/null
        # Clear trap and wait again to get actual exit code
        trap - TERM INT
        wait "$child_pid" 2>/dev/null

        if [[ $? -eq 2 ]]; then
            do_shutdown=1
            break
        fi
    fi
    echo "Restarting application..."
done

if [[ $do_shutdown -eq 1 ]]; then
    echo "Shutting down..."
    sudo poweroff
else
    echo "Exiting application..."
fi
