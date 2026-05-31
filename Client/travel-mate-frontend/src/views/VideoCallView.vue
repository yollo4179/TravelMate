<template>
  <div class="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans relative overflow-hidden select-none">
    <!-- Ambient Background Glows -->
    <div class="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-violet-600/10 blur-[120px] pointer-events-none"></div>
    <div class="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-teal-500/10 blur-[120px] pointer-events-none"></div>

    <!-- Header Section -->
    <header class="w-full py-4 px-6 border-b border-slate-800/60 bg-slate-900/40 backdrop-blur-md flex justify-between items-center z-10">
      <div class="flex items-center space-x-3">
        <div class="w-2.5 h-2.5 bg-rose-500 rounded-full animate-ping"></div>
        <h1 class="text-xl font-bold tracking-tight text-white">화상 회의 통화</h1>
        <span class="text-xs bg-slate-800/80 border border-slate-700/60 px-3 py-1 rounded-full text-slate-300">
          방 ID: {{ roomId }}
        </span>
      </div>
      
      <div class="flex items-center space-x-3">
        <span class="text-sm text-slate-400 font-medium">참여자: {{ totalParticipants }}명</span>
      </div>
    </header>

    <!-- Main Content Grid -->
    <main class="flex-1 p-6 flex flex-col items-center justify-center z-10 overflow-y-auto max-h-[calc(100vh-160px)]">
      <div 
        class="grid gap-6 w-full max-w-6xl mx-auto"
        :class="gridColsClass"
      >
        <!-- Local Video Card -->
        <div class="relative bg-slate-900/80 border border-slate-800/80 rounded-2xl overflow-hidden aspect-video shadow-2xl transition-all duration-300 hover:border-violet-500/30 group">
          <video 
            ref="localVideo" 
            autoplay 
            playsinline 
            muted 
            class="w-full h-full object-cover transform -scale-x-100 rounded-2xl"
          ></video>
          
          <!-- Glassmorphic Overlay Tag -->
          <div class="absolute bottom-3 left-3 bg-slate-950/65 backdrop-blur-md border border-slate-800 px-4 py-1.5 rounded-full flex items-center space-x-2 shadow-lg">
            <span class="text-xs font-semibold text-white">나 ({{ localNickname }})</span>
            <div class="w-1.5 h-1.5 bg-green-500 rounded-full"></div>
          </div>

          <!-- Video Disabled State -->
          <div v-if="!videoActive" class="absolute inset-0 bg-slate-950 flex flex-col items-center justify-center space-y-4">
            <div class="w-16 h-16 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-400">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-8 h-8">
                <path stroke-linecap="round" stroke-linejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z" />
              </svg>
            </div>
            <span class="text-sm font-medium text-slate-400">카메라가 꺼져 있습니다</span>
          </div>
        </div>

        <!-- Remote Videos Grid -->
        <div 
          v-for="(remote, uid) in remoteStreams" 
          :key="uid"
          class="relative bg-slate-900/80 border border-slate-800/80 rounded-2xl overflow-hidden aspect-video shadow-2xl transition-all duration-300 hover:border-teal-500/30"
        >
          <video 
            :ref="el => setRemoteVideoRef(el, uid)"
            autoplay 
            playsinline 
            class="w-full h-full object-cover rounded-2xl"
          ></video>

          <!-- Glassmorphic Overlay Tag -->
          <div class="absolute bottom-3 left-3 bg-slate-950/65 backdrop-blur-md border border-slate-800 px-4 py-1.5 rounded-full flex items-center space-x-2 shadow-lg">
            <span class="text-xs font-semibold text-white">{{ getNickname(uid) }}</span>
          </div>
        </div>
      </div>
    </main>

    <!-- Sleek Control Panel Overlay -->
    <footer class="w-full py-5 px-6 border-t border-slate-800/60 bg-slate-900/40 backdrop-blur-md flex justify-center items-center z-10 space-x-4">
      <!-- Mute Mic Button -->
      <button 
        @click="toggleAudio"
        class="w-12 h-12 rounded-full border flex items-center justify-center transition-all duration-200 shadow-md"
        :class="audioActive ? 'bg-slate-800 border-slate-700/80 hover:bg-slate-700 text-slate-200' : 'bg-red-500/20 border-red-500/50 hover:bg-red-500/30 text-red-500'"
      >
        <svg v-if="audioActive" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z" />
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.172 16.172a4 4 0 0 1-5.656-5.656m3.536-3.536L17.657 17.657M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
      </button>

      <!-- Toggle Video Button -->
      <button 
        @click="toggleVideo"
        class="w-12 h-12 rounded-full border flex items-center justify-center transition-all duration-200 shadow-md"
        :class="videoActive ? 'bg-slate-800 border-slate-700/80 hover:bg-slate-700 text-slate-200' : 'bg-red-500/20 border-red-500/50 hover:bg-red-500/30 text-red-500'"
      >
        <svg v-if="videoActive" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
          <path stroke-linecap="round" stroke-linejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z" />
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
          <path stroke-linecap="round" stroke-linejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M12 18.75H4.5a2.25 2.25 0 0 1-2.25-2.25v-9a2.25 2.25 0 0 1 2.25-2.25h9a2.25 2.25 0 0 1 2.25 2.25v5" />
        </svg>
      </button>

      <!-- Leave Room Button -->
      <button 
        @click="leaveCall"
        class="px-6 h-12 rounded-full bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white font-semibold transition-all duration-200 shadow-lg flex items-center space-x-2"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M12 9l-3 3m0 0 3 3m-3-3h12.75" />
        </svg>
        <span>전화 끊기</span>
      </button>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import axios from 'axios';
import { useAuthStore } from '@/piniaStores/AuthStore';
import { useUserStore } from '@/piniaStores/MyStore';
import WebsocketService from '@/Services/WebsocketService';
import { WebRTCManager } from '@/Services/WebRTCService';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const userStore = useUserStore();

const roomId = computed(() => route.params.roomId);
const localVideo = ref(null);
const remoteStreams = ref({}); // uid -> MediaStream
const memberNicknames = ref({}); // uid -> Nickname

const audioActive = ref(true);
const videoActive = ref(true);

let rtcManager = null;

const localNickname = computed(() => userStore.nickname.value || userStore.userDesc?.nickname || '나');
const localUid = computed(() => userStore.userDesc?.uid);

const totalParticipants = computed(() => {
  return 1 + Object.keys(remoteStreams.value).length;
});

// Dynamic layout class for video grid based on participant count
const gridColsClass = computed(() => {
  const count = totalParticipants.value;
  if (count === 1) return 'grid-cols-1 max-w-2xl';
  if (count === 2) return 'grid-cols-1 md:grid-cols-2';
  return 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3';
});

// Helper to look up nicknames dynamically
const getNickname = (uid) => {
  return memberNicknames.value[uid] || `User (${uid.slice(0, 5)})`;
};

// Callback triggered when remote track is received
const onRemoteStreamAdded = (peerUid, stream) => {
  console.log(`Setting remote stream for: ${peerUid}`);
  remoteStreams.value[peerUid] = stream;
};

// Callback triggered when peer disconnects
const onRemoteStreamRemoved = (peerUid) => {
  console.log(`Removing remote stream for: ${peerUid}`);
  delete remoteStreams.value[peerUid];
};

// Dynamic ref assignment for remote video elements
const setRemoteVideoRef = (el, uid) => {
  if (el && remoteStreams.value[uid]) {
    el.srcObject = remoteStreams.value[uid];
  }
};

// Fetch room member details to map nicknames
const fetchRoomMembers = async () => {
  try {
    const response = await axios.get(`/api/rooms/${roomId.value}/members`, {
      headers: {
        Authorization: `Bearer ${authStore.accessToken}`
      }
    });
    response.data.forEach((member) => {
      memberNicknames.value[member.uid] = member.nickname;
    });
  } catch (error) {
    console.error('Failed to fetch room members:', error);
  }
};

// Toggle microphone track
const toggleAudio = () => {
  if (rtcManager && rtcManager.localStream) {
    const audioTrack = rtcManager.localStream.getAudioTracks()[0];
    if (audioTrack) {
      audioTrack.enabled = !audioTrack.enabled;
      audioActive.value = audioTrack.enabled;
    }
  }
};

// Toggle camera track
const toggleVideo = () => {
  if (rtcManager && rtcManager.localStream) {
    const videoTrack = rtcManager.localStream.getVideoTracks()[0];
    if (videoTrack) {
      videoTrack.enabled = !videoTrack.enabled;
      videoActive.value = videoTrack.enabled;
    }
  }
};

// Leave the call and clean up
const leaveCall = async () => {
  if (rtcManager) {
    rtcManager.leaveRoom();
  }
  
  // Call leave room API on backend
  try {
    await axios.post(`/api/rooms/${roomId.value}/leave`, {}, {
      headers: {
        Authorization: `Bearer ${authStore.accessToken}`
      }
    });
  } catch (error) {
    console.error('Failed to notify backend of leave:', error);
  }

  WebsocketService.disconnect();
  router.push('/home');
};

onMounted(async () => {
  if (!authStore.accessToken) {
    alert('로그인이 필요한 서비스입니다.');
    router.push('/login');
    return;
  }

  // 1. Fetch room members for nicknames mapping
  await fetchRoomMembers();

  // 2. Initialize STOMP websocket connection
  WebsocketService.connect(
    authStore.accessToken,
    async () => {
      console.log('Signaling websocket connected.');
      
      // 3. Initialize WebRTC manager
      rtcManager = new WebRTCManager(
        roomId.value,
        localUid.value,
        localVideo.value,
        onRemoteStreamAdded,
        onRemoteStreamRemoved
      );

      // 4. Access camera/mic
      try {
        await rtcManager.initLocalStream();
        // 5. Join signaling room
        rtcManager.joinRoom();
      } catch (err) {
        alert('카메라 및 마이크 장치 접근 권한이 필요합니다.');
        leaveCall();
      }
    },
    (err) => {
      console.error('STOMP connection error:', err);
      alert('회의 서버 연결에 실패했습니다.');
      router.push('/home');
    }
  );
});

onUnmounted(() => {
  if (rtcManager) {
    rtcManager.leaveRoom();
  }
  WebsocketService.disconnect();
});
</script>

<style scoped>
/* Glassmorphism backdrop filter support */
.backdrop-blur-md {
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
</style>
