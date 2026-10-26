<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

declare(strict_types=1);

namespace OMV\Garage;

/**
 * Where a draining datastore is on its way out. Only rebalance moves
 * blocks off a read-only data folder, and garage forgets it on restart, so
 * an empty folder is only proven once the running garage has it read-only
 * and a rebalance has finished since it started.
 */
enum DrainStatus
{
	/** Garage does not run with the datastore read-only yet. */
	case Pending;
	case Migrating;
	/** Nothing left to move: the row can go. */
	case Empty;
}

/**
 * @param ?int $blockFiles Null when the folder holds no garage data
 *   directory, for example because it is not mounted.
 */
function drainStatus(bool $runsReadOnly, bool $rebalanced, ?int $blockFiles): DrainStatus
{
	if (!$runsReadOnly) {
		return DrainStatus::Pending;
	}
	return $rebalanced && $blockFiles === 0
		? DrainStatus::Empty : DrainStatus::Migrating;
}

/**
 * Whether the garage process that started at $startedAt (null when not
 * running) loaded $toml, written at $tomlMtime, with $path as a read-only
 * data folder. A trailing "/" does not matter.
 */
function runsReadOnly(string $toml, string $path, ?int $startedAt, int $tomlMtime): bool
{
	if (is_null($startedAt) || $startedAt < $tomlMtime) {
		return false;
	}
	preg_match_all('/^\s*\{ path = ("(?:[^"\\\\]|\\\\.)*"), read_only = true \}/m',
		$toml, $matches);
	return in_array(rtrim($path, "/"), array_map(
		fn($entry) => rtrim(json_decode($entry), "/"), $matches[1]), true);
}

/**
 * The block files garage keeps in data folder $dir, counted up to $limit.
 * Null when $dir has no garage marker.
 */
function blockFiles(string $dir, int $limit): ?int
{
	if (!is_file($dir . "/garage-marker")) {
		return null;
	}
	$files = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($dir,
		\FilesystemIterator::SKIP_DOTS));
	$count = 0;
	foreach ($files as $file) {
		if ($count >= $limit) {
			break;
		}
		if ($file->isFile() && $file->getFilename() !== "garage-marker") {
			$count++;
		}
	}
	return $count;
}
