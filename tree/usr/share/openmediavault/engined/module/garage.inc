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

class OMVModuleGarage extends \OMV\Engine\Module\ServiceAbstract
		implements \OMV\Engine\Notify\IListener {
	public function getName() {
		return "garage";
	}

	public function bindListeners(\OMV\Engine\Notify\Dispatcher $dispatcher) {
		$dispatcher->addListener(
			OMV_NOTIFY_MODIFY,
			"org.openmediavault.conf.service.garage",
			[$this, "setDirty"]);
		foreach (["instance", "datastore"] as $model) {
			$dispatcher->addListener(
				OMV_NOTIFY_CREATE | OMV_NOTIFY_MODIFY | OMV_NOTIFY_DELETE,
				"org.openmediavault.conf.service.garage." . $model,
				[$this, "setDirty"]);
		}
	}
}
