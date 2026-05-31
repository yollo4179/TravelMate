import WebsocketService from './WebsocketService'

export class WebRTCManager {
  constructor(
    roomId,
    currentUserUid,
    localVideoElement,
    onRemoteStreamAdded,
    onRemoteStreamRemoved,
  ) {
    this.roomId = roomId
    this.currentUserUid = currentUserUid
    this.localVideoElement = localVideoElement
    this.onRemoteStreamAdded = onRemoteStreamAdded // callback: (peerUid, stream)
    this.onRemoteStreamRemoved = onRemoteStreamRemoved // callback: (peerUid)

    this.localStream = null
    this.peerConnections = {} // peerUid -> RTCPeerConnection
    this.subscription = null

    // Ice Servers configuration (using public STUN servers for now)
    this.rtcConfig = {
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' },
      ],
    }
  }

  // 1. Initialize local media (Camera/Mic)
  async initLocalStream() {
    try {
      this.localStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      })
      if (this.localVideoElement) {
        this.localVideoElement.srcObject = this.localStream
      }
      console.log('Local stream initialized successfully')
      return this.localStream
    } catch (error) {
      console.error('Error accessing media devices:', error)
      throw error
    }
  }

  // 2. Connect to signaling channel and start exchange
  joinRoom() {
    const destination = `/topic/group/${this.roomId}/channel/1` // Using channel 1 as default for room

    // Subscribe to signaling messages
    this.subscription = WebsocketService.subscribe(destination, (message) => {
      this.handleSignalingMessage(message)
    })

    // Broadcast "join" message to the room to notify others of our presence
    WebsocketService.send(`/app/group/${this.roomId}/channel/1/signal`, {
      type: 'join',
      senderId: this.currentUserUid,
      sdp: null,
      candidate: null,
    })
  }

  // 3. Handle incoming signaling messages
  async handleSignalingMessage(message) {
    const { type, senderId, sdp, candidate } = message

    // Ignore our own messages
    if (senderId === this.currentUserUid) return

    console.log(`Received signal: ${type} from ${senderId}`)

    if (type === 'join') {
      // A new user has joined. As the existing peer, we will initiate the connection.
      // We create a peer connection and send an Offer to the joiner.
      await this.initiateCall(senderId)
    } else if (type === 'offer') {
      // Check if this offer is meant for us
      if (sdp && sdp.receiverId === this.currentUserUid) {
        await this.handleOffer(senderId, sdp)
      }
    } else if (type === 'answer') {
      // Check if this answer is meant for us
      if (sdp && sdp.receiverId === this.currentUserUid) {
        await this.handleAnswer(senderId, sdp)
      }
    } else if (type === 'candidate') {
      // Check if this candidate is meant for us
      if (candidate && candidate.receiverId === this.currentUserUid) {
        await this.handleIceCandidate(senderId, candidate)
      }
    }
  }

  // 4. Create peer connection for a peer
  createPeerConnection(peerUid) {
    if (this.peerConnections[peerUid]) {
      return this.peerConnections[peerUid]
    }

    const pc = new RTCPeerConnection(this.rtcConfig)
    this.peerConnections[peerUid] = pc

    // Add local tracks to peer connection
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => {
        pc.addTrack(track, this.localStream)
      })
    }

    // ICE candidate gathering
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        WebsocketService.send(`/app/group/${this.roomId}/channel/1/signal`, {
          type: 'candidate',
          senderId: this.currentUserUid,
          sdp: null,
          candidate: {
            candidate: event.candidate.candidate,
            sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
            receiverId: peerUid,
          },
        })
      }
    }

    // Connection state change logging
    pc.onconnectionstatechange = () => {
      console.log(`Connection state with ${peerUid}: ${pc.connectionState}`)
      if (
        pc.connectionState === 'disconnected' ||
        pc.connectionState === 'failed' ||
        pc.connectionState === 'closed'
      ) {
        this.closeConnection(peerUid)
      }
    }

    // Remote stream track added
    pc.ontrack = (event) => {
      console.log(`Received remote track from ${peerUid}`)
      if (event.streams && event.streams[0]) {
        this.onRemoteStreamAdded(peerUid, event.streams[0])
      }
    }

    return pc
  }

  // 5. Initiate a call (create Offer)
  async initiateCall(peerUid) {
    console.log(`Initiating WebRTC call to peer: ${peerUid}`)
    const pc = this.createPeerConnection(peerUid)

    try {
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      WebsocketService.send(`/app/group/${this.roomId}/channel/1/signal`, {
        type: 'offer',
        senderId: this.currentUserUid,
        sdp: {
          type: 'offer',
          sdp: offer.sdp,
          receiverId: peerUid,
        },
        candidate: null,
      })
    } catch (error) {
      console.error(`Error creating offer for ${peerUid}:`, error)
    }
  }

  // 6. Handle received Offer
  async handleOffer(peerUid, sdpPayload) {
    console.log(`Handling offer from peer: ${peerUid}`)
    const pc = this.createPeerConnection(peerUid)

    try {
      await pc.setRemoteDescription(
        new RTCSessionDescription({
          type: 'offer',
          sdp: sdpPayload.sdp,
        }),
      )

      const answer = await pc.createAnswer()
      await pc.setLocalDescription(answer)

      WebsocketService.send(`/app/group/${this.roomId}/channel/1/signal`, {
        type: 'answer',
        senderId: this.currentUserUid,
        sdp: {
          type: 'answer',
          sdp: answer.sdp,
          receiverId: peerUid,
        },
        candidate: null,
      })
    } catch (error) {
      console.error(`Error handling offer from ${peerUid}:`, error)
    }
  }

  // 7. Handle received Answer
  async handleAnswer(peerUid, sdpPayload) {
    console.log(`Handling answer from peer: ${peerUid}`)
    const pc = this.peerConnections[peerUid]
    if (!pc) return

    try {
      await pc.setRemoteDescription(
        new RTCSessionDescription({
          type: 'answer',
          sdp: sdpPayload.sdp,
        }),
      )
    } catch (error) {
      console.error(`Error setting remote description for ${peerUid}:`, error)
    }
  }

  // 8. Handle received ICE candidate
  async handleIceCandidate(peerUid, candidatePayload) {
    const pc = this.peerConnections[peerUid]
    if (!pc) return

    try {
      await pc.addIceCandidate(
        new RTCIceCandidate({
          candidate: candidatePayload.candidate,
          sdpMid: candidatePayload.sdpMid,
          sdpMLineIndex: candidatePayload.sdpMLineIndex,
        }),
      )
    } catch (error) {
      console.error(`Error adding ICE candidate for ${peerUid}:`, error)
    }
  }

  // 9. Close a specific connection
  closeConnection(peerUid) {
    if (this.peerConnections[peerUid]) {
      this.peerConnections[peerUid].close()
      delete this.peerConnections[peerUid]
      this.onRemoteStreamRemoved(peerUid)
      console.log(`Closed peer connection with: ${peerUid}`)
    }
  }

  // 10. Clean up everything when leaving
  leaveRoom() {
    console.log('Leaving room and cleaning up WebRTC connections')

    // Stop local tracks
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => track.stop())
      this.localStream = null
    }

    // Close all peer connections
    Object.keys(this.peerConnections).forEach((peerUid) => {
      this.closeConnection(peerUid)
    })

    // Unsubscribe from websocket channel
    if (this.subscription) {
      const destination = `/topic/group/${this.roomId}/channel/1`
      WebsocketService.unsubscribe(destination)
      this.subscription = null
    }
  }
}
