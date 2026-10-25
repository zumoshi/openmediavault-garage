#!/usr/bin/env dash
#
# This file is part of the openmediavault-garage plugin.
#
# @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
#
# Garage owns its buckets, access keys and permissions, so the copies
# earlier versions kept in confdb go. The admin API is always on, so the
# switch goes too. Deleting a node that is already gone is a no-op.

set -e

. /usr/share/openmediavault/scripts/helper-functions

omv_config_delete "/config/services/garage/buckets"
omv_config_delete "/config/services/garage/keys"
omv_config_delete "/config/services/garage/mappings"
omv_config_delete "/config/services/garage/instances/instance/adminenable"

exit 0
