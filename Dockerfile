FROM python:3.11-slim

RUN mkdir -p /workfolder
WORKDIR /workfolder
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    DISPLAY=:99 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    curl \
    wget \
    gnupg \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libnss3 \
    libatk-bridge2.0-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libxshmfence1 \
    libxss1 \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxcb1 \
    libxcb-render0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-xinerama0 \
    libxcb-util1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install -r src/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

RUN playwright install --with-deps

CMD ["python", "src/gui_main.py"]