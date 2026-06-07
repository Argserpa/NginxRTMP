# Imagen base Ubuntu
FROM ubuntu:22.04

# Dependencias necesarias para compilar Nginx y el módulo RTMP
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    libpcre3 libpcre3-dev \
    zlib1g zlib1g-dev \
    libssl-dev \
    wget \
    git \
    net-tools \
    procps \
    curl \
    ffmpeg \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y ca-certificates && \
    update-ca-certificates

# Descarga del código fuente de Nginx en una versión estable
ENV NGINX_VERSION=1.28.0
RUN wget http://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz -O /tmp/nginx-${NGINX_VERSION}.tar.gz && \
    tar -zxvf /tmp/nginx-${NGINX_VERSION}.tar.gz -C /tmp

# Descarga del módulo RTMP en una versión estable
ENV NGINX_RTMP_MODULE_VERSION=1.2.2
RUN git clone https://github.com/arut/nginx-rtmp-module.git /tmp/nginx-rtmp-module

# Copia de los certificados SSL desde el directorio local './certs'
COPY ../certs/nginx.crt /etc/nginx/certs/nginx.crt
COPY ../certs/nginx.key /etc/nginx/certs/nginx.key

# Compilación de Nginx con el módulo RTMP
WORKDIR /tmp/nginx-${NGINX_VERSION}

RUN ./configure \
    --with-http_stub_status_module \
    --with-http_ssl_module \
    --add-module=/tmp/nginx-rtmp-module && \
    make && \
    make install


# Directorios para los logs de Nginx, HLS/DASH, el FLV temporal y las grabaciones.
# /tmp/rec y /recordings deben ser escribibles por el usuario 'nginx' (los workers
# que graban corren como ese usuario, no como root), de ahí el chmod 0777.
RUN mkdir -p /usr/local/nginx/logs && \
    mkdir -p /tmp/hls && \
    mkdir -p /tmp/vod/files && \
    mkdir -p /tmp/dash && \
    mkdir -p /tmp/rec && \
    mkdir -p /recordings && \
    chmod 0777 /tmp/rec /recordings

# Script que convierte el FLV grabado a MPEG-TS por fecha (exec_record_done)
COPY ./nginx/record-done.sh /usr/local/bin/record-done.sh
RUN chmod +x /usr/local/bin/record-done.sh

# Directorio y contenido de la página web servida por el contenedor
RUN mkdir -p /usr/share/nginx/html
COPY ./nginx/html /usr/share/nginx/html
# Archivo de configuración de Nginx
COPY ./nginx/nginx.conf /usr/local/nginx/conf/nginx.conf

# Puertos expuestos: 1935 (RTMP), 80 (HTTP/HLS/DASH) y 443 (HTTPS)
EXPOSE 1935
EXPOSE 80
EXPOSE 443

# Arranque de Nginx al iniciar el contenedor
CMD ["/usr/local/nginx/sbin/nginx", "-g", "daemon off;", "-c", "/usr/local/nginx/conf/nginx.conf"]
# Creación del usuario y grupo nginx
RUN groupadd -r nginx && useradd -r -g nginx nginx

