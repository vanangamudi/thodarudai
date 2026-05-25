FROM node:20-slim AS build
WORKDIR /app
COPY webui1/frontend/package*.json ./
RUN npm ci
COPY webui1/frontend .
ARG VITE_API_BASE=/
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx","-g","daemon off;"]
