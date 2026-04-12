# Lens Demo — Deployment Guide

## 1. Deploy the API Proxy (Cloudflare Worker)

### Prerequisites
- Cloudflare account (free tier works)
- Node.js installed
- Your Anthropic API key

### Steps

```bash
# Install Wrangler CLI
npm install -g wrangler

# Login to Cloudflare
wrangler login

# From this directory, set your API key as a secret
wrangler secret put ANTHROPIC_API_KEY
# Paste your Anthropic API key when prompted

# Deploy the worker
wrangler deploy
```

After deploying, Wrangler will print your worker URL, e.g.:
`https://lens-api-proxy.<your-subdomain>.workers.dev`

### Custom route (optional)
To serve it at `nomocoda.com/api/chat`, add a route in the Cloudflare dashboard:
1. Go to Workers & Pages → lens-api-proxy → Settings → Triggers
2. Add route: `nomocoda.com/api/chat*`

---

## 2. Update the Frontend

Open `lens-experience.html` and update the proxy URL on this line:

```javascript
const PROXY_URL = '/api/chat';
```

Change it to your deployed worker URL:

```javascript
const PROXY_URL = 'https://lens-api-proxy.<your-subdomain>.workers.dev';
```

If you've set up the custom route at `nomocoda.com/api/chat`, the default `/api/chat` will work as-is.

---

## 3. Host the Frontend

### Option A: GitHub Pages (staging)

1. Create a repo (e.g., `nomocoda/lens-demo`)
2. Push `lens-experience.html` to the repo
3. Go to Settings → Pages → Deploy from branch → `main`
4. Access at `https://nomocoda.github.io/lens-demo/lens-experience.html`

### Option B: nomocoda.com/lens (production)

Upload `lens-experience.html` to your hosting provider (Framer, Vercel, Netlify, etc.) and configure it to be served at `/lens` or `/lens-experience`.

If using Framer:
- Add a code embed page at `/lens`
- Paste the full HTML content

---

## 4. Verify

- [ ] Open the page on mobile — full screen, no scroll issues
- [ ] Swipe left/right on the bottom bar — carousel transitions
- [ ] Tap an Explore question — sends to Lens
- [ ] Type a message in Ask mode — gets real AI response
- [ ] View page source — no API key visible
- [ ] Close button works
