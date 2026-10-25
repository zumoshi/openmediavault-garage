#!/usr/bin/php
<?php
/**
 * Print the bcrypt hash of the web UI password read from stdin, reusing
 * the one in the env file while it still matches.
 *
 * Usage: webui-password-hash.php <env-file> < password
 *
 * Part of the openmediavault-garage plugin.
 * @license https://www.gnu.org/licenses/gpl.html GPL Version 3
 */

require_once("/usr/share/openmediavault/garage/lib/webui.php");

$env = is_readable($argv[1]) ? file_get_contents($argv[1]) : "";
echo \OMV\Garage\webUiPasswordHash(stream_get_contents(STDIN), $env);
