ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.13-alpine3.24

ARG BUILD_VERSION=0.3.1
ARG BUILD_ARCH=amd64

LABEL \
  io.hass.name="Monitoring Center" \
  io.hass.description="Local network and website monitoring center for Home Assistant" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /app

COPY requirements.txt /app/
COPY wheels /wheels
RUN python -m venv /opt/monitoring-center \
  && /opt/monitoring-center/bin/pip install --no-cache-dir --no-index --find-links=/wheels -r /app/requirements.txt \
  && rm -rf /wheels

COPY monitoring_center /app/monitoring_center
COPY static /app/static
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8099
CMD ["/run.sh"]
