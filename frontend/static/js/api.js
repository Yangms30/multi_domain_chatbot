// API Base URL: empty for local (same origin), Render URL for production
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? ''
    : 'https://multi-domain-chatbot-5ebb.onrender.com';

const api = {
    // --- Chatbots ---
    async getChatbots(category = 'all') {
        const res = await fetch(`${API_BASE}/api/chatbots?category=${category}`);
        return res.json();
    },

    async getChatbot(domain) {
        const res = await fetch(`${API_BASE}/api/chatbots/${domain}`);
        return res.json();
    },

    // --- Chat (non-streaming) ---
    async sendMessage(message, domain, sessionId = null) {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, domain, session_id: sessionId, stream: false }),
        });
        return res.json();
    },

    // --- Chat (streaming) ---
    async streamMessage(message, domain, sessionId = null, model = null) {
        const body = { message, domain, session_id: sessionId, stream: true };
        if (model) body.model = model;
        const res = await fetch(`${API_BASE}/api/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return res.body.getReader();
    },

    // --- Chat with Image (streaming) ---
    async streamImageMessage(message, domain, imageData, sessionId = null, model = null) {
        const body = { message, domain, session_id: sessionId, image_data: imageData, stream: true };
        if (model) body.model = model;
        const res = await fetch(`${API_BASE}/api/chat/image/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return res.body.getReader();
    },

    // --- History ---
    async getHistory(domain = null, page = 1) {
        let url = `${API_BASE}/api/history?page=${page}`;
        if (domain) url += `&domain=${domain}`;
        const res = await fetch(url);
        return res.json();
    },

    async getSessionMessages(sessionId) {
        const res = await fetch(`${API_BASE}/api/history/${sessionId}`);
        return res.json();
    },

    async deleteSession(sessionId) {
        const res = await fetch(`${API_BASE}/api/history/${sessionId}`, { method: 'DELETE' });
        return res.json();
    },

    async getStats() {
        const res = await fetch(`${API_BASE}/api/history/stats`);
        return res.json();
    },

    // --- Config ---
    async getConfig() {
        const res = await fetch(`${API_BASE}/api/config`);
        return res.json();
    },

    async updateConfig(config) {
        const res = await fetch(`${API_BASE}/api/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        });
        return res.json();
    },
};

// SSE stream parser utility
function parseSSEStream(reader, onChunk, onDone, onError) {
    const decoder = new TextDecoder();
    let buffer = '';
    let doneReceived = false;

    function processBuffer() {
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.error) {
                        if (onError) onError(data.error);
                    } else if (data.done) {
                        doneReceived = true;
                        onDone(data);
                    } else if (data.content) {
                        onChunk(data);
                    } else if (data.start) {
                        onChunk(data);
                    }
                } catch (e) { /* skip parse errors */ }
            }
        }
    }

    function read() {
        reader.read().then(({ done, value }) => {
            if (done) {
                processBuffer();
                // Safety: if stream ended without a done event, force onDone
                if (!doneReceived) {
                    onDone({ session_id: '', forced: true });
                }
                return;
            }
            buffer += decoder.decode(value, { stream: true });
            processBuffer();
            read();
        });
    }

    read();
}
