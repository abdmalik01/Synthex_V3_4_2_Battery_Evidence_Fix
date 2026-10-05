FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    HOME=/tmp \
    SYNTHEX_PUBLIC_MODE=true \
    SYNTHEX_DATA_ROOT=/var/lib/synthex

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./

RUN useradd --uid 10001 --create-home --home-dir /var/lib/synthex synthex \
    && chown -R synthex:synthex /var/lib/synthex
USER 10001:10001

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1
CMD ["python", "-m", "streamlit", "run", "platform_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
