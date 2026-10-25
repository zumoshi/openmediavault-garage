<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

use function OMV\Garage\webUiPasswordHash;

final class WebUiPasswordHashTest extends TestCase
{
    private static function env(string $hash): string
    {
        return "PORT=3910\nAUTH_USER_PASS=admin:{$hash}\nS3_REGION=garage\n";
    }

    public function testHashesThePasswordWithoutAnEnvFile(): void
    {
        $hash = webUiPasswordHash("secret", "");

        self::assertStringStartsWith('$2y$', $hash);
        self::assertTrue(password_verify("secret", $hash));
    }

    public function testKeepsTheRenderedHashWhileItMatches(): void
    {
        $hash = password_hash("secret", PASSWORD_BCRYPT);

        self::assertSame($hash, webUiPasswordHash("secret", self::env($hash)));
    }

    public function testRehashesARenewedPassword(): void
    {
        $old = password_hash("old", PASSWORD_BCRYPT);
        $hash = webUiPasswordHash("new", self::env($old));

        self::assertNotSame($old, $hash);
        self::assertTrue(password_verify("new", $hash));
    }
}
