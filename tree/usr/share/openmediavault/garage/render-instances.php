#!/usr/bin/php
<?php
/**
 * Print the render model of every Garage instance as JSON, everything the
 * deployment writes for it, and the shared folders no instance uses:
 * {"instances": {"<name>": {"model": {...}} or {"error": "..."}},
 *  "unused_shares": ["<path>", ...]}
 * Exits 1 with the reason on stderr when the configuration cannot be read.
 *
 * Part of the openmediavault-garage plugin.
 * @license https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

require_once("openmediavault/autoloader.inc");
require_once("openmediavault/globals.inc");
require_once("/usr/share/openmediavault/garage/lib/render.php");

use function OMV\Garage\renderModel;
use function OMV\Garage\unusedShares;

// The way Salt's omv_conf.get_sharedfolder_path builds it, ending in "/".
function sharedFolderPath(\OMV\Config\Database $db, string $uuid): string
{
	$folder = $db->get("conf.system.sharedfolder", $uuid);
	$mount = $db->get("conf.system.filesystem.mountpoint",
		$folder->get("mntentref"));
	$dir = $mount->get("dir");
	$path = $dir . (str_ends_with($dir, "/") ? "" : "/") .
		ltrim($folder->get("reldirpath"), "/");
	return rtrim($path, "/") . "/";
}

function instanceModel(\OMV\Config\Database $db, \OMV\Config\ConfigObject $instance): array
{
	$datastores = array_map(fn($datastore) => $datastore->getAssoc(),
		$db->getByFilter("conf.service.garage.datastore", [
			"operator" => "stringEquals", "arg0" => "instanceuuid",
			"arg1" => $instance->get("uuid")]));
	$shares = array_merge(array_column($datastores, "shareuuid"),
		[$instance->get("storageshareuuid")]);
	if ($instance->get("storagesplit")) {
		$shares[] = $instance->get("metadatashareuuid");
	}
	if (strlen($instance->get("snapshotsshareuuid")) === 36) {
		$shares[] = $instance->get("snapshotsshareuuid");
	}
	$paths = [];
	foreach ($shares as $uuid) {
		$paths[$uuid] = sharedFolderPath($db, $uuid);
	}
	return renderModel($instance->getAssoc(), $datastores, $paths);
}

try {
	\OMV\DataModel\Manager::getInstance()->load();
	$db = \OMV\Config\Database::getInstance();
	$instances = [];
	$models = [];
	foreach ($db->get("conf.service.garage.instance") as $instance) {
		try {
			$model = instanceModel($db, $instance);
			$instances[$instance->get("name")] = ["model" => $model];
		} catch (\Throwable $e) {
			$model = null;
			$instances[$instance->get("name")] = ["error" =>
				"garage@" . $instance->get("name") . ": " . $e->getMessage()];
		}
		$models[] = $model;
	}
	$sharePaths = [];
	foreach ($db->get("conf.system.sharedfolder") as $folder) {
		try {
			$sharePaths[] = sharedFolderPath($db, $folder->get("uuid"));
		} catch (\Exception $e) {
			// A folder without a mount point has no ACL to revoke.
		}
	}
	echo json_encode(["instances" => (object)$instances,
		"unused_shares" => unusedShares($sharePaths, $models)],
		JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
} catch (\Throwable $e) {
	fwrite(STDERR, "garage: " . $e->getMessage() . "\n");
	exit(1);
}
