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
 * at least one writable data folder, and a capacity on every writable
 * entry of a list. A draining datastore is a read-only entry.
 *
 * @param array[] $datastores The instance's datastore rows.
 */
function storageError(bool $split, int $storageCapacity, array $datastores): ?StorageError
{
	$active = array_filter($datastores, fn($datastore) => !draining($datastore));
	if ($split && !$active) {
		return StorageError::NoDatastore;
	}
	if (!$split && $datastores && $storageCapacity < 1) {
		return StorageError::NoStorageCapacity;
	}
	return null;
}

function draining(array $datastore): bool
{
	return $datastore["state"] === "draining";
}

/**
 * Everything the deployment writes for one instance.
 *
 * @param array $instance The instance's confdb row.
 * @param array[] $datastores The instance's datastore rows.
 * @param array<string,string> $paths The path of every shared folder the
 *   instance uses by uuid, ending in "/" the way OMV builds it.
 * @return array{metadata_dir: string, snapshots_dir: ?string,
 *   data_dir: string|list<array>, ports: array<string,?int>,
 *   shares: array<string,string>, dirs: list<string>,
 *   layout_capacity: int, drain: bool} `data_dir` is a single path
 *   without a capacity for the storage folder alone. A draining datastore
 *   is a `read_only` entry without capacity. `shares` maps the shared
 *   folders systemd mounts and lets garage write to the ACL permissions
 *   garage needs on them: "rwx" where garage writes into the folder
 *   itself, "--x" where it only enters the directories made for it.
 *   `drain` starts a rebalance with garage, which moves the blocks off the
 *   read-only entries.
 * @throws \DomainException For a StorageError.
 */
function renderModel(array $instance, array $datastores, array $paths): array
{
	$split = (bool)$instance["storagesplit"];
	$storageCapacity = intval($instance["storagecapacity"]);
	$error = storageError($split, $storageCapacity, $datastores);
	if (!is_null($error)) {
		throw new \DomainException($error->message());
	}

	$shares = [];
	$grant = function (string $path, string $perms) use (&$shares): void {
		if (($shares[$path] ?? "") !== "rwx") {
			$shares[$path] = $perms;
		}
	};
	$storage = $paths[$instance["storageshareuuid"]];
	$storageBase = rtrim($storage, "/");
	$dataDirs = [];
	if (!$split) {
		$metadataDir = $storageBase . "/meta";
		$dirs = [$metadataDir, $storageBase . "/data"];
		$dataDirs[] = ["path" => $storageBase . "/data",
			"capacity" => $storageCapacity];
		$grant($storage, "--x");
	} elseif ($instance["metadatashareuuid"] === $instance["storageshareuuid"]) {
		$metadataDir = $storage;
		$dirs = [];
		$grant($storage, "rwx");
	} else {
		$metadata = $paths[$instance["metadatashareuuid"]];
		$metadataDir = rtrim($metadata, "/") . "/meta";
		$dirs = [$metadataDir];
		$grant($storage, "--x");
		$grant($metadata, "--x");
	}

	$snapshots = $paths[$instance["snapshotsshareuuid"]] ?? null;
	if (!is_null($snapshots)) {
		$grant($snapshots, "rwx");
	}
	foreach ($datastores as $datastore) {
		$path = $paths[$datastore["shareuuid"]];
		$grant($path, "rwx");
		$dataDirs[] = draining($datastore)
			? ["path" => $path, "read_only" => true]
			: ["path" => $path, "capacity" => intval($datastore["capacity"])];
	}

	if ($datastores) {
		$dataDir = array_map(fn($dir) => isset($dir["capacity"])
			? ["path" => $dir["path"], "capacity" => $dir["capacity"] . "GiB"]
			: $dir, $dataDirs);
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
		"shares" => $shares,
		"dirs" => $dirs,
		"layout_capacity" => $layoutCapacity,
		"drain" => in_array("draining", array_column($datastores, "state"), true),
	];
}

/**
 * The shared folders no instance uses, whose garage ACL can go. None while
 * an instance cannot render (null model), as its folders are unknown.
 *
 * @param list<string> $sharePaths Every shared folder's path.
 * @param list<?array> $models Every instance's render model.
 * @return list<string>
 */
function unusedShares(array $sharePaths, array $models): array
{
	if (in_array(null, $models, true)) {
		return [];
	}
	$used = array_merge([], ...array_map(
		fn($model) => array_keys($model["shares"]), $models));
	return array_values(array_diff($sharePaths, $used));
}
