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

	public function getName()
	{
		return "Garage";
	}

	public function initialize()
	{
		$this->registerMethod("getSettings");
		$this->registerMethod("setSettings");
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

	// ------------------------------------------------------------------
	// Settings
	// ------------------------------------------------------------------

	public function getSettings($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage");
		$object->remove("instances");
		$object->remove("datastores");
		$object->remove("buckets");
		$object->remove("keys");
		$object->remove("mappings");
		return $object->getAssoc();
	}

	public function setSettings($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.setsettings");
		$db = \OMV\Config\Database::getInstance();
		$object = $db->get("conf.service.garage");
		$object->setAssoc($params);
		$db->set($object);
		$object->remove("instances");
		$object->remove("datastores");
		$object->remove("buckets");
		$object->remove("keys");
		$object->remove("mappings");
		return $object->getAssoc();
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
				"enable" => false,
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
				"rpcsecret" => "",
				"admintoken" => "",
				"webuienable" => false,
				"webuiport" => $ports["webuiport"],
				"webuiuser" => "admin",
				"webuipassword" => ""
			];
			return $assoc;
		}
		$this->validateMethodParams($params, "rpc.common.objectuuid");
		return $db->getAssoc("conf.service.garage.instance", $params["uuid"]);
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

		if ($isNew) {
			// Silently resolve duplicate ports with the next free port. The
			// create dialog pre-suggests unused ports, but a stale page or a
			// race with another creation must not block a plain "next-next"
			// workflow.
			$used = array_merge(
				$this->collectUsedPorts($db, null),
				$this->collectListeningPorts()
			);
			foreach (array_keys(self::DEFAULT_PORTS) as $key) {
				$port = intval($params[$key]);
				while (in_array($port, $used)) {
					$port++;
				}
				$params[$key] = $port;
				$used[] = $port;
			}
			// Secrets and credentials.
			if (empty($params["rpcsecret"])) {
				$params["rpcsecret"] = $this->generateSecret();
			}
			if (empty($params["admintoken"])) {
				$params["admintoken"] = $this->generateSecret();
			}
			if (empty($params["webuipassword"])) {
				$params["webuipassword"] = $this->generatePassword();
			}
			$params["webuipasswordhash"] =
				password_hash($params["webuipassword"], PASSWORD_BCRYPT);
		} else {
			// On edit, ports must not collide with other instances. Explicit
			// conflicts are reported, not silently resolved.
			$used = $this->collectUsedPorts($db, $params["uuid"]);
			foreach (array_keys(self::DEFAULT_PORTS) as $key) {
				if (in_array(intval($params[$key]), $used)) {
					throw new \OMV\Exception(sprintf(
						gettext("Port %d is already used by another Garage instance."),
						$params[$key]));
				}
			}
		}

		if (!empty($params["webuienable"]) && empty($params["adminenable"])) {
			throw new \OMV\Exception(
				gettext("The web UI requires the admin API to be enabled."));
		}

		$object = new \OMV\Config\ConfigObject("conf.service.garage.instance");
		$object->setAssoc($params);
		if ($isNew) {
			$db->assertIsUnique($object, "name");
		}
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
							$result = $this->jsonApi($db, $params["instanceuuid"], "ListBuckets", "{}");
							foreach ($result as $bucket) {
								foreach ($bucket["globalAliases"] ?? [] as $alias) {
									$live[$alias] = [
										"garageid" => $bucket["id"],
										"bytes" => $bucket["bytes"] ?? 0,
										"objects" => $bucket["objects"] ?? 0
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
							"alias" => $existing->get("name")
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
			"id" => $object->get("garageid"),
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
			json_encode($body));
	}

	// ------------------------------------------------------------------
	// Keys
	// ------------------------------------------------------------------

	public function getKeyList($params, $context)
	{
		$this->validateMethodContext($context, ["role" => OMV_ROLE_ADMINISTRATOR]);
		$this->validateMethodParams($params, "rpc.garage.getlist");
		$db = \OMV\Config\Database::getInstance();
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
					"name" => $params["name"]]));
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
		$perms = [
			"read" => !$denyAll && $object->get("allowread"),
			"write" => !$denyAll && $object->get("allowwrite"),
			"owner" => !$denyAll && $object->get("allowowner")
		];
		$endpoint = "AllowBucketKey";
		if ($denyAll || (!$perms["read"] && !$perms["write"] && !$perms["owner"])) {
			$endpoint = "DenyBucketKey";
		}
		$this->jsonApi($db, $object->get("instanceuuid"), $endpoint, json_encode([
			"bucketId" => $bucket->get("garageid"),
			"keyId" => $key->get("keyid"),
			"permissions" => $perms
		]));
		if ($endpoint === "DenyBucketKey") {
			// Deny each permission explicitly to converge.
			foreach (["read", "write", "owner"] as $perm) {
				if ($perms[$perm]) {
					continue;
				}
				$this->jsonApi($db, $object->get("instanceuuid"), "DenyBucketKey",
					json_encode([
						"bucketId" => $bucket->get("garageid"),
						"keyId" => $key->get("keyid"),
						"permissions" => [$perm => true]
					]));
			}
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

	private function jsonApi($db, $instanceUuid, $endpoint, $payload)
	{
		$instance = $db->get("conf.service.garage.instance", $instanceUuid);
		$configPath = self::GARAGE_ETC . "/" . $instance->get("name") . ".toml";
		$output = [];
		$cmd = new Process([
			self::GARAGE_BIN, "-c", $configPath,
			"json-api", $endpoint, $payload
		]);
		try {
			$cmd->execute($output);
		} catch (\Exception $e) {
			throw new \OMV\Exception(sprintf(
				gettext("Garage admin operation '%s' failed: %s"),
				$endpoint, implode(" ", $output)));
		}
		$result = json_decode(implode("\n", $output), true);
		if (is_null($result)) {
			return [];
		}
		return $result;
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
		$shares = [];
		if (!empty($instance->get("metadatashareuuid"))) {
			$shares[] = $instance->get("metadatashareuuid");
		}
		if (!empty($instance->get("snapshotsshareuuid"))) {
			$shares[] = $instance->get("snapshotsshareuuid");
		}
		foreach ($db->get("conf.service.garage.datastore") as $dsv) {
			if ($dsv->get("instanceuuid") !== $instance->get("uuid")) {
				$shares[] = $dsv->get("shareuuid");
			}
		}
		// Find shares still used by other instances, including their
		// datastores. Those keep their ACL.
		$stillUsed = [];
		foreach ($db->get("conf.service.garage.instance") as $instancev) {
			if ($instancev->get("uuid") === $instance->get("uuid")) {
				continue;
			}
			if (!empty($instancev->get("metadatashareuuid"))) {
				$stillUsed[] = $instancev->get("metadatashareuuid");
			}
			if (!empty($instancev->get("snapshotsshareuuid"))) {
				$stillUsed[] = $instancev->get("snapshotsshareuuid");
			}
		}
		foreach ($db->get("conf.service.garage.datastore") as $dsv) {
			if ($dsv->get("instanceuuid") !== $instance->get("uuid")) {
				$stillUsed[] = $dsv->get("shareuuid");
			}
		}
		foreach (array_unique($shares) as $shareUuid) {
			if (in_array($shareUuid, $stillUsed) || empty($shareUuid)) {
				continue;
			}
			$sharedFolder = $db->get("conf.system.sharedfolder", $shareUuid);
			$mount = $db->get("conf.system.filesystem.mountpoint",
				$sharedFolder->get("mntentref"));
			$path = $mount->get("dir");
			$cmd = new Process(["setfacl", "-x", "u:garage", $path]);
			try {
				$cmd->execute($output);
			} catch (\Exception $e) {
			}
		}
	}

}
