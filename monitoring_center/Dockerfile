ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

ARG BUILD_VERSION=0.3.0
ARG BUILD_ARCH=amd64

LABEL \
  io.hass.name="Monitoring Center" \
  io.hass.description="Local network and website monitoring center for Home Assistant" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN retries=0; \
    until apk add --no-cache \
        iputils \
        tzdata; do \
      retries=$((retries + 1)); \
      if [ "${retries}" -ge 5 ]; then \
        exit 1; \
      fi; \
      sleep $((retries * 5)); \
    done

WORKDIR /app

COPY requirements.txt /app/
RUN python -m venv /opt/monitoring-center \
  && /opt/monitoring-center/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/monitoring-center/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY monitoring_center /app/monitoring_center
COPY static /app/static
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8099
CMD ["/run.sh"]
