import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Dialog shows its body only while open; the rest of frappe-ui is decoration here.
vi.mock('frappe-ui', () => {
	const stub = defineComponent({ render: () => h('span') })
	const Dialog = defineComponent({
		props: { open: Boolean },
		setup: (props, { slots }) => () => (props.open ? h('div', slots.default?.()) : null),
	})
	return { Dialog, Badge: stub, Button: stub, Spinner: stub, Avatar: stub, Select: stub }
})

vi.mock('@/boot/session', () => ({
	useCurrentUser: () => ({ user: ref(OWNER.name), fullName: ref(OWNER.full_name), imageURL: ref('') }),
}))

const api = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('../../utils/api.js', () => api)

import ShareDialog from './ShareDialog.vue'

const OWNER = { name: 'alex@example.com', full_name: 'Alex Owner', user_image: null }
const ALICE = { name: 'alice@example.com', full_name: 'Alice Brown', user_image: null }
const BOB = { name: 'bob@example.com', full_name: 'Bob Wilson', user_image: null }

const SEARCH_DELAY = 250

// One entry per lookup of the site's people; a test answers each when it chooses to.
let lookups = []

function answerLookup(index, people) {
	lookups[index](people)
	return settle()
}

async function settle() {
	for (let i = 0; i < 5; i++) await Promise.resolve()
	await nextTick()
}

function mountDialog() {
	const open = ref(false)
	const host = document.body.appendChild(document.createElement('div'))
	const app = createApp({
		render: () => h(ShareDialog, { modelValue: open.value, sheetId: 'sheet-1', ownerId: OWNER.name }),
	})
	app.mount(host)

	const setOpen = async (value) => {
		open.value = value
		await settle()
	}
	const type = async (text) => {
		const input = host.querySelector('input.sd-stage-input')
		input.value = text
		input.dispatchEvent(new Event('input'))
		await settle()
	}
	const waitForSearch = () => vi.advanceTimersByTimeAsync(SEARCH_DELAY)
	const matches = () =>
		[...host.querySelectorAll('.sd-result-row .sd-primary-text')].map((el) => el.textContent)

	return { app, open: () => setOpen(true), close: () => setOpen(false), type, waitForSearch, matches }
}

describe('finding people to share a sheet with', () => {
	let dialog

	beforeEach(() => {
		vi.useFakeTimers()
		lookups = []
		api.call.mockImplementation((method) => {
			if (method === 'suite.drive.api.product.get_users') {
				return new Promise((resolve) => lookups.push(resolve))
			}
			return Promise.resolve(method === 'suite.sheets.api.get_sheet_shares' ? [] : undefined)
		})
		dialog = mountDialog()
	})

	afterEach(() => {
		dialog.app.unmount()
		document.body.innerHTML = ''
		vi.useRealTimers()
	})

	it('matches by name and leaves the owner out', async () => {
		await dialog.open()
		await dialog.type('al')
		await dialog.waitForSearch()
		await answerLookup(0, [OWNER, ALICE, BOB])

		expect(dialog.matches()).toEqual(['Alice Brown'])
	})

	it('finds someone who joined after the dialog was last open', async () => {
		await dialog.open()
		await dialog.type('bo')
		await dialog.waitForSearch()
		await answerLookup(0, [OWNER, ALICE])
		expect(dialog.matches()).toEqual([])

		await dialog.close()
		await dialog.open()
		await dialog.type('bo')
		await dialog.waitForSearch()
		await answerLookup(1, [OWNER, ALICE, BOB])

		expect(dialog.matches()).toEqual(['Bob Wilson'])
	})

	it('keeps the current matches when a search from an earlier opening answers late', async () => {
		await dialog.open()
		await dialog.type('al')
		await dialog.waitForSearch()

		await dialog.close()
		await dialog.open()
		await dialog.type('bo')
		await dialog.waitForSearch()
		await answerLookup(1, [OWNER, ALICE, BOB])
		expect(dialog.matches()).toEqual(['Bob Wilson'])

		await answerLookup(0, [OWNER, ALICE, BOB])

		expect(dialog.matches()).toEqual(['Bob Wilson'])
	})

	it('drops a search that had not started when the dialog closed', async () => {
		await dialog.open()
		await dialog.type('al')

		await dialog.close()
		await dialog.open()
		await dialog.waitForSearch()
		await Promise.all(lookups.map((_, index) => answerLookup(index, [OWNER, ALICE, BOB])))

		expect(dialog.matches()).toEqual([])
	})
})
