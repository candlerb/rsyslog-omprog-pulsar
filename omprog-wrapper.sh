#!/bin/sh

# I found problems where rsyslog in Ubuntu 18.04 would segfault if given
# binary="/path/to/omprog-pulsar.py -c /path/to/omprog-pulsar.yaml"
#
# This wrapper avoids the issue, by setting the current directory
# which is where the config is searched for by default.

cd "$(dirname $0)"
exec ./omprog-pulsar.py
