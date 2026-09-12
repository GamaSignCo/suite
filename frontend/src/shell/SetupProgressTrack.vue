<template>
  <div
    class="relative flex h-5 items-center transition-all duration-300 motion-reduce:transition-none"
    :class="isComplete ? 'gap-0' : 'gap-1.5'"
    aria-hidden="true"
  >
    <span v-for="step in totalSteps" :key="step" :class="segmentClass(step - 1)" />
    <LucideCheck
      v-if="isComplete"
      class="tick absolute top-0 right-0 size-5 stroke-[1.5] text-black dark:text-white"
    />
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ totalSteps: number; currentStep: number; isComplete?: boolean }>()

function segmentClass(index: number) {
  return [
    'h-[3px] rounded-full transition-all duration-300 motion-reduce:transition-none',
    props.isComplete ? 'w-0 opacity-0' : index === props.currentStep ? 'w-6' : 'w-2',
    index <= props.currentStep ? 'bg-black dark:bg-white' : 'bg-surface-gray-5',
  ]
}
</script>

<style scoped>
.tick {
  animation: tickIn 80ms ease 300ms both;
}

@keyframes tickIn {
  from {
    opacity: 0;
    transform: scale(0.8);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tick {
    animation: none;
  }
}
</style>
