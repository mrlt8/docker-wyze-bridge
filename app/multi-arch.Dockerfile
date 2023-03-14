FROM amd64/python:3.11-slim-buster as base_amd64
FROM arm32v7/python:3.11-slim-buster as base_arm
ARG ARM=1
FROM base_arm AS base_arm64

FROM base_$TARGETARCH as builder
ENV PYTHONUNBUFFERED=1
ARG ARM
ARG LIB_ARCH=${ARM:+arm}
ARG RTSP_ARCH=${ARM:+armv7}
ARG FFMPEG_ARCH=${ARM:+armv7l}
RUN apt-get update \
    && apt-get install -y tar unzip curl jq g++ git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --disable-pip-version-check --prefix=/build/usr/local -r /tmp/requirements.txt
COPY *.lib /tmp/lib/
RUN mkdir -p /build/app /build/tokens /build/img \
    && curl -L https://github.com/homebridge/ffmpeg-for-homebridge/releases/latest/download/ffmpeg-debian-${FFMPEG_ARCH:-x86_64}.tar.gz \
    | tar xzf - -C /build \
    && RTSP_TAG=$(curl -s https://api.github.com/repos/aler9/rtsp-simple-server/releases/latest | jq -r .tag_name) \
    && echo -n $RTSP_TAG > /build/RTSP_TAG \
    && curl -L https://github.com/aler9/rtsp-simple-server/releases/download/${RTSP_TAG}/rtsp-simple-server_${RTSP_TAG}_linux_${RTSP_ARCH:-amd64}.tar.gz \
    | tar xzf - -C /build/app \
    && cp /tmp/lib/${LIB_ARCH:-amd}.lib /build/usr/local/lib/libIOTCAPIs_ALL.so\
    && rm -rf /tmp/*
COPY . /build/app/

FROM base_$TARGETARCH
ENV PYTHONUNBUFFERED=1 RTSP_PROTOCOLS=tcp RTSP_READTIMEOUT=20s RTSP_LOGLEVEL=warn RTSP_WEBRTCICEUDPMUXADDRESS=:8189 SDK_KEY=AQAAADQA6XDOFkuqH88f65by3FGpOiz2Dm6VtmRcohNFh/rK6OII97hoGzIJJv/qRjS3EDx17r7hKtmDA/a6oBLGOTC5Gml7PgFGe26VYBaZqQF34BwIwAMQX7BGsONLW8cqQbdI5Nm560hm50N6cYfT2YpE9ctsv5vP5S49Q5gg864IauaY3NuO1e9ZVOvJyLcIJqJRy95r4fMkTAwXZiQuFDAb FLASK_APP=frontend
COPY --from=builder /build /
WORKDIR /app
CMD [ "flask", "run", "--host=0.0.0.0"]