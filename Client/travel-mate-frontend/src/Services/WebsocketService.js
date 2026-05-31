import { Client } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import { API_CONFIG } from '../utils/Constants'
//서버와의 통신용임 Signaling의 역할을 수행
class WebsocketService {
  constructor() {
    this.client = null
    this.connected = false
    this.subscriptions = {} //내가 들어가 있는 채팅방 목록
  }

  //WebSocketService 만들고 connect 를 일단 호출해서 연결시도 , callBack은 내가 구현 ... 스톰프 컨트롤렁

  connect(token, onConnectCallback, onErrorCallback) {
    if (this.client && this.connected) {
      if (onConnectCallback) onConnectCallback()
      return
    }
    /**stompjs의 client 객체임 ***/
    this.client = new Client({
      webSocketFactory: () => new SockJS(`${API_CONFIG.BASE_API_URL}/ws-stomp`),
      //client.activate()시 webSocketFactory를 호출하면서 new SockJS가 할당됨 -
      // -> ws-stomp 엔드포인트로 소켓 연결 시도
      connectHeaders: {
        //서버에서
        Authorization: `Bearer ${token}`,
      },
      //http 헤더 아님, 웹소켓 연결 시 서버로 전달되는 헤더.

      debug: (str) => {
        console.log('[STOMP] ' + str)
      },
      reconnectDelay: 5000,
      heartbeatIncoming: 4000,
      heartbeatOutgoing: 4000,
    })
    // Client 생성하자마자 서버랑 연결 시도. 연결 성공하면 onConnectCallback 실행
    this.client.onConnect = (frame) => {
      console.log('Connected to STOMP server')
      this.connected = true
      if (onConnectCallback) onConnectCallback(frame) //
    }
    // 연결 실패 시 에러 로그 찍고 onErrorCallback 실행
    this.client.onStompError = (frame) => {
      console.error('Broker reported error: ' + frame.headers['message'])
      console.error('Additional details: ' + frame.body)
      if (onErrorCallback) onErrorCallback(frame)
    }
    // 연결이 끊어졌을 때 로그 찍고 상태 업데이트
    this.client.onWebSocketClose = () => {
      console.log('STOMP Connection closed')
      this.connected = false
    }
    // 스톰프 연결 활성화
    this.client.activate()
  }
  // 연결 끊기. 구독도 모두 해제하고 상태 초기화
  disconnect() {
    if (this.client) {
      // Unsubscribe all active subscriptions
      Object.keys(this.subscriptions).forEach((dest) => {
        this.unsubscribe(dest)
      })
      // 스톰프 연결 비활성화
      this.client.deactivate()
      this.client = null
      this.connected = false
      this.subscriptions = {}
      console.log('STOMP Connection deactivated')
    }
  }
  //구독 메시지
  subscribe(destination, onMessageCallback) {
    if (!this.client || !this.connected) {
      console.warn('Cannot subscribe. Not connected.')
      return null
    }

    if (this.subscriptions[destination]) {
      console.log(`Already subscribed to ${destination}`)
      return this.subscriptions[destination]
    }

    const subscription = this.client.subscribe(destination, (message) => {
      try {
        const payload = JSON.parse(message.body)
        onMessageCallback(payload)
      } catch (e) {
        console.error('Error parsing stomp message body', e)
      }
    })

    this.subscriptions[destination] = subscription
    return subscription
  }
  //구독 메시지 해제
  unsubscribe(destination) {
    if (this.subscriptions[destination]) {
      this.subscriptions[destination].unsubscribe()
      delete this.subscriptions[destination]
      console.log(`Unsubscribed from ${destination}`)
    }
  }
  //메시지 보냅니다( signalling or chat...)
  send(destination, body) {
    if (!this.client || !this.connected) {
      console.warn('Cannot send message. Not connected.')
      return
    }

    this.client.publish({
      destination: destination,
      body: JSON.stringify(body),
    })
  }
}

export default new WebsocketService()
