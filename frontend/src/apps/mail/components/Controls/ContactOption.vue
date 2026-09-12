<template>
	<div class="min-w-0">
		<div class="text-ink-gray-8 truncate">{{ contact.display_name || contact.email }}</div>
		<!-- Only worth a second line when the first one isn't already the address. -->
		<div v-if="contact.display_name" class="text-ink-gray-5 truncate text-xs">
			{{ contact.email }}
		</div>
	</div>
</template>

<script setup lang="ts">
import type { DraftRecipient } from '@/apps/mail/types'

// How a contact reads in any of the pickers — recipient autocomplete, the contacts
// combobox, `@` mentions. The address is the disambiguator between two people with
// the same name, so it stays visible under the name rather than replacing it.
defineProps<{ contact: DraftRecipient }>()
</script>
