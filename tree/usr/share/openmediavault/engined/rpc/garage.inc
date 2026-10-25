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

use OMV\Rpc\ServiceAbstract;
use OMV\System\Process;
use OMV\System\SystemCtl;

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
		"webuipasswordhash", "webuiport"];

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
			$this->backfillStorage($assoc);
			$name = $assoc["name"];
			$assoc["running"] = (new SystemCtl("garage@" . $name))->isActive();
			$assoc["webuirunning"] = $assoc["webuienable"] &&
				(new SystemCtl("omv-garage-webui@" . $name))->isActive();
			$assoc["status"] = empty($assoc["enable"]) ? "disabled"
				: ($assoc["running"] ? "running" : "stopped");
			$datastores = $db->get("conf.service.garage.datastore");
			$count = 0;
			foreach ($datastores as $dsv) {
				if ($dsv->get("instanceuuid") === $assoc["uuid"]) {
					$count++;
				}
			}
			$assoc["datastorecount"] = $count;
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
			$ports = $this->computeSuggestedPorts();
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
				"adminenable" => true,
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
		$assoc = $db->getAssoc("conf.service.garage.instance", $params["uuid"]);
		$this->backfillStorage($assoc);
		return $assoc;
	}

	private function backfillStorage(array &$assoc): void
	{
		// Instances created before the unified storage field only recorded
		// metadatashareuuid. Present them as split-storage instances so the
		// form and the deployment render exactly what they were created with.
		if (strlen($assoc["storageshareuuid"] ?? "") !== 36 &&
			strlen($assoc["metadatashareuuid"] ?? "") === 36) {
			$assoc["storagesplit"] = true;
			$assoc["storageshareuuid"] = $assoc["metadatashareuuid"];
		}
	}

	public function suggestPorts($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		return $this->computeSuggestedPorts();
	}

	private function computeSuggestedPorts()
	{
		$db = \OMV\Config\Database::getInstance();
		$used = $this->collectUsedPorts($db, null);
		$used = array_merge($used, $this->collectListeningPorts());
		$result = [];
		foreach (self::DEFAULT_PORTS as $key => $default) {
			$port = $default;
			while (in_array($port, $used)) {
				$port++;
			}
			$result[$key] = $port;
			$used[] = $port;
		}
		return $result;
	}

	private function collectUsedPorts($db, $excludeUuid)
	{
		$used = [];
		$objects = $db->get("conf.service.garage.instance");
		foreach ($objects as $objectv) {
			if (!is_null($excludeUuid) &&
				$objectv->get("uuid") === $excludeUuid) {
				continue;
			}
			foreach (array_keys(self::DEFAULT_PORTS) as $key) {
				$port = $objectv->get($key);
				if (!empty($port)) {
					$used[] = intval($port);
				}
			}
		}
		return $used;
	}

	private function collectListeningPorts()
	{
		$used = [];
		$output = [];
		// Parse the local port column of 'ss -tln', e.g.
		// LISTEN 0 128 0.0.0.0:22 0.0.0.0:*
		exec("export LANG=C; ss -tln 2>/dev/null | awk '{print $4}'", $output);
		foreach ($output as $line) {
			$pos = strrpos($line, ":");
			if (false === $pos) {
				continue;
			}
			$port = intval(substr($line, $pos + 1));
			if ($port > 0) {
				$used[] = $port;
			}
		}
		return $used;
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
			$suggested = $this->computeSuggestedPorts();
			$used = array_merge(
				$this->collectUsedPorts($db, null),
				$this->collectListeningPorts()
			);
			foreach (array_keys(self::DEFAULT_PORTS) as $key) {
				$port = intval($params[$key] ?? $suggested[$key]);
				while (in_array($port, $used)) {
					$port++;
				}
				$params[$key] = $port;
				$used[] = $port;
			}
			$params["rpcsecret"] = $this->generateSecret();
			$params["admintoken"] = $this->generateSecret();
			$params["webuipassword"] = $this->generatePassword();
			$params["webuipasswordhash"] =
				password_hash($params["webuipassword"], PASSWORD_BCRYPT);
			$object = new \OMV\Config\ConfigObject("conf.service.garage.instance");
		} else {
			// On edit, ports must not collide with other instances. Explicit
			// conflicts are reported, not silently resolved. Fields the form
			// does not post keep their stored value.
			$used = $this->collectUsedPorts($db, $params["uuid"]);
			foreach (array_keys(self::DEFAULT_PORTS) as $key) {
				if (!isset($params[$key]) || $params[$key] === "" ||
					is_null($params[$key])) {
					continue;
				}
				if (in_array(intval($params[$key]), $used)) {
					throw new \OMV\Exception(sprintf(
						gettext("Port %d is already used by another Garage instance."),
						$params[$key]));
				}
			}
			$object = $db->get("conf.service.garage.instance", $params["uuid"]);
		}

		// Optional tuning fields fall back to the Garage defaults.
		foreach (["blockmaxconcurrentreads" => 16,
			"blockmaxconcurrentwrites" => 3] as $field => $fallback) {
			if (array_key_exists($field, $params) && is_null($params[$field])) {
				$params[$field] = $fallback;
			}
		}
		$object->setAssoc($params);

		if ($object->get("webuienable") && !$object->get("adminenable")) {
			throw new \OMV\Exception(
				gettext("The web UI requires the admin API to be enabled."));
		}

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

		// Delete children.
		foreach (["datastore", "bucket", "key", "mapping"] as $model) {
			$children = $db->get("conf.service.garage." . $model);
			foreach ($children as $child) {
				if ($child->get("instanceuuid") === $params["uuid"]) {
					$db->delete($child);
				}
			}
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
		$object->set("webuipasswordhash",
			password_hash($password, PASSWORD_BCRYPT));
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
		$objects = $db->get("conf.service.garage.datastore");
		$objectsAssoc = [];
		foreach ($objects as $objectv) {
			if (!empty($params["instanceuuid"]) &&
				$objectv->get("instanceuuid") !== $params["instanceuuid"]) {
				continue;
			}
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
	// Buckets
	// ------------------------------------------------------------------

	public function getBucketList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$db = \OMV\Config\Database::getInstance();
		if (!empty($params["instanceuuid"])) {
			$this->reconcileLive($db, $params["instanceuuid"]);
		}
		$objects = $db->get("conf.service.garage.bucket");
		// Merge live state, if possible.
		$live = [];
		$liveInstanceRunning = false;
		if (!empty($params["instanceuuid"])) {
			$instances = $db->get("conf.service.garage.instance");
			foreach ($instances as $instancev) {
				if ($instancev->get("uuid") === $params["instanceuuid"]) {
					$liveInstanceRunning = (new SystemCtl(
						"garage@" . $instancev->get("name")))->isActive();
					if ($liveInstanceRunning) {
						try {
							$result = $this->jsonApi($db, $params["instanceuuid"], "ListBuckets");
							foreach ($result as $bucket) {
								$info = $this->jsonApi($db, $params["instanceuuid"],
									"GetBucketInfo",
									json_encode(["id" => $bucket["id"]]));
								foreach ($bucket["globalAliases"] ?? [] as $alias) {
									$live[$alias] = [
										"garageid" => $bucket["id"],
										"bytes" => $info["bytes"] ?? 0,
										"objects" => $info["objects"] ?? 0
									];
								}
							}
						} catch (\Exception $e) {
							$liveInstanceRunning = false;
						}
					}
				}
			}
		}
		$objectsAssoc = [];
		foreach ($objects as $objectv) {
			if (!empty($params["instanceuuid"]) &&
				$objectv->get("instanceuuid") !== $params["instanceuuid"]) {
				continue;
			}
			$assoc = $objectv->getAssoc();
			$assoc["state"] = $liveInstanceRunning
				? (isset($live[$assoc["name"]])
					? gettext("Applied")
					: gettext("Pending"))
				: gettext("Unknown");
			if (isset($live[$assoc["name"]])) {
				$assoc["bytes"] = $live[$assoc["name"]]["bytes"];
				$assoc["objects"] = $live[$assoc["name"]]["objects"];
			}
			$objectsAssoc[] = $assoc;
		}
		return $this->applyFilter($objectsAssoc, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	public function getBucket($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		if ($params["uuid"] === $newUuid) {
			return [
				"uuid" => $newUuid,
				"instanceuuid" => $params["instanceuuid"] ?? "",
				"name" => "",
				"garageid" => "",
				"maxsize" => 0,
				"maxobjects" => 0,
				"website" => false,
				"indexdoc" => "",
				"errordoc" => ""
			];
		}
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		return $db->getAssoc("conf.service.garage.bucket", $params["uuid"]);
	}

	public function setBucket($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setbucket");
		$db = \OMV\Config\Database::getInstance();
		$instance = $this->assertInstanceExists($db, $params["instanceuuid"]);
		$this->assertInstanceRunning($db, $params["instanceuuid"]);

		$object = new \OMV\Config\ConfigObject("conf.service.garage.bucket");
		$object->setAssoc($params);
		$isNew = $object->isNew();
		if ($isNew) {
			$db->assertIsUnique($object, "name");
			$result = $this->jsonApi($db, $params["instanceuuid"], "CreateBucket",
				json_encode(["globalAlias" => $params["name"]]));
			$object->set("garageid", $result["id"] ?? "");
		} else {
			$existing = $db->get("conf.service.garage.bucket", $params["uuid"]);
			if ($existing->get("name") !== $params["name"]) {
				// Rename = re-alias. The garage id is kept.
				$this->jsonApi($db, $params["instanceuuid"], "AddBucketAlias",
					json_encode([
						"bucketId" => $existing->get("garageid"),
						"globalAlias" => $params["name"]
					]));
				try {
					$this->jsonApi($db, $params["instanceuuid"], "RemoveBucketAlias",
						json_encode([
							"bucketId" => $existing->get("garageid"),
							"globalAlias" => $existing->get("name")
						]));
				} catch (\Exception $e) {
					// The old alias may already be gone.
				}
			}
			$object->set("garageid", $existing->get("garageid"));
		}
		$db->set($object);
		$this->applyBucketSettings($db, $object);
		return $object->getAssoc();
	}

	public function deleteBucket($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage.bucket", $params["uuid"]);
		$this->assertInstanceRunning($db, $object->get("instanceuuid"));
		if (!empty($object->get("garageid"))) {
			$this->jsonApi($db, $object->get("instanceuuid"), "DeleteBucket",
				json_encode(["id" => $object->get("garageid")]));
		}
		// Drop the mappings that reference this bucket.
		$mappings = $db->get("conf.service.garage.mapping");
		foreach ($mappings as $mappingv) {
			if ($mappingv->get("bucketuuid") === $params["uuid"]) {
				$db->delete($mappingv);
			}
		}
		$db->delete($object);
		return $object->getAssoc();
	}

	private function applyBucketSettings($db, $object)
	{
		$body = [
			"quotas" => [
				"maxSize" => floatval($object->get("maxsize")) > 0
					? intval(floatval($object->get("maxsize")) * 1024 * 1024 * 1024)
					: null,
				"maxObjects" => intval($object->get("maxobjects")) > 0
					? intval($object->get("maxobjects")) : null
			]
		];
		if ($object->get("website")) {
			$body["websiteAccess"] = [
				"enabled" => true,
				"indexDocument" => $object->get("indexdoc") ?: "index.html",
				"errorDocument" => $object->get("errordoc") ?: null
			];
		} else {
			$body["websiteAccess"] = ["enabled" => false];
		}
		$this->jsonApi($db, $object->get("instanceuuid"), "UpdateBucket",
			json_encode(["id" => $object->get("garageid"), "body" => $body]));
	}

	// ------------------------------------------------------------------
	// Keys
	// ------------------------------------------------------------------

	public function getKeyList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$db = \OMV\Config\Database::getInstance();
		if (!empty($params["instanceuuid"])) {
			$this->reconcileLive($db, $params["instanceuuid"]);
		}
		$objects = $db->get("conf.service.garage.key");
		$objectsAssoc = [];
		foreach ($objects as $objectv) {
			if (!empty($params["instanceuuid"]) &&
				$objectv->get("instanceuuid") !== $params["instanceuuid"]) {
				continue;
			}
			$objectsAssoc[] = $objectv->getAssoc();
		}
		return $this->applyFilter($objectsAssoc, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	public function getKey($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		if ($params["uuid"] === $newUuid) {
			return [
				"uuid" => $newUuid,
				"instanceuuid" => $params["instanceuuid"] ?? "",
				"name" => "",
				"keyid" => "",
				"secret" => ""
			];
		}
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		return $db->getAssoc("conf.service.garage.key", $params["uuid"]);
	}

	public function setKey($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setkey");
		$db = \OMV\Config\Database::getInstance();
		$this->assertInstanceExists($db, $params["instanceuuid"]);
		$this->assertInstanceRunning($db, $params["instanceuuid"]);

		$object = new \OMV\Config\ConfigObject("conf.service.garage.key");
		$object->setAssoc($params);
		if ($object->isNew()) {
			$db->assertIsUnique($object, "name");
			if (!empty($params["keyid"]) && !empty($params["secret"])) {
				// Import an existing key pair.
				$result = $this->jsonApi($db, $params["instanceuuid"], "ImportKey",
					json_encode([
						"name" => $params["name"],
						"accessKeyId" => $params["keyid"],
						"secretAccessKey" => $params["secret"]
					]));
			} else {
				$result = $this->jsonApi($db, $params["instanceuuid"], "CreateKey",
					json_encode(["name" => $params["name"]]));
			}
			$object->set("keyid", $result["accessKeyId"] ?? "");
			$object->set("secret", $result["secretAccessKey"] ?? "");
		} else {
			// Only the name can be changed after creation.
			$this->jsonApi($db, $params["instanceuuid"], "UpdateKey",
				json_encode(["id" => $object->get("keyid") ?? "",
					"body" => ["name" => $params["name"]]]));
		}
		$db->set($object);
		return $object->getAssoc();
	}

	public function deleteKey($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage.key", $params["uuid"]);
		$this->assertInstanceRunning($db, $object->get("instanceuuid"));
		if (!empty($object->get("keyid"))) {
			$this->jsonApi($db, $object->get("instanceuuid"), "DeleteKey",
				json_encode(["id" => $object->get("keyid")]));
		}
		$mappings = $db->get("conf.service.garage.mapping");
		foreach ($mappings as $mappingv) {
			if ($mappingv->get("keyuuid") === $params["uuid"]) {
				$db->delete($mappingv);
			}
		}
		$db->delete($object);
		return $object->getAssoc();
	}

	// ------------------------------------------------------------------
	// Mappings (key to bucket permissions)
	// ------------------------------------------------------------------

	public function getMappingList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$db = \OMV\Config\Database::getInstance();
		if (!empty($params["instanceuuid"])) {
			$this->reconcileLive($db, $params["instanceuuid"]);
		}
		$keys = [];
		foreach ($db->get("conf.service.garage.key") as $keyv) {
			$keys[$keyv->get("uuid")] = $keyv->get("name");
		}
		$buckets = [];
		foreach ($db->get("conf.service.garage.bucket") as $bucketv) {
			$buckets[$bucketv->get("uuid")] = $bucketv->get("name");
		}
		$objectsAssoc = [];
		foreach ($db->get("conf.service.garage.mapping") as $mappingv) {
			if (!empty($params["instanceuuid"]) &&
				$mappingv->get("instanceuuid") !== $params["instanceuuid"]) {
				continue;
			}
			$assoc = $mappingv->getAssoc();
			$assoc["keyname"] = $keys[$assoc["keyuuid"]] ?? gettext("n/a");
			$assoc["bucketname"] = $buckets[$assoc["bucketuuid"]] ?? gettext("n/a");
			$objectsAssoc[] = $assoc;
		}
		return $this->applyFilter($objectsAssoc, $params["start"], $params["limit"],
			$params["sortfield"], $params["sortdir"]);
	}

	public function getMapping($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		if ($params["uuid"] === $newUuid) {
			return [
				"uuid" => $newUuid,
				"instanceuuid" => $params["instanceuuid"] ?? "",
				"keyuuid" => "",
				"bucketuuid" => "",
				"allowread" => true,
				"allowwrite" => true,
				"allowowner" => false
			];
		}
		$db = \OMV\Config\Database::getInstance();
		return $db->getAssoc("conf.service.garage.mapping", $params["uuid"]);
	}

	public function setMapping($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setmapping");
		$db = \OMV\Config\Database::getInstance();
		$this->assertInstanceExists($db, $params["instanceuuid"]);
		$this->assertInstanceRunning($db, $params["instanceuuid"]);

		$object = new \OMV\Config\ConfigObject("conf.service.garage.mapping");
		$object->setAssoc($params);
		if ($object->isNew()) {
			// One row per key and bucket.
			$existing = $db->get("conf.service.garage.mapping");
			foreach ($existing as $mappingv) {
				if ($mappingv->get("instanceuuid") === $params["instanceuuid"] &&
					$mappingv->get("keyuuid") === $params["keyuuid"] &&
					$mappingv->get("bucketuuid") === $params["bucketuuid"]) {
					throw new \OMV\Exception(
						gettext("A mapping for this key and bucket already exists."));
				}
			}
		}
		$db->set($object);
		$this->applyMapping($db, $object);
		return $object->getAssoc();
	}

	public function deleteMapping($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage.mapping", $params["uuid"]);
		$this->assertInstanceRunning($db, $object->get("instanceuuid"));
		try {
			$this->applyMapping($db, $object, true);
		} catch (\Exception $e) {
			// The key or bucket may already be gone.
		}
		$db->delete($object);
		return $object->getAssoc();
	}

	private function applyMapping($db, $object, $denyAll = false)
	{
		$key = $db->get("conf.service.garage.key", $object->get("keyuuid"));
		$bucket = $db->get("conf.service.garage.bucket", $object->get("bucketuuid"));
		$allow = [];
		$deny = [];
		$fields = ["read" => "allowread", "write" => "allowwrite",
			"owner" => "allowowner"];
		foreach ($fields as $perm => $field) {
			if (!$denyAll && $object->get($field)) {
				$allow[$perm] = true;
			} else {
				$deny[$perm] = true;
			}
		}
		$base = [
			"bucketId" => $bucket->get("garageid"),
			"accessKeyId" => $key->get("keyid")
		];
		if (!empty($allow)) {
			$this->jsonApi($db, $object->get("instanceuuid"), "AllowBucketKey",
				json_encode($base + ["permissions" => $allow]));
		}
		if (!empty($deny)) {
			$this->jsonApi($db, $object->get("instanceuuid"), "DenyBucketKey",
				json_encode($base + ["permissions" => $deny]));
		}
	}

	public function enumerateKeys($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$db = \OMV\Config\Database::getInstance();
		$result = [];
		if (!empty($params["addnone"])) {
			$result[] = ["uuid" => "", "name" => gettext("None")];
		}
		foreach ($db->get("conf.service.garage.key") as $objectv) {
			if (!empty($params["instanceuuid"]) &&
				$objectv->get("instanceuuid") !== $params["instanceuuid"]) {
				continue;
			}
			$result[] = [
				"uuid" => $objectv->get("uuid"),
				"name" => $objectv->get("name")
			];
		}
		return $result;
	}

	public function enumerateBuckets($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$db = \OMV\Config\Database::getInstance();
		$result = [];
		if (!empty($params["addnone"])) {
			$result[] = ["uuid" => "", "name" => gettext("None")];
		}
		foreach ($db->get("conf.service.garage.bucket") as $objectv) {
			if (!empty($params["instanceuuid"]) &&
				$objectv->get("instanceuuid") !== $params["instanceuuid"]) {
				continue;
			}
			$result[] = [
				"uuid" => $objectv->get("uuid"),
				"name" => $objectv->get("name")
			];
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

	private function assertInstanceRunning($db, $uuid)
	{
		$instance = $this->assertInstanceExists($db, $uuid);
		$ctl = new SystemCtl("garage@" . $instance->get("name"));
		if (!$ctl->isActive()) {
			throw new \OMV\Exception(sprintf(
				gettext("The Garage instance '%s' is not running. Apply the configuration changes first."),
				$instance->get("name")));
		}
		return $instance;
	}

	private function jsonApi($db, $instanceUuid, $endpoint, $payload = "")
	{
		$instance = $db->get("conf.service.garage.instance", $instanceUuid);
		$configPath = self::GARAGE_ETC . "/" . $instance->get("name") . ".toml";
		$output = [];
		// OMV\System\Process does not shell-escape its arguments, so the
		// full command line is built and quoted here. Endpoints without a
		// request body must be called without a payload.
		$cmdLine = sprintf("%s -c %s json-api %s",
			escapeshellarg(self::GARAGE_BIN),
			escapeshellarg($configPath),
			escapeshellarg($endpoint));
		if ($payload !== "") {
			$cmdLine .= " " . escapeshellarg($payload);
		}
		// Capture stderr into the output array; PHP exec() would
		// otherwise send it to the engine daemon's stderr.
		$cmdLine .= " 2>&1";
		$cmd = new Process($cmdLine);
		// Right after a deploy the admin API can fail the first calls
		// before the daemon finished binding. An empty output means
		// nothing happened, so retrying is safe.
		for ($attempt = 0; ; $attempt++) {
			$output = [];
			$exitStatus = 0;
			try {
				$cmd->execute($output, $exitStatus);
				break;
			} catch (\Exception $e) {
				if (count($output) > 0 || $attempt >= 2) {
					throw new \OMV\Exception(sprintf(
						gettext("Garage admin operation '%s' failed (rc %s): %s"),
						$endpoint, $exitStatus, implode(" ", $output)));
				}
				sleep(1);
			}
		}
		$result = json_decode(implode("\n", $output), true);
		if (is_null($result)) {
			return [];
		}
		return $result;
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

	// ------------------------------------------------------------------
	// Live state reconciliation
	// ------------------------------------------------------------------

	/**
	 * Synchronize the confdb bucket/key/mapping tables with live Garage
	 * state. The web UI (and S3 clients) can create and delete buckets
	 * and keys behind OMV's back; reconciliation runs on every list
	 * request so the workbench always mirrors the daemon. Garage is the
	 * source of truth for what exists, confdb for OMV-side metadata.
	 */
	private function reconcileLive($db, $instanceUuid)
	{
		static $lastRun = [];
		$now = microtime(true);
		if (isset($lastRun[$instanceUuid]) &&
			$now - $lastRun[$instanceUuid] < 5) {
			return;
		}
		$lastRun[$instanceUuid] = $now;
		$newUuid = \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID");
		try {
			$liveKeys = $this->jsonApi($db, $instanceUuid, "ListKeys");
			$liveBuckets = $this->jsonApi($db, $instanceUuid, "ListBuckets");
		} catch (\Exception $e) {
			return; // instance down or starting; show confdb as-is
		}

		// ---- Buckets: drop dead rows, backfill legacy ids, import new.
		$liveBucketById = [];
		foreach ($liveBuckets as $b) {
			$liveBucketById[$b["id"]] = $b["globalAliases"] ?? [];
		}
		$bucketIdToUuid = [];
		$deadBuckets = [];
		foreach ($db->get("conf.service.garage.bucket") as $b) {
			if ($b->get("instanceuuid") !== $instanceUuid) {
				continue;
			}
			$gid = $b->get("garageid");
			if (strlen($gid) > 0 && isset($liveBucketById[$gid])) {
				$bucketIdToUuid[$gid] = $b->get("uuid");
				continue;
			}
			if (strlen($gid) === 0) {
				// Legacy row without a stored garage id: match by name.
				foreach ($liveBucketById as $id => $aliases) {
					if (in_array($b->get("name"), $aliases, true)) {
						$b->set("garageid", $id);
						$db->set($b);
						$bucketIdToUuid[$id] = $b->get("uuid");
						continue 2;
					}
				}
			}
			$deadBuckets[] = $b;
		}
		foreach ($deadBuckets as $b) {
			$db->delete($b);
		}
		foreach ($liveBuckets as $b) {
			if (isset($bucketIdToUuid[$b["id"]])) {
				continue;
			}
			$alias = ($b["globalAliases"] ?? [])[0] ??
				("imported-" . substr($b["id"], 0, 8));
			$object = new \OMV\Config\ConfigObject(
				"conf.service.garage.bucket");
			$object->setAssoc([
				"uuid" => $newUuid,
				"instanceuuid" => $instanceUuid,
				"name" => $this->uniqueName($db, "conf.service.garage.bucket",
					"instanceuuid", $instanceUuid, "name", $alias),
				"garageid" => $b["id"],
				"maxsize" => 0, "maxobjects" => 0, "website" => False,
				"indexdoc" => "", "errordoc" => ""
			]);
			$db->set($object);
			$bucketIdToUuid[$b["id"]] = $object->get("uuid");
		}

		// ---- Keys: same pattern, with secret recovery on import.
		$liveKeyById = [];
		foreach ($liveKeys as $k) {
			$liveKeyById[$k["id"]] = $k;
		}
		$keyIdToUuid = [];
		$deadKeys = [];
		foreach ($db->get("conf.service.garage.key") as $k) {
			if ($k->get("instanceuuid") !== $instanceUuid) {
				continue;
			}
			$keyid = $k->get("keyid");
			if (strlen($keyid) > 0 && isset($liveKeyById[$keyid])) {
				$keyIdToUuid[$keyid] = $k->get("uuid");
				continue;
			}
			$deadKeys[] = $k;
		}
		foreach ($deadKeys as $k) {
			$db->delete($k);
		}
		foreach ($liveKeys as $k) {
			if (isset($keyIdToUuid[$k["id"]])) {
				continue;
			}
			$secret = "";
			try {
				$info = $this->jsonApi($db, $instanceUuid, "GetKeyInfo",
					json_encode(["id" => $k["id"], "showSecretKey" => true]));
				$secret = $info["secretAccessKey"] ?? "";
			} catch (\Exception $e) {
			}
			$object = new \OMV\Config\ConfigObject(
				"conf.service.garage.key");
			$object->setAssoc([
				"uuid" => $newUuid,
				"instanceuuid" => $instanceUuid,
				"name" => $this->uniqueName($db, "conf.service.garage.key",
					"instanceuuid", $instanceUuid, "name",
					$k["name"] ?? "imported-key"),
				"keyid" => $k["id"],
				"secret" => $secret
			]);
			$db->set($object);
			$keyIdToUuid[$k["id"]] = $object->get("uuid");
		}

		// ---- Mappings: mirror live per-key bucket permissions.
		$liveMaps = [];
		foreach ($liveKeys as $k) {
			try {
				$info = $this->jsonApi($db, $instanceUuid, "GetKeyInfo",
					json_encode(["id" => $k["id"]]));
			} catch (\Exception $e) {
				continue;
			}
			foreach ($info["buckets"] ?? [] as $be) {
				$perms = $be["permissions"] ?? [];
				$liveMaps[$k["id"] . "|" . $be["id"]] = [
					!empty($perms["read"]), !empty($perms["write"]),
					!empty($perms["owner"])];
			}
		}
		$mappingByKey = [];
		$deadMappings = [];
		foreach ($db->get("conf.service.garage.mapping") as $m) {
			if ($m->get("instanceuuid") !== $instanceUuid) {
				continue;
			}
			$keyid = array_search($m->get("keyuuid"), $keyIdToUuid, true);
			$gid = array_search($m->get("bucketuuid"), $bucketIdToUuid, true);
			$pair = ($keyid === false || $gid === false)
				? "stale" : $keyid . "|" . $gid;
			if (!isset($liveMaps[$pair])) {
				$deadMappings[] = $m;
				continue;
			}
			$mappingByKey[$pair] = $m;
			$flags = $liveMaps[$pair];
			if ($m->get("allowread") !== $flags[0] ||
				$m->get("allowwrite") !== $flags[1] ||
				$m->get("allowowner") !== $flags[2]) {
				$m->set("allowread", $flags[0]);
				$m->set("allowwrite", $flags[1]);
				$m->set("allowowner", $flags[2]);
				$db->set($m);
			}
		}
		foreach ($deadMappings as $m) {
			$db->delete($m);
		}
		foreach ($liveMaps as $pair => $flags) {
			if (isset($mappingByKey[$pair])) {
				continue;
			}
			[$keyid, $gid] = explode("|", $pair);
			$object = new \OMV\Config\ConfigObject(
				"conf.service.garage.mapping");
			$object->setAssoc([
				"uuid" => $newUuid,
				"instanceuuid" => $instanceUuid,
				"keyuuid" => $keyIdToUuid[$keyid],
				"bucketuuid" => $bucketIdToUuid[$gid],
				"allowread" => $flags[0], "allowwrite" => $flags[1],
				"allowowner" => $flags[2]
			]);
			$db->set($object);
		}
	}

	private function uniqueName($db, $model, $parentField, $parentValue,
		$nameField, $base)
	{
		$used = [];
		foreach ($db->get($model) as $objectv) {
			if ($objectv->get($parentField) === $parentValue) {
				$used[] = $objectv->get($nameField);
			}
		}
		if (!in_array($base, $used, true)) {
			return $base;
		}
		for ($i = 2; ; $i++) {
			$candidate = $base . "-" . $i;
			if (!in_array($candidate, $used, true)) {
				return $candidate;
			}
		}
	}


	private function revokeAcls($db, $instance)
	{
		$uuid = $instance->get("uuid");
		$stor = $instance->get("storageshareuuid");
		// Legacy instances only recorded metadatashareuuid; their storage
		// folder is the metadata folder.
		if (strlen($stor ?? "") !== 36 &&
			strlen($instance->get("metadatashareuuid") ?? "") === 36) {
			$stor = $instance->get("metadatashareuuid");
		}
		$shares = [];
		if (strlen($stor ?? "") === 36) {
			$shares[] = $stor;
		}
		if (strlen($instance->get("metadatashareuuid") ?? "") === 36) {
			$shares[] = $instance->get("metadatashareuuid");
		}
		if (strlen($instance->get("snapshotsshareuuid") ?? "") === 36) {
			$shares[] = $instance->get("snapshotsshareuuid");
		}
		foreach ($db->get("conf.service.garage.datastore") as $dsv) {
			if ($dsv->get("instanceuuid") === $uuid) {
				$shares[] = $dsv->get("shareuuid");
			}
		}
		// Find shares still used by other instances, including their
		// datastores. Those keep their ACL.
		$stillUsed = [];
		foreach ($db->get("conf.service.garage.instance") as $instancev) {
			if ($instancev->get("uuid") === $uuid) {
				continue;
			}
			$otherStor = $instancev->get("storageshareuuid");
			if (strlen($otherStor ?? "") !== 36 &&
				strlen($instancev->get("metadatashareuuid") ?? "") === 36) {
				$otherStor = $instancev->get("metadatashareuuid");
			}
			if (strlen($otherStor ?? "") === 36) {
				$stillUsed[] = $otherStor;
			}
			if (strlen($instancev->get("metadatashareuuid") ?? "") === 36) {
				$stillUsed[] = $instancev->get("metadatashareuuid");
			}
			if (strlen($instancev->get("snapshotsshareuuid") ?? "") === 36) {
				$stillUsed[] = $instancev->get("snapshotsshareuuid");
			}
		}
		foreach ($db->get("conf.service.garage.datastore") as $dsv) {
			if ($dsv->get("instanceuuid") !== $uuid) {
				$stillUsed[] = $dsv->get("shareuuid");
			}
		}
		foreach (array_unique($shares) as $shareUuid) {
			if (in_array($shareUuid, $stillUsed) || strlen($shareUuid ?? "") !== 36) {
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

}
