package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"sync"
	"time"

	"github.com/gorilla/mux"
	"github.com/gorilla/websocket"
	"github.com/pion/interceptor"
	"github.com/pion/webrtc/v3"
)

type WebRTCStream struct {
	peerConnection    *webrtc.PeerConnection
	wsConn            *websocket.Conn
	remoteDescription *webrtc.SessionDescription
	etag              string // Add ETag field
	videoTrack        *webrtc.TrackLocalStaticRTP
}

type ICEServer struct {
	URL        string `json:"url"`
	Username   string `json:"username"`
	Credential string `json:"credential"`
}

type WebRTCConfig struct {
	SignalingURL string      `json:"signaling_url"`
	ICEServers   []ICEServer `json:"ice_servers"`
}

var streams = make(map[string]*WebRTCStream)
var streamsMu sync.Mutex

func main() {

	r := mux.NewRouter()

	r.HandleFunc("/whep/{streamID}", whepHandler).Methods("GET", "OPTIONS", "POST")
	r.HandleFunc("/websocket/{streamID}", websocketHandler).Methods("GET", "POST")

	go func() {
		fmt.Println("[WHEP_PROXY] Listening on :8080")
		err := http.ListenAndServe(":8080", r)
		if err != nil {
			panic(err)
		}
	}()

	sigchan := make(chan os.Signal, 1)
	signal.Notify(sigchan, os.Interrupt)
	<-sigchan

	fmt.Println("[WHEP_PROXY] Exiting.")

	streamsMu.Lock()
	defer streamsMu.Unlock()
	for streamID, stream := range streams {
		cleanupStream(streamID, stream)
	}
}

func cleanupStream(streamID string, stream *WebRTCStream) {
	fmt.Printf("[WHEP_PROXY] Cleaning up stream %s\n", streamID)
	if stream.wsConn != nil {
		err := stream.wsConn.Close()
		if err != nil {
			fmt.Printf("[WHEP_PROXY] Error closing WebSocket for stream %s: %v\n", streamID, err)
		} else {
			fmt.Printf("[WHEP_PROXY] WebSocket closed for stream %s\n", streamID)
		}
	}
	if stream.peerConnection != nil {
		err := stream.peerConnection.Close()
		if err != nil {
			fmt.Printf("[WHEP_PROXY] Error closing PeerConnection for stream %s: %v\n", streamID, err)
		} else {
			fmt.Printf("[WHEP_PROXY] PeerConnection closed for stream %s\n", streamID)
		}
	}
	delete(streams, streamID)
	fmt.Printf("[WHEP_PROXY] Stream %s cleaned up\n", streamID)
}

func websocketHandler(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	streamID := vars["streamID"]

	var config WebRTCConfig
	var wsURL string
	fmt.Println(r.Body)
	// Parse configuration if POST request
	if r.Method == "POST" {
		if err := json.NewDecoder(r.Body).Decode(&config); err != nil {
			http.Error(w, "Invalid JSON configuration", http.StatusBadRequest)
			return
		}
		fmt.Println("[WHEP_PROXY] Config:", config)
		// Use signaling URL from config if provided
		if config.SignalingURL == "" {
			panic("Signaling URL is required")
		}
	}

	// Parse the URL to unescape any escaped characters
	parsedURL, err := url.Parse(config.SignalingURL)
	if err != nil {
		fmt.Printf("[WHEP_PROXY] Failed to parse WebSocket URL: %v\n", err)
		http.Error(w, fmt.Sprintf("Failed to parse WebSocket URL: %v", err), http.StatusInternalServerError)
		return
	}
	wsURL = parsedURL.String()

	// Connect to WebSocket
	dialer := websocket.Dialer{}
	fmt.Printf("[WHEP_PROXY] Attempting to connect to WebSocket: %s\n", wsURL) // Log connection attempt

	conn, resp, err := dialer.Dial(wsURL, nil)
	if err != nil {
		fmt.Println("[WHEP_PROXY] Response:", resp)
		bodyBytes := make([]byte, 1024)
		n, err := resp.Body.Read(bodyBytes)
		if err != nil && err != io.EOF {
			fmt.Println("Error reading response body:", err)
		} else {
			fmt.Println("response body", string(bodyBytes[:n]))
		}
		fmt.Println("conn:", conn)
		fmt.Printf("[WHEP_PROXY] Failed to connect to WebSocket: %v\n", err) // Log connection failure
		http.Error(w, fmt.Sprintf("Failed to connect to WebSocket: %v", err), http.StatusInternalServerError)
		return
	}
	fmt.Println("[WHEP_PROXY] Successfully connected to WebSocket") // Log successful connection

	streamsMu.Lock()
	defer streamsMu.Unlock()

	stream, ok := streams[streamID]
	if !ok {

		// Convert ICE servers configuration
		iceServers := []webrtc.ICEServer{}
		for _, server := range config.ICEServers {
			iceServers = append(iceServers, webrtc.ICEServer{
				URLs:       []string{server.URL},
				Username:   server.Username,
				Credential: server.Credential,
			})
		}

		// If no ICE servers provided, use a default STUN server
		if len(iceServers) == 0 {
			iceServers = []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			}
		}

		// Create media engine
		m := &webrtc.MediaEngine{}

		// Register RTP header extensions
		for _, extension := range []string{
			"urn:ietf:params:rtp-hdrext:sdes:mid",
			"urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id",
			"urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id",
		} {
			if err := m.RegisterHeaderExtension(webrtc.RTPHeaderExtensionCapability{URI: extension}, webrtc.RTPCodecTypeVideo); err != nil {
				fmt.Printf("[WHEP_PROXY] Error registering extension %s: %v\n", extension, err)
				return
			}
			if err := m.RegisterHeaderExtension(webrtc.RTPHeaderExtensionCapability{URI: extension}, webrtc.RTPCodecTypeAudio); err != nil {
				fmt.Printf("[WHEP_PROXY] Error registering extension %s: %v\n", extension, err)
				return
			}
		}

		// Register H264 codec
		if err := m.RegisterCodec(webrtc.RTPCodecParameters{
			RTPCodecCapability: webrtc.RTPCodecCapability{
				MimeType:    webrtc.MimeTypeH264,
				ClockRate:   90000,
				Channels:    0,
				SDPFmtpLine: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f",
				RTCPFeedback: []webrtc.RTCPFeedback{
					{Type: "nack", Parameter: ""},
				},
			},
			PayloadType: 102,
		}, webrtc.RTPCodecTypeVideo); err != nil {
			fmt.Println("[WHEP_PROXY] Error registering H264 codec:", err)
			return
		}

		// Register PCMU codec
		if err := m.RegisterCodec(webrtc.RTPCodecParameters{
			RTPCodecCapability: webrtc.RTPCodecCapability{
				MimeType:  "audio/PCMU",
				ClockRate: 8000,
				Channels:  1,
				RTCPFeedback: []webrtc.RTCPFeedback{
					{Type: "nack", Parameter: ""},
				},
			},
			PayloadType: 0,
		}, webrtc.RTPCodecTypeAudio); err != nil {
			fmt.Println("[WHEP_PROXY] Error registering PCMU codec:", err)
			return
		}
		interceptorRegistry := &interceptor.Registry{}
		// Use the default set of Interceptors
		if err := webrtc.RegisterDefaultInterceptors(m, interceptorRegistry); err != nil {
			panic(err)
		}

		// Create the API object with the MediaEngine
		peerConnection, err := webrtc.NewAPI(
			webrtc.WithMediaEngine(m),
			webrtc.WithInterceptorRegistry(interceptorRegistry),
		).NewPeerConnection(webrtc.Configuration{
			ICEServers: iceServers,
		})
		if err != nil {
			fmt.Println("[WHEP_PROXY] Error creating peer connection:", err)
			return
		}

		stream = &WebRTCStream{
			peerConnection: peerConnection,
			wsConn:         conn, // Store the WebSocket connection
		}
		if stream.videoTrack, err = webrtc.NewTrackLocalStaticRTP(webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264}, "video", "pion"); err != nil {
			panic(err)
		}
		streams[streamID] = stream

		if _, err = peerConnection.AddTransceiverFromKind(webrtc.RTPCodecTypeVideo); err != nil {
			panic(err)
		}

		// Create offer
		offer, err := peerConnection.CreateOffer(nil)
		if err != nil {
			fmt.Println("[WHEP_PROXY] Error creating offer:", err)
			return
		}

		// Set local description
		err = peerConnection.SetLocalDescription(offer)
		if err != nil {
			fmt.Println("[WHEP_PROXY] Error setting local description:", err)
			return
		}

		peerConnection.OnICECandidate(func(c *webrtc.ICECandidate) {
			if c != nil {
				candidate := c.ToJSON()
				fmt.Printf("[WHEP_PROXY] New ICE candidate: %v\n", candidate)
				if err := conn.WriteJSON(map[string]interface{}{"type": "iceCandidate", "candidate": candidate}); err != nil {
					fmt.Println("[WHEP_PROXY] Error sending ICE candidate:", err)
					return
				}
			}
		})

		// Gather ICE candidates
		gatherComplete := webrtc.GatheringCompletePromise(peerConnection)

		// Wait for ICE gathering to complete
		<-gatherComplete
		fmt.Println("[WHEP_PROXY] ICE gathering complete")

		// Send offer through WebSocket
		offerJSON := map[string]interface{}{"type": "offer", "sdp": offer.SDP}
		offerJSONBytes, _ := json.Marshal(offerJSON)
		offerBase64 := base64.StdEncoding.EncodeToString(offerJSONBytes)

		if err := conn.WriteJSON(map[string]interface{}{
			"action":            "SDP_OFFER",
			"messagePayload":    offerBase64,
			"recipientClientId": "ada06f08-87f4-4e13-b699-e82db8517ae5",
		}); err != nil {
			fmt.Println("[WHEP_PROXY] Error sending offer:", err)
			return
		}

		peerConnection.OnTrack(func(track *webrtc.TrackRemote, receiver *webrtc.RTPReceiver) {
			fmt.Println("[WHEP_PROXY] Got track:", track.ID(), track.StreamID())

			for {
				pkt, _, err := track.ReadRTP()
				if err != nil {
					panic(err)
				}

				if err = stream.videoTrack.WriteRTP(pkt); err != nil {
					panic(err)
				}
			}
		})

		// Handle incoming messages from the WebSocket (offer/answer)
		go func() {
			for {
				var msg map[string]interface{}
				if _, _, err := conn.ReadMessage(); err != nil {
					fmt.Printf("[WHEP_PROXY] WebSocket closed: %v\n", err)
					streamsMu.Lock()
					stream.wsConn.Close()
					streamsMu.Unlock()
					return
				}
				err := conn.ReadJSON(&msg)
				if len(msg) == 0 && err == nil {
					continue
				}

				if err != nil {
					if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
						fmt.Printf("[WHEP_PROXY] error: %v", err)
					}
					fmt.Println("[WHEP_PROXY] Error reading JSON:", err)
					continue
				}

				msgType, ok := msg["messageType"].(string)
				if !ok {
					fmt.Println("[WHEP_PROXY] Invalid message format")
					continue
				}

				switch msgType {
				case "SDP_ANSWER":
					var answer webrtc.SessionDescription
					payload := msg["messagePayload"].(string)
					decoded, err := base64.StdEncoding.DecodeString(payload)
					if err != nil {
						fmt.Println("[WHEP_PROXY] Error decoding base64:", err)
						continue
					}
					answerSDP := string(decoded)

					if err := json.Unmarshal([]byte(answerSDP), &answer); err != nil {
						fmt.Println("[WHEP_PROXY] Error unmarshaling answer:", err)
						continue
					}
					if err := stream.peerConnection.SetRemoteDescription(answer); err != nil {
						fmt.Println("[WHEP_PROXY] Error setting remote description:", err)
						continue
					}
					stream.remoteDescription = &answer

				case "ICE_CANDIDATE":
					var candidate webrtc.ICECandidateInit
					payload := msg["messagePayload"].(string)
					decoded, err := base64.StdEncoding.DecodeString(payload)
					if err != nil {
						fmt.Println("[WHEP_PROXY] Error decoding base64:", err)
						continue
					}
					var candidateMap map[string]interface{}
					if err := json.Unmarshal(decoded, &candidateMap); err != nil {
						fmt.Println("[WHEP_PROXY] Error unmarshaling candidate:", err)
						continue
					}

					candidateString, ok := candidateMap["candidate"].(string)
					if !ok {
						fmt.Println("[WHEP_PROXY] Invalid candidate format")
						continue
					}
					candidate.Candidate = candidateString

					sdpMid, ok := candidateMap["sdpMid"].(string)
					if ok {
						candidate.SDPMid = &sdpMid
					}

					if mLineIndex, ok := candidateMap["sdpMLineIndex"].(float64); ok {
						uint16Val := uint16(mLineIndex)
						candidate.SDPMLineIndex = &uint16Val
					}

					if err := stream.peerConnection.AddICECandidate(candidate); err != nil {
						fmt.Println("[WHEP_PROXY] Error adding ICE candidate:", err)
						continue
					}

				default:
					fmt.Println("[WHEP_PROXY] Unknown message type:", msgType)
				}
			}
		}()

	} else {
		stream.wsConn = conn // Update websocket connection
	}

}

func whepHandler(w http.ResponseWriter, r *http.Request) {
	// Log incoming request
	fmt.Printf("[WHEP_PROXY] %s %s from %s\n", r.Method, r.URL.Path, r.RemoteAddr)
	fmt.Printf("[WHEP_PROXY] Headers: %v\n", r.Header)

	vars := mux.Vars(r)
	streamID := vars["streamID"]
	fmt.Printf("[WHEP_PROXY] Stream ID: %s\n", streamID)

	streamsMu.Lock()
	defer streamsMu.Unlock()

	stream, ok := streams[streamID]
	if !ok {
		fmt.Printf("[WHEP_PROXY] Error: Stream %s not found\n", streamID)
		http.Error(w, fmt.Sprintf("Stream %s not found", streamID), http.StatusNotFound)
		return
	}

	switch r.Method {
	case http.MethodOptions:
		w.Header().Set("Content-Type", "application/sdp")
		fmt.Printf("[WHEP_PROXY] Sending OPTIONS response for stream %s\n", streamID)
		fmt.Fprint(w, "")

	case http.MethodGet:
		fmt.Fprint(w, "")

	case http.MethodPost:
		contentType := r.Header.Get("Content-Type")
		if contentType != "application/sdp" {
			fmt.Printf("[WHEP_PROXY] Error: Invalid Content-Type %s\n", contentType)
			http.Error(w, "Content-Type must be application/sdp", http.StatusUnsupportedMediaType)
			return
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			fmt.Printf("[WHEP_PROXY] Error reading request body: %v\n", err)
			http.Error(w, "Error reading request body", http.StatusBadRequest)
			return
		}
		offer := string(body)
		fmt.Printf("[WHEP_PROXY] Received POST offer for stream %s\n", streamID)

		peerConnectionConfiguration := webrtc.Configuration{}
		peerConnection, err := webrtc.NewPeerConnection(peerConnectionConfiguration)
		if err != nil {
			cleanupStream(streamID, stream)
			panic(err)
		}

		rtpSender, err := peerConnection.AddTrack(stream.videoTrack)
		if err != nil {
			panic(err)
		}

		go func() {
			rtcpBuf := make([]byte, 1500)
			for {
				if _, _, rtcpErr := rtpSender.Read(rtcpBuf); rtcpErr != nil {
					return
				}
			}
		}()

		peerConnection.OnICEConnectionStateChange(func(connectionState webrtc.ICEConnectionState) {
			fmt.Printf("[WHEP_PROXY] ICE Connection State has changed: %s\n", connectionState.String())

			if connectionState == webrtc.ICEConnectionStateFailed {
				_ = peerConnection.Close()
			}
		})

		// Set the remote description first
		err = peerConnection.SetRemoteDescription(webrtc.SessionDescription{
			Type: webrtc.SDPTypeOffer,
			SDP:  offer,
		})
		if err != nil {
			fmt.Printf("[WHEP_PROXY] Error setting remote description: %v\n", err)
			http.Error(w, "Error setting remote description", http.StatusInternalServerError)
			return
		}
		gatherComplete := webrtc.GatheringCompletePromise(peerConnection)
		// Create a new SDP answer
		answer, err := peerConnection.CreateAnswer(&webrtc.AnswerOptions{})

		if err != nil {
			fmt.Printf("[WHEP_PROXY] Error creating SDP answer: %v\n", err)
			http.Error(w, "Error creating SDP answer", http.StatusInternalServerError)
			return
		} else if err = peerConnection.SetLocalDescription(answer); err != nil {
			fmt.Printf("[WHEP_PROXY] Error setting local description: %v\n", err)
			http.Error(w, "Error setting local description", http.StatusInternalServerError)
			return
		}

		// Generate ETag if not exists
		if stream.etag == "" {
			stream.etag = fmt.Sprintf("\"%x\"", time.Now().UnixNano())
		}
		<-gatherComplete
		// Set response headers
		w.Header().Set("Content-Type", "application/sdp")
		w.Header().Set("Location", fmt.Sprintf("/whep/%s", streamID))
		w.Header().Set("ETag", stream.etag)
		w.WriteHeader(http.StatusCreated) // 201

		// Filter out application media section before sending
		fmt.Printf("[WHEP_PROXY] Sending POST response (answer) for stream %s with ETag %s\n", streamID, stream.etag)
		fmt.Fprint(w, peerConnection.LocalDescription().SDP)

	default:
		fmt.Printf("[WHEP_PROXY] Error: Method %s not allowed\n", r.Method)
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}
