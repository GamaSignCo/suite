<template>
	<!-- In the sidebar only once storage is critical — the meter arrives already
	     red. Until then the number lives in Settings → Account, where "how much
	     do I have?" is a question rather than a nag. -->
	<SidebarStorage
		v-if="isCritical"
		:used-percentage
		:label
		:limited="isLimited"
		:collapsed="isCollapsed"
	/>
</template>

<script setup lang="ts">
import SidebarStorage from '@/components/SidebarStorage.vue'
import { useQuota } from '@/apps/mail/composables/useQuota'

const { isCollapsed } = defineProps<{ isCollapsed: boolean }>()

const { isLimited, isCritical, usedPercentage, label } = useQuota()
</script>
