const restartPause = 2000;
class Receiver {
    constructor(signalJson) {

        this.signalJson = signalJson;
        this.terminated = false;
        this.ws = null;
        this.pc = null;
        this.restartTimeout = null;
        if (signalJson.result === "ok") {
            this.start();
        } else {
            console.error("signaling json not ok");
        }
    }
    start() {
        this.ws = new WebSocket(this.signalJson.signalingUrl);
        this.ws.onopen = () => this.onOpen();
        this.ws.onerror = () => {
            console.log("ws error");
            if (this.ws === null) {
                return;
            }
            this.ws.close();
            this.ws = null;
        };
        this.ws.onclose = () => {
            console.log("ws closed");
            this.ws = null;
            this.scheduleRestart();
        };
        this.ws.onmessage = (msg) => this.onRemoteDescription(msg);
    }

    onOpen() {
        this.pc = new RTCPeerConnection({
            iceServers: this.signalJson.servers
        });
        this.pc.onicecandidate = (evt) => this.onIceCandidate(evt);
        this.pc.oniceconnectionstatechange = () => {
            if (this.pc === null) {
                return;
            }
            console.log("peer connection state:", this.pc.iceConnectionState);
            switch (this.pc.iceConnectionState) {
                case "disconnected":
                    this.scheduleRestart();
                    break;
                case "failed":
                    this.scheduleRestart();
            }
        };

        this.pc.ontrack = (evt) => {
            console.log("new track: " + evt.track.kind);
            let vid = document.querySelector(`video[data-cam='${this.signalJson.cam}']`);
            vid.srcObject = evt.streams[0];
            vid.oncanplay = () => {
                vid.autoplay = true;
                vid.play();
            };

        };
        const direction = ("rss" in this.signalJson) ? "sendrecv" : "recvonly";
        this.pc.addTransceiver("video", { "direction": direction });
        this.pc.addTransceiver("audio", { "direction": direction });

        this.pc.createOffer()
            .then((desc) => {
                this.pc.setLocalDescription(desc);
                this.sendToServer("SDP_OFFER", desc);
            });

    }
    sendToServer(action, payload) {
        if ("rss" in this.signalJson === false) {
            payload = { "action": action, "messagePayload": btoa(JSON.stringify(payload)), "recipientClientId": this.signalJson.ClientId };
        }
        this.ws.send(JSON.stringify(payload));
    }

    onRemoteDescription(msg) {
        if (this.pc === null || this.ws === null || msg.data === "") { return; }
        let eventData = JSON.parse(msg.data);
        if ("rss" in this.signalJson) {
            if ("sdp" in eventData) {
                this.pc.setRemoteDescription(new RTCSessionDescription(eventData));
            } else if ("candidate" in eventData) {
                this.pc.addIceCandidate(eventData);
            }
        } else {
            let payload = JSON.parse(atob(eventData.messagePayload));
            switch (eventData.messageType) {
                case "SDP_OFFER":
                case "SDP_ANSWER":
                    this.pc.setRemoteDescription(new RTCSessionDescription(payload));
                    break;
                case "ICE_CANDIDATE":
                    if ("candidate" in payload) {
                        this.pc.addIceCandidate(payload);
                    }
            }
        }
    }

    onIceCandidate(evt) {
        if (evt.candidate !== null) {
            this.sendToServer("ICE_CANDIDATE", evt.candidate);
        }
    }

    scheduleRestart() {
        if (this.terminated) {
            return;
        }

        if (this.ws !== null) {
            this.ws.close();
            this.ws = null;
        }

        if (this.pc !== null) {
            this.pc.close();
            this.pc = null;
        }

        this.restartTimeout = window.setTimeout(() => {
            this.restartTimeout = null;
            this.start();
        }, restartPause);
    }
}
