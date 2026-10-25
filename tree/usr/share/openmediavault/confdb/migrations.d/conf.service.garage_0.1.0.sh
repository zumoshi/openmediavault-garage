#!/usr/bin/env dash
#
# This file is part of the openmediavault-garage plugin.
#
# @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
#
# Garage owns its buckets, access keys and permissions, so the copies
# earlier versions kept in confdb go. The admin API is always on, so the
# switch goes too. Deleting a node that is already gone is a no-op.
#
# The first pre-release only recorded metadatashareuuid, with the metadata
# at that folder's root. That is a split instance whose storage folder is
# the metadata folder. Rows that already name a storage folder are left
# alone, so running this twice changes nothing.

set -e

. /usr/share/openmediavault/scripts/helper-functions

omv_config_delete "/config/services/garage/buckets"
omv_config_delete "/config/services/garage/keys"
omv_config_delete "/config/services/garage/mappings"
omv_config_delete "/config/services/garage/instances/instance/adminenable"

xmlstarlet sel -t -m "/config/services/garage/instances/instance[string-length(storageshareuuid) != 36 and string-length(metadatashareuuid) = 36]" \
	-v "uuid" -n \
	${OMV_CONFIG_FILE} | xmlstarlet unesc |
	while read uuid; do
		row="/config/services/garage/instances/instance[uuid='${uuid}']"
		meta=$(omv_config_get "${row}/metadatashareuuid")
		omv_config_delete "${row}/storageshareuuid"
		omv_config_delete "${row}/storagesplit"
		omv_config_add_key "${row}" "storageshareuuid" "${meta}"
		omv_config_add_key "${row}" "storagesplit" "1"
	done

exit 0
