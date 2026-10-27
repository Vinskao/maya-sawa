---
title: "container-database-frontend-backend"
publishDate: "2024-04-09 12:00:00"
img: /tymultiverse/assets/container.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/04/09
level: advance
category: Docker
tags:
  - Docker Network
  - Azure SQL Edge
  - Spring Boot
  - Vue
  - Container
---

## 網路部分（共同）

```bash
docker network create discord_network
```

## SQL 部分

### 先備份舊容器數據複製至本機

先啟動 SQL Server 容器後執行以下：

```bash
docker cp sql_volume:/var/opt/mssql /Users/vinskao/volume/temp
```

### 從本機複製到新容器

```bash
docker cp /Users/vinskao/volume/temp sql_edge:/var/opt/mssql
```

### 創建新 volume

```bash
docker volume create discord_db_data
```

### 開啟本機資料夾修改權限

```bash
sudo chmod -R 777 /Users/vinskao/volume/temp
```

### 將本機資料放入 discord_db_data

```bash
docker run --rm -v discord_db_data:/var/opt/mssql -v /Users/vinskao/volume/temp:/backup alpine cp -a /backup/. /var/opt/mssql
```

### 執行 SQL 鏡像

```bash
docker run -e "ACCEPT_EULA=Y" \
   -e "MSSQL_SA_PASSWORD=xxx" \
   -e "MSSQL_COLLATION=Chinese_Taiwan_Stroke_CI_AI" \
   -e "TZ=Asia/Taipei" \
   -p 1433:1433 \
   --name sql_edge \
   --network discord_network \
   --hostname sql_edge \
   -v discord_db_data:/var/opt/mssql \
   -d \
   mcr.microsoft.com/azure-sql-edge
```

## Spring Boot 部分

### Dockerfile 撰寫

```dockerfile
# 使用 Maven 和 OpenJDK 11 的官方基礎映像來構建專案
FROM maven:3.8.4-openjdk-11-slim as build

# 複製專案文件到容器內的/app目錄
COPY . /app

# 設定工作目錄為/app
WORKDIR /app

# 使用 Maven 命令來構建專案
RUN mvn clean package -DskipTests

# 使用 OpenJDK 11 的輕量級基礎映像來運行構建好的應用
FROM openjdk:11-jre-slim

# 從構建階段複製構建好的應用到運行階段的容器內
COPY --from=build /app/target/discord-0.0.1-SNAPSHOT.war /discord.war

# 指定運行應用的命令
ENTRYPOINT ["java", "-jar", "/discord.war"]

# 定義容器內應用將會使用的端口
EXPOSE 8088
```

### 將 java properties 改成資料庫容器連接點

```yml
url: jdbc:sqlserver://sql_edge:1433;databaseName=discord;trustServerCertificate=true
```

### 創造 Image

在 Spring Boot 根目錄執行以下：

```bash
docker build -t discord-backend .
```

### 創建新 volume

```bash
docker volume create java_logs
```

### 執行 Image

如果 application.yml 沒有設定 datasource

```bash
docker run -d -p 8088:8088 --name discord-backend \
  -v java_logs:/var/opt/logs/discord \
  --network discord_network \
  --hostname discord-backend-host \
  discord-backend
```

如果 application.yml 有設定 datasource

```bash
docker run -d -p 8088:8088 --name discord-backend \
  -v java_logs:/var/opt/logs/discord \
  -e "DATASOURCE_URL=jdbc:sqlserver://sql_edge:1433;databaseName=discord;trustServerCertificate=true" \
  -e DATASOURCE_USERNAME=SA \
  -e DATASOURCE_PASSWORD=xxx \
  --network discord_network \
  discord-backend
```

## Vue 部分

### Dockerfile 撰寫

```dockerfile
# 使用 Node.js 官方镜像作为构建环境
FROM node:lts AS build

# 设置工作目录
WORKDIR /app

# 复制 package.json 和 package-lock.json（如果可用）
COPY package*.json ./

# 安装项目依赖
RUN npm install

# 复制项目文件和文件夹到工作目录
COPY . .

# 暴露端口 8090
EXPOSE 8090

# 启动开发服务器，直接使用 Vite 提供的命令行选项来禁用自动打开浏览器的功能。
CMD ["npx", "vite", "--host", "--port", "8090", "--no-open"]

```

### 創建新 volume

```bash
docker volume create vue_storage
```

### 創造 Image

在 Vue 根目錄執行以下：

```bash
docker build -t discord-frontend .
```

### 執行 Image

在容器內的/app 目錄會掛載到主機上的 vue_storage 目錄。

```bash
docker run -d -p 8090:8090 --name discord-frontend --hostname discord-frontend-host --network discord_network -v vue_storage:/app discord-frontend
```
