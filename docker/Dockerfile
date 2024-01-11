ARG BUILD
ARG BUILD_DATE
ARG GITHUB_SHA
FROM python:3.12-slim-bookworm as base

FROM base as builder
ARG BUILD_DATE
RUN apt-get update \
    && apt-get install -y curl tar gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
COPY ../app/ /build/app/
RUN pip3 install --disable-pip-version-check --prefix=/build/usr/local -r /build/app/requirements.txt
RUN echo "BUILDING IMAGE FOR $(uname -m)" && \
    if [ "$(uname -m)" = "armv7l" ]; then \
    LIB_ARCH=arm; FFMPEG_ARCH=arm32v7; MTX_ARCH=armv7; \
    elif [ "$(uname -m)" = "aarch64" ]; then \
    LIB_ARCH=arm64; FFMPEG_ARCH=aarch64; MTX_ARCH=arm64v8; \
    else \
    LIB_ARCH=amd64; FFMPEG_ARCH=x86_64; MTX_ARCH=amd64; \
    fi && \
    cd /build \
    && . app/.env \
    && mkdir -p tokens img \
    && curl -SL https://github.com/homebridge/ffmpeg-for-homebridge/releases/latest/download/ffmpeg-alpine-${FFMPEG_ARCH}.tar.gz \
    | tar xzf - -C . \
    && curl -SL https://github.com/bluenviron/mediamtx/releases/download/v${MTX_TAG}/mediamtx_v${MTX_TAG}_linux_${MTX_ARCH}.tar.gz \
    | tar xzf - -C app \
    && cp app/lib/lib.${LIB_ARCH} usr/local/lib/libIOTCAPIs_ALL.so \
    && rm -rf app/*.txt app/lib/  \ 
    && if [ -z "${BUILD_DATE}" ]; then echo BUILD_DATE=$(date) > .build_date; else echo BUILD_DATE=${BUILD_DATE} > .build_date; fi


FROM base
ARG BUILD
ARG GITHUB_SHA
COPY --from=builder /build /
ENV PYTHONUNBUFFERED=1 FLASK_APP=frontend BUILD=$BUILD GITHUB_SHA=$GITHUB_SHA
WORKDIR /app
CMD ["flask", "run", "--host=0.0.0.0"]