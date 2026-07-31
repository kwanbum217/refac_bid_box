FROM node:20-alpine

WORKDIR /app

COPY package.json ./

RUN npm install

COPY . .

ENV NODE_OPTIONS="--dns-result-order=ipv4first"
EXPOSE 5173

CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173"]
