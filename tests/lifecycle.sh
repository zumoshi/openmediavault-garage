#!/bin/bash
# Install/upgrade/remove/purge cycle for a built plugin deb on an OMV host.
#
#   tests/lifecycle.sh root@omv-test.lan dist/openmediavault-garage_0.1.0-1_amd64.deb
#
# It purges the installed plugin first and purges it again in the cycle.
# Purge stops every instance the plugin manages and deletes them from
# confdb, so the script refuses to run while confdb holds an instance that
# is not a throwaway gt<hex> one, unless --force is given. Instance data on
# disk is never deleted. The host keeps the tested deb installed.
set -euo pipefail

if [ "${1:-}" != --on-target ]; then
	[ $# -ge 2 ] || {
		echo "usage: $0 <ssh-host> <deb> [--force]" >&2
		exit 2
	}
	host=$1 deb=$2 force=${3:-}
	ssh "$host" 'rm -rf /tmp/omv-garage-lifecycle && mkdir -m 0700 /tmp/omv-garage-lifecycle'
	scp -q "$0" "$host:/tmp/omv-garage-lifecycle/lifecycle.sh"
	scp -q "$deb" "$host:/tmp/omv-garage-lifecycle/plugin.deb"
	status=0
	ssh "$host" bash /tmp/omv-garage-lifecycle/lifecycle.sh --on-target \
		/tmp/omv-garage-lifecycle/plugin.deb "$force" || status=$?
	ssh "$host" 'rm -rf /tmp/omv-garage-lifecycle'
	exit $status
fi

deb=$2 force=${3:-}
work=$(dirname "$deb")
config=/etc/openmediavault/config.xml
record=/var/lib/openmediavault-garage/acls.json
fails=0

check() {
	local desc=$1
	shift
	if "$@"; then
		echo "ok   $desc"
	else
		echo "FAIL $desc"
		fails=$((fails + 1))
	fi
}

die() {
	echo "ERROR $*" >&2
	exit 2
}

rpc() { omv-rpc -u admin "$1" "$2" "${3:-"{}"}"; }
apply() { rpc Config applyChanges "{\"modules\": $1, \"force\": true}" >/dev/null; }
not() { ! "$@"; }
installed() { dpkg-query -W -f '${db:Status-Status}' openmediavault-garage 2>/dev/null | grep -qx installed; }
known() { dpkg-query -W openmediavault-garage >/dev/null 2>&1; }
active() { systemctl is-active --quiet "$1"; }
pid() { systemctl show -p MainPID --value "$1"; }
garage_acl() { getfacl -p "$1" 2>/dev/null | grep -q '^user:garage:'; }
confdb_has_node() { xmlstarlet sel -t -c /config/services/garage "$config" >/dev/null; }
confdb_has_instance() { [ "$(xmlstarlet sel -t -v "count(/config/services/garage/instances/instance[name='$1'])" "$config")" = 1 ]; }
rpc_serves() { rpc Garage enumerateInstances >/dev/null 2>&1; }
rpc_lists() { rpc Garage enumerateInstances 2>/dev/null | jq -e --arg n "$1" 'any(.[]; .name == $n)' >/dev/null; }
rpc_gone() {
	local out
	out=$(rpc Garage enumerateInstances 2>&1) && return 1
	grep -q "RPC service 'Garage' not found" <<<"$out"
}
workbench_has_garage() { grep -q 'services/garage' /var/www/openmediavault/assets/route-config.json; }
workbench_loads() { [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/)" = 200 ]; }
none_exist() { local f; for f in "$@"; do [ ! -e "$f" ] || return 1; done; }
data_kept() { [ -s "$work/data-before" ] && find "$1" -type f | sort | comm -23 "$work/data-before" - | not grep -q .; }
all_exist() { local f; for f in "$@"; do [ -e "$f" ] || return 1; done; }

# Runs a dpkg command and counts the engine restarts it caused. The
# restart-engined trigger asks monit, which restarts the engine after dpkg
# returns, so wait for the first restart and then give a second one time to
# show up.
engined_starts=0
dpkg_counting() {
	local cursor
	cursor=$(journalctl -u openmediavault-engined -n 0 --show-cursor | sed -n 's/^-- cursor: //p')
	"$@" >"$work/dpkg.log" 2>&1 || {
		cat "$work/dpkg.log" >&2
		die "$* failed"
	}
	starts() {
		journalctl -u openmediavault-engined --after-cursor "$cursor" -o cat | grep -c '^Started ' || true
	}
	for _ in $(seq 30); do
		[ "$(starts)" -gt 0 ] && break
		sleep 1
	done
	sleep 10
	engined_starts=$(starts)
}

foreign=$(xmlstarlet sel -t -v '/config/services/garage/instances/instance/name' -n "$config" 2>/dev/null |
	grep -v -x 'gt[0-9a-f]\{6\}' || true)
if [ -n "$foreign" ] && [ "$force" != --force ]; then
	die "purge would stop and forget these instances: ${foreign//$'\n'/ }. Back them up and pass --force."
fi

id=gt$(openssl rand -hex 3)
share=${id}a
hand=${id}h
handdir=/srv/$hand
handbase=3980
files=("/etc/garage/$id.toml" "/etc/garage/$id.rpc_secret" "/etc/garage/$id.webui.env"
	"/etc/nginx/openmediavault-webgui.d/garage-webui-$id.conf"
	"/etc/systemd/system/garage@$id.service.d")

make_hand_instance() {
	install -d -o garage -g garage -m 0700 "$handdir/meta" "$handdir/data"
	setfacl -m u:garage:rwx "$handdir"
	cat >"/etc/garage/$hand.toml" <<EOF
metadata_dir = "$handdir/meta"
data_dir = "$handdir/data"
replication_factor = 1
rpc_bind_addr = "127.0.0.1:$((handbase + 1))"
rpc_public_addr = "127.0.0.1:$((handbase + 1))"
rpc_secret_file = "/etc/garage/$hand.rpc_secret"

[s3_api]
s3_region = "garage"
api_bind_addr = "127.0.0.1:$handbase"

[admin]
api_bind_addr = "127.0.0.1:$((handbase + 3))"
EOF
	openssl rand -hex 32 >"/etc/garage/$hand.rpc_secret"
	chown root:garage "/etc/garage/$hand.toml"
	chmod 0640 "/etc/garage/$hand.toml"
	chown garage:garage "/etc/garage/$hand.rpc_secret"
	chmod 0600 "/etc/garage/$hand.rpc_secret"
	mkdir -p "/etc/systemd/system/garage@$hand.service.d"
	printf '[Service]\nReadWritePaths=%s\n' "$handdir" \
		>"/etc/systemd/system/garage@$hand.service.d/override.conf"
	systemctl daemon-reload
	systemctl start "garage@$hand.service"
}

share_uuid() { rpc ShareMgmt enumerateSharedFolders | jq -r --arg n "$share" '.[] | select(.name == $n) | .uuid'; }
share_path() { rpc ShareMgmt enumerateSharedFolders | jq -r --arg n "$share" '.[] | select(.name == $n) | .mntent.dir + "/" + .reldirpath'; }

finish() {
	set +e
	installed || dpkg -i "$deb" >/dev/null 2>&1 || echo "ERROR could not reinstall $deb" >&2
	uuid=$(rpc Garage enumerateInstances 2>/dev/null | jq -r --arg n "$id" '.[] | select(.name == $n) | .uuid')
	if [ -n "$uuid" ]; then
		rpc Garage deleteInstance "{\"uuid\": \"$uuid\"}" >/dev/null
		apply '["garage"]'
	fi
	systemctl stop "garage@$hand.service" 2>/dev/null
	rm -rf "/etc/garage/$hand.toml" "/etc/garage/$hand.rpc_secret" \
		"/etc/systemd/system/garage@$hand.service.d" "$handdir"
	systemctl daemon-reload
	uuid=$(share_uuid)
	if [ -n "$uuid" ]; then
		rpc ShareMgmt delete "{\"uuid\": \"$uuid\", \"recursive\": true}" >/dev/null
		apply '["sharedfolders", "systemd", "task"]'
	fi
	apply '["garage"]'
}
trap finish EXIT

if known; then
	dpkg_counting dpkg -P openmediavault-garage
fi

echo "# install"
dpkg_counting dpkg -i "$deb"
check "install restarted the engine once (got $engined_starts)" [ "$engined_starts" = 1 ]
check "the engine serves the Garage RPC" rpc_serves
check "confdb has /config/services/garage" confdb_has_node
check "workbench has the garage pages" workbench_has_garage
check "plugin is in the OMV network section" \
	[ "$(dpkg-query -W -f '${Plugin-Section}' openmediavault-garage)" = network ]

mntent=$(rpc ShareMgmt enumerateSharedFolders | jq -r '.[0].mntentref // empty')
[ -n "$mntent" ] || mntent=$(rpc FileSystemMgmt getMountCandidates | jq -r '.[0].uuid')
rpc ShareMgmt set "{\"uuid\": \"fa4b1c66-ef79-11e5-87a0-0002b3a176b4\", \"name\": \"$share\",
	\"reldirpath\": \"$share/\", \"comment\": \"lifecycle test\", \"mntentref\": \"$mntent\",
	\"mode\": \"775\"}" >/dev/null
apply '["sharedfolders", "systemd", "task"]'
sharedir=$(share_path)
rpc Garage setInstance "{\"uuid\": \"fa4b1c66-ef79-11e5-87a0-0002b3a176b4\", \"enable\": true,
	\"name\": \"$id\", \"storageshareuuid\": \"$(share_uuid)\", \"storagesplit\": false,
	\"s3port\": 3900, \"rpcport\": 3901, \"webport\": 3902, \"adminport\": 3903,
	\"s3region\": \"garage\", \"dbengine\": \"lmdb\", \"compressionlevel\": 1,
	\"loglevel\": \"info\", \"webuienable\": true, \"webuiuser\": \"admin\"}" >/dev/null
apply '["garage"]'
make_hand_instance
active "garage@$id" || die "garage@$id did not start"
active "omv-garage-webui@$id" || die "omv-garage-webui@$id did not start"
active "garage@$hand" || die "hand-made garage@$hand did not start"
hand_pid=$(pid "garage@$hand")
check "plugin instance has its files" all_exist "${files[@]}"
check "the share the instance uses has the garage ACL" garage_acl "$sharedir"
check "the ACL record lists the share" grep -qF "\"$sharedir\"" "$record"

echo "# upgrade"
rm -rf "$work/repack"
dpkg-deb -R "$deb" "$work/repack"
sed -i 's/^Version: .*/&+lifecycle1/' "$work/repack/DEBIAN/control"
dpkg-deb -b "$work/repack" "$work/plugin-next.deb" >/dev/null
garage_pid=$(pid "garage@$id")
webui_pid=$(pid "omv-garage-webui@$id")
dpkg_counting dpkg -i "$work/plugin-next.deb"
check "upgrade installed $(dpkg-deb -f "$work/plugin-next.deb" Version)" \
	[ "$(dpkg-query -W -f '${Version}' openmediavault-garage)" = "$(dpkg-deb -f "$work/plugin-next.deb" Version)" ]
check "upgrade restarted the engine once (got $engined_starts)" [ "$engined_starts" = 1 ]
check "upgrade left garage@$id running as is" [ "$(pid "garage@$id")" = "$garage_pid" ]
check "upgrade restarted the running web UI ($webui_pid -> $(pid "omv-garage-webui@$id"))" \
	[ "$(pid "omv-garage-webui@$id")" != "$webui_pid" ]
check "web UI is active after upgrade" active "omv-garage-webui@$id"
check "web UI unit needs no daemon-reload" \
	[ "$(systemctl show -p NeedDaemonReload --value "omv-garage-webui@$id")" = no ]

echo "# remove"
dpkg_counting dpkg -r openmediavault-garage
check "remove restarted the engine once (got $engined_starts)" [ "$engined_starts" = 1 ]
check "the engine no longer serves the Garage RPC" rpc_gone
check "remove stopped garage@$id" not active "garage@$id"
check "remove stopped omv-garage-webui@$id" not active "omv-garage-webui@$id"
check "remove deleted the instance's files" none_exist "${files[@]}"
check "remove kept the instance in confdb" confdb_has_instance "$id"
check "remove kept the ACL record" grep -qF "\"$sharedir\"" "$record"
check "remove kept the instance data" [ -n "$(ls -A "$sharedir")" ]
check "remove left the hand-made instance running" [ "$(pid "garage@$hand")" = "$hand_pid" ]
check "remove kept the hand-made instance's files" all_exist "/etc/garage/$hand.toml" "/etc/garage/$hand.rpc_secret"
check "workbench dropped the garage pages" not workbench_has_garage
check "workbench loads" workbench_loads

echo "# reinstall"
dpkg -i "$deb" >/dev/null 2>&1 || die "reinstall failed"
check "reinstall marks garage dirty" grep -q '"garage"' /var/lib/openmediavault/dirtymodules.json
apply '["garage"]'
check "apply after reinstall starts garage@$id from confdb" active "garage@$id"
check "apply after reinstall starts its web UI" active "omv-garage-webui@$id"
check "the RPC lists $id again" rpc_lists "$id"

echo "# purge"
find "$sharedir" -type f | sort >"$work/data-before"
dpkg_counting dpkg -P openmediavault-garage
check "purge removed the package" not known
check "purge stopped garage@$id" not active "garage@$id"
check "purge deleted the instance's files" none_exist "${files[@]}"
check "purge deleted /config/services/garage" not confdb_has_node
check "purge revoked the recorded garage ACL" not garage_acl "$sharedir"
check "purge deleted /var/lib/openmediavault-garage" [ ! -e /var/lib/openmediavault-garage ]
check "purge deleted no instance data" data_kept "$sharedir"
check "purge left the hand-made instance running" [ "$(pid "garage@$hand")" = "$hand_pid" ]
check "purge kept the hand-made instance's ACL" garage_acl "$handdir"
check "workbench dropped the garage pages" not workbench_has_garage
check "workbench loads" workbench_loads

echo "# $fails failed"
[ "$fails" -eq 0 ]
