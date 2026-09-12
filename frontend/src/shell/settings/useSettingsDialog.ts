import { ref } from 'vue'

export const showSettings = ref(false)
export const settingsTab = ref('profile')

export function openSettings(tab = 'profile') {
  settingsTab.value = tab
  showSettings.value = true
}
