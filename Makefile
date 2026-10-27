PHP_IMAGE := php:8.4.27-cli@sha256:debadc2e36b857657846e2e952cbaf52702e55482dd3c2c43806f68d8c534a70
COMPOSER_IMAGE := composer:2.10.3@sha256:b6dcd72ca98fa19d0e5b8476de179859704891fad06dd9e0b96833d4c430a5fc
DEBIAN_IMAGE := debian:trixie@sha256:4c25275446ca371766b8b093c696782eabce06263fccacb8d5d813b3dc44b308
DOCKER_RUN := docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR):/app -w /app

.PHONY: unit lint package-test e2e

unit: vendor/composer/installed.json
	$(DOCKER_RUN) $(PHP_IMAGE) vendor/bin/phpunit $(ARGS)

vendor/composer/installed.json: composer.json composer.lock
	$(DOCKER_RUN) -e COMPOSER_HOME=/tmp/composer $(COMPOSER_IMAGE) install --no-interaction
	touch $@

lint: dist/.built
	printf 'FROM $(DEBIAN_IMAGE)\nRUN apt-get update && apt-get install -y --no-install-recommends lintian\n' \
		| docker build -q -t openmediavault-garage-lintian - >/dev/null
	docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR)/dist:/dist:ro openmediavault-garage-lintian \
		sh -c 'lintian --version && lintian --fail-on error,warning,info -I /dist/*.deb'

package-test: lint
	cd tests/package && uv run pytest $(ARGS)

dist/.built: build.sh nfpm.yaml debian/changelog $(wildcard $(shell git ls-files --cached --others --exclude-standard tree scripts checksums))
	rm -rf dist
	./build.sh
	touch $@

e2e:
	cd tests/e2e && uv run playwright install chromium && uv run pytest $(ARGS)
