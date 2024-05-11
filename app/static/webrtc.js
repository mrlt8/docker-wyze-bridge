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
        this.eTag = '';
        this.start();
    }
    start() {
        if (this.whep) { return this.onOpen(); }
        this.ws = new WebSocket(this.signalJson.signalingUrl);
        this.ws.onopen = () => this.onOpen();
        this.ws.onmessage = (msg) => this.onWsMessage(msg);
        this.ws.onerror = (err) => this.onClose(err);
        this.ws.onclose = () => this.onClose();
    }

    onClose(err = null) {
        if (err) { console.error('Error:', err); }
        if (this.ws !== null) {
            this.ws.close();
            this.ws = null;
        }
        this.scheduleRestart();
    }
    onOpen() {
        const direction = this.whep ? "sendrecv" : "recvonly";

        this.pc = new RTCPeerConnection({ iceServers: this.signalJson.servers });
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

        console.log('Sending offer');
        this.offerData = parseOffer(desc.sdp);
        let headers = { 'Content-Type': 'application/sdp' };

        const server = this.signalJson.servers && this.signalJson.servers.length > 0 ? this.signalJson.servers[0] : null;
        if (server && server.credential && server.username) {
            headers['Authorization'] = 'Basic ' + btoa(server.username + ':' + server.credential);
        }
        fetch(this.signalJson.whep, {
            method: 'POST',
            headers: headers,
            body: desc.sdp,
        })
            .then((res) => {
                if (res.status !== 201) { throw new Error('Bad status code'); }
                this.eTag = res.headers.get('ETag');
                return res.text();
            })
            .then((sdp) => this.onRemoteDescription(sdp))
            .catch((err) => this.onClose(err));
    }
    sendToServer(action, payload) {
        this.ws.send(JSON.stringify({ "action": action, "messagePayload": btoa(JSON.stringify(payload)), "recipientClientId": this.signalJson.ClientId }));
    }
    sendLocalCandidates(candidates) {
        fetch(this.signalJson.whep, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/trickle-ice-sdpfrag',
                'If-Match': this.eTag,
            },
            body: generateSdpFragment(this.offerData, candidates),
        })
            .then((res) => {
                if (res.status !== 204) {
                    throw new Error('bad status code');
                }
            })
            .catch((err) => {
                console.error('error: ' + err);
                this.scheduleRestart();
            });
    }

    onTrack(event) {
        console.log("new track: " + event.track.kind);
        let vid = document.querySelector(`video[data-cam='${this.signalJson.cam}']`);
        vid.srcObject = event.streams[0];
        vid.oncanplay = () => {
            vid.autoplay = true;
            vid.play();
        };

    }

    onConnectionStateChange() {
        if (this.restartTimeout !== null) { return; }

        console.log('Peer connection state:', this.pc.iceConnectionState);
        switch (this.pc.iceConnectionState) {
            case 'disconnected':
            case 'failed':
                this.scheduleRestart();
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
            if (this.eTag === '') {
                this.queuedCandidates.push(evt.candidate);
            } else {
                this.sendLocalCandidates([evt.candidate]);
            }
        } else {
            this.sendToServer('ICE_CANDIDATE', evt.candidate);
        }
    }

    scheduleRestart() {
        if (this.restartTimeout !== null) {
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
        this.eTag = '';
        this.queuedCandidates = [];
    }
}