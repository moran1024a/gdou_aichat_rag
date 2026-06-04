FROM python:3.11.6

# 设置工作目录
WORKDIR /app

RUN rm -f /etc/apt/sources.list && \
    rm -rf /etc/apt/sources.list.d/* && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm main non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security/ bookworm-security main non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm-updates main non-free non-free-firmware" >> /etc/apt/sources.list
    
# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgtk-3-0 && \
    rm -rf /var/lib/apt/lists/*


# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
RUN printf "modelscope\npipeline\n" | mineru-models-download
# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 安装gunicorn
RUN pip install gunicorn -i https://pypi.tuna.tsinghua.edu.cn/simple/
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "300", "server.wsgi:application"]