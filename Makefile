PHP_IMAGE := php:8.4.27-cli@sha256:debadc2e36b857657846e2e952cbaf52702e55482dd3c2c43806f68d8c534a70
COMPOSER_IMAGE := composer:2.10.3@sha256:b6dcd72ca98fa19d0e5b8476de179859704891fad06dd9e0b96833d4c430a5fc
DOCKER_RUN := docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR):/app -w /app

.PHONY: unit

unit: vendor/composer/installed.json
	$(DOCKER_RUN) $(PHP_IMAGE) vendor/bin/phpunit $(ARGS)

vendor/composer/installed.json: composer.json composer.lock
	$(DOCKER_RUN) -e COMPOSER_HOME=/tmp/composer $(COMPOSER_IMAGE) install --no-interaction
	touch $@
