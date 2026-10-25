<?php

declare(strict_types=1);

use OMV\Garage\PortConflict;
use PHPUnit\Framework\TestCase;

use function OMV\Garage\portConflicts;

final class PortConflictsTest extends TestCase
{
    private const PORTS = ["s3port" => 3900, "rpcport" => 3901, "adminport" => 3903];

    public function testFreePortsHaveNoConflicts(): void
    {
        self::assertSame([], portConflicts(self::PORTS, [3910, 3911], [22, 80]));
    }

    public function testPortUsedTwiceIsReportedOnTheLaterField(): void
    {
        $ports = ["s3port" => 3903] + self::PORTS;

        self::assertSame(["adminport" => PortConflict::SameInstance],
            portConflicts($ports, [], []));
    }

    public function testPortOfAnotherInstance(): void
    {
        self::assertSame(["rpcport" => PortConflict::OtherInstance],
            portConflicts(self::PORTS, [3801, 3901], []));
    }

    public function testPortAnotherServiceListensOn(): void
    {
        self::assertSame(["s3port" => PortConflict::OtherService],
            portConflicts(self::PORTS, [], [22, 3900]));
    }

    public function testRunningInstanceIsNamedRatherThanItsListener(): void
    {
        self::assertSame(["s3port" => PortConflict::OtherInstance],
            portConflicts(self::PORTS, [3900], [3900]));
    }

    public function testEveryConflictingFieldIsReported(): void
    {
        $ports = ["webuiport" => 3901] + self::PORTS;

        self::assertSame([
            "rpcport" => PortConflict::SameInstance,
            "adminport" => PortConflict::OtherService,
        ], portConflicts($ports, [], [3903]));
    }
}
