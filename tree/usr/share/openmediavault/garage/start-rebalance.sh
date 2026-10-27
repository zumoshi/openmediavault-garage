#!/bin/sh
#
# Starts a rebalance in garage instance $1 unless one is running. While a
# datastore drains, garage@<name> runs this after each start and every
# apply runs it: only a rebalance moves blocks off a read-only data folder,
# garage forgets it when it stops, and one that hits write errors ends with
# blocks left.
#
# Part of the openmediavault-garage plugin.
# @license https://www.gnu.org/licenses/gpl.html GPL Version 3

api() {
	/usr/bin/garage -c "/etc/garage/$1.toml" json-api "$2" "$3" 2>/dev/null
}

for _ in $(seq 60); do
	if workers=$(api "$1" ListWorkers '{"node":"self","body":{"busyOnly":true}}'); then
		case $workers in
		*'"Block rebalance worker"'*) exit 0 ;;
		esac
		api "$1" LaunchRepairOperation \
			'{"node":"self","body":{"repairType":"rebalance"}}' >/dev/null &&
			exit 0
	fi
	sleep 1
done
echo "garage@$1: the rebalance did not start" >&2
exit 1
