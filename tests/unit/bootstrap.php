<?php

declare(strict_types=1);

// The RPC require_once's these files on the box; load them the same way.
foreach (glob(__DIR__ . '/../../tree/usr/share/openmediavault/garage/lib/*.php') as $file) {
    require_once $file;
}
