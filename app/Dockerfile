ARG ARM
ARG ARCH=${ARM:+arm32v7}
FROM ${ARCH:-amd64}/python:3.9-slim-buster as base

FROM base as builder
ENV PYTHONUNBUFFERED=1
ARG ARM
ARG TUTK_ARCH=${ARM:+Arm11_BCM2835_4.8.3}
ARG RTSP_ARCH=${ARM:+armv7}
ARG FFMPEG_ARCH=${ARM:+armv7l}
RUN apt-get update \
    && apt-get install -y tar unzip curl jq g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --disable-pip-version-check --prefix=/build/usr/local mintotp paho-mqtt requests https://github.com/mrlt8/wyzecam/archive/refs/heads/main.zip
ADD https://github.com/miguelangel-nubla/videoP2Proxy/archive/refs/heads/master.zip /tmp/tutk.zip
RUN mkdir -p /build/app /build/tokens /build/img \
    && curl -L https://github.com/homebridge/ffmpeg-for-homebridge/releases/latest/download/ffmpeg-debian-${FFMPEG_ARCH:-x86_64}.tar.gz \
    | tar xzf - -C /build \
    && RTSP_TAG=$(curl -s https://api.github.com/repos/aler9/rtsp-simple-server/releases/latest | jq -r .tag_name) \
    && echo -n $RTSP_TAG > /build/RTSP_TAG \
    && curl -L https://github.com/aler9/rtsp-simple-server/releases/download/${RTSP_TAG}/rtsp-simple-server_${RTSP_TAG}_linux_${RTSP_ARCH:-amd64}.tar.gz \
    | tar xzf - -C /build/app \
    && unzip -j /tmp/tutk.zip */lib/Linux/${TUTK_ARCH:-x64}/*.a -d /tmp/tutk/ \
    && g++ -fpic -shared -Wl,--whole-archive /tmp/tutk/libAVAPIs.a /tmp/tutk/libIOTCAPIs.a -Wl,--no-whole-archive -o /build/usr/local/lib/libIOTCAPIs_ALL.so \
    && rm -rf /tmp/*
COPY *.py /build/app/

FROM base
ENV PYTHONUNBUFFERED=1 RTSP_PROTOCOLS=tcp RTSP_READTIMEOUT=30s RTSP_READBUFFERCOUNT=2048 RTSP_LOGLEVEL=warn
COPY --from=builder /build /
CMD [ "python3", "/app/wyze_bridge.py" ]