ARG ARM
ARG BUILD
ARG ARCH=${ARM:+arm32v7}
FROM ${ARCH:-amd64}/python:3.11-slim-bullseye as base

FROM base as builder
ARG ARM
ARG LIB_ARCH=${ARM:+arm}
ARG MTX_ARCH=${ARM:+armv7}
ARG FFMPEG_ARCH=${ARM:+armv7l}
RUN apt-get update && \
    apt-get install -y curl gcc tar && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --disable-pip-version-check --prefix=/build/usr/local -r /tmp/requirements.txt
COPY *.lib /tmp/lib/
COPY . /build/app/
RUN mkdir -p /build/tokens /build/img && \
    . /build/app/.env && \
    curl -L https://github.com/homebridge/ffmpeg-for-homebridge/releases/latest/download/ffmpeg-debian-${FFMPEG_ARCH:-x86_64}.tar.gz \
    | tar xzf - -C /build && \
    curl -L https://github.com/bluenviron/mediamtx/releases/download/v${MTX_TAG}/mediamtx_v${MTX_TAG}_linux_${MTX_ARCH:-amd64}.tar.gz \
    | tar xzf - -C /build/app && \
    cp /tmp/lib/${LIB_ARCH:-amd}.lib /build/usr/local/lib/libIOTCAPIs_ALL.so && \
    rm -rf /tmp/*

FROM base
ARG BUILD
COPY --from=builder /build /
ENV PYTHONUNBUFFERED=1 FLASK_APP=frontend BUILD=$BUILD
WORKDIR /app
CMD [ "flask", "run", "--host=0.0.0.0"]