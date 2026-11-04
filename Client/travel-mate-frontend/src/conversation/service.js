import axios from 'axios'
import { validateReply } from './contracts'
import { EmotionTags } from './character'
export async function conversationTurn({
  message,
  history,
  filters,
  intentHint,
  plan,
  conversationId,
}) {
  const response = await axios.post(
    '/api/v1/conversation/turns',
    {
      message,
      history,
      searchContext: filters,
      intentHint,
      planningRequest: plan,
    },
    {
      timeout: Number(import.meta.env.VITE_CONVERSATION_TIMEOUT_MS || 120000),
      skipAuthRetry: true,
      headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-Conversation-Id': conversationId },
    },
  )
  return validateReply(response.data, EmotionTags)
}
export async function conversationOptions() {
  return (await axios.get('/api/v1/conversation/options')).data
}
