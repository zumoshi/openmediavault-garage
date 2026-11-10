#!/usr/bin/env dash
#
# This file is part of the openmediavault-garage plugin.
#
# @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
#
# OpenMediaVault is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.

set -e

. /usr/share/openmediavault/scripts/helper-functions

########################################################################
# Update the configuration.
# <config>
#   <services>
#     <garage>
#       <instances>
#         <instance>
#           <uuid>...</uuid>
#           <enable>0|1</enable>
#           <storageshareuuid>...</storageshareuuid>
#           <storagesplit>0|1</storagesplit>
#           <storagecapacity>0</storagecapacity>
#           <name>...</name>
#           <s3port>3900</s3port>
#           <rpcport>3901</rpcport>
#           <s3region>garage</s3region>
#           <s3rootdomain></s3rootdomain>
#           <s3publicendpoint></s3publicendpoint>
#           <webenable>0|1</webenable>
#           <webport>3902</webport>
#           <webrootdomain></webrootdomain>
#           <adminport>3903</adminport>
#           <dbengine>lmdb</dbengine>
#           <compressionlevel>1</compressionlevel>
#           <compressiondisable>0|1</compressiondisable>
#           <snapshotinterval></snapshotinterval>
#           <metadatashareuuid>...</metadatashareuuid>
#           <snapshotsshareuuid></snapshotsshareuuid>
#           <metadatafsync>0|1</metadatafsync>
#           <datafsync>0|1</datafsync>
#           <disablescrub>0|1</disablescrub>
#           <loglevel>info</loglevel>
#           <blocksize></blocksize>
#           <blockrambuffermax></blockrambuffermax>
#           <blockmaxconcurrentreads></blockmaxconcurrentreads>
#           <blockmaxconcurrentwrites></blockmaxconcurrentwrites>
#           <lmdbmapsize></lmdbmapsize>
#           <rpcsecret>...</rpcsecret>
#           <admintoken>...</admintoken>
#           <webuienable>0|1</webuienable>
#           <webuiport>3910</webuiport>
#           <webuiuser>admin</webuiuser>
#           <webuipassword>...</webuipassword>
#         </instance>
#       </instances>
#       <datastores>
#         <datastore>
#           <uuid>...</uuid>
#           <instanceuuid>...</instanceuuid>
#           <shareuuid>...</shareuuid>
#           <capacity>1</capacity>
#           <state>active|draining</state>
#         </datastore>
#       </datastores>
#     </garage>
#   </services>
# </config>
########################################################################
if ! omv_config_exists "/config/services/garage"; then
	omv_config_add_node "/config/services" "garage"
	omv_config_add_node "/config/services/garage" "instances"
	omv_config_add_node "/config/services/garage" "datastores"
fi

exit 0
