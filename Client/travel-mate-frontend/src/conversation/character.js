import catalog from '@lili/catalog.json'
// Vite resolves the repository's original resources; there is no copied public/ backup.
const assets = import.meta.glob('../../../../Resouces/Images/LiLi/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
})
export const EmotionAssets = Object.freeze(
  Object.fromEntries(
    catalog.assets.map((item) => {
      const path = Object.keys(assets).find((key) => key.endsWith('/' + item.file))
      if (!path) throw new Error(`Missing LiLi asset: ${item.emotion}`)
      return [item.emotion, { ...item, url: assets[path] }]
    }),
  ),
)
export const EmotionTags = new Set(Object.keys(EmotionAssets))
