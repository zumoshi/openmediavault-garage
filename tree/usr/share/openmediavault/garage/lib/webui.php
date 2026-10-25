<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

declare(strict_types=1);

namespace OMV\Garage;

/**
 * The bcrypt hash for AUTH_USER_PASS in the web UI env file `$env`. The
 * hash already there is kept while it matches the password: a fresh salt
 * on every apply would rewrite the file and restart the web UI.
 */
function webUiPasswordHash(string $password, string $env): string
{
	if (preg_match('/^AUTH_USER_PASS=[^:\n]*:(.+)$/m', $env, $match) &&
		password_verify($password, $match[1])) {
		return $match[1];
	}
	return password_hash($password, PASSWORD_BCRYPT);
}
