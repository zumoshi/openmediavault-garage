FROM debian:trixie@sha256:4c25275446ca371766b8b093c696782eabce06263fccacb8d5d813b3dc44b308
RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates curl dpkg-dev lintian python3 shellcheck yamllint \
	&& rm -rf /var/lib/apt/lists/*
ARG UV_WHEEL=https://files.pythonhosted.org/packages/5c/43/0688ff5142934238f2812e348f4a24e09b57d48bfb38dd8f850325a0d9de/uv-0.13.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
ARG UV_SHA256=22759b8895e1103578de6fb4cd27e94b4399d021023378d29f01333717751fba
RUN curl -fsSL -o /tmp/uv.whl "$UV_WHEEL" \
	&& echo "$UV_SHA256  /tmp/uv.whl" | sha256sum -c - \
	&& python3 -m zipfile -e /tmp/uv.whl /tmp/uv \
	&& install -m 0755 /tmp/uv/uv-*.data/scripts/uv /usr/local/bin/uv \
	&& rm -rf /tmp/uv /tmp/uv.whl
ENV UV_CACHE_DIR=/tmp/uv-cache UV_PROJECT_ENVIRONMENT=/tmp/venv UV_PYTHON_DOWNLOADS=never
