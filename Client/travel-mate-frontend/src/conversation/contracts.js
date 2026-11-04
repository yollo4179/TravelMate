export const Intent = Object.freeze({
  AUTO: 'AUTO',
  CONVERSATION: 'CONVERSATION',
  RECOMMENDATION: 'RECOMMENDATION',
  PLAN: 'PLAN',
})
export const IntentOptions = Object.freeze([
  { value: Intent.AUTO, label: '자동 판단', icon: '✨' },
  { value: Intent.RECOMMENDATION, label: '후보 추천', icon: '📍' },
  { value: Intent.PLAN, label: '일정 만들기', icon: '🗓' },
  { value: Intent.CONVERSATION, label: '대화', icon: '💬' },
])

// radiusBounds is the server's { min, max } from /api/v1/conversation/options; the client keeps no copy.
export function searchContext(filters, radiusBounds) {
  const latitude = Number(filters.latitude)
  const longitude = Number(filters.longitude)
  const radius = Number(filters.radius)
  if (filters.useArea && !radiusBounds) {
    throw new Error('서버의 반경 범위를 불러온 뒤 다시 시도해 주세요.')
  }
  if (
    filters.useArea &&
    (!Number.isFinite(latitude) ||
      !Number.isFinite(longitude) ||
      latitude < -90 ||
      latitude > 90 ||
      longitude < -180 ||
      longitude > 180 ||
      !Number.isFinite(radius) ||
      radius < radiusBounds.min ||
      radius > radiusBounds.max)
  ) {
    throw new Error(
      `위도·경도와 반경 ${radiusBounds.min.toLocaleString()}~${radiusBounds.max.toLocaleString()}m를 확인해 주세요.`,
    )
  }
  return {
    region: filters.region.trim() || null,
    city: filters.city.trim() || null,
    category: filters.category || null,
    excludePlaceIds: [],
    area: filters.useArea
      ? { type: 'CIRCLE', center: { lat: latitude, lon: longitude }, radiusMeters: radius }
      : null,
    themes: filters.themes
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean),
  }
}

export function planningRequest(filters, settings, radiusBounds) {
  if (!settings.startAt || !settings.endAt) return null
  const context = searchContext(filters, radiusBounds)
  if (!context.area) throw new Error('일정 생성을 위해 기준 핀과 반경을 설정해 주세요.')
  const startAt = new Date(settings.startAt)
  const endAt = new Date(settings.endAt)
  if (!Number.isFinite(startAt.getTime()) || !Number.isFinite(endAt.getTime()) || startAt >= endAt)
    throw new Error('일정 시작·종료 시간을 확인해 주세요.')
  return {
    inputMethod: 'TEXT',
    requiredStops: [],
    context: {
      area: { ...context.area, regionId: null },
      origin: {
        coordinate: context.area.center,
        label: '선택한 기준 핀',
        source: 'SELECTED_POINT',
      },
      destination: null,
      startAt: startAt.toISOString(),
      endAt: endAt.toISOString(),
      transportMode: settings.transportMode,
      objective: 'DURATION',
      preferences: {
        themes: context.themes,
        avoid: [],
        pace: 'RELAXED',
        partySize: 1,
        budgetKrw: null,
      },
      categoryRequirements: [],
      additionalRequest: null,
      unknownHoursPolicy: 'ALLOW_WITH_WARNING',
    },
  }
}

export function validateReply(reply, emotions) {
  if (
    !reply ||
    typeof reply.message !== 'string' ||
    !reply.message.trim() ||
    !Array.isArray(reply.items) ||
    !Array.isArray(reply.citations) ||
    !emotions.has(reply.emotion) ||
    !Object.values(Intent).includes(reply.intent) ||
    reply.intent === Intent.AUTO
  ) {
    throw new Error('서버 응답 계약이 맞지 않습니다. 이전 서버 버전이 아닌지 확인해 주세요.')
  }
  return reply
}

export const ReplyType = Object.freeze({
  PLACES: 'PLACES',
  RECOMMENDATION_JOB: 'RECOMMENDATION_JOB',
})
export const JobStatus = Object.freeze({
  QUEUED: 'QUEUED',
  RUNNING: 'RUNNING',
  SUCCEEDED: 'SUCCEEDED',
  FAILED: 'FAILED',
})
export const TerminalJobStatuses = Object.freeze(new Set([JobStatus.SUCCEEDED, JobStatus.FAILED]))
export const MAX_DISPLAYED_PLACES = 20

// The list the user is looking at, in screen order. LiLi's "첫 번째" is position 1 of exactly this list,
// so it is sent as shown; a list longer than the server accepts is not truncated into a different order.
export function displayedResult(resultId, places) {
  if (!resultId || !Array.isArray(places) || !places.length || places.length > MAX_DISPLAYED_PLACES)
    return null
  return { resultId, placeIds: places.map((place) => place.placeId) }
}

// One bubble per visual-novel cut; older replies without cuts fall back to the single message.
export function dialogueCuts(reply) {
  return Array.isArray(reply.dialogue) && reply.dialogue.length
    ? reply.dialogue
    : [{ text: reply.message, emotion: reply.emotion }]
}
