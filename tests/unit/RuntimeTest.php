<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class RuntimeTest extends TestCase
{
    public function testRunsOnThePhpThatOmv8Ships(): void
    {
        self::assertSame('8.4', PHP_MAJOR_VERSION . '.' . PHP_MINOR_VERSION, 'OMV 8 on Debian 13 ships PHP 8.4');
    }
}
