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

export function searchContext(filters) {
  const latitude = Number(filters.latitude)
  const longitude = Number(filters.longitude)
  const radius = Number(filters.radius)
  if (
    filters.useArea &&
    (!Number.isFinite(latitude) ||
      !Number.isFinite(longitude) ||
      latitude < -90 ||
      latitude > 90 ||
      longitude < -180 ||
      longitude > 180 ||
      radius < 500 ||
      radius > 10000)
  ) {
    throw new Error('위도·경도와 반경 500~10,000m를 확인해 주세요.')
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

export function planningRequest(filters, settings) {
  if (!settings.startAt || !settings.endAt) return null
  const context = searchContext(filters)
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
