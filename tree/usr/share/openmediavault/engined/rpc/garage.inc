<?php
/**
 * This file is part of the openmediavault-garage plugin.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 *
 * OpenMediaVault is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

require_once("openmediavault/functions.inc");
require_once("/usr/share/openmediavault/garage/lib/live.php");
require_once("/usr/share/openmediavault/garage/lib/ports.php");

use OMV\Garage\PortConflict;
use OMV\Rpc\ServiceAbstract;
use OMV\System\Process;
use OMV\System\SystemCtl;

use function OMV\Garage\aliasChanges;
use function OMV\Garage\bucketLabel;
use function OMV\Garage\bucketRow;
use function OMV\Garage\bucketSettings;
use function OMV\Garage\permissionChanges;
use function OMV\Garage\permissionRows;
use function OMV\Garage\portConflicts;

use const OMV\Garage\PERMISSIONS;

class OMVRpcServiceGarage extends ServiceAbstract
{
	private const GARAGE_BIN = "/usr/bin/garage";
	private const GARAGE_ETC = "/etc/garage";
	private const DEFAULT_PORTS = [
		"s3port" => 3900,
		"rpcport" => 3901,
		"webport" => 3902,
		"adminport" => 3903,
		"webuiport" => 3910
	];
	// Generated on create, never taken from params. Only renewWebUiPassword
	// rotates the web UI password afterwards.
	private const SERVER_OWNED = ["rpcsecret", "admintoken", "webuipassword",
		"webuiport"];

	public function getName()
	{
		return "Garage";
	}

	public function initialize()
	{
		$this->registerMethod("getVersion");

		$this->registerMethod("getInstanceList");
		$this->registerMethod("getInstance");
		$this->registerMethod("setInstance");
		$this->registerMethod("deleteInstance");
		$this->registerMethod("suggestPorts");
		$this->registerMethod("enumerateInstances");
		$this->registerMethod("renewWebUiPassword");

		$this->registerMethod("getDatastoreList");
		$this->registerMethod("getDatastore");
		$this->registerMethod("setDatastore");
		$this->registerMethod("deleteDatastore");

		$this->registerMethod("getBucketList");
		$this->registerMethod("getBucket");
		$this->registerMethod("setBucket");
		$this->registerMethod("deleteBucket");

		$this->registerMethod("getKeyList");
		$this->registerMethod("getKey");
		$this->registerMethod("setKey");
		$this->registerMethod("deleteKey");

		$this->registerMethod("enumerateKeys");
		$this->registerMethod("enumerateBuckets");

		$this->registerMethod("getMappingList");
		$this->registerMethod("getMapping");
		$this->registerMethod("setMapping");
		$this->registerMethod("deleteMapping");

		$this->registerMethod("getWebUiLogin");
	}

	public function getVersion($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$output = [];
		$cmd = new Process([self::GARAGE_BIN, "--version"]);
		try {
			$cmd->execute($output);
		} catch (\Exception $e) {
			return ["version" => gettext("Not installed")];
		}
		return ["version" => implode(" ", $output)];
	}

	// ------------------------------------------------------------------
	// Instances
	// ------------------------------------------------------------------

	public function getInstanceList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.getlist");
		$db = \OMV\Config\Database::getInstance();
		$objects = $db->get("conf.service.garage.instance");
		$objectsAssoc = [];
		foreach ($objects as $objectv) {
			$assoc = $objectv->getAssoc();
			$assoc["rpcsecret"] = strlen($assoc["rpcsecret"] ?? "") > 0;
			$assoc["admintoken"] = strlen($assoc["admintoken"] ?? "") > 0;
			$assoc["webuipassword"] = strlen($assoc["webuipassword"] ?? "") > 0;
			$name = $assoc["name"];
			$assoc["running"] = (new SystemCtl("garage@" . $name))->isActive();
			$assoc["webuirunning"] = $assoc["webuienable"] &&
				(new SystemCtl("omv-garage-webui@" . $name))->isActive();
			$assoc["status"] = empty($assoc["enable"]) ? "disabled"
				: ($assoc["running"] ? "running" : "stopped");
			$assoc["datastorecount"] = count($this->datastores($db, $assoc["uuid"]));
			$objectsAssoc[] = $assoc;
		}
		return $this->applyFilter($objectsAssoc, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	public function getInstance($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$db = \OMV\Config\Database::getInstance();
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		if ($params["uuid"] === $newUuid) {
			// Return defaults for the create dialog, with unused ports.
			$ports = $this->freePorts(self::DEFAULT_PORTS);
			$assoc = [
				"uuid" => $newUuid,
				"enable" => true,
				"name" => "",
				"s3port" => $ports["s3port"],
				"rpcport" => $ports["rpcport"],
				"s3region" => "garage",
				"s3rootdomain" => "",
				"webenable" => false,
				"webport" => $ports["webport"],
				"webrootdomain" => "",
				"adminport" => $ports["adminport"],
				"dbengine" => "lmdb",
				"compressionlevel" => 1,
				"compressiondisable" => false,
				"snapshotinterval" => "",
				"metadatashareuuid" => "",
				"snapshotsshareuuid" => "",
				"metadatafsync" => false,
				"datafsync" => false,
				"disablescrub" => false,
				"loglevel" => "info",
				"blocksize" => "",
				"blockrambuffermax" => "",
				"blockmaxconcurrentreads" => null,
				"blockmaxconcurrentwrites" => null,
				"lmdbmapsize" => "",
				"webuienable" => false,
				"webuiuser" => "admin"
			];
			return $assoc;
		}
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		return $db->getAssoc("conf.service.garage.instance", $params["uuid"]);
	}

	public function suggestPorts($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		return $this->freePorts(self::DEFAULT_PORTS);
	}

	// Moves every taken port up to the next free one.
	private function freePorts(array $ports): array
	{
		$db = \OMV\Config\Database::getInstance();
		$instancePorts = $this->collectUsedPorts($db, null);
		$listening = $this->collectListeningPorts();
		while ($conflicts = portConflicts($ports, $instancePorts, $listening)) {
			$ports[array_key_first($conflicts)]++;
		}
		return $ports;
	}

	private function instancePorts($object): array
	{
		$ports = [];
		foreach (array_keys(self::DEFAULT_PORTS) as $key) {
			$ports[$key] = $object->get($key);
		}
		return $ports;
	}

	private function collectUsedPorts($db, $excludeUuid)
	{
		$used = [];
		foreach ($db->get("conf.service.garage.instance") as $objectv) {
			if ($objectv->get("uuid") !== $excludeUuid) {
				array_push($used, ...array_values($this->instancePorts($objectv)));
			}
		}
		return $used;
	}

	private function collectListeningPorts()
	{
		$output = [];
		exec("ss -ltnH", $output);
		$ports = [];
		foreach ($output as $line) {
			// The local address, e.g. 0.0.0.0:22 or [::]:22.
			$local = preg_split("/\s+/", $line)[3];
			$ports[] = intval(substr($local, strrpos($local, ":") + 1));
		}
		return $ports;
	}

	public function setInstance($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setinstance");
		$db = \OMV\Config\Database::getInstance();
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		$isNew = ($params["uuid"] === $newUuid);
		$params = array_diff_key($params, array_flip(self::SERVER_OWNED));

		if ($isNew) {
			// Silently resolve duplicate ports with the next free port. The
			// create dialog pre-suggests unused ports, but a stale page or a
			// race with another creation must not block a plain "next-next"
			// workflow.
			$params = $this->freePorts(array_merge(self::DEFAULT_PORTS,
				array_intersect_key($params, self::DEFAULT_PORTS))) + $params;
			$params["rpcsecret"] = $this->generateSecret();
			$params["admintoken"] = $this->generateSecret();
			$params["webuipassword"] = $this->generatePassword();
			$object = new \OMV\Config\ConfigObject("conf.service.garage.instance");
		} else {
			// On edit, a taken port is reported, not silently resolved.
			$object = $db->get("conf.service.garage.instance", $params["uuid"]);
			if ($params["name"] !== $object->get("name")) {
				throw new \OMV\Exception(
					gettext("The name of a Garage instance cannot be changed."));
			}
			$stored = $this->instancePorts($object);
			$ports = array_merge($stored,
				array_intersect_key($params, self::DEFAULT_PORTS));
			$running = (new SystemCtl("garage@" . $object->get("name")))->isActive();
			$conflicts = portConflicts($ports,
				$this->collectUsedPorts($db, $params["uuid"]),
				array_diff($this->collectListeningPorts(), $running ? $stored : []));
			$field = array_key_first($conflicts);
			if (!is_null($field)) {
				throw new \OMV\Exception(sprintf(match ($conflicts[$field]) {
					PortConflict::SameInstance =>
						gettext("Port %d is used twice in this instance."),
					PortConflict::OtherInstance =>
						gettext("Port %d is already used by another Garage instance."),
					PortConflict::OtherService =>
						gettext("Port %d is already used by another service."),
				}, $ports[$field]));
			}
		}

		// Optional tuning fields fall back to the Garage defaults.
		foreach (["blockmaxconcurrentreads" => 16,
			"blockmaxconcurrentwrites" => 3] as $field => $fallback) {
			if (array_key_exists($field, $params) && is_null($params[$field])) {
				$params[$field] = $fallback;
			}
		}
		$object->setAssoc($params);

		// Storage layout. The storage folder holds the data and, unless a
		// separate metadata folder is configured, the metadata database.
		$storage = $object->get("storageshareuuid");
		if (strlen($storage) !== 36) {
			throw new \OMV\Exception(
				gettext("Please select a storage shared folder."));
		}
		if ($object->get("storagesplit") &&
			strlen($object->get("metadatashareuuid")) !== 36) {
			throw new \OMV\Exception(
				gettext("Please select a metadata shared folder."));
		}
		$datastores = $db->get("conf.service.garage.datastore");
		foreach ($datastores as $dsv) {
			if ($dsv->get("shareuuid") === $storage) {
				throw new \OMV\Exception(
					gettext("The storage shared folder is already used as a datastore."));
			}
		}
		$instances = $db->get("conf.service.garage.instance");
		foreach ($instances as $objectv) {
			if ($objectv->get("uuid") !== $params["uuid"] &&
				$objectv->get("storageshareuuid") === $storage) {
				throw new \OMV\Exception(
					gettext("The storage shared folder is already used by another Garage instance."));
			}
		}

		$db->assertIsUnique($object, "name", sprintf(
			gettext("A Garage instance named '%s' already exists."),
			$object->get("name")));
		$db->set($object);
		return $object->getAssoc();
	}

	public function deleteInstance($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage.instance", $params["uuid"]);
		$name = $object->get("name");

		// Stop and disable the units.
		foreach (["garage@" . $name, "omv-garage-webui@" . $name] as $unit) {
			try {
				(new SystemCtl($unit))->disable(true);
			} catch (\Exception $e) {
				// The unit may not exist (never started), ignore.
			}
		}

		// Remove rendered files.
		$this->removeFiles($name);

		// Revoke ACLs that are no longer needed.
		$this->revokeAcls($db, $object);

		foreach ($this->datastores($db, $params["uuid"]) as $datastore) {
			$db->delete($datastore);
		}

		$db->delete($object);
		return $object->getAssoc();
	}

	public function enumerateInstances($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$db = \OMV\Config\Database::getInstance();
		$objects = $db->get("conf.service.garage.instance");
		$result = [];
		if (!empty($params["addnone"])) {
			$result[] = ["uuid" => "", "name" => "None"];
		}
		foreach ($objects as $objectv) {
			$result[] = [
				"uuid" => $objectv->get("uuid"),
				"name" => $objectv->get("name")
			];
		}
		return $result;
	}

	public function renewWebUiPassword($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage.instance", $params["uuid"]);
		$password = $this->generatePassword();
		$object->set("webuipassword", $password);
		$db->set($object);
		return ["password" => $password];
	}

	public function getWebUiLogin($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getwebuilogin");
		$db = \OMV\Config\Database::getInstance();
		$objects = $db->get("conf.service.garage.instance");
		foreach ($objects as $objectv) {
			if ($objectv->get("name") === $params["name"]) {
				if (!$objectv->get("webuienable")) {
					throw new \OMV\Exception(
						gettext("The web UI is not enabled for this instance."));
				}
				return [
					"url" => "/garage-webui-" . $params["name"] . "/",
					"username" => $objectv->get("webuiuser"),
					"password" => $objectv->get("webuipassword")
				];
			}
		}
		throw new \OMV\Exception(gettext("Garage instance not found."));
	}

	// ------------------------------------------------------------------
	// Datastores
	// ------------------------------------------------------------------

	public function getDatastoreList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$db = \OMV\Config\Database::getInstance();
		$objects = empty($params["instanceuuid"])
			? $db->get("conf.service.garage.datastore")
			: $this->datastores($db, $params["instanceuuid"]);
		$objectsAssoc = [];
		foreach ($objects as $objectv) {
			$assoc = $objectv->getAssoc();
			$assoc["sharedfoldername"] = $this->getSharedFolderName(
				$db, $objectv->get("shareuuid"));
			$objectsAssoc[] = $assoc;
		}
		return $this->applyFilter($objectsAssoc, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	public function getDatastore($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		if ($params["uuid"] === $newUuid) {
			return [
				"uuid" => $newUuid,
				"instanceuuid" => $params["instanceuuid"] ?? "",
				"shareuuid" => "",
				"capacity" => 10
			];
		}
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		return $db->getAssoc("conf.service.garage.datastore", $params["uuid"]);
	}

	public function setDatastore($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setdatastore");
		$db = \OMV\Config\Database::getInstance();
		$this->assertInstanceExists($db, $params["instanceuuid"]);
		$storage = $db->getAssoc("conf.service.garage.instance",
			$params["instanceuuid"]);
		if ($storage["storageshareuuid"] === $params["shareuuid"]) {
			throw new \OMV\Exception(
				gettext("This shared folder is the storage folder of the instance. Pick another one."));
		}
		$object = new \OMV\Config\ConfigObject("conf.service.garage.datastore");
		$object->setAssoc($params);
		if ($object->isNew()) {
			$db->assertIsUnique($object, "shareuuid");
		}
		$db->set($object);
		return $object->getAssoc();
	}

	public function deleteDatastore($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage.datastore", $params["uuid"]);
		$db->delete($object);
		return $object->getAssoc();
	}

	// ------------------------------------------------------------------
	// Buckets, access keys and permissions. Garage owns them; these
	// methods read and write its admin API, nothing is kept in confdb.
	// ------------------------------------------------------------------

	public function getBucketList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$instance = $this->runningInstance($params["instanceuuid"]);
		$rows = array_map(bucketRow(...), $this->bucketInfos($instance));
		return $this->applyFilter($rows, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	public function getBucket($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.liveobject");
		$instance = $this->runningInstance($params["instanceuuid"]);
		return bucketRow($this->adminApi($instance, "GetBucketInfo",
			["id" => $params["id"]]));
	}

	public function setBucket($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setbucket");
		$instance = $this->runningInstance($params["instanceuuid"]);
		$id = $params["id"];
		if ($id === "") {
			if ($params["name"] === "") {
				throw new \OMV\Exception(gettext("A new bucket needs a name."));
			}
			$id = $this->adminApi($instance, "CreateBucket", [],
				["globalAlias" => $params["name"]])["id"];
		} else {
			$info = $this->adminApi($instance, "GetBucketInfo", ["id" => $id]);
			foreach (aliasChanges($id, $info["globalAliases"], $params["name"])
				as [$endpoint, $body]) {
				$this->adminApi($instance, $endpoint, [], $body);
			}
		}
		return bucketRow($this->adminApi($instance, "UpdateBucket", ["id" => $id],
			bucketSettings(floatval($params["maxsize"]), intval($params["maxobjects"]),
				boolval($params["website"] ?? false), $params["indexdoc"] ?? "",
				$params["errordoc"] ?? "")));
	}

	public function deleteBucket($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.liveobject");
		$instance = $this->runningInstance($params["instanceuuid"]);
		$this->adminApi($instance, "DeleteBucket", ["id" => $params["id"]], []);
	}

	public function enumerateBuckets($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.enumerate");
		$instance = $this->runningInstance($params["instanceuuid"]);
		return array_map(fn($bucket) => ["id" => $bucket["id"],
			"label" => bucketLabel($bucket)],
			$this->adminApi($instance, "ListBuckets"));
	}

	public function getKeyList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$instance = $this->runningInstance($params["instanceuuid"]);
		$rows = array_map(fn($key) => ["id" => $key["id"], "name" => $key["name"]],
			$this->adminApi($instance, "ListKeys"));
		return $this->applyFilter($rows, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	// The only method that returns a key's secret.
	public function getKey($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.liveobject");
		$instance = $this->runningInstance($params["instanceuuid"]);
		return $this->keyForm($this->adminApi($instance, "GetKeyInfo",
			["id" => $params["id"], "showSecretKey" => "true"]));
	}

	public function setKey($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setkey");
		$instance = $this->runningInstance($params["instanceuuid"]);
		if ($params["id"] !== "") {
			return $this->keyForm($this->adminApi($instance, "UpdateKey",
				["id" => $params["id"]], ["name" => $params["name"]]));
		}
		$import = array_filter([$params["importid"] ?? "", $params["importsecret"] ?? ""]);
		if (count($import) === 1) {
			throw new \OMV\Exception(gettext(
				"To import a key, enter both its key ID and its secret."));
		}
		return $this->keyForm($import
			? $this->adminApi($instance, "ImportKey", [], ["name" => $params["name"],
				"accessKeyId" => $params["importid"],
				"secretAccessKey" => $params["importsecret"]])
			: $this->adminApi($instance, "CreateKey", [], ["name" => $params["name"]]));
	}

	private function keyForm(array $info): array
	{
		return ["id" => $info["accessKeyId"], "keyid" => $info["accessKeyId"],
			"name" => $info["name"], "secret" => $info["secretAccessKey"] ?? ""];
	}

	public function deleteKey($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.liveobject");
		$instance = $this->runningInstance($params["instanceuuid"]);
		$this->adminApi($instance, "DeleteKey", ["id" => $params["id"]], []);
	}

	public function enumerateKeys($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.enumerate");
		$instance = $this->runningInstance($params["instanceuuid"]);
		return array_map(fn($key) => ["id" => $key["id"],
			"label" => sprintf("%s (%s)", $key["name"], $key["id"])],
			$this->adminApi($instance, "ListKeys"));
	}

	public function getMappingList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$instance = $this->runningInstance($params["instanceuuid"]);
		return $this->applyFilter(permissionRows($this->bucketInfos($instance)),
			$params["start"], $params["limit"], $params["sortfield"],
			$params["sortdir"]);
	}

	public function getMapping($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.permission");
		$instance = $this->runningInstance($params["instanceuuid"]);
		[, $bucketId] = explode(":", $params["id"]);
		$rows = permissionRows([$this->adminApi($instance, "GetBucketInfo",
			["id" => $bucketId])]);
		foreach ($rows as $row) {
			if ($row["id"] === $params["id"]) {
				return $row;
			}
		}
		throw new \OMV\Exception(gettext("The key has no permission on this bucket."));
	}

	public function setMapping($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setmapping");
		$instance = $this->runningInstance($params["instanceuuid"]);
		$wanted = [];
		foreach (PERMISSIONS as $permission => $field) {
			$wanted[$permission] = boolval($params[$field] ?? false);
		}
		if (!in_array(true, $wanted, true)) {
			throw new \OMV\Exception(gettext(
				"Select at least one permission. To revoke all access, delete the permission."));
		}
		$this->applyPermissions($instance, $params["keyid"], $params["bucketid"], $wanted);
	}

	public function deleteMapping($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.permission");
		$instance = $this->runningInstance($params["instanceuuid"]);
		[$keyId, $bucketId] = explode(":", $params["id"]);
		$this->applyPermissions($instance, $keyId, $bucketId,
			array_fill_keys(array_keys(PERMISSIONS), false));
	}

	private function applyPermissions($instance, string $keyId, string $bucketId,
		array $wanted): void
	{
		foreach (permissionChanges($keyId, $bucketId, $wanted) as [$endpoint, $body]) {
			$this->adminApi($instance, $endpoint, [], $body);
		}
	}

	private function bucketInfos($instance): array
	{
		return array_map(fn($bucket) => $this->adminApi($instance, "GetBucketInfo",
			["id" => $bucket["id"]]), $this->adminApi($instance, "ListBuckets"));
	}

	private function runningInstance(string $uuid): \OMV\Config\ConfigObject
	{
		$instance = \OMV\Config\Database::getInstance()->get(
			"conf.service.garage.instance", $uuid);
		if (!(new SystemCtl("garage@" . $instance->get("name")))->isActive()) {
			throw new \OMV\Exception(sprintf(gettext(
				"The Garage instance '%s' is not running. Make sure it is enabled and apply the pending configuration changes."),
				$instance->get("name")));
		}
		return $instance;
	}

	/**
	 * Calls the admin API v2 of a running instance on loopback. A request
	 * with a body is a POST. Garage's own error message becomes the RPC
	 * error.
	 */
	private function adminApi(\OMV\Config\ConfigObject $instance, string $endpoint,
		array $query = [], ?array $body = null): array
	{
		$name = $instance->get("name");
		$port = $instance->get("adminport");
		$url = sprintf("http://127.0.0.1:%d/v2/%s", $port, $endpoint);
		if ($query) {
			$url .= "?" . http_build_query($query);
		}
		$headers = ["Authorization: Bearer " . $instance->get("admintoken")];
		if ($body) {
			$headers[] = "Content-Type: application/json";
		}
		$response = @file_get_contents($url, false, stream_context_create(["http" => [
			"method" => is_null($body) ? "GET" : "POST",
			"header" => $headers,
			"content" => $body ? json_encode($body) : "",
			"ignore_errors" => true,
			"timeout" => 10,
		]]));
		if ($response === false) {
			throw new \OMV\Exception(sprintf(gettext(
				"Cannot reach the admin API of the Garage instance '%s' on port %d."),
				$name, $port));
		}
		$status = intval(explode(" ", http_get_last_response_headers()[0] ?? "")[1] ?? 0);
		$result = $response === "" ? [] : json_decode($response, true);
		if ($status >= 400 || !is_array($result)) {
			throw new \OMV\Exception(sprintf(gettext("Garage instance '%s': %s"),
				$name, $result["message"] ?? $response));
		}
		return $result;
	}

	// ------------------------------------------------------------------
	// Helpers
	// ------------------------------------------------------------------

	private function assertInstanceExists($db, $uuid)
	{
		return $db->get("conf.service.garage.instance", $uuid);
	}

	private function getSharedFolderPath($db, $shareUuid)
	{
		try {
			$sharedFolder = $db->get("conf.system.sharedfolder", $shareUuid);
			$mount = $db->get("conf.system.filesystem.mountpoint",
				$sharedFolder->get("mntentref"));
			return rtrim($mount->get("dir"), "/") . "/" .
				ltrim($sharedFolder->get("reldirpath"), "/");
		} catch (\Exception $e) {
			return "";
		}
	}

	private function getSharedFolderName($db, $shareUuid)
	{
		if (empty($shareUuid)) {
			return gettext("n/a");
		}
		try {
			$object = $db->get("conf.system.sharedfolder", $shareUuid);
			return $object->get("name");
		} catch (\Exception $e) {
			return gettext("n/a");
		}
	}

	private function generateSecret()
	{
		return bin2hex(random_bytes(32));
	}

	private function generatePassword()
	{
		$alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
		$password = "";
		for ($i = 0; $i < 24; $i++) {
			$password .= $alphabet[random_int(0, strlen($alphabet) - 1)];
		}
		return $password;
	}

	private function removeFiles($name)
	{
		$paths = [
			self::GARAGE_ETC . "/" . $name . ".toml",
			self::GARAGE_ETC . "/" . $name . ".rpc_secret",
			self::GARAGE_ETC . "/" . $name . ".webui.env",
			"/etc/systemd/system/garage@" . $name . ".service.d/override.conf",
			"/etc/nginx/openmediavault-webgui.d/garage-webui-" . $name . ".conf"
		];
		foreach ($paths as $path) {
			if (file_exists($path)) {
				@unlink($path);
			}
		}
		$dropInDir = "/etc/systemd/system/garage@" . $name . ".service.d";
		if (is_dir($dropInDir)) {
			@rmdir($dropInDir);
		}
		$cmd = new Process(["systemctl", "daemon-reload"]);
		try {
			$cmd->execute($output);
		} catch (\Exception $e) {
		}
	}

	private function revokeAcls($db, $instance)
	{
		$uuid = $instance->get("uuid");
		$shares = $this->instanceShares($db, $instance);
		// Shares still used by other instances keep their ACL.
		$stillUsed = [];
		foreach ($db->get("conf.service.garage.instance") as $instancev) {
			if ($instancev->get("uuid") !== $uuid) {
				array_push($stillUsed, ...$this->instanceShares($db, $instancev));
			}
		}
		foreach (array_unique($shares) as $shareUuid) {
			if (in_array($shareUuid, $stillUsed)) {
				continue;
			}
			$path = $this->getSharedFolderPath($db, $shareUuid);
			if (empty($path)) {
				continue;
			}
			$cmd = new Process(["setfacl", "-x", "u:garage", $path]);
			try {
				$cmd->execute($output);
			} catch (\Exception $e) {
			}
		}
	}

	// Every shared folder the instance uses: storage, metadata, snapshots
	// and datastores.
	private function instanceShares($db, $instance): array
	{
		return array_merge(array_filter([$instance->get("storageshareuuid"),
			$instance->get("metadatashareuuid"),
			$instance->get("snapshotsshareuuid")],
			fn($share) => strlen($share) === 36),
			array_map(fn($datastore) => $datastore->get("shareuuid"),
				$this->datastores($db, $instance->get("uuid"))));
	}

	private function datastores($db, string $instanceUuid): array
	{
		return $db->getByFilter("conf.service.garage.datastore", [
			"operator" => "stringEquals",
			"arg0" => "instanceuuid",
			"arg1" => $instanceUuid
		]);
	}
}
