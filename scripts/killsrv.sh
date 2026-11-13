#!/usr/bin/env bash
# stop leftover servers from an interrupted run (matches only python processes, not this shell)
ps -eo pid,comm,args | awk '$2 ~ /^python/ && /inventory\.py/ {print $1}' | xargs -r kill
