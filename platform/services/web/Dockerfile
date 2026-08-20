FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite bakes VITE_* vars into the built JS at build time, not runtime - it
# must be the URL the STUDENT'S BROWSER can reach (the API's host-mapped
# port), never the api container's internal Docker-network hostname, which
# only other containers can resolve.
ARG VITE_API_BASE=http://localhost:8100
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
