FROM spaneng/doover_device_base AS base_image
LABEL com.doover.app="true"
LABEL com.doover.managed="true"
HEALTHCHECK --interval=30s --timeout=2s --start-period=5s CMD curl -f "127.0.0.1:$HEALTHCHECK_PORT" || exit 1

## FIRST STAGE ##
FROM base_image AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# give the app access to our pipenv installed packages
RUN uv venv --system-site-packages
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

## OPENVPN STAGE ##
FROM kylemanna/openvpn:latest AS openvpn_source

## OPENVPN LIBS STAGE ##
FROM openvpn_source AS openvpn_libs
RUN mkdir -p /tmp/libs && \
    ldd /usr/sbin/openvpn 2>/dev/null | awk '/=>/ {print $3}' | grep -v '^$' | while read lib; do \
      if [ -f "$lib" ]; then \
        libdir=$(dirname "$lib"); \
        mkdir -p "/tmp/libs$libdir"; \
        cp "$lib" "/tmp/libs$lib"; \
      fi; \
    done || true

## SECOND STAGE ##
FROM base_image AS final_image

# Copy OpenVPN binary
COPY --from=openvpn_source /usr/sbin/openvpn /usr/sbin/openvpn
# Copy OpenVPN required libraries
COPY --from=openvpn_libs /tmp/libs/ /

# Copy application code
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["doover-app-run"]
