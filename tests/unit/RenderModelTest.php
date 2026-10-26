<?php

declare(strict_types=1);

use OMV\Garage\StorageError;
use PHPUnit\Framework\TestCase;

use function OMV\Garage\renderModel;
use function OMV\Garage\storageError;

final class RenderModelTest extends TestCase
{
    private const STORAGE = "11111111-1111-4111-8111-111111111111";
    private const META = "22222222-2222-4222-8222-222222222222";
    private const SNAPS = "33333333-3333-4333-8333-333333333333";
    private const DS1 = "44444444-4444-4444-8444-444444444444";
    private const DS2 = "55555555-5555-4555-8555-555555555555";

    private const PATHS = [
        self::STORAGE => "/srv/disk/my store/",
        self::META => "/srv/ssd/meta/",
        self::SNAPS => "/srv/disk/snaps/",
        self::DS1 => "/srv/disk1/ds1/",
        self::DS2 => "/srv/disk2/ds2/",
    ];

    private static function instance(array $fields = []): array
    {
        return $fields + [
            "storageshareuuid" => self::STORAGE,
            "storagesplit" => false,
            "storagecapacity" => 0,
            "metadatashareuuid" => "",
            "snapshotsshareuuid" => "",
            "s3port" => 3900,
            "rpcport" => 3901,
            "webenable" => false,
            "webport" => 3902,
            "adminport" => 3903,
            "webuienable" => false,
            "webuiport" => 3910,
        ];
    }

    private static function datastore(string $share, int $capacity,
        string $state = "active"): array
    {
        return ["shareuuid" => $share, "capacity" => $capacity,
            "state" => $state];
    }

    public function testStorageFolderAloneIsOneDataDirWithoutCapacity(): void
    {
        self::assertSame([
            "metadata_dir" => "/srv/disk/my store/meta",
            "snapshots_dir" => null,
            "data_dir" => "/srv/disk/my store/data",
            "ports" => ["s3" => 3900, "rpc" => 3901, "admin" => 3903,
                "web" => null, "webui" => null],
            "shares" => ["/srv/disk/my store/" => "--x"],
            "dirs" => ["/srv/disk/my store/meta", "/srv/disk/my store/data"],
            "layout_capacity" => 1024 ** 4,
            "drain" => false,
        ], renderModel(self::instance(), [], self::PATHS));
    }

    public function testDatastoresGiveEveryDataDirItsCapacity(): void
    {
        $model = renderModel(self::instance(["storagecapacity" => 20]),
            [self::datastore(self::DS1, 5), self::datastore(self::DS2, 1)],
            self::PATHS);

        self::assertSame([
            ["path" => "/srv/disk/my store/data", "capacity" => "20GiB"],
            ["path" => "/srv/disk1/ds1/", "capacity" => "5GiB"],
            ["path" => "/srv/disk2/ds2/", "capacity" => "1GiB"],
        ], $model["data_dir"]);
        self::assertSame(26 * 1024 ** 3, $model["layout_capacity"]);
        self::assertSame(["/srv/disk/my store/" => "--x",
            "/srv/disk1/ds1/" => "rwx", "/srv/disk2/ds2/" => "rwx"],
            $model["shares"]);
    }

    public function testSeparateMetadataFolderKeepsDataOnTheDatastores(): void
    {
        $model = renderModel(self::instance(["storagesplit" => true,
            "metadatashareuuid" => self::META]),
            [self::datastore(self::DS1, 5)], self::PATHS);

        self::assertSame("/srv/ssd/meta/meta", $model["metadata_dir"]);
        self::assertSame([["path" => "/srv/disk1/ds1/", "capacity" => "5GiB"]],
            $model["data_dir"]);
        self::assertSame(["/srv/ssd/meta/meta"], $model["dirs"]);
        self::assertSame(["/srv/disk/my store/" => "--x",
            "/srv/ssd/meta/" => "--x", "/srv/disk1/ds1/" => "rwx"],
            $model["shares"]);
        self::assertSame(5 * 1024 ** 3, $model["layout_capacity"]);
    }

    // The layout the first pre-release wrote: metadata at the root of the
    // storage folder, data on the datastores. alpha on omv-test uses it.
    public function testMetadataAtTheRootOfTheStorageFolder(): void
    {
        self::assertSame([
            "metadata_dir" => "/srv/disk/my store/",
            "snapshots_dir" => "/srv/disk/snaps/",
            "data_dir" => [
                ["path" => "/srv/disk1/ds1/", "capacity" => "10GiB"],
                ["path" => "/srv/disk2/ds2/", "capacity" => "5GiB"],
            ],
            "ports" => ["s3" => 3900, "rpc" => 3901, "admin" => 3903,
                "web" => null, "webui" => 3910],
            "shares" => ["/srv/disk/my store/" => "rwx",
                "/srv/disk/snaps/" => "rwx", "/srv/disk1/ds1/" => "rwx",
                "/srv/disk2/ds2/" => "rwx"],
            "dirs" => [],
            "layout_capacity" => 15 * 1024 ** 3,
            "drain" => false,
        ], renderModel(self::instance(["storagesplit" => true,
            "metadatashareuuid" => self::STORAGE,
            "snapshotsshareuuid" => self::SNAPS, "webuienable" => true]),
            [self::datastore(self::DS1, 10), self::datastore(self::DS2, 5)],
            self::PATHS));
    }

    public function testWebsitePortOnlyWhenWebsiteHostingIsOn(): void
    {
        $model = renderModel(self::instance(["webenable" => true]), [],
            self::PATHS);

        self::assertSame(3902, $model["ports"]["web"]);
    }

    public function testStorageFolderCapacityIsIgnoredWithoutDatastores(): void
    {
        $model = renderModel(self::instance(["storagecapacity" => 20]), [],
            self::PATHS);

        self::assertSame("/srv/disk/my store/data", $model["data_dir"]);
        self::assertSame(1024 ** 4, $model["layout_capacity"]);
    }

    public function testSeparateMetadataFolderWithoutDatastoreIsRejected(): void
    {
        $this->expectExceptionObject(new DomainException(
            StorageError::NoDatastore->message()));

        renderModel(self::instance(["storagesplit" => true,
            "metadatashareuuid" => self::META]), [], self::PATHS);
    }

    public function testDatastoresWithoutStorageFolderCapacityAreRejected(): void
    {
        $this->expectExceptionObject(new DomainException(
            StorageError::NoStorageCapacity->message()));

        renderModel(self::instance(), [self::datastore(self::DS1, 5)],
            self::PATHS);
    }

    public function testStorageRules(): void
    {
        $active = self::datastore(self::DS1, 5);
        self::assertSame(
            [null, null, StorageError::NoStorageCapacity, null,
                StorageError::NoDatastore, null],
            [storageError(false, 0, []), storageError(false, 20, []),
                storageError(false, 0, [$active]),
                storageError(false, 20, [$active, $active]),
                storageError(true, 20, []), storageError(true, 0, [$active])]);
    }

    public function testDrainingDatastoresDoNotCountAsStorage(): void
    {
        $active = self::datastore(self::DS1, 5);
        $draining = self::datastore(self::DS2, 5, "draining");
        self::assertSame(
            [StorageError::NoDatastore, null, StorageError::NoStorageCapacity,
                null],
            [storageError(true, 0, [$draining]),
                storageError(true, 0, [$draining, $active]),
                storageError(false, 0, [$draining]),
                storageError(false, 20, [$draining])]);
    }

    public function testDrainingDatastoreIsReadOnlyWithoutCapacity(): void
    {
        $model = renderModel(self::instance(["storagecapacity" => 20]),
            [self::datastore(self::DS1, 5),
                self::datastore(self::DS2, 7, "draining")],
            self::PATHS);

        self::assertSame([
            ["path" => "/srv/disk/my store/data", "capacity" => "20GiB"],
            ["path" => "/srv/disk1/ds1/", "capacity" => "5GiB"],
            ["path" => "/srv/disk2/ds2/", "read_only" => true],
        ], $model["data_dir"]);
        self::assertSame(25 * 1024 ** 3, $model["layout_capacity"]);
        self::assertSame("rwx", $model["shares"]["/srv/disk2/ds2/"]);
        self::assertTrue($model["drain"]);
    }

    public function testLastDatastoreDrainingKeepsTheListForm(): void
    {
        $model = renderModel(self::instance(["storagecapacity" => 20]),
            [self::datastore(self::DS1, 5, "draining")], self::PATHS);

        self::assertSame([
            ["path" => "/srv/disk/my store/data", "capacity" => "20GiB"],
            ["path" => "/srv/disk1/ds1/", "read_only" => true],
        ], $model["data_dir"]);
        self::assertSame(20 * 1024 ** 3, $model["layout_capacity"]);
    }

    public function testSplitInstanceDrainsOntoItsOtherDatastores(): void
    {
        $model = renderModel(self::instance(["storagesplit" => true,
            "metadatashareuuid" => self::META]),
            [self::datastore(self::DS1, 5, "draining"),
                self::datastore(self::DS2, 3)], self::PATHS);

        self::assertSame([
            ["path" => "/srv/disk1/ds1/", "read_only" => true],
            ["path" => "/srv/disk2/ds2/", "capacity" => "3GiB"],
        ], $model["data_dir"]);
        self::assertSame(3 * 1024 ** 3, $model["layout_capacity"]);
    }

    public function testSnapshotsInTheStorageFolderNeedWriteAccessToIt(): void
    {
        $model = renderModel(self::instance(
            ["snapshotsshareuuid" => self::STORAGE]), [], self::PATHS);

        self::assertSame(["/srv/disk/my store/" => "rwx"], $model["shares"]);
    }
}
