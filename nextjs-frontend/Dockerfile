# Development image for docker compose (ADR-006: Docker is for local dev and CI only;
# Vercel builds the frontend itself). No secrets are baked in: configuration comes from
# the environment at run time.
FROM node:22-bookworm-slim

# Prisma's engines need OpenSSL.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /app \
    && chown node:node /app

WORKDIR /app
USER node

ENV NEXT_TELEMETRY_DISABLED=1

COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --ignore-scripts

# .next is created here so the named volume mounted over it is writable by "node".
COPY --chown=node:node . .
RUN npx prisma generate && mkdir -p .next

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
