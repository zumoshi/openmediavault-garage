#!/usr/bin/php
<?php
/**
 * Print the render model of a Garage instance as JSON: everything the
 * deployment writes for it. Exits 1 with the reason on stderr when the
 * instance cannot be rendered.
 *
 * Usage: render-instance.php <name>
 *
 * Part of the openmediavault-garage plugin.
 * @license https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

require_once("openmediavault/autoloader.inc");
require_once("openmediavault/globals.inc");
require_once("/usr/share/openmediavault/garage/lib/render.php");

use function OMV\Garage\renderModel;

function byField(\OMV\Config\Database $db, string $id, string $field,
	string $value): array
{
	return $db->getByFilter($id, ["operator" => "stringEquals",
		"arg0" => $field, "arg1" => $value]);
}

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

try {
	\OMV\DataModel\Manager::getInstance()->load();
	$db = \OMV\Config\Database::getInstance();
	$instance = byField($db, "conf.service.garage.instance", "name",
		$argv[1] ?? "")[0] ?? null;
	if (is_null($instance)) {
		throw new \Exception("no Garage instance named '" . ($argv[1] ?? "") . "'");
	}
	$datastores = array_map(fn($datastore) => $datastore->getAssoc(),
		byField($db, "conf.service.garage.datastore", "instanceuuid",
			$instance->get("uuid")));
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
	echo json_encode(renderModel($instance->getAssoc(), $datastores, $paths),
		JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
} catch (\Throwable $e) {
	fwrite(STDERR, "garage@" . ($argv[1] ?? "") . ": " . $e->getMessage() . "\n");
	exit(1);
}
