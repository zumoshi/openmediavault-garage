<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

declare(strict_types=1);

namespace OMV\Garage;

enum PortConflict
{
	case SameInstance;
	case OtherInstance;
	case OtherService;
}

/**
 * The fields of an instance whose port is taken. A port used by two fields
 * is reported on the later one.
 *
 * @param array<string,int> $ports The instance's ports by field.
 * @param int[] $instancePorts The ports of every other Garage instance.
 * @param int[] $listening The ports something listens on, without the ones
 *   this instance holds itself.
 * @return array<string,PortConflict>
 */
function portConflicts(array $ports, array $instancePorts, array $listening): array
{
	$conflicts = [];
	$claimed = [];
	foreach ($ports as $field => $port) {
		if (in_array($port, $claimed)) {
			$conflicts[$field] = PortConflict::SameInstance;
		} elseif (in_array($port, $instancePorts)) {
			$conflicts[$field] = PortConflict::OtherInstance;
		} elseif (in_array($port, $listening)) {
			$conflicts[$field] = PortConflict::OtherService;
		}
		$claimed[] = $port;
	}
	return $conflicts;
}
