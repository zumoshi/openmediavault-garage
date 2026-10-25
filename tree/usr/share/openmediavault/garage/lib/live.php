<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * Garage owns buckets, keys and permissions. These functions turn its
 * admin API v2 responses into workbench rows, and form values into the
 * admin API calls that apply them.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

declare(strict_types=1);

namespace OMV\Garage;

const GIB = 1073741824;
const PERMISSIONS = ["read" => "allowread", "write" => "allowwrite", "owner" => "allowowner"];

/**
 * A bucket's display name: its first global alias, or the start of its id
 * for a bucket that has none (made through a local alias or the web UI).
 *
 * @param array $bucket A ListBuckets item or a GetBucketInfo response.
 */
function bucketLabel(array $bucket): string
{
	return $bucket["globalAliases"][0] ?? substr($bucket["id"], 0, 16);
}

/**
 * The workbench row and form values of a bucket. `name` is the global
 * alias the form edits, empty for an alias-less bucket.
 *
 * @param array $info A GetBucketInfo response.
 */
function bucketRow(array $info): array
{
	$website = $info["websiteConfig"] ?? [];
	return [
		"id" => $info["id"],
		"name" => $info["globalAliases"][0] ?? "",
		"label" => bucketLabel($info),
		"objects" => $info["objects"],
		"bytes" => $info["bytes"],
		"maxsize" => ($info["quotas"]["maxSize"] ?? 0) / GIB,
		"maxobjects" => $info["quotas"]["maxObjects"] ?? 0,
		"website" => $info["websiteAccess"],
		"indexdoc" => $website["indexDocument"] ?? "",
		"errordoc" => $website["errorDocument"] ?? "",
	];
}

/**
 * The UpdateBucket body for the bucket form's values. Zero means no quota.
 */
function bucketSettings(float $maxsize, int $maxobjects, bool $website,
	string $indexdoc, string $errordoc): array
{
	return [
		"quotas" => [
			"maxSize" => $maxsize > 0 ? intval($maxsize * GIB) : null,
			"maxObjects" => $maxobjects > 0 ? $maxobjects : null,
		],
		"websiteAccess" => $website ? [
			"enabled" => true,
			"indexDocument" => $indexdoc ?: "index.html",
			"errorDocument" => $errordoc ?: null,
		] : ["enabled" => false],
	];
}

/**
 * The admin API calls that make `$wanted` the bucket's name, in order. The
 * new alias is added before the old one is removed, so a failure in
 * between leaves the bucket reachable.
 *
 * @param string[] $globalAliases The bucket's current global aliases.
 * @return array<array{string,array}> [endpoint, body] pairs.
 */
function aliasChanges(string $bucketId, array $globalAliases, string $wanted): array
{
	$current = $globalAliases[0] ?? "";
	if ($wanted === $current) {
		return [];
	}
	$changes = [];
	if ($wanted !== "" && !in_array($wanted, $globalAliases, true)) {
		$changes[] = ["AddBucketAlias", ["bucketId" => $bucketId, "globalAlias" => $wanted]];
	}
	if ($current !== "") {
		$changes[] = ["RemoveBucketAlias", ["bucketId" => $bucketId, "globalAlias" => $current]];
	}
	return $changes;
}

/**
 * One row per key and bucket the key holds any permission on.
 *
 * @param array[] $bucketInfos GetBucketInfo responses.
 */
function permissionRows(array $bucketInfos): array
{
	$rows = [];
	foreach ($bucketInfos as $info) {
		foreach ($info["keys"] as $key) {
			if (!in_array(true, $key["permissions"], true)) {
				continue;
			}
			$row = [
				"id" => $key["accessKeyId"] . ":" . $info["id"],
				"keyid" => $key["accessKeyId"],
				"keyname" => $key["name"],
				"bucketid" => $info["id"],
				"bucketname" => bucketLabel($info),
			];
			foreach (PERMISSIONS as $permission => $field) {
				$row[$field] = $key["permissions"][$permission] ?? false;
			}
			$rows[] = $row;
		}
	}
	return $rows;
}

/**
 * The admin API calls that leave the key with exactly the wanted
 * permissions on the bucket.
 *
 * @param array<string,bool> $wanted By permission: read, write, owner.
 * @return array<array{string,array}> [endpoint, body] pairs.
 */
function permissionChanges(string $keyId, string $bucketId, array $wanted): array
{
	$changes = [];
	foreach (["AllowBucketKey" => true, "DenyBucketKey" => false] as $endpoint => $flag) {
		$permissions = array_fill_keys(array_keys($wanted, $flag, true), true);
		if ($permissions) {
			$changes[] = [$endpoint, ["bucketId" => $bucketId,
				"accessKeyId" => $keyId, "permissions" => $permissions]];
		}
	}
	return $changes;
}
