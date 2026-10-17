import { useComputedColorScheme } from '@mantine/core'

// Categorical palette (validated reference palette, fixed order). Slots are assigned in order,
// never cycled: charts fold everything past the shown series into "Другое".
const LIGHT = {
  series: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  other: '#a3a29b',
  grid: '#e6e5e0',
  axis: '#77766f',
  surface: '#ffffff',
}
const DARK = {
  series: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
  other: '#6f6e68',
  grid: '#33332f',
  axis: '#9d9c94',
  surface: '#242424',
}

export function usePalette() {
  const scheme = useComputedColorScheme('light')
  return scheme === 'dark' ? DARK : LIGHT
}
