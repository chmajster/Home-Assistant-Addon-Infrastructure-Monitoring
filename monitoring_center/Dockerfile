ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH=amd64

LABEL \
  io.hass.name="Monitoring Center" \
  io.hass.description="Local network and website monitoring center for Home Assistant" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    bash \
    iputils \
    python3 \
    py3-pip \
    tzdata

WORKDIR /app

COPY requirements.txt /app/
RUN python3 -m venv /opt/monitoring-center \
  && /opt/monitoring-center/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/monitoring-center/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY monitoring_center /app/monitoring_center
COPY static /app/static
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8099
CMD ["/run.sh"]
