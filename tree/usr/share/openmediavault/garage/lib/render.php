<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

declare(strict_types=1);

namespace OMV\Garage;

require_once(__DIR__ . "/live.php");

/**
 * The layout capacity of an instance without datastores. With one node it
 * is only a weight, garage needs some value, and free space must not move
 * it: a changed capacity would bump the layout on every apply.
 */
const SINGLE_DIR_LAYOUT_CAPACITY = 1024 * GIB;

enum StorageError
{
	case NoDatastore;
	case NoStorageCapacity;

	public function message(): string
	{
		return match ($this) {
			self::NoDatastore => "With a separate metadata shared folder, the data is stored on datastores only, so the instance needs at least one. Disable the instance, add a datastore in its details view, then enable it.",
			self::NoStorageCapacity => "Garage needs a capacity for every data folder once an instance has datastores. Enter the storage folder capacity in the instance settings.",
		};
	}
}

/**
 * Why an instance's data folders cannot be rendered, or null. Garage needs
 * at least one data folder, and a capacity on every entry of a list.
 */
function storageError(bool $split, int $storageCapacity, int $datastores): ?StorageError
{
	if ($split && $datastores === 0) {
		return StorageError::NoDatastore;
	}
	if (!$split && $datastores > 0 && $storageCapacity < 1) {
		return StorageError::NoStorageCapacity;
	}
	return null;
}

/**
 * Everything the deployment writes for one instance.
 *
 * @param array $instance The instance's confdb row.
 * @param array[] $datastores The instance's datastore rows.
 * @param array<string,string> $paths The path of every shared folder the
 *   instance uses by uuid, ending in "/" the way OMV builds it.
 * @return array{metadata_dir: string, snapshots_dir: ?string,
 *   data_dir: string|list<array{path: string, capacity: string}>,
 *   ports: array<string,?int>, paths: list<string>, dirs: list<string>,
 *   layout_capacity: int} `data_dir` is a single path without a capacity
 *   for the storage folder alone. `paths` are the shared folders systemd
 *   mounts and lets garage write, and that get the garage ACL.
 * @throws \DomainException For a StorageError.
 */
function renderModel(array $instance, array $datastores, array $paths): array
{
	$split = (bool)$instance["storagesplit"];
	$storageCapacity = intval($instance["storagecapacity"]);
	$error = storageError($split, $storageCapacity, count($datastores));
	if (!is_null($error)) {
		throw new \DomainException($error->message());
	}

	$storage = $paths[$instance["storageshareuuid"]];
	$storageBase = rtrim($storage, "/");
	$shares = [$storage];
	$dataDirs = [];
	if (!$split) {
		$metadataDir = $storageBase . "/meta";
		$dirs = [$metadataDir, $storageBase . "/data"];
		$dataDirs[] = ["path" => $storageBase . "/data",
			"capacity" => $storageCapacity];
	} elseif ($instance["metadatashareuuid"] === $instance["storageshareuuid"]) {
		$metadataDir = $storage;
		$dirs = [];
	} else {
		$metadata = $paths[$instance["metadatashareuuid"]];
		$metadataDir = rtrim($metadata, "/") . "/meta";
		$dirs = [$metadataDir];
		$shares[] = $metadata;
	}

	$snapshots = $paths[$instance["snapshotsshareuuid"]] ?? null;
	if (!is_null($snapshots)) {
		$shares[] = $snapshots;
	}
	foreach ($datastores as $datastore) {
		$path = $paths[$datastore["shareuuid"]];
		$shares[] = $path;
		$dataDirs[] = ["path" => $path, "capacity" => intval($datastore["capacity"])];
	}

	if ($datastores) {
		$dataDir = array_map(fn($dir) => ["path" => $dir["path"],
			"capacity" => $dir["capacity"] . "GiB"], $dataDirs);
		$layoutCapacity = array_sum(array_column($dataDirs, "capacity")) * GIB;
	} else {
		$dataDir = $dataDirs[0]["path"];
		$layoutCapacity = SINGLE_DIR_LAYOUT_CAPACITY;
	}

	return [
		"metadata_dir" => $metadataDir,
		"snapshots_dir" => $snapshots,
		"data_dir" => $dataDir,
		"ports" => [
			"s3" => intval($instance["s3port"]),
			"rpc" => intval($instance["rpcport"]),
			"admin" => intval($instance["adminport"]),
			"web" => $instance["webenable"] ? intval($instance["webport"]) : null,
			"webui" => $instance["webuienable"] ? intval($instance["webuiport"]) : null,
		],
		"paths" => $shares,
		"dirs" => $dirs,
		"layout_capacity" => $layoutCapacity,
	];
}
