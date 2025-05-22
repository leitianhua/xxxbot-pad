FROM ubuntu:24.04

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV TZ=Asia/Shanghai
ENV IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg

# 更新软件源
RUN apt-get update && \
    apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip \
    ffmpeg redis-server build-essential p7zip-full unrar-free curl netcat-openbsd \
    nodejs npm procps && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/7za /usr/bin/7z || echo "无法创建7z链接，但继续执行" && \
    npm install -g wetty@2.5.0 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 复制 Redis 配置
COPY redis.conf /etc/redis/redis.conf

# 复制依赖文件
COPY requirements.txt .

# 升级pip并安装Python依赖
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir websockets httpx

# 复制应用代码
COPY . .

# 设置权限
RUN chmod -R 755 /app \
    && find /app -name "XYWechatPad" -exec chmod +x {} \; \
    && find /app -type f -name "*.py" -exec chmod +x {} \; \
    && find /app -type f -name "*.sh" -exec chmod +x {} \;

# 创建日志目录
RUN mkdir -p /app/logs && chmod 777 /app/logs

# 启动脚本
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 暴露端口
EXPOSE 9090 3000

CMD ["./entrypoint.sh"]