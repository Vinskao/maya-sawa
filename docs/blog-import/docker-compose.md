---
title: "docker-compose"
publishDate: "2024-04-10 12:00:00"
img: /assets/container.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/04/10
level: advance
category: Docker
tags:
  - Docker Compose
  - Azure SQL Edge
  - Spring Boot
  - Vue
---

使用 docker-compose.yml 一次啟動多服務。

總共需要額外撰寫 docker-compose.yml、前端 Dockerfile、後端 Dockerfile、start-services.sh、資料庫 init-db.sql 五個檔案。

init-db.sql 裡面放資料庫一啟動就想要建立的表跟插入的資料，直接在跟目錄建立一個 data 資料夾，然後把 sql 檔案放入。

## Dockerfile 撰寫

##### Spring Boot

```dockerfile
# 第一階段，選用了一個包含Maven 3.8.4和OpenJDK 11的官方基礎映像。這個映像被用作構建階段，即編譯和打包Java應用。as build部分給這一階段命名為build
# 使用 Maven 和 OpenJDK 11 的官方基礎映像來構建專案
FROM maven:3.8.4-openjdk-11-slim as build

# 複製專案文件到容器內的/app目錄
COPY . /app

# 設定工作目錄為/app
WORKDIR /app

# 使用 Maven 命令來構建專案，跳過單元測試
RUN mvn clean package -DskipTests

# 第二階段，這次選用的是僅包含OpenJDK 11 JRE（Java運行時環境）的輕量級基礎映像。這個映像用於運行已經構建好的Java應用，而不包含構建應用所需的任何額外工具或庫
# 使用 OpenJDK 11 的輕量級基礎映像來運行構建好的應用
FROM openjdk:11-jre-slim

# 從構建階段複製構建好的 JAR 應用到運行階段的容器內
COPY --from=build /app/target/discord-0.0.1-SNAPSHOT.jar /discord.jar

# 指定運行應用的命令
ENTRYPOINT ["java", "-jar", "/discord.jar"]

# 定義容器內應用將會使用的端口
EXPOSE 8088
```

##### Vue

```dockerfile
# 以 Node.js 官方的長期支持版本作為基礎映像
FROM node:lts AS build

# 設定容器內的工作目錄為 /app。接下來的指令將會在這個目錄下執行
WORKDIR /app

# 複製依賴文件
COPY package*.json ./

# 安裝依賴
RUN npm install

# 將除了 .dockerignore 文件中指定的內容外，將專案的所有其他文件和目錄都複製到工作目錄中。
COPY . .

# 指示 Docker 在運行容器時監聽 8090 端口
EXPOSE 8090

# 啟動開發伺服器，直接使用 Vite 提供的命令行選項來禁用自動打開瀏覽器的功能。
CMD ["npx", "vite", "--host", "--port", "8090", "--no-open"]
```

## docker-compose.yml

此檔案寫入前後端、資料庫的啟動容器設定。

```yml
version: "3.8"

services:
  sql_edge:
    image: mcr.microsoft.com/azure-sql-edge:latest
    environment:
      ACCEPT_EULA: "Y"
      SA_PASSWORD: "${MSSQL_SA_PASSWORD}"
      MSSQL_COLLATION: "Chinese_Taiwan_Stroke_CI_AI"
      TZ: "Asia/Taipei"
    ports:
      - "1433:1433"
    volumes:
      - discord_db_data:/var/opt/mssql
    networks:
      - discord_network

  sqlcmd:
    image: mcr.microsoft.com/mssql-tools:latest
    command: >
      /bin/bash -c "
        sleep 20;
        /opt/mssql-tools/bin/sqlcmd -S sql_edge -U SA -P \"$$MSSQL_SA_PASSWORD\" -d master -i /data/init-db.sql;
        "
    environment:
      MSSQL_SA_PASSWORD: "${MSSQL_SA_PASSWORD}"
    volumes:
      - ./data:/data
    networks:
      - discord_network

  discord_backend:
    build:
      context: ./discord-back-end
      dockerfile: Dockerfile
    ports:
      - "8088:8088"
    volumes:
      - java_logs:/var/opt/logs/discord
    networks:
      - discord_network
    environment:
      - DATASOURCE_URL=jdbc:sqlserver://sql_edge:1433;databaseName=discord;trustServerCertificate=true
      - DATASOURCE_USERNAME=SA
      - DATASOURCE_PASSWORD=${DATASOURCE_PASSWORD}

  discord_frontend:
    build:
      context: ./discord-front-end
      dockerfile: Dockerfile
    ports:
      - "8090:8090"
    networks:
      - discord_network

volumes:
  discord_db_data:
  java_logs:

networks:
  discord_network:
    name: discord_network
    external: true
```

啟動前，請透過環境變數或不提交至版本控制的 `.env` 設定資料庫密碼：

```dotenv
MSSQL_SA_PASSWORD=<your-strong-password>
```

請將 `.env` 加入 `.gitignore`，避免帳密被提交至版本控制。

寫完此檔案，在根目錄執行：

```bash
docker-compose up
```

就可以一次啟動整個服務。但是因為是同時啟動，如果有資料庫要先完成，後端再插入初始資料的需求，就可能在後端插入資料時資料庫還沒建好。

## start-services.sh

此為腳本，目的為決定 docker-coompose 中服務的執行順序。在每個服務啟動中間設定等待時間，以確保後啟動的服務可以運用先啟動的服務之功能。

```sh
#!/bin/bash

# 步驟 1: 啟動資料庫服務
echo "正在啟動資料庫服務..."
docker-compose up -d sql_edge

# 等待資料庫服務啟動
echo "正在等待資料庫服務啟動..."
sleep 5

# 步驟 2: 執行資料庫初始化腳本
echo "正在初始化資料庫..."
docker-compose up -d sqlcmd

# 等待資料庫初始化完成
echo "正在等待資料庫初始化完成..."
sleep 20

# 步驟 3: 禁用 Docker BuildKit，建構並啟動後端服務
echo "正在建構並啟動後端服務..."
# 如果不用重build
docker-compose up -d discord_backend
# 如果要重build
docker-compose up --build -d discord_backend


# 步驟 4: 啟動前端服務
echo "正在啟動前端服務..."
# 如果不用重build
docker-compose up -d discord_frontend
# 如果要重build
docker-compose up --build -d discord_frontend

echo "所有服務已啟動完成。"

```

執行以下一次啟動所有服務：

```bash
./start-services.sh
```

## 服務調試與故障排除

- **服務依賴：** 建議使用 start-services.sh 來管理各服務啟動的順序，確保資料庫等依賴服務先行就緒。
- **日誌檢查：** 定期檢查容器日誌，利用 docker-compose logs 命令協助偵錯。
- **環境變數：** 確保環境變數配置正確，避免因配置錯誤導致服務啟動失敗。
