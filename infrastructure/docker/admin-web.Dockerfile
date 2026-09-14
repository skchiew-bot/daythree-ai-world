FROM node:24-alpine
WORKDIR /app

COPY apps/admin-web/package.json apps/admin-web/package-lock.json* ./
RUN npm install

COPY apps/admin-web ./

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
