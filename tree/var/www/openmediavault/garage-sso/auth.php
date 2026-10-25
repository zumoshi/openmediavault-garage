<?php
// nginx auth_request target guarding /garage-webui-<name>/. Answers 204 for
// an OMV administrator session, 401 without a valid session and 403 for any
// other role. read_and_close keeps the check read-only: it releases the
// session lock right after reading and never refreshes the session's last
// access time, so a web UI tab cannot keep an idle OMV session alive.
require_once("openmediavault/autoloader.inc");
require_once("openmediavault/env.inc");
require_once("openmediavault/functions.inc");

function omvSessionStatus(): int
{
    // Without a cookie session_start() would create an empty session file.
    if (!isset($_COOKIE[session_name()])) {
        return 401;
    }
    session_start(["read_and_close" => true]);
    $session = &\OMV\Session::getInstance();
    if (!$session->isAuthenticated() || $session->isTimeout() ||
            false === posix_getpwnam($session->getUsername())) {
        return 401;
    }
    return ($session->getRole() & OMV_ROLE_ADMINISTRATOR) ? 204 : 403;
}

http_response_code(omvSessionStatus());
