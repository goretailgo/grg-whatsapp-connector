FROM node:20-alpine
RUN apk add --no-cache git
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY index.js ./
ENV NODE_ENV=production PORT=3100 SESSIONS_DIR=/app/sessions
EXPOSE 3100
CMD ["node", "index.js"]
