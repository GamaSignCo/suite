<template>
	<!-- The month at a glance, on the sidebar's own type scale: nothing louder
	     than 13px. A day wears one tick that widens with how much is on it —
	     a density map rather than a count — today is filled in, and clicking
	     a day takes the calendar there. Paging here only turns this card: the
	     calendar itself moves when a day is picked, and the card follows the
	     calendar whenever that changes month. -->
	<div class="rounded-5 border border-outline-gray-1 bg-surface-elevation-1 p-2">
		<div class="mb-1 flex items-center gap-1.5 px-0.5">
			<span class="text-sm font-medium leading-4 text-ink-gray-9">{{ monthName }}</span>
			<span class="text-sm leading-4 text-ink-gray-4">{{ year }}</span>
			<span class="flex-1" />
			<Button variant="ghost" size="sm" icon="lucide-chevron-left" @click="page(-1)" />
			<Button variant="ghost" size="sm" icon="lucide-chevron-right" @click="page(1)" />
		</div>
		<div class="relative grid grid-cols-7 gap-0.5">
			<span
				v-for="letter in weekdays"
				:key="letter"
				class="pb-1 pt-1 text-center text-xs text-ink-gray-4"
			>
				{{ letter }}
			</span>
			<!-- The week the calendar shows, as a band behind its row. An absolutely
			     positioned grid child takes its box from its grid placement, so the
			     band covers the row exactly without pixel arithmetic — both lines
			     spelled out, since for such a child an `auto` end line means the
			     container's edge. The day buttons are positioned and paint over it. -->
			<span
				v-if="selectedRow != null"
				class="pointer-events-none absolute inset-0 rounded-2 bg-surface-gray-2"
				:style="{ gridRow: `${selectedRow + 2} / ${selectedRow + 3}`, gridColumn: '1 / 8' }"
			/>
			<button
				v-for="day in days"
				:key="day.key"
				class="relative rounded-2 pb-2.5 pt-1 text-center text-xs leading-4"
				:class="
					day.isToday
						? 'bg-surface-gray-10 text-ink-gray-1'
						: day.isSelected
							? 'bg-surface-gray-3 text-ink-gray-9'
							: [
									'hover:bg-surface-gray-2',
									// Neighbouring months fill the grid dimmed, so a week that
									// straddles a month edge still reads as one row.
									day.inMonth ? 'text-ink-gray-8' : 'text-ink-gray-4',
								]
				"
				@click="emit('select', day.date)"
			>
				{{ day.date.date() }}
				<!-- The tick sits 3px under the numerals rather than on their baseline,
				     and steps 6 → 11 → 16px for one, a few, and many events. Its width
				     is the day's load; its colour is split into one segment per
				     calendar with something on the day, so the silhouette still reads
				     as density and the colours say whose. Days of the neighbouring
				     months stay bare: their number is orientation, not an invitation
				     to read. -->
				<span
					v-if="day.inMonth && day.load"
					class="absolute bottom-[3px] left-1/2 flex h-[3px] -translate-x-1/2 gap-px opacity-80"
					:class="day.load === 1 ? 'w-1.5' : day.load <= 3 ? 'w-[11px]' : 'w-4'"
				>
					<span
						v-for="color in day.colors"
						:key="color"
						class="min-w-0 flex-1 rounded-full"
						:style="{ background: day.isToday ? 'var(--surface-elevation-1)' : tickColor(color) }"
					/>
				</span>
			</button>
		</div>
	</div>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { Button } from 'frappe-ui'
import { CalendarColorMap } from 'frappe-ui/experimental'

const dayjs = inject('$dayjs')

const props = defineProps<{
	/** The month the calendar shows; the card starts here and resyncs when it changes. */
	month: number
	year: number
	/** Calendar events with `fromDate`/`toDate` (`YYYY-MM-DD`, inclusive) and a palette `color`. */
	events: { fromDate: string; toDate: string; color?: string }[]
	/** The day the calendar is on, and which view: Day marks the day, Week its whole row. */
	selected?: Date
	view?: 'Month' | 'Week' | 'Day'
}>()

const emit = defineEmits<{ select: [date: Date] }>()

// The month on the card, which the arrows turn without touching the calendar.
const viewed = ref({ month: props.month, year: props.year })

watch(
	() => [props.month, props.year],
	([month, year]) => (viewed.value = { month, year }),
)

const page = (months: number) => {
	const date = new Date(viewed.value.year, viewed.value.month + months, 1)
	viewed.value = { month: date.getMonth(), year: date.getFullYear() }
}

const weekdays = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

const monthName = computed(() => dayjs().month(viewed.value.month).format('MMMM'))
const year = computed(() => viewed.value.year)

/** Segments a tick can split into; more would be slivers at these widths. */
const MAX_SEGMENTS = 3

/** How many events touch the day, and the calendar colours among them, in order of first appearance. */
const loadOn = (key: string) => {
	let load = 0
	const colors: string[] = []
	for (const event of props.events) {
		// Density answers "how busy am I": a draft claims the time, a decline does not.
		if (event.isDeclined) continue
		if (event.fromDate > key || event.toDate < key) continue
		load++
		const color = event.color || 'green'
		if (!colors.includes(color) && colors.length < MAX_SEGMENTS) colors.push(color)
	}
	return { load, colors }
}

const selectedKey = computed(() =>
	props.selected ? dayjs(props.selected).format('YYYY-MM-DD') : '',
)

const days = computed(() => {
	const first = dayjs(new Date(viewed.value.year, viewed.value.month, 1))
	const start = first.subtract(first.day(), 'day')
	const today = dayjs().format('YYYY-MM-DD')
	// Six rows keeps the card the same height from month to month.
	return Array.from({ length: 42 }, (_, i) => {
		const date = start.add(i, 'day')
		const key = date.format('YYYY-MM-DD')
		return {
			key,
			date,
			inMonth: date.month() === viewed.value.month,
			isToday: key === today,
			isSelected: props.view === 'Day' && key === selectedKey.value,
			...loadOn(key),
		}
	})
})

/** Row of the calendar's week on this card, when the card is showing it. */
const selectedRow = computed(() => {
	if (props.view !== 'Week' || !selectedKey.value) return null
	const index = days.value.findIndex((day) => day.key === selectedKey.value)
	return index < 0 ? null : Math.floor(index / 7)
})

const tickColor = (color: string) => CalendarColorMap[color]?.color || CalendarColorMap.green.color
</script>
