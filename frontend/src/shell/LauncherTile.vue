<template>
  <component
    :is="tag"
    v-bind="tagAttrs"
    class="flex flex-col items-center text-center focus:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
  >
    <div class="flex size-[54px] items-center justify-center">
      <img
        :src="logo"
        :alt="__('{0} logo', [label])"
        class="size-[54px] object-contain"
        draggable="false"
      />
    </div>
    <div class="mt-3 text-sm-medium leading-none text-ink-gray-9">{{ label }}</div>
  </component>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps<{
  logo: string
  label: string
  to?: string
  href?: string
}>()

const tag = computed(() => (props.to ? RouterLink : props.href ? 'a' : 'button'))
const tagAttrs = computed(() => {
  if (props.to) return { to: props.to }
  if (props.href) return { href: props.href }
  return { type: 'button' }
})
</script>
