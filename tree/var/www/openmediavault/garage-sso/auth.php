<?php
// nginx auth_request target guarding /garage-webui-<name>/. Answers 204 for
// an OMV administrator session, 401 without a valid session and 403 for any
// other role. An administrator's request refreshes the session's last access
// like every rpc.php call does, so a web UI in use keeps the OMV session
// alive. The check runs on a read_and_close session; the session lock is
// only taken again for that one write.
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
    if (!($session->getRole() & OMV_ROLE_ADMINISTRATOR)) {
        return 403;
    }
    session_start();
    // A logout between the check and the lock destroyed the session.
    if (!$session->isAuthenticated()) {
        session_abort();
        return 401;
    }
    $session->updateLastAccess();
    $session->commit();
    return 204;
}

http_response_code(omvSessionStatus());
