import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { io } = vi.hoisted(() => ({ io: vi.fn(() => ({ on: vi.fn() })) }))
vi.mock('socket.io-client', () => ({ io }))
vi.mock('@/utils/calendarAlert', () => ({ showCalendarAlert: vi.fn() }))

beforeEach(() => vi.resetModules())
afterEach(() => {
	vi.unstubAllGlobals()
	vi.clearAllMocks()
})

describe('site socket connections', () => {
	it.each([
		['http:', 'develop.example.local', '', 'http://develop.example.local/site'],
		['https:', 'erp.example.com', '', 'https://erp.example.com/site'],
		['http:', 'localhost', '8080', 'http://localhost:9000/site'],
	])('uses the page protocol %s', async (protocol, hostname, port, expected) => {
		vi.stubGlobal('window', {
			location: { protocol, hostname, port },
			site_name: 'site',
			socketio_port: '9000',
		})
		const { createSiteSocket } = await import('./realtime')

		createSiteSocket({ transports: ['websocket'] })

		expect(io).toHaveBeenNthCalledWith(1, expected, { withCredentials: true })
		expect(io).toHaveBeenNthCalledWith(2, expected, {
			withCredentials: true,
			reconnectionAttempts: 5,
			transports: ['websocket'],
		})
	})

	it('keeps a single reminder connection across multiple app connections', async () => {
		vi.stubGlobal('window', {
			location: { protocol: 'https:', hostname: 'erp.example.com', port: '' },
			site_name: 'site',
			socketio_port: '9000',
		})
		const { createSiteSocket } = await import('./realtime')

		createSiteSocket()
		createSiteSocket()

		expect(io).toHaveBeenCalledTimes(3)
		expect(io.mock.results[0].value.on).toHaveBeenCalledTimes(1)
	})
})
