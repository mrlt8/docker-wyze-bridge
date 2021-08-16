FROM amd64/python:3.9-slim as base_amd64
FROM arm32v7/python:3.9-slim as base_arm
ARG ARM=1
FROM base_arm AS base_arm64

FROM base_$TARGETARCH as builder
ENV PYTHONUNBUFFERED=1
ARG ARM
ARG TUTK_ARCH=${ARM:+Arm11_BCM2835_4.8.3}
ARG RTSP_ARCH=${ARM:+armv7}
ARG FFMPEG_ARCH=${ARM:+armhf}
RUN apt-get update \
    && apt-get install -y tar xz-utils unzip curl jq g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --disable-pip-version-check --prefix=/build/usr/local https://github.com/mrlt8/wyzecam/archive/refs/heads/main.zip supervisor requests
ADD https://johnvansickle.com/ffmpeg/builds/ffmpeg-git-${FFMPEG_ARCH:-amd64}-static.tar.xz /tmp/ffmpeg.tar.xz
ADD https://github.com/miguelangel-nubla/videoP2Proxy/archive/refs/heads/master.zip /tmp/tutk.zip
RUN mkdir -p /build/app /build/tokens \
    && RTSP_TAG=$(curl -s https://api.github.com/repos/aler9/rtsp-simple-server/releases/latest | jq -r .tag_name) \
    && curl -L https://github.com/aler9/rtsp-simple-server/releases/download/${RTSP_TAG}/rtsp-simple-server_${RTSP_TAG}_linux_${RTSP_ARCH:-amd64}.tar.gz \
    | tar xzf - -C /build/app \
    && unzip -j /tmp/tutk.zip */lib/Linux/${TUTK_ARCH:-x64}/*.a -d /tmp/tutk/ \
    && g++ -fpic -shared -Wl,--whole-archive /tmp/tutk/libAVAPIs.a /tmp/tutk/libIOTCAPIs.a -Wl,--no-whole-archive -o /build/usr/local/lib/libIOTCAPIs_ALL.so \
    && tar --strip-components=1 -C /build/usr/local/bin -xf /tmp/ffmpeg.tar.xz --wildcards '*ffmpeg' \
    && rm -rf /tmp/*

FROM base_$TARGETARCH
ENV PYTHONUNBUFFERED=1 RTSP_PROTOCOLS=tcp
COPY --from=builder /build /
COPY wyze_bridge.py supervisord.conf /app/
CMD [ "supervisord", "-c", "/app/supervisord.conf" ]