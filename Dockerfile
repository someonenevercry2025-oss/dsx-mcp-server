FROM python:3.12-slim

WORKDIR /app

# System deps (optional LibreOffice for PDF — large; omit for free tiers if only DOCX needed)
# RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY server.py .

ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=streamable-http
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["python", "server.py"]
