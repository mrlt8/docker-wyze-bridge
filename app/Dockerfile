ARG ARM
FROM ${ARM:+arm32v7/}python:3.9-slim as base

FROM base as builder
ENV PYTHONUNBUFFERED=1
ARG ARM
ARG TUTK_ARCH=${ARM:+Arm11_BCM2835_4.8.3}
ARG RTSP_ARCH=${ARM:+armv7}
ARG FFMPEG_ARCH=${ARM:+armhf}
RUN apt-get update &&\
    apt-get install -y tar xz-utils unzip g++ &&\
    apt-get clean &&\
    rm -rf /var/lib/apt/lists/*

# TEMP Patch START
# RUN pip3 install --no-warn-script-location --prefix=/build requests wyzecam wyze_sdk supervisor
ADD https://github.com/mrlt8/wyzecam/archive/refs/heads/patch-1.zip /tmp/wyzecam.zip
RUN unzip /tmp/wyzecam.zip -d /tmp/ &&\
    cd /tmp/wyzecam-patch-1 &&\
    pip3 install --no-warn-script-location --prefix=/build . requests wyze_sdk supervisor &&\
    sed -i '/x-api-key/a \            '\''user-agent'\''\: '\''wyze_ios_2.22.32'\'',' /build/lib/python3.9/site-packages/wyze_sdk/service/auth_service.py
# TEMP Patch END

ADD https://johnvansickle.com/ffmpeg/builds/ffmpeg-git-${FFMPEG_ARCH:-amd64}-static.tar.xz /tmp/ffmpeg.tar.xz
ADD https://github.com/miguelangel-nubla/videoP2Proxy/archive/refs/heads/master.zip /tmp/tutk.zip
ADD https://github.com/aler9/rtsp-simple-server/releases/download/v0.16.4/rtsp-simple-server_v0.16.4_linux_${RTSP_ARCH:-amd64}.tar.gz /tmp/rtsp.tar.gz
RUN mkdir -p /app &&\
    unzip -j /tmp/tutk.zip */lib/Linux/${TUTK_ARCH:-x64}/*.a -d /tmp/tutk/ &&\
    cd /tmp/tutk &&\
    g++ -fpic -shared -Wl,--whole-archive libAVAPIs.a libIOTCAPIs.a -Wl,--no-whole-archive -o /build/lib/libIOTCAPIs_ALL.so &&\
    tar -xzf /tmp/rtsp.tar.gz -C /app &&\
    tar --strip-components=1 -C /build/bin -xf /tmp/ffmpeg.tar.xz --wildcards '*ffmpeg' &&\
    rm -rf /tmp/*

FROM base
ENV PYTHONUNBUFFERED=1
COPY --from=builder /build /usr/local
COPY --from=builder /app /app
RUN mkdir -p /tokens 
COPY wyze_bridge.py supervisord.conf /app/
CMD ["supervisord", "-c", "/app/supervisord.conf" ]