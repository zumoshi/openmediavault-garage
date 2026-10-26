<?php

declare(strict_types=1);

use OMV\Garage\DrainStatus;
use PHPUnit\Framework\TestCase;

use function OMV\Garage\blockFiles;
use function OMV\Garage\drainStatus;
use function OMV\Garage\runsReadOnly;

final class DrainTest extends TestCase
{
    private const TOML = <<<'TOML'
        metadata_dir = "/srv/meta/"
        data_dir = [
          { path = "/srv/a/", capacity = "10GiB" },
          { path = "/srv/b \"q\" é/", read_only = true }
        ]
        TOML;

    private string $dir;

    protected function setUp(): void
    {
        $this->dir = sys_get_temp_dir() . "/drain-" . bin2hex(random_bytes(4));
        mkdir($this->dir . "/ab/cd", 0777, true);
    }

    protected function tearDown(): void
    {
        exec("rm -rf " . escapeshellarg($this->dir));
    }

    public function testRunsReadOnlyOnlyWhenGarageLoadedTheReadOnlyEntry(): void
    {
        $path = "/srv/b \"q\" é/";
        self::assertSame([true, true, true, false, false, false],
            [runsReadOnly(self::TOML, $path, 1000, 1000),
                runsReadOnly(self::TOML, rtrim($path, "/"), 1000, 1000),
                runsReadOnly(self::TOML, $path, 1001, 1000),
                runsReadOnly(self::TOML, $path, 999, 1000),
                runsReadOnly(self::TOML, $path, null, 1000),
                runsReadOnly(self::TOML, "/srv/a/", 1001, 1000)]);
    }

    public function testDrainStatus(): void
    {
        self::assertSame(
            [DrainStatus::Pending, DrainStatus::Pending,
                DrainStatus::Migrating, DrainStatus::Migrating,
                DrainStatus::Migrating, DrainStatus::Empty],
            [drainStatus(false, true, 0), drainStatus(false, false, 3),
                drainStatus(true, true, 3), drainStatus(true, false, 0),
                drainStatus(true, true, null), drainStatus(true, true, 0)]);
    }

    public function testBlockFilesSkipsTheMarkerAndStopsAtTheLimit(): void
    {
        touch($this->dir . "/garage-marker");
        self::assertSame(0, blockFiles($this->dir, 3));
        foreach (["a", "b", "c", "d"] as $file) {
            touch($this->dir . "/ab/cd/" . $file);
        }
        self::assertSame([3, 4], [blockFiles($this->dir, 3),
            blockFiles($this->dir, 10)]);
    }

    public function testBlockFilesIsUnknownWithoutTheMarker(): void
    {
        self::assertNull(blockFiles($this->dir, 10));
        self::assertNull(blockFiles($this->dir . "/missing", 10));
    }
}
