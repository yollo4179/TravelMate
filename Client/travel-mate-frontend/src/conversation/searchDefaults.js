// Starting values for the search panel only.
// Allowed radius bounds are not defined here; they come from GET /api/v1/conversation/options.
export const SearchDefaults = Object.freeze({
  CENTER: Object.freeze({ latitude: 35.1796, longitude: 129.0756 }), // 부산시청
  RADIUS_METERS: 2000,
  RADIUS_STEP_METERS: 100,
})
