FROM node:20-slim AS node-base

# ── Stage 1: Install Node dependencies ──
WORKDIR /app
COPY package.json ./
RUN npm install --production

COPY slik-bridge/package.json slik-bridge/package-lock.json ./slik-bridge/
RUN cd slik-bridge && npm install --production

# ── Stage 2: Final image with Python + Node ──
FROM python:3.11-slim

# Install Node.js 20 (copies from node-base so we don't bloat with build tools)
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node dependencies (pre-built)
COPY --from=node-base /app/node_modules ./node_modules
COPY --from=node-base /app/slik-bridge/node_modules ./slik-bridge/node_modules

# Application code
COPY . .

# Create session temp directory
RUN mkdir -p /tmp/slik-sessions

EXPOSE 8000

CMD ["bash", "start.sh"]
