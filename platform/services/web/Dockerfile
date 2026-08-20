FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# No VITE_API_BASE build arg (deliberately, as of this fix) - the frontend
# now calls a RELATIVE /api/... path by default (see src/api/chat.ts),
# which nginx.conf proxies server-side to the api container. Baking an
# absolute http://localhost:PORT in here only ever worked from the same
# machine running Docker - it broke the first time this was shared with a
# remote tester through a tunnel, since "localhost" in their browser meant
# THEIR machine. Only set VITE_API_BASE explicitly (as a --build-arg) for
# the genuine edge case where the API truly lives on a different origin
# than the frontend.
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
