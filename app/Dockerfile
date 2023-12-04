ARG BUILD

FROM python:3.11-slim-bookworm as base

FROM base as builder
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y curl tar \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
COPY . /build/app/
RUN pip3 install --disable-pip-version-check --prefix=/build/usr/local -r /build/app/requirements.txt
RUN case $(uname -m) in \
    armv7l) TARGETARCH=arm; FFMPEG_ARCH=armv7; MTX_ARCH=armv7;; \
    aarch64) TARGETARCH=arm64; FFMPEG_ARCH=aarch64; MTX_ARCH=arm64v8;; \
    *) TARGETARCH=amd64; FFMPEG_ARCH=x86_64; MTX_ARCH=amd64;; \
    esac && \
    cd /build \
    && . app/.env \
    && mkdir -p tokens img \
    && curl -SL https://github.com/homebridge/ffmpeg-for-homebridge/releases/latest/download/ffmpeg-alpine-${FFMPEG_ARCH}.tar.gz \
    | tar xzf - -C . \
    && curl -SL https://github.com/bluenviron/mediamtx/releases/download/v${MTX_TAG}/mediamtx_v${MTX_TAG}_linux_${MTX_ARCH}.tar.gz \
    | tar xzf - -C app \
    && cp app/lib.${TARGETARCH} usr/local/lib/libIOTCAPIs_ALL.so \
    && rm app/*.txt app/lib.*  \ 
    && echo BUILD_DATE=$(date) > .build_date


FROM base
ARG BUILD
COPY --from=builder /build /
ENV PYTHONUNBUFFERED=1 FLASK_APP=frontend BUILD=$BUILD
WORKDIR /app
CMD ["flask", "run", "--host=0.0.0.0"]