PHP_IMAGE := php:8.4.27-cli@sha256:debadc2e36b857657846e2e952cbaf52702e55482dd3c2c43806f68d8c534a70
COMPOSER_IMAGE := composer:2.10.3@sha256:b6dcd72ca98fa19d0e5b8476de179859704891fad06dd9e0b96833d4c430a5fc
TOOLS_IMAGE := openmediavault-garage-tools
ACTIONLINT_IMAGE := rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667
NFPM_VERSION := 2.48.0
NFPM_TARBALL := .tools/nfpm_$(NFPM_VERSION)_Linux_x86_64.tar.gz
NFPM := .tools/nfpm-$(NFPM_VERSION)/nfpm
DOCKER_RUN := docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR):/app -w /app
SHELL_SCRIPTS = $(shell git ls-files -z | xargs -0 awk 'FNR == 1 { if (/^#!.*\/(env )?(ba|da)?sh( |$$)/) print FILENAME; nextfile }')
PHP_FILES = $(shell git ls-files '*.php' '*.inc')

.PHONY: check unit lint package-test e2e tools-image

check: tools-image
	ci/check-no-private-keys.sh
	docker run --rm -v $(CURDIR):/repo:ro -w /repo $(ACTIONLINT_IMAGE)
	docker run --rm -v $(CURDIR):/app:ro -w /app $(TOOLS_IMAGE) shellcheck $(SHELL_SCRIPTS)
	docker run --rm -v $(CURDIR):/app:ro -w /app $(PHP_IMAGE) \
		sh -c 'status=0; for f; do php -l "$$f" >/dev/null || status=1; done; exit $$status' sh $(PHP_FILES)
	docker run --rm -v $(CURDIR):/app:ro -w /app $(TOOLS_IMAGE) yamllint --strict tree/usr/share/openmediavault/workbench

unit: vendor/composer/installed.json
	$(DOCKER_RUN) $(PHP_IMAGE) vendor/bin/phpunit $(ARGS)

vendor/composer/installed.json: composer.json composer.lock
	$(DOCKER_RUN) -e COMPOSER_HOME=/tmp/composer $(COMPOSER_IMAGE) install --no-interaction
	touch $@

lint: dist/.built tools-image
	docker run --rm -u $(shell id -u):$(shell id -g) -v $(CURDIR)/dist:/dist:ro $(TOOLS_IMAGE) \
		sh -c 'lintian --version && lintian --fail-on error,warning,info -I /dist/*.deb'

package-test: lint
	$(DOCKER_RUN) -w /app/tests/package $(TOOLS_IMAGE) uv run --locked pytest -p no:cacheprovider $(ARGS)

tools-image:
	docker build -q -t $(TOOLS_IMAGE) - <ci/tools.Dockerfile >/dev/null

dist/.built: build.sh nfpm.yaml debian/changelog $(wildcard $(shell git ls-files --cached --others --exclude-standard tree scripts checksums)) | $(NFPM)
	rm -rf dist
	NFPM=$(CURDIR)/$(NFPM) ./build.sh
	touch $@

$(NFPM_TARBALL):
	mkdir -p $(@D)
	curl -fsSL -o $@.part https://github.com/goreleaser/nfpm/releases/download/v$(NFPM_VERSION)/$(@F)
	mv $@.part $@

$(NFPM): $(NFPM_TARBALL) checksums/$(notdir $(NFPM_TARBALL)).sha256
	echo "$$(cat checksums/$(notdir $(NFPM_TARBALL)).sha256)  $<" | sha256sum -c - || { rm -f $<; exit 1; }
	mkdir -p $(@D)
	tar -xzf $< -C $(@D) nfpm
	touch $@

e2e:
	cd tests/e2e && uv run playwright install chromium && uv run pytest $(ARGS)
