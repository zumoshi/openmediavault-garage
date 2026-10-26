#!/bin/sh
#
# Starts a rebalance in garage instance $1. garage@<name> runs this after
# each start while a datastore drains: only a rebalance moves blocks off a
# read-only data folder, and garage forgets it when it stops.
#
# Part of the openmediavault-garage plugin.
# @license https://www.gnu.org/licenses/gpl.html GPL Version 3

for _ in $(seq 60); do
	/usr/bin/garage -c "/etc/garage/$1.toml" json-api LaunchRepairOperation \
		'{"node":"self","body":{"repairType":"rebalance"}}' >/dev/null 2>&1 &&
		exit 0
	sleep 1
done
echo "garage@$1: the rebalance did not start" >&2
exit 1
