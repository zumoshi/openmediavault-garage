#!/usr/bin/php
<?php
/**
 * Bootstrap a single-node Garage instance: wait for the daemon, assign the
 * layout role with the aggregated datastore capacity, and keep the role in
 * sync when the capacity changes. Idempotent.
 *
 * Usage: bootstrap-instance.php <name> <capacity-in-bytes>
 *
 * Part of the openmediavault-garage plugin.
 * @license https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

if ($argc < 3) {
	fwrite(STDERR, "usage: bootstrap-instance.php <name> <capacity-in-bytes>\n");
	exit(2);
}

$name = $argv[1];
$capacity = intval($argv[2]);
$zone = getenv("OMV_GARAGE_ZONE") ?: "omv";
$configPath = "/etc/garage/" . $name . ".toml";

if (!is_readable($configPath)) {
	fwrite(STDERR, "config not readable: $configPath\n");
	exit(1);
}

function garageApi(string $configPath, string $endpoint, string $payload = "{}"): array
{
	$cmd = sprintf(
		"/usr/bin/garage -c %s json-api %s %s 2>&1",
		escapeshellarg($configPath),
		escapeshellarg($endpoint),
		escapeshellarg($payload)
	);
	$output = [];
	$rc = 0;
	exec($cmd, $output, $rc);
	if ($rc !== 0) {
		throw new RuntimeException("$endpoint failed: " . implode("\n", $output));
	}
	$json = json_decode(implode("\n", $output), true);
	if (!is_array($json)) {
		throw new RuntimeException("$endpoint returned no JSON: " . implode("\n", $output));
	}
	return $json;
}

// Wait for the daemon to answer RPCs (it may still be starting up).
$status = null;
for ($i = 0; $i < 30; $i++) {
	try {
		$status = garageApi($configPath, "GetClusterStatus");
		break;
	} catch (RuntimeException $e) {
		sleep(2);
	}
}
if (is_null($status)) {
	fwrite(STDERR, "garage@{$name} did not come up in time\n");
	exit(1);
}

$layoutVersion = intval($status["layoutVersion"] ?? 0);
$nodes = $status["nodes"] ?? [];
if (count($nodes) < 1) {
	fwrite(STDERR, "no node id available yet\n");
	exit(1);
}
$nodeId = $nodes[0]["id"];

$layout = $layoutVersion > 0
	? garageApi($configPath, "GetClusterLayout")
	: ["version" => 0, "roles" => []];

// Find the current role of this node, if any.
$existingRole = null;
foreach ($layout["roles"] ?? [] as $role) {
	if (($role["id"] ?? "") === $nodeId) {
		$existingRole = $role;
		break;
	}
}
foreach ($layout["stagedRoleChanges"] ?? [] as $role) {
	if (($role["id"] ?? "") === $nodeId) {
		$existingRole = $role;
		break;
	}
}

if ($layoutVersion > 0 && !is_null($existingRole)
		&& intval($existingRole["capacity"] ?? 0) === $capacity) {
	// Already converged. Update the staged role if the node id changed.
	exit(0);
}

$role = [
	"id" => $nodeId,
	"zone" => $zone,
	"capacity" => $capacity,
	"tags" => ["omv"]
];
garageApi($configPath, "UpdateClusterLayout",
	json_encode(["roles" => [$role]]));
garageApi($configPath, "ApplyClusterLayout",
	json_encode(["version" => $layoutVersion + 1]));
echo "garage@{$name}: layout applied (node {$nodeId}, capacity {$capacity})\n";
