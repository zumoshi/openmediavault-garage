<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

use function OMV\Garage\aliasChanges;
use function OMV\Garage\bucketLabel;
use function OMV\Garage\bucketRow;
use function OMV\Garage\bucketSettings;
use function OMV\Garage\permissionChanges;
use function OMV\Garage\permissionRows;

final class LiveStateTest extends TestCase
{
    private const BUCKET_ID = '62d52ea102db14a7bd26da245a81f2fb4e3c7a0d5ffec71b376f686baee00e14';
    private const OTHER_ID = 'a3f1000000000000000000000000000000000000000000000000000000000000';
    private const GIB = 1073741824;

    /** A GetBucketInfo response as garage 2.4.1 sends it. */
    private static function info(array $overrides = []): array
    {
        return array_merge([
            'id' => self::BUCKET_ID,
            'created' => '2026-10-18T11:58:40.871Z',
            'globalAliases' => ['media'],
            'websiteAccess' => false,
            'websiteConfig' => null,
            'keys' => [],
            'objects' => 1,
            'bytes' => 22,
            'unfinishedUploads' => 0,
            'unfinishedMultipartUploads' => 0,
            'unfinishedMultipartUploadParts' => 0,
            'unfinishedMultipartUploadBytes' => 0,
            'quotas' => ['maxSize' => null, 'maxObjects' => null],
        ], $overrides);
    }

    private static function grant(string $keyId, string $name, bool $read,
        bool $write, bool $owner): array
    {
        return ['accessKeyId' => $keyId, 'name' => $name, 'bucketLocalAliases' => [],
            'permissions' => ['read' => $read, 'write' => $write, 'owner' => $owner]];
    }

    public function testBucketIsLabelledByItsFirstGlobalAlias(): void
    {
        self::assertSame('media', bucketLabel(['id' => self::BUCKET_ID,
            'globalAliases' => ['media', 'films']]));
    }

    public function testAliaslessBucketIsLabelledByTheStartOfItsId(): void
    {
        self::assertSame('62d52ea102db14a7', bucketLabel(['id' => self::BUCKET_ID,
            'globalAliases' => []]));
    }

    public function testBucketRowCarriesUsageQuotasAndWebsite(): void
    {
        $row = bucketRow(self::info([
            'websiteAccess' => true,
            'websiteConfig' => ['indexDocument' => 'home.html', 'errorDocument' => '404.html'],
            'quotas' => ['maxSize' => 3 * self::GIB / 2, 'maxObjects' => 50],
        ]));

        self::assertEquals([
            'id' => self::BUCKET_ID,
            'name' => 'media',
            'label' => 'media',
            'objects' => 1,
            'bytes' => 22,
            'maxsize' => 1.5,
            'maxobjects' => 50,
            'website' => true,
            'indexdoc' => 'home.html',
            'errordoc' => '404.html',
        ], $row);
    }

    public function testAliaslessBucketRowHasNoNameButALabelAndItsUsage(): void
    {
        $row = bucketRow(self::info(['globalAliases' => [], 'objects' => 3, 'bytes' => 4096]));

        self::assertSame(['', '62d52ea102db14a7', 3, 4096],
            [$row['name'], $row['label'], $row['objects'], $row['bytes']]);
    }

    public function testUnlimitedQuotasAndNoWebsiteReadAsZeroAndEmpty(): void
    {
        $row = bucketRow(self::info());

        self::assertSame([0, 0, false, '', ''], [$row['maxsize'], $row['maxobjects'],
            $row['website'], $row['indexdoc'], $row['errordoc']]);
    }

    public function testSettingsTurnGibAndZeroIntoGarageQuotas(): void
    {
        self::assertSame([
            'quotas' => ['maxSize' => 3 * self::GIB / 2, 'maxObjects' => null],
            'websiteAccess' => ['enabled' => false],
        ], bucketSettings(1.5, 0, false, '', ''));
    }

    public function testWebsiteDefaultsToIndexHtmlAndNoErrorDocument(): void
    {
        self::assertSame([
            'quotas' => ['maxSize' => null, 'maxObjects' => 7],
            'websiteAccess' => ['enabled' => true, 'indexDocument' => 'index.html',
                'errorDocument' => null],
        ], bucketSettings(0, 7, true, '', ''));
    }

    public function testSettingsReadBackAsWritten(): void
    {
        $body = bucketSettings(2.25, 9, true, 'a.html', 'b.html');
        $row = bucketRow(self::info([
            'quotas' => $body['quotas'],
            'websiteAccess' => $body['websiteAccess']['enabled'],
            'websiteConfig' => ['indexDocument' => $body['websiteAccess']['indexDocument'],
                'errorDocument' => $body['websiteAccess']['errorDocument']],
        ]));

        self::assertEquals([2.25, 9, true, 'a.html', 'b.html'], [$row['maxsize'],
            $row['maxobjects'], $row['website'], $row['indexdoc'], $row['errordoc']]);
    }

    public function testKeepingTheNameChangesNoAlias(): void
    {
        self::assertSame([], aliasChanges(self::BUCKET_ID, ['media'], 'media'));
        self::assertSame([], aliasChanges(self::BUCKET_ID, [], ''));
    }

    public function testRenameAddsTheNewAliasBeforeRemovingTheOld(): void
    {
        self::assertSame([
            ['AddBucketAlias', ['bucketId' => self::BUCKET_ID, 'globalAlias' => 'films']],
            ['RemoveBucketAlias', ['bucketId' => self::BUCKET_ID, 'globalAlias' => 'media']],
        ], aliasChanges(self::BUCKET_ID, ['media'], 'films'));
    }

    public function testNamingAnAliaslessBucketOnlyAddsAnAlias(): void
    {
        self::assertSame([
            ['AddBucketAlias', ['bucketId' => self::BUCKET_ID, 'globalAlias' => 'films']],
        ], aliasChanges(self::BUCKET_ID, [], 'films'));
    }

    public function testRenameToAnotherOfItsAliasesOnlyRemovesTheFirst(): void
    {
        self::assertSame([
            ['RemoveBucketAlias', ['bucketId' => self::BUCKET_ID, 'globalAlias' => 'media']],
        ], aliasChanges(self::BUCKET_ID, ['media', 'films'], 'films'));
    }

    public function testClearingTheNameRemovesTheAlias(): void
    {
        self::assertSame([
            ['RemoveBucketAlias', ['bucketId' => self::BUCKET_ID, 'globalAlias' => 'media']],
        ], aliasChanges(self::BUCKET_ID, ['media'], ''));
    }

    public function testOnePermissionRowPerKeyAndBucketWithAGrant(): void
    {
        $rows = permissionRows([
            self::info(['keys' => [
                self::grant('GKaa', 'alice', true, false, false),
                self::grant('GKbb', 'bob', true, true, true),
            ]]),
            self::info(['id' => self::OTHER_ID, 'globalAliases' => [], 'keys' => [
                self::grant('GKaa', 'alice', false, true, false),
            ]]),
        ]);

        self::assertSame([
            ['id' => 'GKaa:' . self::BUCKET_ID, 'keyid' => 'GKaa', 'keyname' => 'alice',
                'bucketid' => self::BUCKET_ID, 'bucketname' => 'media',
                'allowread' => true, 'allowwrite' => false, 'allowowner' => false],
            ['id' => 'GKbb:' . self::BUCKET_ID, 'keyid' => 'GKbb', 'keyname' => 'bob',
                'bucketid' => self::BUCKET_ID, 'bucketname' => 'media',
                'allowread' => true, 'allowwrite' => true, 'allowowner' => true],
            ['id' => 'GKaa:' . self::OTHER_ID, 'keyid' => 'GKaa', 'keyname' => 'alice',
                'bucketid' => self::OTHER_ID, 'bucketname' => 'a3f1000000000000',
                'allowread' => false, 'allowwrite' => true, 'allowowner' => false],
        ], $rows);
    }

    public function testKeyWithOnlyALocalAliasHasNoPermissionRow(): void
    {
        $aliasOnly = self::grant('GKaa', 'alice', false, false, false);
        $aliasOnly['bucketLocalAliases'] = ['mine'];

        self::assertSame([], permissionRows([self::info(['keys' => [$aliasOnly]])]));
    }

    public function testWantedFlagsAreAllowedAndTheRestDenied(): void
    {
        $base = ['bucketId' => self::BUCKET_ID, 'accessKeyId' => 'GKaa'];

        self::assertSame([
            ['AllowBucketKey', $base + ['permissions' => ['read' => true, 'owner' => true]]],
            ['DenyBucketKey', $base + ['permissions' => ['write' => true]]],
        ], permissionChanges('GKaa', self::BUCKET_ID,
            ['read' => true, 'write' => false, 'owner' => true]));
    }

    public function testNoWantedFlagDeniesAllWithoutAnAllow(): void
    {
        self::assertSame([
            ['DenyBucketKey', ['bucketId' => self::BUCKET_ID, 'accessKeyId' => 'GKaa',
                'permissions' => ['read' => true, 'write' => true, 'owner' => true]]],
        ], permissionChanges('GKaa', self::BUCKET_ID,
            ['read' => false, 'write' => false, 'owner' => false]));
    }

    public function testAllWantedFlagsAllowWithoutADeny(): void
    {
        self::assertSame([
            ['AllowBucketKey', ['bucketId' => self::BUCKET_ID, 'accessKeyId' => 'GKaa',
                'permissions' => ['read' => true, 'write' => true, 'owner' => true]]],
        ], permissionChanges('GKaa', self::BUCKET_ID,
            ['read' => true, 'write' => true, 'owner' => true]));
    }
}
