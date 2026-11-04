import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import {
  searchContext,
  planningRequest,
  validateReply,
  Intent,
} from '../src/conversation/contracts.js'
const filters = {
  latitude: 37.58,
  longitude: 126.99,
  radius: 2000,
  useArea: true,
  region: '서울',
  city: '종로',
  category: '관광지',
  themes: '역사, 조용한 산책',
}
test('explicit radius/location and exact categories survive the API projection', () => {
  const context = searchContext(filters)
  assert.deepEqual(context.area, {
    type: 'CIRCLE',
    center: { lat: 37.58, lon: 126.99 },
    radiusMeters: 2000,
  })
  assert.equal(context.category, '관광지')
  assert.deepEqual(context.themes, ['역사', '조용한 산책'])
})
test('no selected range means no silent coordinate restriction', () => {
  assert.equal(searchContext({ ...filters, useArea: false }).area, null)
})
test('invalid coordinates cannot dispatch a request', () => {
  assert.throws(() => searchContext({ ...filters, latitude: 91 }))
  assert.throws(() => searchContext({ ...filters, radius: 20 }))
})
test('incomplete plan conditions are left for clarification, not fabricated', () => {
  assert.equal(planningRequest(filters, { startAt: '', endAt: '', transportMode: 'WALK' }), null)
})
test('plan request preserves explicit times, themes and walking preference', () => {
  const request = planningRequest(filters, {
    startAt: '2027-01-15T10:00:00+09:00',
    endAt: '2027-01-15T12:00:00+09:00',
    transportMode: 'WALK',
  })
  assert.equal(request.context.transportMode, 'WALK')
  assert.deepEqual(request.context.preferences.themes, ['역사', '조용한 산책'])
  assert.equal(request.context.startAt, '2027-01-15T01:00:00.000Z')
  assert.deepEqual(request.requiredStops, [])
})
test('responses require text, known emotion, intent and array candidates/plans', () => {
  const reply = {
    message: '확인한 원문입니다.',
    items: [],
    citations: [],
    emotion: 'GUIDING',
    intent: Intent.RECOMMENDATION,
  }
  assert.equal(validateReply(reply, new Set(['GUIDING'])), reply)
  assert.throws(() => validateReply({ ...reply, items: {} }, new Set(['GUIDING'])))
  assert.throws(() => validateReply({ ...reply, emotion: 'UNKNOWN' }, new Set(['GUIDING'])))
})
test('each character expression has one original image with preserved bytes', async () => {
  const root = new URL('../../../Resouces/Images/LiLi/', import.meta.url)
  const catalog = JSON.parse(await readFile(new URL('catalog.json', root), 'utf8'))
  assert.equal(new Set(catalog.assets.map((item) => item.emotion)).size, 10)
  for (const item of catalog.assets)
    assert.equal(
      createHash('sha256')
        .update(await readFile(new URL(item.file, root)))
        .digest('hex'),
      item.sha256,
    )
})
