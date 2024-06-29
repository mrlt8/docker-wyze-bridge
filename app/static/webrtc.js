const restartPause = 2000;

const parseOffer = (offer) => {
    const ret = {
        iceUfrag: '',
        icePwd: '',
        medias: [],
    };

    offer.split('\r\n').forEach((line) => {
        if (line.startsWith('m=')) {
            ret.medias.push(line.slice('m='.length));
        } else if (ret.iceUfrag === '' && line.startsWith('a=ice-ufrag:')) {
            ret.iceUfrag = line.slice('a=ice-ufrag:'.length);
        } else if (ret.icePwd === '' && line.startsWith('a=ice-pwd:')) {
            ret.icePwd = line.slice('a=ice-pwd:'.length);
        }
    });

    return ret;
};

const generateSdpFragment = (offerData, candidates) => {
    const candidatesByMedia = {};
    for (const candidate of candidates) {
        const mid = candidate.sdpMLineIndex;
        if (!candidatesByMedia.hasOwnProperty(mid)) {
            candidatesByMedia[mid] = [];
        }
        candidatesByMedia[mid].push(candidate);
    }

    let frag = `a=ice-ufrag:${offerData.iceUfrag}\r\na=ice-pwd:${offerData.icePwd}\r\n`;
    let mid = 0;
    for (const media of offerData.medias) {
        if (candidatesByMedia.hasOwnProperty(mid)) {
            frag += `m=${media}\r\na=mid:${mid}\r\n`;

            for (const candidate of candidatesByMedia[mid]) {
                frag += `a=${candidate.candidate}\r\n`;
            }
        }
        mid++;
    }

    return frag;
};

class Receiver {
    constructor(signalJson) {
        if (signalJson.result !== "ok") { return console.error("signaling json not ok"); }
        this.signalJson = signalJson;
        this.whep = !!("whep" in this.signalJson);
        this.restartTimeout = null;
        this.queuedCandidates = [];
        this.ws = null;
        this.pc = null;
        this.sessionUrl = '';
        this.iceConnectionTimer;
        this.start();
    }
    start() {
        if (this.whep) { return this.onOpen(); }
        this.ws = new WebSocket(this.signalJson.signalingUrl);
        this.ws.onopen = () => this.onOpen();
        this.ws.onmessage = (msg) => this.onWsMessage(msg);
        this.ws.onerror = (err) => this.onError(err);
        this.ws.onclose = () => this.onError();
    }

    onOpen() {
        const direction = this.whep ? "sendrecv" : "recvonly";
        this.pc = new RTCPeerConnection({ iceServers: this.signalJson.servers, sdpSemantics: 'unified-plan' });
        this.pc.addTransceiver("video", { direction });
        this.pc.addTransceiver("audio", { direction });
        this.pc.ontrack = (evt) => this.onTrack(evt);
        this.pc.onicecandidate = (evt) => this.onIceCandidate(evt);
        this.pc.oniceconnectionstatechange = () => this.onConnectionStateChange();
        this.pc.createOffer().then((desc) => this.createOffer(desc));
    }
    createOffer(desc) {
        this.pc.setLocalDescription(desc);
        if (!this.whep) { return this.sendToServer("SDP_OFFER", desc); }
        this.offerData = parseOffer(desc.sdp);
        const headers = this.authHeaders();
        headers['Content-Type'] = 'application/sdp'
        fetch(this.signalJson.whep, {
            method: 'POST',
            headers: headers,
            body: desc.sdp,
        })
            .then((res) => {
                if (res.status !== 201) { throw new Error('Bad status code'); }
                this.sessionUrl = new URL(res.headers.get('location'), this.signalJson.whep).toString();
                return res.text();
            })
            .then((sdp) => this.onRemoteDescription(sdp))
            .catch((err) => this.onError(err));
    }
    authHeaders() {
        const server = this.signalJson.servers && this.signalJson.servers.length > 0 ? this.signalJson.servers[0] : null;
        if (server && server.credential && server.username) {
            return { 'Authorization': 'Basic ' + btoa(server.username + ':' + server.credential) };
        }
        return {}
    }

    sendToServer(action, payload) {
        this.ws.send(JSON.stringify({ "action": action, "messagePayload": btoa(JSON.stringify(payload)), "recipientClientId": this.signalJson.ClientId }));
    }
    sendLocalCandidates(candidates) {
        const headers = this.authHeaders();
        headers['Content-Type'] = 'application/trickle-ice-sdpfrag'
        headers['If-Match'] = '*'

        fetch(this.sessionUrl, {
            method: 'PATCH',
            headers: headers,
            body: generateSdpFragment(this.offerData, candidates),
        })
            .then((res) => {
                switch (res.status) {
                    case 204:
                        break;
                    case 404:
                        throw new Error('stream not found');
                    default:
                        throw new Error(`bad status code ${res.status}`);
                }
            })
            .catch((err) => {
                this.onError(err.toString());
            });
    }

    onTrack(event) {
        let vid = document.querySelector(`video[data-cam='${this.signalJson.cam}']`);
        vid.srcObject = event.streams[0];
        vid.autoplay = true;
        vid.play().catch((err) => {
            console.info('play() error:', err);
        });
    }

    onConnectionStateChange() {
        clearTimeout(this.iceConnectionTimer);
        if (this.restartTimeout !== null) { return; }
        switch (this.pc.iceConnectionState) {
            case 'disconnected':
            case 'failed':
                this.onError()
                break;
        }
    }

    onRemoteDescription(sdp) {
        if (this.restartTimeout !== null) { return; }

        this.pc.setRemoteDescription(new RTCSessionDescription({
            type: 'answer',
            sdp,
        }));

        if (this.queuedCandidates.length !== 0) {
            this.sendLocalCandidates(this.queuedCandidates);
            this.queuedCandidates = [];
        }
    }

    onWsMessage(msg) {
        if (this.pc === null || this.ws === null || msg.data === '') { return; }
        const eventData = JSON.parse(msg.data);
        const payload = JSON.parse(atob(eventData.messagePayload));
        switch (eventData.messageType) {
            case 'SDP_OFFER':
            case 'SDP_ANSWER':
                this.pc.setRemoteDescription(new RTCSessionDescription(payload));
                break;
            case 'ICE_CANDIDATE':
                if ('candidate' in payload) {
                    this.pc.addIceCandidate(payload);
                }
                break;
        }
    }

    onIceCandidate(evt) {
        if (this.restartTimeout !== null || evt.candidate === null) { return; }
        if (this.whep) {
            if (this.sessionUrl === '') {
                this.queuedCandidates.push(evt.candidate);
            } else {
                this.sendLocalCandidates([evt.candidate]);
            }
        } else {
            this.sendToServer('ICE_CANDIDATE', evt.candidate);
            if (!this.iceConnectionTimer) {
                this.iceConnectionTimer = setTimeout(() => {
                    if (this.pc.iceConnectionState !== 'start') {
                        this.pc.close();
                        this.onError("ICE connection timeout")
                    }
                }, 30000);
            }
        }
    }
    refreshSignal() {
        fetch(new URL(`signaling/${this.signalJson.cam}?${this.whep ? 'webrtc' : 'kvs'}`, window.location.href))
            .then((resp) => resp.json())
            .then((signalJson) => {
                if (signalJson.result !== "ok") { return console.error("signaling json not ok"); }
                this.signalJson = signalJson;
            });
    }

    onError(err = undefined) {
        if (this.restartTimeout !== null) {
            return;
        }
        if (err !== undefined) { console.error('Error:', err.toString()); }
        clearTimeout(this.iceConnectionTimer);
        this.iceConnectionTimer = null;

        if (this.ws !== null) {
            this.ws.close();
            this.ws = null;
        }
        if (this.pc !== null) {
            this.pc.close();
            this.pc = null;
        }
        const connection = document.getElementById("connection-lost");
        const offline = connection && connection.style.display === "block";

        this.restartTimeout = window.setTimeout(() => {
            this.restartTimeout = null;
            if (offline) {
                this.onError()
            } else {
                this.refreshSignal();
                this.start();
            }
        }, restartPause);

        if (this.sessionUrl !== '' && !offline) {
            fetch(this.sessionUrl, {
                method: 'DELETE',
                headers: this.authHeaders(),
            }).catch(() => { });
        }
        this.sessionUrl = '';
        this.queuedCandidates = [];
    }
};
