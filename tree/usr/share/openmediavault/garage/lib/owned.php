<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

declare(strict_types=1);

namespace OMV\Garage;

/** The line every toml the plugin renders carries. */
const MARKER = "# Managed by openmediavault-garage.";

/**
 * The instances the plugin rendered that must no longer run: deleted or
 * disabled. A toml without the marker line belongs to the admin, not to
 * the plugin.
 *
 * @param array<string, string> $tomls Each toml's contents by instance name.
 * @param list<string> $names The enabled instances.
 * @return list<string>
 */
function orphans(array $tomls, array $names): array
{
	$rendered = array_filter($tomls, fn($toml) =>
		preg_match("/^" . preg_quote(MARKER, "/") . "/m", $toml) === 1);
	return array_values(array_diff(array_keys($rendered), $names));
}

/**
 * The shared folders the plugin holds a garage ACL on. An apply records
 * `granted` before it grants, revokes `revoke`, then records `kept`, so the
 * record always covers every ACL the plugin made. Folders it did not
 * record, such as a hand-made instance's, are never revoked.
 *
 * @param list<string> $recorded The record of the previous apply.
 * @param list<?array> $models Every instance's render model, null for one
 *   that cannot render: its folders are unknown, so nothing is revoked.
 * @return array{granted: list<string>, revoke: list<string>, kept: list<string>}
 */
function aclGrants(array $recorded, array $models): array
{
	$used = array_merge([], ...array_map(
		fn($model) => array_keys($model["shares"] ?? []), $models));
	$granted = array_values(array_unique(array_merge($recorded, $used)));
	sort($granted);
	$revoke = in_array(null, $models, true)
		? [] : array_values(array_diff($recorded, $used));
	return ["granted" => $granted, "revoke" => $revoke,
		"kept" => array_values(array_diff($granted, $revoke))];
}
