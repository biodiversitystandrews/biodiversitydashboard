/* Shared frontend deployment settings.
 *
 * Change PRODUCTION_API_URL when the FastAPI service moves from Render to a
 * University host. Both dashboard pages read this file, preventing their API
 * settings from drifting apart. Local static development expects port 8000.
 */
(function configureDashboard(global) {
    'use strict';

    const PRODUCTION_API_URL = 'https://biodiversity-dashboard-icck.onrender.com';
    const LOCAL_API_URL = 'http://127.0.0.1:8000';
    const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '']);

    global.DASHBOARD_CONFIG = Object.freeze({
        apiBaseUrl: LOCAL_HOSTS.has(global.location.hostname)
            ? LOCAL_API_URL
            : PRODUCTION_API_URL
    });
}(window));
