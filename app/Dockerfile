FROM python:3.9-slim
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install ffmpeg tar unzip g++ -y && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip3 install requests wyzecam wyze_sdk supervisor
ADD https://github.com/nblavoie/wyzecam-api/raw/master/wyzecam-sdk/TUTK_IOTC_Platform_14W42P1.zip /tmp/tutk.zip
RUN unzip /tmp/tutk.zip -d /tmp/tutk/ && cd /tmp/tutk/Lib/Linux/x64/ && g++ -fpic -shared -Wl,--whole-archive libAVAPIs.a libIOTCAPIs.a -Wl,--no-whole-archive -o libIOTCAPIs_ALL.so && cp libIOTCAPIs_ALL.so /usr/local/lib/ && rm -rf /tmp/*
ADD https://github.com/aler9/rtsp-simple-server/releases/download/v0.16.4/rtsp-simple-server_v0.16.4_linux_amd64.tar.gz /tmp/rtsp.tar.gz
RUN mkdir -p /app /tokens && tar -xzf /tmp/rtsp.tar.gz -C /app && rm -rf /tmp/*
COPY wyze_bridge.py supervisord.conf /app/
CMD ["supervisord", "-c", "/app/supervisord.conf" ]