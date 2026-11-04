<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useAuthStore } from '@/piniaStores/AuthStore'
import {
  Intent,
  IntentOptions,
  ReplyType,
  TerminalJobStatuses,
  JobStatus,
  searchContext,
  planningRequest,
  displayedResult,
  dialogueCuts,
  validateReply,
} from '@/conversation/contracts'
import { EmotionAssets, EmotionTags } from '@/conversation/character'
import { conversationTurn, conversationOptions, recommendationJob } from '@/conversation/service'
import RangeMap from '@/conversation/RangeMap.vue'
import KakaoRangeMap from '@/conversation/KakaoRangeMap.vue'
import { KakaoMapKey } from '@/conversation/kakaoMap'
import { SearchDefaults } from '@/conversation/searchDefaults'
const auth = useAuthStore()
const filters = reactive({
  region: '',
  city: '',
  category: '',
  themes: '',
  useArea: false,
  latitude: SearchDefaults.CENTER.latitude,
  longitude: SearchDefaults.CENTER.longitude,
  radius: SearchDefaults.RADIUS_METERS,
})
// Server-owned bounds; the range stays disabled until the options contract fills them.
const radiusBounds = reactive({ min: null, max: null })
const radiusLoaded = computed(
  () => Number.isFinite(radiusBounds.min) && Number.isFinite(radiusBounds.max),
)
const mapUnavailable = ref(KakaoMapKey ? '' : '카카오 지도 키가 없어 좌표 보기로 표시합니다.')
const plan = reactive({ startAt: '', endAt: '', transportMode: 'WALK' })
const intent = ref(Intent.AUTO)
const draft = ref('')
const busy = ref(false)
const error = ref('')
const messages = ref([])
const categories = ref([])
const reply = ref(null)
// The recommendation the user is looking at; LiLi's "첫 번째" refers to this list, never to a new search.
const shown = ref(null)
const conversationId = crypto.randomUUID()
const RECOMMENDATION_POLL_MS = 2000
const RECOMMENDATION_WAIT_MS = 180000
const avatar = computed(
  () => EmotionAssets[busy.value ? 'THINKING' : reply.value?.emotion || 'HAPPY'],
)
const places = computed(() => (reply.value?.type === 'PLACES' ? reply.value.items : []))
const plans = computed(() => (reply.value?.type === 'DRAFT' ? reply.value.items : []))
async function send() {
  if (busy.value || !draft.value.trim()) return
  if (!auth.accessToken) {
    error.value = '로그인 후 여행 메이트와 이야기할 수 있어요.'
    return
  }
  error.value = ''
  busy.value = true
  const text = draft.value.trim()
  try {
    const bounds = radiusLoaded.value ? radiusBounds : null
    const context = searchContext(filters, bounds)
    const planning = planningRequest(filters, plan, bounds)
    const history = messages.value
      .slice(-20)
      .map((item) => ({ role: item.role, content: item.text }))
    const result = await conversationTurn({
      message: text,
      history,
      filters: context,
      intentHint: intent.value,
      plan: planning,
      conversationId,
      displayed: shown.value,
    })
    messages.value.push({ role: 'USER', text })
    showReply(result)
    draft.value = ''
    if (result.messageSource === 'SERVER_FALLBACK')
      error.value = '서버 대체 응답입니다. 모델 설명은 생성되지 않았습니다.'
    if (result.type === ReplyType.RECOMMENDATION_JOB) await followRecommendation(result.data.jobId)
  } catch (failure) {
    error.value =
      failure.response?.data?.message || failure.message || '요청을 완료하지 못했습니다.'
  } finally {
    busy.value = false
  }
}
function showReply(result, resultId = null) {
  const cuts = dialogueCuts(result)
  cuts.forEach((cut, index) =>
    messages.value.push({
      role: 'ASSISTANT',
      text: cut.text,
      citations: index === cuts.length - 1 ? result.citations : [],
    }),
  )
  reply.value = result
  if (result.type === ReplyType.PLACES)
    shown.value = displayedResult(resultId || result.primaryResultId, result.items)
}
// LiLi's first line is already on screen; the grounded cards and her explanation arrive when the job ends.
async function followRecommendation(jobId) {
  const deadline = Date.now() + RECOMMENDATION_WAIT_MS
  while (Date.now() < deadline) {
    const job = await recommendationJob(jobId)
    if (TerminalJobStatuses.has(job.status)) {
      if (job.status === JobStatus.FAILED || !job.result) {
        error.value = job.errorMessage || '추천 결과를 만들지 못했어요. 잠시 후 다시 물어봐 줘.'
        return
      }
      showReply(validateReply(job.result, EmotionTags), jobId)
      return
    }
    await new Promise((resolve) => setTimeout(resolve, RECOMMENDATION_POLL_MS))
  }
  error.value = '추천 결과가 늦어지고 있어요. 잠시 후 다시 물어봐 줘.'
}
function currentLocation() {
  navigator.geolocation?.getCurrentPosition(
    (position) => {
      filters.latitude = position.coords.latitude
      filters.longitude = position.coords.longitude
      filters.useArea = true
    },
    () => {
      error.value = '현재 위치를 받지 못했어요. 좌표나 지도에서 기준 핀을 선택해 주세요.'
    },
  )
}
function checkJob() {
  if (!reply.value?.data?.jobId || busy.value) return
  intent.value = Intent.PLAN
  draft.value = `작업 ${reply.value.data.jobId}의 현재 상태와 완성된 초안을 확인해줘.`
  send()
}
async function loadOptions() {
  if (!auth.accessToken) return
  try {
    const options = await conversationOptions()
    const known = new Set(Object.values(Intent))
    if (
      options.intents?.length !== known.size ||
      !options.intents.every((value) => known.has(value))
    )
      throw new Error('intent mismatch')
    categories.value = options.categories
    Object.assign(radiusBounds, options.radiusMeters)
  } catch {
    error.value = '서버의 메타데이터 계약을 불러오지 못했습니다.'
  }
}
onMounted(loadOptions)
</script>
<template>
  <main class="travel-shell">
    <header class="trip-header">
      <div>
        <span class="eyebrow">YOUR TRAVEL COMPANION</span>
        <h1>TravelMate <span>with LiLi</span></h1>
        <p>가고 싶은 곳부터, 오늘의 이야기까지.</p>
      </div>
      <RouterLink v-if="!auth.accessToken" to="/login" class="sign-in">로그인 →</RouterLink
      ><span v-else class="connected">텍스트 대화</span>
    </header>
    <div class="travel-grid">
      <aside class="search-panel">
        <h2>어디로 떠나볼까요?</h2>
        <p class="muted">범위는 메타데이터로, 분위기는 의미로 찾아요.</p>
        <div class="field-row">
          <label>지역<input v-model="filters.region" placeholder="예: 부산" /></label
          ><label>도시·구<input v-model="filters.city" placeholder="예: 해운대" /></label>
        </div>
        <label
          >장소 분류<select v-model="filters.category" @focus="loadOptions">
            <option value="">전체 · 제한 없음</option>
            <option v-for="value in categories" :key="value">{{ value }}</option>
          </select></label
        >
        <label
          >여행 테마 <small>의미 검색 · 쉼표로 구분</small
          ><input v-model="filters.themes" placeholder="바다, 조용한 산책, 사진"
        /></label>
        <label class="toggle"
          ><input v-model="filters.useArea" type="checkbox" /> 기준 위치와 반경으로 제한</label
        >
        <div class="field-row">
          <label
            >위도<input
              v-model.number="filters.latitude"
              type="number"
              step="0.00001"
              min="-90"
              max="90" /></label
          ><label
            >경도<input
              v-model.number="filters.longitude"
              type="number"
              step="0.00001"
              min="-180"
              max="180"
          /></label>
        </div>
        <button class="location" @click="currentLocation">⌖ 내 위치를 기준으로</button>
        <label
          >여행 범위 <b>{{ filters.radius.toLocaleString() }}m</b
          ><input
            v-model.number="filters.radius"
            type="range"
            :min="radiusBounds.min"
            :max="radiusBounds.max"
            :step="SearchDefaults.RADIUS_STEP_METERS"
            :disabled="!radiusLoaded"
        /></label>
        <KakaoRangeMap
          v-if="!mapUnavailable"
          :latitude="Number(filters.latitude)"
          :longitude="Number(filters.longitude)"
          :radius="filters.radius"
          :places="places"
          @unavailable="(reason) => (mapUnavailable = reason)"
          @select="
            (position) => {
              filters.latitude = position.latitude
              filters.longitude = position.longitude
              filters.useArea = true
            }
          "
        />
        <small v-else class="muted">{{ mapUnavailable }}</small>
        <RangeMap
          v-if="mapUnavailable"
          :latitude="Number(filters.latitude)"
          :longitude="Number(filters.longitude)"
          :radius="filters.radius"
          :places="places"
          @select="
            (position) => {
              filters.latitude = position.latitude
              filters.longitude = position.longitude
              filters.useArea = true
            }
          "
        />
        <details>
          <summary>일정 조건 입력</summary>
          <label>시작<input v-model="plan.startAt" type="datetime-local" /></label
          ><label>종료<input v-model="plan.endAt" type="datetime-local" /></label
          ><label
            >이동<select v-model="plan.transportMode">
              <option value="WALK">도보</option>
            </select></label
          ><small
            >초안은 체류시간 등을 검사합니다. 실제 이동시간·운영시간은 별도 확인이 필요해요.</small
          >
        </details>
      </aside>
      <section class="conversation-panel">
        <div class="character-scene">
          <div class="sky-note">New places,<br />new stories.</div>
          <img :src="avatar.url" :alt="'LiLi · ' + avatar.visual_description" />
          <div class="character-caption">
            <b>여행 메이트 LiLi</b
            ><span>{{ busy ? '검색 근거와 질문을 확인하고 있어요…' : avatar.usage }}</span>
          </div>
        </div>
        <div class="chat-area" aria-live="polite">
          <p v-if="!messages.length" class="welcome">
            안녕! 원하는 여행지나 조건을 알려줘요.<br />추천 이유와 확인한 원문을 함께 보여드릴게요.
          </p>
          <article
            v-for="(item, index) in messages"
            :key="index"
            :class="['bubble', item.role.toLowerCase()]"
          >
            <p>{{ item.text }}</p>
            <details v-if="item.citations?.length">
              <summary>판단 근거 {{ item.citations.length }}개</summary>
              <blockquote
                v-for="citation in item.citations"
                :key="citation.evidenceId + citation.quote"
              >
                {{ citation.quote
                }}<small>장소 {{ citation.placeId }} · {{ citation.sourceId }}</small>
              </blockquote>
            </details>
          </article>
        </div>
        <div v-if="places.length" class="result-strip">
          <article v-for="place in places" :key="place.placeId" class="place-card">
            <img v-if="place.imageUrl" :src="place.imageUrl" :alt="place.name" /><b>{{
              place.name
            }}</b
            ><span>{{ place.region }} {{ place.city }}</span>
            <p>{{ place.description }}</p>
          </article>
        </div>
        <div v-for="itinerary in plans" :key="itinerary.planId" class="itinerary">
          <h3>{{ itinerary.title }}</h3>
          <ol>
            <li v-for="pin in itinerary.pins" :key="pin.placeId">
              {{ pin.name }} · {{ pin.stayMinutes }}분
              <p v-if="pin.explanation">{{ pin.explanation }}</p>
            </li>
          </ol>
          <p v-for="warning in itinerary.warnings" :key="warning">{{ warning }}</p>
        </div>
        <p v-if="reply?.type === 'PLANNING_JOB'" class="job-status">
          작업 {{ reply.data.jobId }} · {{ reply.data.status }}<br />
          <button type="button" :disabled="busy" @click="checkJob">작업 상태 확인</button>
        </p>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <form @submit.prevent="send" class="composer">
          <div class="intent-buttons">
            <button
              v-for="option in IntentOptions"
              :key="option.value"
              type="button"
              :class="{ selected: intent === option.value }"
              :aria-pressed="intent === option.value"
              @click="intent = option.value"
            >
              {{ option.icon }} {{ option.label }}
            </button>
          </div>
          <div class="send-row">
            <textarea
              v-model="draft"
              maxlength="4000"
              placeholder="가고 싶은 곳, 궁금한 점을 적어주세요…"
              rows="2"
              :disabled="busy"
            /><button :disabled="busy || !draft.trim()" aria-label="메시지 전송">
              {{ busy ? '…' : '↗' }}
            </button>
          </div>
          <small>버튼 선택은 선택 사항이에요. 음성 대화는 후속 확장입니다.</small>
        </form>
      </section>
    </div>
  </main>
</template>
<style scoped>
.travel-shell {
  max-width: 1400px;
  margin: auto;
  padding: 28px 32px 40px;
  color: #244064;
  font-family: 'Pretendard', 'Noto Sans KR', sans-serif;
  background: #f8f7f2;
  min-height: 100vh;
}
.trip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 26px;
}
.eyebrow {
  letter-spacing: 3px;
  font-size: 10px;
  color: #7695b0;
}
h1 {
  font-family: Georgia, serif;
  font-style: italic;
  font-size: 42px;
  color: #1976c9;
  margin: 5px 0;
}
h1 span {
  font: 14px sans-serif;
  color: #7896ad;
}
h2 {
  font-size: 21px;
  font-weight: 750;
}
.trip-header p,
.muted {
  font-size: 13px;
  color: #7b8d9b;
}
.sign-in,
.connected {
  font-size: 12px;
  padding: 10px 17px;
  border-radius: 20px;
  background: #e5f2ff;
  text-decoration: none;
}
.travel-grid {
  display: grid;
  grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
  gap: 26px;
}
.search-panel,
.conversation-panel {
  background: white;
  border: 1px solid #e6eceb;
  border-radius: 26px;
  box-shadow: 0 10px 28px #25699a09;
}
.search-panel {
  padding: 24px;
}
.field-row {
  display: flex;
  gap: 10px;
}
.field-row label {
  flex: 1;
  min-width: 0;
}
label {
  display: block;
  font-size: 12px;
  margin: 14px 0;
  color: #53718b;
}
input:not([type='range']):not([type='checkbox']),
select,
textarea {
  width: 100%;
  border: 1px solid #dce6eb;
  border-radius: 12px;
  padding: 10px 11px;
  background: #fcfdfd;
  color: #244064;
  font: 14px inherit;
  margin-top: 5px;
}
input[type='range'] {
  display: block;
  width: 100%;
  accent-color: #2b8ad0;
  margin-top: 12px;
}
.toggle {
  display: flex;
  align-items: center;
  gap: 7px;
}
.location {
  border: 0;
  border-radius: 14px;
  padding: 8px 14px;
  background: #ecf5ff;
  color: #2772b5;
  font-size: 12px;
}
label b {
  float: right;
}
small {
  font-size: 10px;
  color: #8a9aa7;
}
details {
  font-size: 12px;
  margin-top: 15px;
}
summary {
  cursor: pointer;
}
.conversation-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 760px;
}
.character-scene {
  height: 360px;
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 80% 10%, #fff6da 0%, transparent 40%),
    linear-gradient(130deg, #a5d6f3, #e6f4fa 60%, #dcebdc);
}
.character-scene:after {
  content: '';
  position: absolute;
  bottom: -80px;
  left: -10%;
  width: 120%;
  height: 140px;
  border-radius: 50%;
  background: #5fbdc32b;
}
.character-scene img {
  height: 510px;
  position: absolute;
  right: 9%;
  top: 15px;
  object-fit: contain;
}
.sky-note {
  font:
    italic 30px/1.4 Georgia,
    serif;
  transform: rotate(-6deg);
  position: absolute;
  left: 26px;
  top: 28px;
  color: #387fbe;
}
.character-caption {
  position: absolute;
  bottom: 16px;
  left: 20px;
  z-index: 1;
  background: #fffffff0;
  border-radius: 16px;
  padding: 12px 17px;
  display: flex;
  flex-direction: column;
  font-size: 13px;
  box-shadow: 0 4px 20px #4b809c14;
}
.character-caption span {
  font-size: 11px;
  margin-top: 4px;
  color: #7b92a2;
}
.chat-area {
  padding: 18px 22px;
  max-height: 370px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 13px;
}
.welcome {
  color: #5f7d93;
  font-size: 14px;
  line-height: 1.8;
}
.bubble {
  padding: 13px 16px;
  border-radius: 18px;
  max-width: 90%;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.bubble p {
  margin: 0;
}
.assistant {
  background: #f4f8fa;
  align-self: flex-start;
}
.user {
  background: #258ce5;
  color: white;
  align-self: flex-end;
}
.bubble blockquote {
  font-size: 12px;
  border-left: 2px solid #83afd3;
  padding-left: 9px;
  margin: 8px 0;
}
.bubble small {
  display: block;
  overflow-wrap: anywhere;
}
.composer {
  padding: 16px 22px 20px;
  margin-top: auto;
  border-top: 1px solid #edf1f2;
}
.intent-buttons {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
}
.intent-buttons button {
  border: 1px solid #e0ebf1;
  border-radius: 12px;
  background: white;
  font-size: 11px;
  padding: 8px 12px;
  color: #537390;
}
.intent-buttons .selected {
  background: #e8f4ff;
  border-color: #86b9e4;
  color: #156caf;
}
.send-row {
  display: flex;
  align-items: center;
  gap: 9px;
}
.send-row textarea {
  resize: none;
  font-size: 14px;
}
.send-row button {
  border: 0;
  border-radius: 50%;
  background: #248ae2;
  color: white;
  font-size: 25px;
  width: 43px;
  height: 43px;
  flex-shrink: 0;
}
.send-row button:disabled {
  opacity: 0.5;
}
.result-strip {
  display: flex;
  gap: 12px;
  padding: 10px 22px 20px;
  overflow: auto;
}
.place-card {
  min-width: 170px;
  max-width: 210px;
  border: 1px solid #e4edf1;
  border-radius: 16px;
  padding: 10px;
  font-size: 12px;
}
.place-card img {
  width: 100%;
  height: 90px;
  object-fit: cover;
  border-radius: 10px;
  margin-bottom: 8px;
}
.place-card b,
.place-card span {
  display: block;
}
.place-card span {
  font-size: 10px;
  color: #8ba0ad;
}
.place-card p {
  margin: 7px 0 0;
  max-height: 66px;
  overflow: auto;
}
.error,
.job-status,
.itinerary {
  margin: 10px 22px;
  padding: 12px;
  border-radius: 12px;
  background: #fff5e8;
  font-size: 12px;
}
.error {
  color: #b14134;
  background: #fff1ed;
}
.itinerary h3 {
  font-size: 16px;
}
@media (max-width: 800px) {
  .travel-shell {
    padding: 18px 12px;
  }
  .travel-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .search-panel {
    padding: 18px;
  }
  .character-scene {
    height: 300px;
  }
  .character-scene img {
    height: 450px;
    right: 0;
  }
  h1 {
    font-size: 34px;
  }
  .conversation-panel {
    min-height: 600px;
  }
  .sky-note {
    font-size: 25px;
  }
  .trip-header {
    margin-bottom: 16px;
  }
}
</style>
