FROM python:3.11-slim

# Without this, outbound HTTPS calls (e.g. to the Anthropic API) fail with
# httpx.ConnectError("Connection error.") -- python:3.11-slim doesn't
# reliably ship a usable CA trust store on its own.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD streamlit run app.py \
    --server.port=$PORT \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
